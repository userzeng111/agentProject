from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
import hashlib
import json
from app.observability import get_logger
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.context.cache_store import FileBackedCacheStore, InMemoryCacheStore, LayeredCacheStore
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.domain.models import ChapterDraft, ChapterPlan, DraftResult, StoryPlan, TaskMode
from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient
from app.settings.config import Settings

logger = get_logger(__name__)

_OUTLINE_RETRY_JSON_PROMPT = (
    "上一次返回的大纲 JSON 不完整、被截断或不可解析。"
    "请重新输出一个更精简且完整的 JSON 对象。"
    "必须保留字段：working_title, logline, world_notes, character_notes, planned_chapter_count, chapter_plan。"
    "请压缩 world_notes 为最多 6 条短句，压缩 character_notes 为最多 6 条短句。"
    "chapter_plan 中每章只保留 number、title、goal 三个字段，不要扩写，不要附加额外说明。"
    "不要输出 Markdown 代码围栏，不要解释，不要补充说明，只返回最终 JSON 对象。"
)

_progress_callback_var: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "story_engine_progress_callback",
    default=None,
)
_exchange_callback_var: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "story_engine_exchange_callback",
    default=None,
)


def set_progress_callback(callback: Callable[[dict[str, Any]], None] | None) -> Token:
    return _progress_callback_var.set(callback)


def reset_progress_callback(token: Token) -> None:
    _progress_callback_var.reset(token)


def set_exchange_callback(callback: Callable[[dict[str, Any]], None] | None) -> Token:
    return _exchange_callback_var.set(callback)


def reset_exchange_callback(token: Token) -> None:
    _exchange_callback_var.reset(token)


class StoryEngine(BaseAgent):
    _skill_subdir = "story_engine"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.progress_callback: Callable[[dict[str, Any]], None] | None = None
        self.exchange_callback: Callable[[dict[str, Any]], None] | None = None
        self.response_cache = LayeredCacheStore(
            [
                InMemoryCacheStore(ttl_seconds=1800),
                FileBackedCacheStore(Path(settings.tasklog_root) / "cache" / "responses", ttl_seconds=86400),
            ]
        )
        self.outline_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一个中文小说策划助手，要输出严格 JSON，不要输出额外解释。",
                ),
                (
                    "human",
                    "请基于以下信息生成小说大纲，并严格返回 JSON，结构必须包含："
                    "working_title(string), logline(string), world_notes(string[]), character_notes(string[]), planned_chapter_count(int), "
                    "chapter_plan([{{number:int,title:string,goal:string}}])。\n"
                    "模式：{mode}\n创作类型：{creative_mode}\n篇幅规模：{novel_size}\n题材：{genre}\n风格：{style}\n风格约束：{style_requirements}\n"
                    "单章字数下限：{chapter_word_min}\n单章建议浮动范围：{chapter_word_range}\n"
                    "章节范围硬约束：{chapter_count_range_text}\n"
                    "{structure_hint}\n用户要求：{prompt}\n"
                    "上下文记忆：{context_memory}\n参考摘要：{reference_excerpt}",
                ),
            ]
        )
        self.draft_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一个中文小说起草助手，要输出严格 JSON，不要输出额外解释。",
                ),
                (
                    "human",
                    "请基于以下信息生成正文初稿总览，并严格返回 JSON，结构必须包含："
                    "title(string), summary(string)。\n"
                    "模式：{mode}\n作品标题：{title}\n一句话梗概：{logline}\n章节计划：{chapter_titles}\n"
                    "上下文记忆：{context_memory}\n参考摘要：{reference_excerpt}",
                ),
            ]
        )
        self.chapter_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一个中文小说章节起草助手，要输出严格 JSON，不要输出额外解释。",
                ),
                (
                    "human",
                    "请只生成当前章节，并严格返回 JSON，结构必须包含："
                    "number(int), title(string), summary(string), content(string)。\n"
                    "模式：{mode}\n创作类型：{creative_mode}\n篇幅规模：{novel_size}\n作品标题：{title}\n一句话梗概：{logline}\n"
                    "单章字数下限：{chapter_word_min}\n当前章节建议字数：{chapter_word_range}\n"
                    "当前章节序号：{chapter_number}\n当前章节标题：{chapter_title}\n当前章节目标：{chapter_goal}\n"
                    "总章节规划：{chapter_titles}\n已完成章节摘要：{completed_summaries}\n"
                    "上一章全文：{previous_chapter_full_text}\n当前章节历史草稿：{current_chapter_existing_draft}\n"
                    "风格目标：{style}\n风格约束：{style_requirements}\n"
                    "上下文记忆：{context_memory}\n参考摘要：{reference_excerpt}\n"
                    "要求：当前章节内容控制在 {chapter_word_range} 字，严格遵守上述风格约束，不得退回默认通用风格。",
                ),
            ]
        )
        # 大纲修订 prompt
        self.outline_revision_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一个中文小说策划助手，要输出严格 JSON，不要输出额外解释。"),
                (
                    "human",
                    "用户对当前大纲提出了以下修改意见，请根据意见重新生成大纲，保持 JSON 结构一致。\n"
                    "修改意见：{revision_comment}\n\n"
                    "当前大纲：{original_plan_json}\n\n"
                    "请严格返回 JSON，结构必须包含："
                    "working_title(string), logline(string), world_notes(string[]), character_notes(string[]), planned_chapter_count(int), "
                    "chapter_plan([{{number:int,title:string,goal:string}}])。\n"
                    "模式：{mode}\n创作类型：{creative_mode}\n篇幅规模：{novel_size}\n题材：{genre}\n风格：{style}\n风格约束：{style_requirements}\n"
                    "单章字数下限：{chapter_word_min}\n单章建议浮动范围：{chapter_word_range}\n"
                    "章节范围硬约束：{chapter_count_range_text}\n"
                    "{structure_hint}\n"
                    "上下文记忆：{context_memory}\n参考摘要：{reference_excerpt}",
                ),
            ]
        )
        # 章节对修订 prompt
        self.chapter_pair_revision_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一个中文小说章节起草助手，要输出严格 JSON，不要输出额外解释。"),
                (
                    "human",
                    "用户对当前章节提出了修改意见，请根据意见重新生成这对章节，保持 JSON 数组结构。\n"
                    "修改意见：{revision_comment}\n\n"
                    "当前章节内容：{current_chapters_json}\n\n"
                    "请严格返回 JSON 数组，每个元素结构为："
                    "{{number:int,title:string,summary:string,content:string}}。\n"
                    "模式：{mode}\n创作类型：{creative_mode}\n篇幅规模：{novel_size}\n作品标题：{title}\n一句话梗概：{logline}\n"
                    "单章字数下限：{chapter_word_min}\n当前章节建议字数：{chapter_word_range}\n"
                    "已完成章节摘要：{completed_summaries}\n"
                    "风格目标：{style}\n风格约束：{style_requirements}\n"
                    "上下文记忆：{context_memory}\n参考摘要：{reference_excerpt}\n"
                    "要求：内容控制在 {chapter_word_range} 字，叙事语气保持一致，并严格遵守上述风格约束。",
                ),
            ]
        )
        # 全文一致性验证 prompt
        self.verification_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一个中文小说质量审核助手，要输出严格 JSON，不要输出额外解释。",
                ),
                (
                    "human",
                    "请对以下小说全文进行一致性验证，检查人物设定、时间线、世界观、情节逻辑等维度。\n"
                    "输出 JSON 必须包含：\n"
                    "issues([{{severity:string,location:string,description:string,suggestion:string}}]),\n"
                    "overall_score(int,0-100), summary(string)。\n\n"
                    "作品标题：{title}\n"
                    "章节计划：{chapter_plan}\n"
                    "已完成正文：\n{full_text}\n\n"
                    "severity 可选值：critical / warning / info",
                ),
            ]
        )
        # 修复问题 prompt
        self.fix_issues_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一个中文小说修订专家，擅长根据审核意见精准修复小说中的问题。你必须输出严格 JSON，不要输出额外解释。"),
                (
                    "human",
                    "请根据以下【审核意见】修复小说中的问题，返回修复后的全部章节内容。\n\n"
                    "【审核意见】（这是主要修复依据，必须逐条处理）：\n{user_comment}\n\n"
                    "【验证报告问题】（辅助参考）：\n{issues_json}\n\n"
                    "需要修复的章节：\n{chapters_json}\n\n"
                    "请严格返回 JSON 数组，每个元素为修复后的章节：\n"
                    "{{number:int,title:string,summary:string,content:string}}。\n"
                    "模式：{mode}\n作品标题：{title}\n一句话梗概：{logline}\n\n"
                    "【重要要求】：\n"
                    "1. 必须返回全部章节，包括未修改的章节（保持原样），不得遗漏任何章节。\n"
                    "2. 优先修复【审核意见】中标记为严重/高优先级的问题。\n"
                    "3. 修复后的内容必须与上下文连贯，不得破坏已有的叙事逻辑。",
                ),
            ]
        )
        if settings.openai_api_key:
            timeout_cfg = {
                "connect": settings.llm_timeout_connect,
                "read": settings.llm_timeout_read,
                "write": settings.llm_timeout_write,
                "pool": settings.llm_timeout_pool,
            }
            self.gateway_client = OpenAICompatibleGatewayClient(
                base_url=settings.openai_base_url,
                api_key=settings.openai_api_key,
                model=settings.default_chat_model,
                timeout=timeout_cfg,
            )
        self._runtime_default_model: str | None = None

        # ── Skill 加载（继承自 BaseAgent） ──
        self._load_skills()

    # skill_id → 硬编码 prompt 属性名映射（fallback 用）
    _PROMPT_MAP: dict[str, str] = {
        "outline-planner": "outline_prompt",
        "draft-writer": "draft_prompt",
        "chapter-writer": "chapter_prompt",
        "outline-reviser": "outline_revision_prompt",
        "chapter-reviser": "chapter_pair_revision_prompt",
        "full-text-verifier": "verification_prompt",
        "issue-fixer": "fix_issues_prompt",
    }

    def _render_skill_prompt(self, skill_id: str, **variables: Any) -> list[dict[str, str]]:
        """从 Skill YAML 或硬编码 ChatPromptTemplate 渲染 prompt，返回消息列表。"""
        # 优先使用 Skill YAML
        if self._skills_loaded:
            try:
                config = self._skill_loader.get(skill_id)
                # 为未提供的变量填充默认值
                for var_def in config.input_variables:
                    if var_def.name not in variables and var_def.default is not None:
                        variables.setdefault(var_def.name, var_def.default)
                messages: list[dict[str, str]] = []
                for role_name in ("system", "human"):
                    template = getattr(config.prompt, role_name, "")
                    if template:
                        content = template.format(**variables)
                        messages.append({"role": role_name, "content": content})
                return messages
            except (KeyError, Exception) as exc:
                logger.debug("Skill [%s] 渲染失败，fallback 到硬编码: %s", skill_id, exc)

        # Fallback: 硬编码 ChatPromptTemplate
        attr_name = self._PROMPT_MAP.get(skill_id)
        if attr_name is None:
            raise ValueError(f"未知的 skill_id: {skill_id}")
        template = getattr(self, attr_name, None)
        if template is None:
            raise ValueError(f"未找到硬编码 prompt: {attr_name}")
        prompt_value = template.invoke(variables)
        return self._prompt_to_messages(prompt_value)

    def resolve_model(self, model: str | None) -> str:
        candidate = (model or "").strip()
        return candidate or self._runtime_default_model or self.settings.default_chat_model

    def set_runtime_default_model(self, model_id: str) -> None:
        """设置运行时默认模型覆盖。"""
        self._runtime_default_model = model_id
        if self.gateway_client is not None:
            self.gateway_client.model = model_id

    def list_models(self) -> list[dict[str, Any]]:
        if self.gateway_client is None:
            return []
        return self.gateway_client.list_models()

    def build_story_plan(
        self,
        spec: dict[str, Any],
        reference_text: str,
        context_packet: dict[str, Any] | None = None,
        model: str | None = None,
        revision_comment: str | None = None,
        original_plan: dict[str, Any] | None = None,
    ) -> StoryPlan:
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()

        # 修订模式
        if revision_comment and original_plan:
            request_messages = self._render_skill_prompt(
                "outline-reviser",
                revision_comment=revision_comment,
                original_plan_json=json.dumps(original_plan, ensure_ascii=False),
                mode=spec["mode"],
                creative_mode=spec.get("creative_mode", spec["mode"]),
                novel_size=spec.get("novel_size", ""),
                genre=spec.get("genre", ""),
                style=spec.get("style", ""),
                style_requirements=self._style_requirements(spec),
                chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
                chapter_word_range=self._chapter_word_range_text(spec, original_plan.get("chapter_plan") or []),
                chapter_count_range_text=spec.get("chapter_count_range_text", ""),
                structure_hint=self._structure_hint(spec),
                context_memory=self._context_memory(context_packet),
                reference_excerpt=self._context_reference(reference_text, context_packet),
            )
            self._require_gateway_client()
            return self._build_story_plan_with_retry(
                request_messages=request_messages,
                model=resolved_model,
                stage="planning",
                exchange_label="outline-revision",
                exchange_callback=active_exchange_callback,
            )

        # 首次生成
        request_messages = self._render_skill_prompt(
            "outline-planner",
            mode=spec["mode"],
            creative_mode=spec.get("creative_mode", spec["mode"]),
            novel_size=spec.get("novel_size", ""),
            genre=spec.get("genre", ""),
            style=spec.get("style", ""),
            style_requirements=self._style_requirements(spec),
            chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
            chapter_word_range=spec.get("chapter_word_range_text", self._chapter_word_range_text(spec, [])),
            chapter_count_range_text=spec.get("chapter_count_range_text", ""),
            structure_hint=self._structure_hint(spec),
            prompt=spec.get("prompt", ""),
            context_memory=self._context_memory(context_packet),
            reference_excerpt=self._context_reference(reference_text, context_packet),
        )
        self._require_gateway_client()
        return self._build_story_plan_with_retry(
            request_messages=request_messages,
            model=resolved_model,
            stage="planning",
            exchange_label="outline",
            exchange_callback=active_exchange_callback,
        )

    @staticmethod
    def _normalize_chapter_payload(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": int(payload.get("number") or 0),
            "title": str(payload.get("title") or ""),
            "summary": str(payload.get("summary") or ""),
            "content": str(payload.get("content") or ""),
        }

    def generate_draft(
        self,
        spec: dict[str, Any],
        story_plan: dict[str, Any],
        reference_text: str,
        context_packet: dict[str, Any] | None = None,
        model: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        initial_conversation_history: list[dict[str, str]] | None = None,
    ) -> DraftResult:
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_progress_callback = progress_callback or self.progress_callback or _progress_callback_var.get()
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()
        title = story_plan["working_title"]
        summary = story_plan["logline"]
        chapter_plan = story_plan["chapter_plan"]
        chapter_word_range = self._chapter_word_range_text(spec, chapter_plan)

        chapters: list[ChapterDraft] = []
        completed_summaries: list[str] = []
        previous_chapter_full_text = "无"
        conversation_history: list[dict[str, str]] = [
            {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
            for item in (initial_conversation_history or [])
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]
        self._require_gateway_client()
        for item in story_plan["chapter_plan"]:
            if active_progress_callback is not None:
                active_progress_callback(
                    {
                        "event_type": "chapter.started",
                        "stage": "drafting",
                        "unit_id": f"chapter-{item['number']:02d}",
                        "message": f"正在生成第 {item['number']} 章：{item['title']}",
                        "payload": {
                            "chapter_number": item["number"],
                            "chapter_title": item["title"],
                        },
                    }
                )
            chapter_request_messages = self._render_skill_prompt(
                "chapter-writer",
                mode=spec["mode"],
                creative_mode=spec.get("creative_mode", spec["mode"]),
                novel_size=spec.get("novel_size", ""),
                title=title,
                logline=summary,
                chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
                chapter_word_range=chapter_word_range,
                chapter_number=item["number"],
                chapter_title=item["title"],
                chapter_goal=item["goal"],
                chapter_titles=" / ".join(ch["title"] for ch in chapter_plan),
                completed_summaries="；".join(completed_summaries) if completed_summaries else "无",
                previous_chapter_full_text=previous_chapter_full_text,
                current_chapter_existing_draft="无",
                style=self._style_label(spec),
                style_requirements=self._style_requirements(spec),
                context_memory=self._context_memory(context_packet),
                reference_excerpt=self._context_reference(reference_text, context_packet),
            )
            request_messages = self._conversation_request_messages(
                conversation_history=conversation_history,
                prompt_messages=chapter_request_messages,
            )
            chapter_payload, conversation_history = self._complete_stream_json_with_cache(
                request_messages=request_messages,
                model=resolved_model,
                stage="drafting",
                exchange_label=f"chapter-{item['number']:02d}",
                exchange_callback=active_exchange_callback,
                progress_callback=active_progress_callback,
            )
            chapter_draft = ChapterDraft.model_validate(self._normalize_chapter_payload(chapter_payload))
            chapters.append(chapter_draft)
            completed_summaries.append(f"{chapter_draft.title}:{chapter_draft.summary}")
            completed_summaries = completed_summaries[-20:]
            previous_chapter_full_text = chapter_draft.content or previous_chapter_full_text
            if active_progress_callback is not None:
                active_progress_callback(
                    {
                        "event_type": "chapter.saved",
                        "stage": "drafting",
                        "unit_id": f"chapter-{chapter_draft.number:02d}",
                        "message": f"第 {chapter_draft.number} 章已生成：{chapter_draft.title}",
                        "payload": {
                            "chapter_number": chapter_draft.number,
                            "chapter_title": chapter_draft.title,
                            "chapter_summary": chapter_draft.summary,
                        },
                    }
                )

        if self._is_short_novel(spec) and len(chapters) <= 3:
            body = "\n\n".join(chapter.content for chapter in chapters)
        else:
            body = "\n\n".join(
                f"## {chapter.title}\n{chapter.content}" for chapter in chapters
            )

        return DraftResult(
            title=title,
            summary=summary,
            body=body,
            chapters=chapters,
        )

    def generate_chapter_pair(
        self,
        spec: dict[str, Any],
        story_plan: dict[str, Any],
        batch_index: int,
        completed_chapters: list[dict[str, Any]],
        reference_text: str,
        context_packet: dict[str, Any] | None = None,
        model: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        requested_batch_size: int | None = None,
        draft_seeds: dict[int, str] | None = None,
    ) -> list[ChapterDraft]:
        """按当前批次生成章节：首批可为两章，后续批次可为单章。"""
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_progress_callback = progress_callback or self.progress_callback or _progress_callback_var.get()
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()
        chapter_plan: list[dict[str, Any]] = story_plan.get("chapter_plan") or []
        chapter_word_range = self._chapter_word_range_text(spec, chapter_plan)
        batch_size = int(requested_batch_size or 0)
        if batch_size <= 0:
            batch_size = self._chapter_batch_size(
                spec,
                completed_count=len(completed_chapters),
                total_chapters=self._planned_chapter_count(story_plan),
            )

        pair_plans = list(chapter_plan[batch_index : batch_index + batch_size])

        if not pair_plans:
            return []

        completed_summaries = self._recent_completed_summaries(completed_chapters)
        completed_text = "；".join(completed_summaries) if completed_summaries else "无"
        previous_chapter_full_text = self._previous_chapter_full_text(completed_chapters)

        # 构建对话历史
        conversation_history: list[dict[str, str]] = []
        title = story_plan.get("working_title", "")
        summary = story_plan.get("logline", "")

        self._require_gateway_client()
        drafts: list[ChapterDraft] = []
        for plan in pair_plans:
            if active_progress_callback:
                active_progress_callback({
                    "event_type": "chapter.started",
                    "stage": "drafting",
                    "unit_id": f"chapter-{plan['number']:02d}",
                    "message": f"正在生成第 {plan['number']} 章：{plan['title']}",
                    "payload": {
                        "chapter_number": plan["number"],
                        "chapter_title": plan["title"],
                    },
                })

            chapter_request_messages = self._render_skill_prompt(
                "chapter-writer",
                mode=spec["mode"],
                creative_mode=spec.get("creative_mode", spec["mode"]),
                novel_size=spec.get("novel_size", ""),
                title=title,
                logline=summary,
                chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
                chapter_word_range=chapter_word_range,
                chapter_number=plan["number"],
                chapter_title=plan["title"],
                chapter_goal=plan["goal"],
                chapter_titles=" / ".join(ch["title"] for ch in chapter_plan),
                completed_summaries=completed_text,
                previous_chapter_full_text=previous_chapter_full_text,
                current_chapter_existing_draft=self._existing_draft_text(draft_seeds, int(plan["number"])),
                style=self._style_label(spec),
                style_requirements=self._style_requirements(spec),
                context_memory=self._context_memory(context_packet),
                reference_excerpt=self._context_reference(reference_text, context_packet),
            )

            request_messages = self._conversation_request_messages(
                conversation_history=conversation_history,
                prompt_messages=chapter_request_messages,
            )
            payload, conversation_history = self._complete_stream_json_with_cache(
                request_messages=request_messages,
                model=resolved_model,
                stage="drafting",
                exchange_label=f"chapter-{plan['number']:02d}",
                exchange_callback=active_exchange_callback,
                progress_callback=active_progress_callback,
            )
            chapter_draft = ChapterDraft.model_validate(self._normalize_chapter_payload(payload))

            drafts.append(chapter_draft)
            completed_summaries.append(f"{chapter_draft.title}:{chapter_draft.summary}")
            completed_summaries = completed_summaries[-20:]
            completed_text = "；".join(completed_summaries)
            previous_chapter_full_text = chapter_draft.content or previous_chapter_full_text

            if active_progress_callback:
                active_progress_callback({
                    "event_type": "chapter.saved",
                    "stage": "drafting",
                    "unit_id": f"chapter-{chapter_draft.number:02d}",
                    "message": f"第 {chapter_draft.number} 章已生成：{chapter_draft.title}",
                    "payload": {
                        "chapter_number": chapter_draft.number,
                        "chapter_title": chapter_draft.title,
                        "chapter_summary": chapter_draft.summary,
                    },
                })

        return drafts

    def revise_chapter_pair(
        self,
        current_pair: list[dict[str, Any]],
        revision_comment: str,
        spec: dict[str, Any],
        story_plan: dict[str, Any],
        completed_chapters: list[dict[str, Any]],
        reference_text: str,
        context_packet: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> list[ChapterDraft]:
        """根据用户修订意见重新生成章节对。"""
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_progress_callback = self.progress_callback or _progress_callback_var.get()
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()
        chapter_plan: list[dict[str, Any]] = story_plan.get("chapter_plan") or []
        title = story_plan.get("working_title", "")
        summary = story_plan.get("logline", "")
        chapter_word_range = self._chapter_word_range_text(spec, chapter_plan)
        completed_summaries = [f"{ch['title']}:{ch['summary']}" for ch in completed_chapters]
        completed_text = "；".join(completed_summaries) if completed_summaries else "无"

        request_messages = self._render_skill_prompt(
            "chapter-reviser",
            revision_comment=revision_comment,
            current_chapters_json=json.dumps(current_pair, ensure_ascii=False),
            mode=spec["mode"],
            creative_mode=spec.get("creative_mode", spec["mode"]),
            novel_size=spec.get("novel_size", ""),
            title=title,
            logline=summary,
            chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
            chapter_word_range=chapter_word_range,
            completed_summaries=completed_text,
            style=self._style_label(spec),
            style_requirements=self._style_requirements(spec),
            context_memory=self._context_memory(context_packet),
            reference_excerpt=self._context_reference(reference_text, context_packet),
        )

        self._require_gateway_client()
        payload, _ = self._complete_stream_json_with_cache(
            request_messages=request_messages,
            model=resolved_model,
            stage="drafting",
            exchange_label="chapter-pair-revision",
            exchange_callback=active_exchange_callback,
            progress_callback=active_progress_callback,
        )
        items = payload if isinstance(payload, list) else [payload]
        return [ChapterDraft.model_validate(self._normalize_chapter_payload(item)) for item in items]

    def verify_full_story(
        self,
        completed_chapters: list[dict[str, Any]],
        story_plan: dict[str, Any],
        spec: dict[str, Any],
        reference_text: str = "",
        context_packet: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """全文一致性验证，返回问题清单和评分。"""
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_progress_callback = self.progress_callback or _progress_callback_var.get()
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()
        title = story_plan.get("working_title", "")
        chapter_plan: list[dict[str, Any]] = story_plan.get("chapter_plan") or []
        full_text = "\n\n".join(
            f"## 第{ch['number']}章 {ch['title']}\n{ch.get('content', '')}"
            for ch in completed_chapters
        )

        request_messages = self._render_skill_prompt(
            "full-text-verifier",
            title=title,
            chapter_plan=" / ".join(f"第{ch['number']}章 {ch['title']}" for ch in chapter_plan),
            full_text=full_text[:8000],  # 截断避免超长
        )

        self._require_gateway_client()
        payload, _ = self._complete_stream_json_with_cache(
            request_messages=request_messages,
            model=resolved_model,
            stage="verification",
            exchange_label="full-story-verification",
            exchange_callback=active_exchange_callback,
            progress_callback=active_progress_callback,
        )
        return payload

    def fix_verified_issues(
        self,
        completed_chapters: list[dict[str, Any]],
        verification_report: dict[str, Any],
        review_comment: str,
        story_plan: dict[str, Any],
        spec: dict[str, Any],
        reference_text: str = "",
        context_packet: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        """根据验证意见修复章节问题。"""
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_progress_callback = self.progress_callback or _progress_callback_var.get()
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()
        title = story_plan.get("working_title", "")
        summary = story_plan.get("logline", "")
        chapters_json = json.dumps(completed_chapters, ensure_ascii=False)
        issues_json = json.dumps(verification_report.get("issues") or [], ensure_ascii=False)

        request_messages = self._render_skill_prompt(
            "issue-fixer",
            issues_json=issues_json,
            user_comment=review_comment,
            chapters_json=chapters_json,
            mode=spec["mode"],
            title=title,
            logline=summary,
        )

        self._require_gateway_client()
        payload, _ = self._complete_stream_json_with_cache(
            request_messages=request_messages,
            model=resolved_model,
            stage="verification",
            exchange_label="fix-issues",
            exchange_callback=active_exchange_callback,
            progress_callback=active_progress_callback,
        )
        items = payload if isinstance(payload, list) else [payload]
        fixed = [dict(ch) for ch in items]

        # 安全检查：如果 LLM 返回的章节数少于原始章节，用原始章节补全
        if len(fixed) < len(completed_chapters):
            logger.warning(
                "issue-fixer 返回 %d 章，原始 %d 章，用原始章节补全缺失部分",
                len(fixed), len(completed_chapters),
            )
            fixed_numbers = {ch.get("number") for ch in fixed}
            for orig_ch in completed_chapters:
                if orig_ch.get("number") not in fixed_numbers:
                    fixed.append(dict(orig_ch))
            # 按 number 排序
            fixed.sort(key=lambda ch: ch.get("number", 0))

        return fixed

    def _prompt_to_text(self, prompt_value) -> str:
        return "\n".join(str(message.content) for message in prompt_value.messages)

    def _prompt_to_messages(self, prompt_value) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for message in prompt_value.messages:
            role = "assistant"
            if message.type in {"system", "human", "ai"}:
                role = {"system": "system", "human": "user", "ai": "assistant"}[message.type]
            messages.append({"role": role, "content": str(message.content)})
        return messages

    def _conversation_request_messages(
        self,
        conversation_history: list[dict[str, str]],
        prompt_messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not conversation_history:
            return [dict(item) for item in prompt_messages]
        current_system_messages = [dict(item) for item in prompt_messages if item.get("role") == "system"]
        historical_messages = [dict(item) for item in conversation_history if item.get("role") != "system"]
        latest_user_messages = [dict(item) for item in prompt_messages if item.get("role") != "system"]
        return current_system_messages + historical_messages + latest_user_messages

    def _append_assistant_message(
        self,
        request_messages: list[dict[str, str]],
        response_payload: dict[str, Any],
    ) -> list[dict[str, str]]:
        assistant_message = {
            "role": "assistant",
            "content": json.dumps(response_payload, ensure_ascii=False),
        }
        return [dict(item) for item in request_messages] + [assistant_message]

    def _complete_json_with_cache(
        self,
        request_messages: list[dict[str, str]],
        model: str,
        stage: str,
        exchange_label: str,
        exchange_callback: Callable[[dict[str, Any]], None] | None,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        cache_key = self._response_cache_key(model=model, request_messages=request_messages)
        cached_payload = self.response_cache.get(cache_key)
        if isinstance(cached_payload, dict):
            conversation_history = self._append_assistant_message(request_messages, cached_payload)
            self._emit_exchange(
                callback=exchange_callback,
                stage=stage,
                exchange_label=exchange_label,
                model=model,
                cache_hit=True,
                request_messages=request_messages,
                conversation_history=conversation_history,
                response_payload=cached_payload,
                cache_key=cache_key,
            )
            return cached_payload, conversation_history

        if self.gateway_client is None:
            raise GatewayClientError("当前没有可用的模型网关。")
        payload = self.gateway_client.complete_json(request_messages, model=model)
        self.response_cache.set(cache_key, payload)
        conversation_history = self._append_assistant_message(request_messages, payload)
        self._emit_exchange(
            callback=exchange_callback,
            stage=stage,
            exchange_label=exchange_label,
            model=model,
            cache_hit=False,
            request_messages=request_messages,
            conversation_history=conversation_history,
            response_payload=payload,
            cache_key=cache_key,
        )
        return payload, conversation_history

    def _complete_stream_json_with_cache(
        self,
        request_messages: list[dict[str, str]],
        model: str,
        stage: str,
        exchange_label: str,
        exchange_callback: Callable[[dict[str, Any]], None] | None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """流式调用 LLM，实时发射思考链事件，最终解析 JSON。

        比 _complete_json_with_cache 多了：
        - 通过 progress_callback 发射 model.thinking 事件
        - 流式读取 reasoning_content 并实时推送
        - 失败时 fallback 到 _complete_json_with_cache
        """
        # 缓存命中则直接返回（不发 thinking 事件）
        cache_key = self._response_cache_key(model=model, request_messages=request_messages)
        cached_payload = self.response_cache.get(cache_key)
        if isinstance(cached_payload, dict):
            conversation_history = self._append_assistant_message(request_messages, cached_payload)
            self._emit_exchange(
                callback=exchange_callback,
                stage=stage,
                exchange_label=exchange_label,
                model=model,
                cache_hit=True,
                request_messages=request_messages,
                conversation_history=conversation_history,
                response_payload=cached_payload,
                cache_key=cache_key,
            )
            return cached_payload, conversation_history

        if self.gateway_client is None:
            raise GatewayClientError("当前没有可用的模型网关。")

        active_progress = progress_callback or self.progress_callback or _progress_callback_var.get()

        # 流式调用（委托 BaseAgent._call_llm_stream）
        try:
            full_content = self._call_llm_stream(
                request_messages,
                model,
                progress_callback=active_progress,
                stage=stage,
                unit_id=exchange_label,
            )
        except (GatewayClientError, Exception) as exc:
            # fallback 到非流式
            logger.warning("流式调用失败，fallback 到非流式: %s", exc)
            return self._complete_json_with_cache(
                request_messages=request_messages,
                model=model,
                stage=stage,
                exchange_label=exchange_label,
                exchange_callback=exchange_callback,
            )

        # 解析 JSON
        payload = self._strip_and_parse_json(full_content)

        self.response_cache.set(cache_key, payload)
        conversation_history = self._append_assistant_message(request_messages, payload)
        self._emit_exchange(
            callback=exchange_callback,
            stage=stage,
            exchange_label=exchange_label,
            model=model,
            cache_hit=False,
            request_messages=request_messages,
            conversation_history=conversation_history,
            response_payload=payload,
            cache_key=cache_key,
        )
        return payload, conversation_history

    def _build_story_plan_with_retry(
        self,
        request_messages: list[dict[str, str]],
        model: str,
        stage: str,
        exchange_label: str,
        exchange_callback: Callable[[dict[str, Any]], None] | None,
    ) -> StoryPlan:
        attempt_messages = request_messages
        for attempt in range(2):
            try:
                payload, _ = self._complete_stream_json_with_cache(
                    request_messages=attempt_messages,
                    model=model,
                    stage=stage,
                    exchange_label=exchange_label if attempt == 0 else f"{exchange_label}-retry",
                    exchange_callback=exchange_callback,
                    progress_callback=None,
                )
                return StoryPlan.model_validate(payload)
            except (GatewayClientError, ValidationError):
                if attempt == 1:
                    raise
                attempt_messages = [dict(item) for item in request_messages] + [
                    {
                        "role": "user",
                        "content": _OUTLINE_RETRY_JSON_PROMPT,
                    }
                ]

    def _emit_exchange(
        self,
        *,
        callback: Callable[[dict[str, Any]], None] | None,
        stage: str,
        exchange_label: str,
        model: str,
        cache_hit: bool,
        request_messages: list[dict[str, str]],
        conversation_history: list[dict[str, str]],
        response_payload: dict[str, Any],
        cache_key: str | None,
    ) -> None:
        if callback is None:
            return
        callback(
            {
                "stage": stage,
                "exchange_label": exchange_label,
                "model": model,
                "cache_hit": cache_hit,
                "cache_key": cache_key,
                "request_messages": request_messages,
                "conversation_history": conversation_history,
                "response_payload": response_payload,
            }
        )

    def _response_cache_key(self, model: str, request_messages: list[dict[str, str]]) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": request_messages,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"response:{digest}"

    def _reference_excerpt(self, text: str) -> str:
        cleaned = " ".join(text.strip().split())
        return cleaned[:80] if cleaned else "无"

    def _context_reference(self, reference_text: str, context_packet: dict[str, Any] | None) -> str:
        if isinstance(context_packet, dict):
            references_text = str(context_packet.get("references_text") or "").strip()
            if references_text:
                return self._reference_excerpt(references_text)
        return self._reference_excerpt(reference_text)

    def _context_memory(self, context_packet: dict[str, Any] | None) -> str:
        if not isinstance(context_packet, dict):
            return "无"
        memory_text = str(context_packet.get("memory_text") or "").strip()
        return memory_text or "无"

    def _recent_completed_summaries(self, completed_chapters: list[dict[str, Any]], limit: int = 20) -> list[str]:
        if limit <= 0:
            return []
        recent_items = completed_chapters[-limit:]
        return [f"{ch['title']}:{ch['summary']}" for ch in recent_items]

    def _previous_chapter_full_text(self, completed_chapters: list[dict[str, Any]]) -> str:
        if not completed_chapters:
            return "无"
        content = str(completed_chapters[-1].get("content") or "").strip()
        return content or "无"

    def _existing_draft_text(self, draft_seeds: dict[int, str] | None, chapter_number: int) -> str:
        if not isinstance(draft_seeds, dict):
            return "无"
        content = str(draft_seeds.get(chapter_number) or "").strip()
        return content or "无"

    def _theme_tail(self, mode: str) -> str:
        if mode == TaskMode.LONG_STORY.value:
            return "长夜分章"
        if mode == TaskMode.FANFIC.value:
            return "支线回响"
        if mode == TaskMode.STYLE_REMIX.value:
            return "风格折返"
        return "短篇初稿"

    def _requested_target_words(self, spec: dict[str, Any]) -> int:
        return int(
            spec.get("chapter_word_min", spec.get("requested_target_words", spec.get("target_words", 1800))) or 1800
        )

    def _chapter_batch_size(self, spec: dict[str, Any], *, completed_count: int, total_chapters: int) -> int:
        remaining = max(total_chapters - completed_count, 0)
        if remaining <= 0:
            return 0
        default_batch_size = 2
        if str(spec.get("creative_mode") or spec.get("mode") or "").strip() == TaskMode.STYLE_REMIX.value and total_chapters > 2:
            default_batch_size = 2 if completed_count == 0 else 1
        return min(default_batch_size, remaining)

    def _style_label(self, spec: dict[str, Any]) -> str:
        profile_name = str(spec.get("style_profile_name") or "").strip()
        style = str(spec.get("style") or "").strip()
        if profile_name and style:
            return f"{profile_name} + {style}"
        return profile_name or style or "未指定"

    def _style_requirements(self, spec: dict[str, Any]) -> str:
        workflow_guidance = str(spec.get("workflow_guidance") or "").strip()
        canon_guidance = str(spec.get("canon_guidance") or "").strip()
        guidance = str(spec.get("style_guidance") or "").strip()
        parts = [part for part in (workflow_guidance, canon_guidance, guidance or self._style_label(spec)) if part]
        return "\n".join(parts)

    def _structure_hint(self, spec: dict[str, Any]) -> str:
        chapter_range = str(spec.get("chapter_count_range_text") or "").strip() or "未指定"
        chapter_word_min = int(spec.get("chapter_word_min", spec.get("target_words", 1800)) or 1800)
        chapter_word_max = int(spec.get("chapter_word_max", chapter_word_min) or chapter_word_min)
        return (
            f"章节规划硬约束：你必须先确定 planned_chapter_count，且总章节数必须落在 {chapter_range} 内。"
            f"单章字数必须不低于 {chapter_word_min} 字，允许按剧情需要上浮到 {chapter_word_max} 字。"
            "章节数由主规划 agent 决定，不要沿用旧的短篇/长篇固定章数套路。"
        )

    def _chapter_word_range_text(
        self,
        spec: dict[str, Any],
        chapter_plan: list[dict[str, Any]] | list[ChapterPlan],
    ) -> str:
        minimum_words = int(spec.get("chapter_word_min", spec.get("target_words", 1800)) or 1800)
        maximum_words = int(spec.get("chapter_word_max", max(int(minimum_words * 1.3), minimum_words)) or minimum_words)
        return f"{minimum_words} 到 {maximum_words}"

    def validate_story_plan(
        self,
        story_plan: dict[str, Any],
        *,
        chapter_count_min: int,
        chapter_count_max: int,
    ) -> StoryPlan:
        plan = StoryPlan.model_validate(story_plan)
        planned_count = int(plan.planned_chapter_count or 0)
        chapter_count = len(plan.chapter_plan)
        if planned_count < chapter_count_min or planned_count > chapter_count_max:
            raise ValueError("大纲规划章节数超出允许范围。")
        if chapter_count != planned_count:
            raise ValueError("大纲章节列表数量与 planned_chapter_count 不一致。")
        return plan

    def _planned_chapter_count(self, story_plan: dict[str, Any]) -> int:
        planned = int(story_plan.get("planned_chapter_count") or 0)
        if planned > 0:
            return planned
        return len(story_plan.get("chapter_plan") or [])

    def _is_short_novel(self, spec: dict[str, Any]) -> bool:
        return str(spec.get("novel_size") or spec.get("mode") or "").strip() in {
            "short",
            TaskMode.SHORT_STORY.value,
        }
