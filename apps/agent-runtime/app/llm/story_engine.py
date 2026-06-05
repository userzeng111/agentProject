from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar, Token
import hashlib
import json
import secrets
import threading
import time
from app.observability import get_logger
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.context.cache_store import FileBackedCacheStore, InMemoryCacheStore, LayeredCacheStore
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError

from app.domain.models import ChapterDraft, ChapterPlan, DraftResult, StoryPlan, TaskMode
from app.llm.gateway_client import (
    GatewayClientError,
    OpenAICompatibleGatewayClient,
    StreamInterruptedAfterStartError,
)
from app.llm.model_capabilities_config import resolve_generation_max_tokens
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

_STREAM_JSON_REPAIR_PROMPT = (
    "上一次返回结果不是可解析的目标 JSON，可能不完整、被截断或包含 Markdown 代码围栏。"
    "请基于当前任务重新输出一个完整、可解析的 JSON 对象。"
    "必须保留原任务要求的字段，不要省略正文内容。"
    "不要输出 Markdown 代码围栏，不要解释，不要补充说明，只返回最终 JSON 对象。"
)

_VERIFICATION_TRUNCATED_RETRY_PROMPT = (
    "上一次全文验证响应被输出预算截断，只产生了模型思考过程，没有返回 JSON。"
    "请停止分析，直接输出一个极短 JSON 对象。"
    "必须包含 issues、overall_score、summary 三个字段。"
    "issues 最多 3 条；description、suggestion、summary 都必须简短。"
    "不要输出 Markdown 代码围栏，不要解释，不要输出分析过程，只返回 JSON。"
)

_VERIFICATION_JSON_REPAIR_PROMPT = (
    "上一次全文验证响应不是可解析 JSON。"
    "请直接重写一个极短 JSON 对象，必须包含 issues、overall_score、summary 三个字段。"
    "issues 最多 3 条；无法确认严重问题时 issues 返回空数组。"
    "不要复述正文，不要输出 Markdown 代码围栏，不要解释，不要输出分析过程，只返回 JSON。"
)

_TRUNCATED_FINISH_REASONS = {"length", "max_tokens"}

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
                    "你是一个中文小说章节起草助手，必须按指定章节分区协议输出，不要输出额外解释。",
                ),
                (
                    "human",
                    "请只生成当前章节，并严格按以下分区协议返回：\n"
                    "{chapter_meta_boundary}\n"
                    "{{\"number\":{chapter_number},\"title\":\"章节标题\",\"summary\":\"不超过80字摘要\"}}\n"
                    "{chapter_content_boundary}\n"
                    "正文原文，不要 JSON 转义；不要用 Markdown 代码围栏包裹整个响应。\n"
                    "{chapter_end_boundary}\n"
                    "元数据 JSON 只允许包含 number、title、summary 三个字段，不得包含 content 字段。\n"
                    "正文中不要输出任何边界行。\n"
                    "模式：{mode}\n创作类型：{creative_mode}\n篇幅规模：{novel_size}\n作品标题：{title}\n一句话梗概：{logline}\n"
                    "单章字数下限：{chapter_word_min}\n当前章节建议字数：{chapter_word_range}\n"
                    "总章节规划：{chapter_titles}\n"
                    "风格目标：{style}\n风格约束：{style_requirements}\n"
                    "上下文记忆：{context_memory}\n参考摘要：{reference_excerpt}\n"
                    "当前章节序号：{chapter_number}\n当前章节标题：{chapter_title}\n当前章节目标：{chapter_goal}\n"
                    "已完成章节摘要：{completed_summaries}\n"
                    "上一章全文：{previous_chapter_full_text}\n当前章节历史草稿：{current_chapter_existing_draft}\n"
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
        # 章节计划批次生成 prompt
        self.chapter_plan_batch_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一个中文小说策划助手，要输出严格 JSON，不要输出额外解释。",
                ),
                (
                    "human",
                    "请基于以下小说总纲，生成指定范围的章节计划，并严格返回 JSON 数组。\n"
                    "每个元素结构为：{{number:int, title:string, goal:string}}\n\n"
                    "作品标题：{title}\n"
                    "一句话梗概：{logline}\n"
                    "世界观：{world_notes}\n"
                    "人物：{character_notes}\n"
                    "预计总章数：{planned_chapter_count}\n"
                    "单章字数下限：{chapter_word_min}\n"
                    "风格目标：{style}\n"
                    "风格约束：{style_requirements}\n\n"
                    "已确认章节标题（作为连贯性约束）：{confirmed_chapter_titles}\n\n"
                    "请只生成第 {start_chapter} 章到第 {end_chapter} 章的计划，不要生成其他章节。\n"
                    "确保新章节与已确认章节在情节、人物发展上保持连贯。",
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
                    "你是一个中文小说质量审核助手，要输出严格 JSON，不要输出额外解释或分析过程。",
                ),
                (
                    "human",
                    "请对以下小说全文进行一致性验证，检查人物设定、时间线、世界观、情节逻辑等维度。\n"
                    "只报告影响主线理解的问题，忽略措辞、局部润色和不影响阅读的小瑕疵。\n"
                    "最多 5 个问题，按严重程度排序；不要逐章复述，不要输出分析过程。\n"
                    "每条 description 不超过 60 个字，每条 suggestion 不超过 60 个字，summary 不超过 80 个字。\n"
                    "输出 JSON 必须包含：\n"
                    "issues([{{severity:string,location:string,description:string,suggestion:string}}]),\n"
                    "overall_score(int,0-100), summary(string)。\n\n"
                    "作品标题：{title}\n"
                    "章节计划：{chapter_plan}\n"
                    "已完成正文或压缩摘录：\n{full_text}\n\n"
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
                    "请根据以下【审核意见】修复小说中的问题，优先只返回需要改动的章节补丁。\n\n"
                    "【审核意见】（这是主要修复依据，必须逐条处理）：\n{user_comment}\n\n"
                    "【验证报告问题】（辅助参考）：\n{issues_json}\n\n"
                    "需要修复的章节：\n{chapters_json}\n\n"
                    "请严格返回 JSON 对象，结构为：\n"
                    "{{\"patches\":[{{number:int,title?:string,summary?:string,content?:string}}]}}。\n"
                    "如果确实需要重写全部章节，也可以返回 JSON 数组，每个元素为修复后的章节。\n"
                    "模式：{mode}\n作品标题：{title}\n一句话梗概：{logline}\n\n"
                    "【重要要求】：\n"
                    "1. 未修改章节不要重复输出，系统会自动复用原文。\n"
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
                default_protocol=settings.default_protocol,
                protocol_overrides_resolver=lambda: settings.effective_protocol_overrides,
                anthropic_base_url=settings.anthropic_base_url,
                anthropic_version=settings.anthropic_version,
                model_capabilities_settings=settings,
            )
        self._runtime_default_model: str | None = None

        # ── Skill 加载（继承自 BaseAgent） ──
        self._load_skills()

    # skill_id → 硬编码 prompt 属性名映射（fallback 用）
    _PROMPT_MAP: dict[str, str] = {
        "outline-planner": "outline_prompt",
        "chapter-plan-batch": "chapter_plan_batch_prompt",
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

    @staticmethod
    def _escape_user_input(text: str) -> str:
        """对用户输入进行边界转义，防止 prompt 注入与模板误解析。"""
        if not isinstance(text, str):
            text = str(text) if text is not None else ""
        # 1. 防止 LangChain prompt template 将 {/} 误解析为变量插值
        text = text.replace("{", "{{").replace("}", "}}")
        # 2. 去除控制字符（保留 \n \t \r）
        text = "".join(ch for ch in text if ch in "\n\t\r" or ord(ch) >= 32)
        # 3. 连续多个换行压缩为单个换行
        while "\n\n" in text:
            text = text.replace("\n\n", "\n")
        return text

    @staticmethod
    def _positive_int(value: Any, default: int = 0) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _generation_max_tokens(self, model: str | None) -> int | None:
        return resolve_generation_max_tokens(model, settings=self.settings)

    def _outline_generation_max_tokens(self, spec: dict[str, Any], model: str | None = None) -> int | None:
        return self._generation_max_tokens(model or spec.get("model_id") or spec.get("model"))

    def _chapter_generation_max_tokens(
        self,
        spec: dict[str, Any],
        *,
        chapter_count: int = 1,
        model: str | None = None,
    ) -> int | None:
        return self._generation_max_tokens(model or spec.get("model_id") or spec.get("model"))

    def _verification_max_tokens(self) -> int:
        return self._positive_int(self.settings.verification_max_tokens, default=4096)

    def _verification_retry_max_tokens(self, model: str | None, base_max_tokens: int) -> int | None:
        model_max_tokens = self._generation_max_tokens(model)
        retry_max_tokens = max(base_max_tokens * 2, base_max_tokens + 2048)
        if model_max_tokens is not None:
            retry_max_tokens = min(retry_max_tokens, model_max_tokens)
        return retry_max_tokens if retry_max_tokens > base_max_tokens else None

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
                revision_comment=self._escape_user_input(revision_comment),
                original_plan_json=json.dumps(original_plan, ensure_ascii=False),
                mode=self._escape_user_input(spec["mode"]),
                creative_mode=self._escape_user_input(spec.get("creative_mode", spec["mode"])),
                novel_size=self._escape_user_input(spec.get("novel_size", "")),
                genre=self._escape_user_input(spec.get("genre", "")),
                style=self._escape_user_input(spec.get("style", "")),
                style_requirements=self._escape_user_input(self._style_requirements(spec)),
                chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
                chapter_word_range=self._chapter_word_range_text(spec, original_plan.get("chapter_plan") or []),
                chapter_count_range_text=self._escape_user_input(spec.get("chapter_count_range_text", "")),
                structure_hint=self._escape_user_input(self._structure_hint(spec)),
                context_memory=self._escape_user_input(self._context_memory(context_packet)),
                reference_excerpt=self._escape_user_input(self._context_reference(reference_text, context_packet)),
            )
            self._require_gateway_client()
            return self._build_story_plan_with_retry(
                request_messages=request_messages,
                model=resolved_model,
                stage="planning",
                exchange_label="outline-revision",
                exchange_callback=active_exchange_callback,
                max_tokens=self._outline_generation_max_tokens(spec, resolved_model),
            )

        # 首次生成
        request_messages = self._render_skill_prompt(
            "outline-planner",
            mode=self._escape_user_input(spec["mode"]),
            creative_mode=self._escape_user_input(spec.get("creative_mode", spec["mode"])),
            novel_size=self._escape_user_input(spec.get("novel_size", "")),
            genre=self._escape_user_input(spec.get("genre", "")),
            style=self._escape_user_input(spec.get("style", "")),
            style_requirements=self._escape_user_input(self._style_requirements(spec)),
            chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
            chapter_word_range=spec.get("chapter_word_range_text", self._chapter_word_range_text(spec, [])),
            chapter_count_range_text=self._escape_user_input(spec.get("chapter_count_range_text", "")),
            structure_hint=self._escape_user_input(self._structure_hint(spec)),
            prompt=self._escape_user_input(spec.get("prompt", "")),
            context_memory=self._escape_user_input(self._context_memory(context_packet)),
            reference_excerpt=self._escape_user_input(self._context_reference(reference_text, context_packet)),
        )
        self._require_gateway_client()
        return self._build_story_plan_with_retry(
            request_messages=request_messages,
            model=resolved_model,
            stage="planning",
            exchange_label="outline",
            exchange_callback=active_exchange_callback,
            max_tokens=self._outline_generation_max_tokens(spec, resolved_model),
        )

    def build_chapter_plan_batch(
        self,
        spec: dict[str, Any],
        story_plan: dict[str, Any],
        batch_index: int,
        batch_size: int,
        confirmed_chapter_plans: list[dict[str, Any]],
        model: str | None = None,
    ) -> list[ChapterPlan]:
        """基于总纲生成指定范围的章节计划批次。"""
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()

        confirmed_titles = " / ".join(
            f"第{ch.get('number')}章 {ch.get('title')}"
            for ch in confirmed_chapter_plans
        ) or "无"

        request_messages = self._render_skill_prompt(
            "chapter-plan-batch",
            title=self._escape_user_input(story_plan.get("working_title", "")),
            logline=self._escape_user_input(story_plan.get("logline", "")),
            world_notes=self._escape_user_input("\n".join(story_plan.get("world_notes", []))),
            character_notes=self._escape_user_input("\n".join(story_plan.get("character_notes", []))),
            planned_chapter_count=story_plan.get("planned_chapter_count", 0),
            chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
            style=self._escape_user_input(self._style_label(spec)),
            style_requirements=self._escape_user_input(self._style_requirements(spec)),
            confirmed_chapter_titles=self._escape_user_input(confirmed_titles),
            start_chapter=batch_index + 1,
            end_chapter=batch_index + batch_size,
        )
        self._require_gateway_client()

        payload, _ = self._complete_stream_json_with_cache(
            request_messages=request_messages,
            model=resolved_model,
            stage="planning",
            exchange_label="chapter-plan-batch",
            exchange_callback=active_exchange_callback,
            progress_callback=None,
            max_tokens=self._generation_max_tokens(resolved_model),
        )
        if not payload:
            raise RuntimeError("章节计划批次生成返回空响应")

        parsed = payload if isinstance(payload, list) else self._parse_strict_json(str(payload))
        if not isinstance(parsed, list):
            raise RuntimeError(f"章节计划批次生成返回非数组 JSON: {type(parsed)}")

        from app.domain.models import ChapterPlan
        result: list[ChapterPlan] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            number = int(item.get("number") or 0)
            title = str(item.get("title") or "")
            goal = str(item.get("goal") or item.get("summary") or "")
            if number > 0 and title:
                result.append(ChapterPlan(number=number, title=title, goal=goal))
        return result

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
        chapter_max_tokens = self._chapter_generation_max_tokens(spec, model=resolved_model)

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
            chapter_boundaries = self._chapter_response_boundaries()
            chapter_request_messages = self._render_skill_prompt(
                "chapter-writer",
                mode=self._escape_user_input(spec["mode"]),
                creative_mode=self._escape_user_input(spec.get("creative_mode", spec["mode"])),
                novel_size=self._escape_user_input(spec.get("novel_size", "")),
                title=self._escape_user_input(title),
                logline=self._escape_user_input(summary),
                chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
                chapter_word_range=chapter_word_range,
                chapter_number=item["number"],
                chapter_title=self._escape_user_input(item["title"]),
                chapter_goal=self._escape_user_input(item["goal"]),
                chapter_titles=self._escape_user_input(" / ".join(ch["title"] for ch in chapter_plan)),
                completed_summaries=self._escape_user_input("；".join(completed_summaries) if completed_summaries else "无"),
                previous_chapter_full_text=self._escape_user_input(previous_chapter_full_text),
                current_chapter_existing_draft="无",
                style=self._escape_user_input(self._style_label(spec)),
                style_requirements=self._escape_user_input(self._style_requirements(spec)),
                context_memory=self._escape_user_input(self._context_memory(context_packet)),
                reference_excerpt=self._escape_user_input(self._context_reference(reference_text, context_packet)),
                chapter_meta_boundary=chapter_boundaries["meta"],
                chapter_content_boundary=chapter_boundaries["content"],
                chapter_end_boundary=chapter_boundaries["end"],
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
                max_tokens=chapter_max_tokens,
                response_parser=lambda raw, boundaries=chapter_boundaries: self._parse_chapter_response(
                    raw,
                    boundaries=boundaries,
                ),
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
        chapter_max_tokens = self._chapter_generation_max_tokens(spec, model=resolved_model)
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
        callback_lock = threading.Lock()

        def emit_progress(event: dict[str, Any]) -> None:
            if active_progress_callback is None:
                return
            with callback_lock:
                active_progress_callback(event)

        def emit_exchange(event: dict[str, Any]) -> None:
            if active_exchange_callback is None:
                return
            with callback_lock:
                active_exchange_callback(event)

        def generate_one_chapter(
            plan: dict[str, Any],
            *,
            prompt_completed_text: str,
            prompt_previous_chapter_full_text: str,
            prompt_conversation_history: list[dict[str, str]],
        ) -> tuple[ChapterDraft, list[dict[str, str]]]:
            emit_progress({
                "event_type": "chapter.started",
                "stage": "drafting",
                "unit_id": f"chapter-{plan['number']:02d}",
                "message": f"正在生成第 {plan['number']} 章：{plan['title']}",
                "payload": {
                    "chapter_number": plan["number"],
                    "chapter_title": plan["title"],
                },
            })

            chapter_boundaries = self._chapter_response_boundaries()
            chapter_request_messages = self._render_skill_prompt(
                "chapter-writer",
                mode=self._escape_user_input(spec["mode"]),
                creative_mode=self._escape_user_input(spec.get("creative_mode", spec["mode"])),
                novel_size=self._escape_user_input(spec.get("novel_size", "")),
                title=self._escape_user_input(title),
                logline=self._escape_user_input(summary),
                chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
                chapter_word_range=chapter_word_range,
                chapter_number=plan["number"],
                chapter_title=self._escape_user_input(plan["title"]),
                chapter_goal=self._escape_user_input(plan["goal"]),
                chapter_titles=self._escape_user_input(" / ".join(ch["title"] for ch in chapter_plan)),
                completed_summaries=self._escape_user_input(prompt_completed_text),
                previous_chapter_full_text=self._escape_user_input(prompt_previous_chapter_full_text),
                current_chapter_existing_draft=self._escape_user_input(self._existing_draft_text(draft_seeds, int(plan["number"]))),
                style=self._escape_user_input(self._style_label(spec)),
                style_requirements=self._escape_user_input(self._style_requirements(spec)),
                context_memory=self._escape_user_input(self._context_memory(context_packet)),
                reference_excerpt=self._escape_user_input(self._context_reference(reference_text, context_packet)),
                chapter_meta_boundary=chapter_boundaries["meta"],
                chapter_content_boundary=chapter_boundaries["content"],
                chapter_end_boundary=chapter_boundaries["end"],
            )

            request_messages = self._conversation_request_messages(
                conversation_history=prompt_conversation_history,
                prompt_messages=chapter_request_messages,
            )
            payload, next_conversation_history = self._complete_stream_json_with_cache(
                request_messages=request_messages,
                model=resolved_model,
                stage="drafting",
                exchange_label=f"chapter-{plan['number']:02d}",
                exchange_callback=emit_exchange,
                progress_callback=emit_progress,
                max_tokens=chapter_max_tokens,
                response_parser=lambda raw, boundaries=chapter_boundaries: self._parse_chapter_response(
                    raw,
                    boundaries=boundaries,
                ),
            )
            chapter_draft = ChapterDraft.model_validate(self._normalize_chapter_payload(payload))

            emit_progress({
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
            return chapter_draft, next_conversation_history

        if self._should_parallel_chapter_draft(spec, pair_plans) and batch_index == 0:
            worker_limit = min(self._chapter_parallel_worker_limit(), len(pair_plans))
            parallel_drafts: list[ChapterDraft] = []
            with ThreadPoolExecutor(max_workers=worker_limit, thread_name_prefix="chapter-draft") as executor:
                futures = [
                    executor.submit(
                        generate_one_chapter,
                        plan,
                        prompt_completed_text=completed_text,
                        prompt_previous_chapter_full_text=previous_chapter_full_text,
                        prompt_conversation_history=conversation_history,
                    )
                    for plan in pair_plans
                ]
                for future in as_completed(futures):
                    chapter_draft, _ = future.result()
                    parallel_drafts.append(chapter_draft)
            return sorted(parallel_drafts, key=lambda item: item.number)

        drafts: list[ChapterDraft] = []
        for plan in pair_plans:
            chapter_draft, conversation_history = generate_one_chapter(
                plan,
                prompt_completed_text=completed_text,
                prompt_previous_chapter_full_text=previous_chapter_full_text,
                prompt_conversation_history=conversation_history,
            )

            drafts.append(chapter_draft)
            completed_summaries.append(f"{chapter_draft.title}:{chapter_draft.summary}")
            completed_summaries = completed_summaries[-20:]
            completed_text = "；".join(completed_summaries)
            previous_chapter_full_text = chapter_draft.content or previous_chapter_full_text

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
        chapter_max_tokens = self._chapter_generation_max_tokens(
            spec,
            chapter_count=max(len(current_pair), 1),
            model=resolved_model,
        )
        completed_summaries = [f"{ch['title']}:{ch['summary']}" for ch in completed_chapters]
        completed_text = "；".join(completed_summaries) if completed_summaries else "无"

        request_messages = self._render_skill_prompt(
            "chapter-reviser",
            revision_comment=self._escape_user_input(revision_comment),
            current_chapters_json=json.dumps(current_pair, ensure_ascii=False),
            mode=self._escape_user_input(spec["mode"]),
            creative_mode=self._escape_user_input(spec.get("creative_mode", spec["mode"])),
            novel_size=self._escape_user_input(spec.get("novel_size", "")),
            title=self._escape_user_input(title),
            logline=self._escape_user_input(summary),
            chapter_word_min=spec.get("chapter_word_min", spec.get("target_words", 1800)),
            chapter_word_range=chapter_word_range,
            completed_summaries=self._escape_user_input(completed_text),
            style=self._escape_user_input(self._style_label(spec)),
            style_requirements=self._escape_user_input(self._style_requirements(spec)),
            context_memory=self._escape_user_input(self._context_memory(context_packet)),
            reference_excerpt=self._escape_user_input(self._context_reference(reference_text, context_packet)),
        )

        self._require_gateway_client()
        payload, _ = self._complete_stream_json_with_cache(
            request_messages=request_messages,
            model=resolved_model,
            stage="drafting",
            exchange_label="chapter-pair-revision",
            exchange_callback=active_exchange_callback,
            progress_callback=active_progress_callback,
            max_tokens=chapter_max_tokens,
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
        full_text = self._verification_full_text(completed_chapters)

        request_messages = self._render_skill_prompt(
            "full-text-verifier",
            title=title,
            chapter_plan=" / ".join(f"第{ch['number']}章 {ch['title']}" for ch in chapter_plan),
            full_text=full_text,
        )

        verification_max_tokens = self._verification_max_tokens()
        verification_retry_max_tokens = self._verification_retry_max_tokens(resolved_model, verification_max_tokens)

        self._require_gateway_client()
        payload, _ = self._complete_stream_json_with_cache(
            request_messages=request_messages,
            model=resolved_model,
            stage="verification",
            exchange_label="full-story-verification",
            exchange_callback=active_exchange_callback,
            progress_callback=active_progress_callback,
            max_tokens=verification_max_tokens,
            repair_prompt=_VERIFICATION_JSON_REPAIR_PROMPT,
            empty_truncated_retry_prompt=_VERIFICATION_TRUNCATED_RETRY_PROMPT,
            empty_truncated_retry_max_tokens=verification_retry_max_tokens,
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
            user_comment=self._escape_user_input(review_comment),
            chapters_json=chapters_json,
            mode=self._escape_user_input(spec["mode"]),
            title=self._escape_user_input(title),
            logline=self._escape_user_input(summary),
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
        return self._merge_issue_fix_payload(completed_chapters, payload)

    def _verification_full_text(self, completed_chapters: list[dict[str, Any]]) -> str:
        if bool(getattr(self.settings, "verification_include_full_text", False)):
            return "\n\n".join(
                f"## 第{ch['number']}章 {ch['title']}\n{ch.get('content', '')}"
                for ch in completed_chapters
            )

        excerpt_chars = self._positive_int(
            getattr(self.settings, "verification_excerpt_chars_per_chapter", 1600),
            default=1600,
        )
        blocks: list[str] = []
        for chapter in completed_chapters:
            number = chapter.get("number", "")
            title = chapter.get("title", "")
            summary = str(chapter.get("summary") or "").strip() or "无"
            content = str(chapter.get("content") or "").strip()
            excerpt = self._head_tail_excerpt(content, excerpt_chars)
            blocks.append(
                f"## 第{number}章 {title}\n"
                f"章节摘要：{summary}\n"
                f"正文摘录：\n{excerpt}"
            )
        return "\n\n".join(blocks)

    def _head_tail_excerpt(self, text: str, max_chars: int) -> str:
        content = text.strip()
        if not content:
            return "无"
        if len(content) <= max_chars:
            return content
        edge_chars = max(max_chars // 2, 1)
        head = content[:edge_chars].rstrip()
        tail = content[-edge_chars:].lstrip()
        omitted = len(content) - len(head) - len(tail)
        return f"{head}\n...[中间省略 {omitted} 字]...\n{tail}"

    def _merge_issue_fix_payload(
        self,
        completed_chapters: list[dict[str, Any]],
        payload: Any,
    ) -> list[dict[str, Any]]:
        patch_items = self._issue_fix_patch_items(payload)
        if not patch_items:
            logger.warning("issue-fixer 未返回可用章节补丁，复用原始章节。")
            return [dict(chapter) for chapter in completed_chapters]

        fixed_by_number: dict[int, dict[str, Any]] = {}
        order: list[int] = []
        for chapter in completed_chapters:
            chapter_number = self._safe_chapter_number(chapter.get("number"))
            if chapter_number is None:
                continue
            fixed_by_number[chapter_number] = dict(chapter)
            order.append(chapter_number)

        for item in patch_items:
            if not isinstance(item, dict):
                continue
            chapter_number = self._safe_chapter_number(item.get("number"))
            if chapter_number is None:
                continue
            merged = dict(fixed_by_number.get(chapter_number, {"number": chapter_number}))
            for field_name in ("title", "summary", "content"):
                if field_name in item and item.get(field_name) is not None:
                    merged[field_name] = item.get(field_name)
            fixed_by_number[chapter_number] = merged
            if chapter_number not in order:
                order.append(chapter_number)

        return [fixed_by_number[number] for number in sorted(order)]

    def _issue_fix_patch_items(self, payload: Any) -> list[Any]:
        if isinstance(payload, dict):
            for key in ("patches", "chapters", "fixed_chapters"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            if payload.get("number") is not None:
                return [payload]
            return []
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _safe_chapter_number(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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

    def _chapter_response_boundaries(self) -> dict[str, str]:
        suffix = secrets.token_hex(6)
        return {
            "meta": f"---CHAPTER_META_JSON_BOUNDARY_{suffix}---",
            "content": f"---CHAPTER_CONTENT_BOUNDARY_{suffix}---",
            "end": f"---CHAPTER_END_BOUNDARY_{suffix}---",
        }

    def _parse_chapter_response(self, raw: str, *, boundaries: dict[str, str]) -> dict[str, Any]:
        text = raw.strip()
        meta_boundary = boundaries["meta"]
        content_boundary = boundaries["content"]
        end_boundary = boundaries["end"]
        if meta_boundary not in text and content_boundary not in text and end_boundary not in text:
            return self._strip_and_parse_json(raw)

        meta_start = text.find(meta_boundary)
        content_start = text.find(content_boundary, meta_start + len(meta_boundary))
        if meta_start < 0 or content_start < 0:
            raise GatewayClientError("章节分区响应缺少必要边界，无法解析。")
        end_start = text.find(end_boundary, content_start + len(content_boundary))
        if end_start < 0:
            end_start = len(text)

        meta_raw = text[meta_start + len(meta_boundary):content_start].strip()
        content = text[content_start + len(content_boundary):end_start].strip()
        if not meta_raw:
            raise GatewayClientError("章节分区响应缺少元数据 JSON。")
        payload = self._strip_and_parse_json(meta_raw)
        if not isinstance(payload, dict):
            raise GatewayClientError("章节分区元数据必须是 JSON 对象。")
        payload["content"] = content
        return payload

    def _complete_json_with_cache(
        self,
        request_messages: list[dict[str, str]],
        model: str,
        stage: str,
        exchange_label: str,
        exchange_callback: Callable[[dict[str, Any]], None] | None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        cache_key = self._response_cache_key(model=model, request_messages=request_messages, max_tokens=max_tokens)
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
        request_kwargs: dict[str, Any] = {}
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        payload = self.gateway_client.complete_json(request_messages, model=model, **request_kwargs)
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
        max_tokens: int | None = None,
        response_parser: Callable[[str], Any] | None = None,
        repair_prompt: str = _STREAM_JSON_REPAIR_PROMPT,
        empty_truncated_retry_prompt: str | None = None,
        empty_truncated_retry_max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """流式调用 LLM，实时发射思考链事件，最终解析 JSON。

        比 _complete_json_with_cache 多了：
        - 通过 progress_callback 发射 model.thinking 事件
        - 流式读取 reasoning_content 并实时推送
        - 失败时 fallback 到 _complete_json_with_cache
        """
        # 缓存命中则直接返回（不发 thinking 事件）
        cache_key = self._response_cache_key(model=model, request_messages=request_messages, max_tokens=max_tokens)
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
            full_content, finish_reason = self._call_llm_stream_with_metadata(
                request_messages,
                model,
                progress_callback=active_progress,
                stage=stage,
                unit_id=exchange_label,
                max_tokens=max_tokens,
            )
        except StreamInterruptedAfterStartError:
            logger.warning("流式响应已开始后中断，不执行非流式重放。")
            raise
        except (GatewayClientError, Exception) as exc:
            # fallback 到非流式
            logger.warning("流式调用失败，fallback 到非流式: %s", exc)
            return self._complete_json_with_cache(
                request_messages=request_messages,
                model=model,
                stage=stage,
                exchange_label=exchange_label,
                exchange_callback=exchange_callback,
                max_tokens=max_tokens,
            )

        # 解析 JSON
        parse_started = time.perf_counter()
        parser = response_parser or self._strip_and_parse_json
        parse_request_messages = request_messages
        parse_exchange_label = exchange_label
        if self._should_retry_empty_truncated_response(
            full_content,
            finish_reason,
            max_tokens=max_tokens,
            retry_max_tokens=empty_truncated_retry_max_tokens,
            retry_prompt=empty_truncated_retry_prompt,
        ):
            retry_messages = [dict(item) for item in request_messages] + [
                {"role": "user", "content": empty_truncated_retry_prompt or ""},
            ]
            retry_max_tokens = empty_truncated_retry_max_tokens
            logger.warning(
                "流式 JSON 响应被截断且正文为空，使用更高预算重试: stage=%s exchange_label=%s finish_reason=%s max_tokens=%s retry_max_tokens=%s",
                stage,
                exchange_label,
                finish_reason,
                max_tokens,
                retry_max_tokens,
            )
            full_content, finish_reason = self._call_llm_stream_with_metadata(
                retry_messages,
                model,
                progress_callback=active_progress,
                stage=stage,
                unit_id=f"{exchange_label}-retry",
                max_tokens=retry_max_tokens,
            )
            parse_request_messages = retry_messages
            parse_exchange_label = f"{exchange_label}-retry"
        try:
            payload = parser(full_content)
        except (GatewayClientError, json.JSONDecodeError) as exc:
            self._emit_parse_failed_exchange(
                callback=exchange_callback,
                stage=stage,
                exchange_label=parse_exchange_label,
                model=model,
                request_messages=parse_request_messages,
                raw_response=full_content,
                finish_reason=finish_reason,
                parse_error=str(exc),
            )
            repair_messages = [dict(item) for item in parse_request_messages] + [
                {"role": "assistant", "content": full_content},
                {"role": "user", "content": repair_prompt},
            ]
            repaired_content = ""
            repair_finish_reason: str | None = None
            try:
                repaired_content, repair_finish_reason = self._call_llm_stream_with_metadata(
                    repair_messages,
                    model,
                    progress_callback=active_progress,
                    stage=stage,
                    unit_id=f"{parse_exchange_label}-repair",
                    max_tokens=max_tokens,
                )
                payload = parser(repaired_content)
            except (GatewayClientError, json.JSONDecodeError) as repair_exc:
                self._emit_parse_failed_exchange(
                    callback=exchange_callback,
                    stage=stage,
                    exchange_label=f"{parse_exchange_label}-repair",
                    model=model,
                    request_messages=repair_messages,
                    raw_response=repaired_content,
                    finish_reason=repair_finish_reason,
                    parse_error=str(repair_exc),
                )
                raise exc from repair_exc
        parse_duration_ms = (time.perf_counter() - parse_started) * 1000

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
            parse_duration_ms=parse_duration_ms,
        )
        return payload, conversation_history

    @staticmethod
    def _should_retry_empty_truncated_response(
        content: str,
        finish_reason: str | None,
        *,
        max_tokens: int | None,
        retry_max_tokens: int | None,
        retry_prompt: str | None,
    ) -> bool:
        if not retry_prompt or not retry_max_tokens:
            return False
        if content.strip():
            return False
        normalized_finish_reason = (finish_reason or "").strip().lower()
        if normalized_finish_reason not in _TRUNCATED_FINISH_REASONS:
            return False
        return max_tokens is None or retry_max_tokens > max_tokens

    def _build_story_plan_with_retry(
        self,
        request_messages: list[dict[str, str]],
        model: str,
        stage: str,
        exchange_label: str,
        exchange_callback: Callable[[dict[str, Any]], None] | None,
        max_tokens: int | None = None,
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
                    max_tokens=max_tokens,
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
        parse_duration_ms: float | None = None,
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
                "prompt_diagnostics": self._prompt_cache_diagnostics(request_messages),
                "parse_duration_ms": parse_duration_ms,
            }
        )

    def _emit_parse_failed_exchange(
        self,
        *,
        callback: Callable[[dict[str, Any]], None] | None,
        stage: str,
        exchange_label: str,
        model: str,
        request_messages: list[dict[str, str]],
        raw_response: str,
        finish_reason: str | None,
        parse_error: str,
    ) -> None:
        if callback is None:
            return
        callback(
            {
                "stage": stage,
                "exchange_label": exchange_label,
                "model": model,
                "response_parse_failed": True,
                "request_messages": request_messages,
                "raw_response": raw_response,
                "finish_reason": finish_reason,
                "parse_error": parse_error,
                "prompt_diagnostics": self._prompt_cache_diagnostics(request_messages),
            }
        )

    def _prompt_cache_diagnostics(self, request_messages: list[dict[str, str]]) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        for index, message in enumerate(request_messages):
            content = str(message.get("content") or "")
            parts.append(
                {
                    "index": index,
                    "role": message.get("role") or "",
                    "chars": len(content),
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
                }
            )
        stable_prefix = "\n".join(
            str(message.get("content") or "")
            for message in request_messages
            if message.get("role") == "system"
        )
        dynamic_tail = "\n".join(
            str(message.get("content") or "")
            for message in request_messages
            if message.get("role") != "system"
        )
        return {
            "message_count": len(request_messages),
            "total_chars": sum(int(item["chars"]) for item in parts),
            "stable_prefix_hash": hashlib.sha256(stable_prefix.encode("utf-8")).hexdigest()[:16],
            "dynamic_tail_hash": hashlib.sha256(dynamic_tail.encode("utf-8")).hexdigest()[:16],
            "parts": parts,
        }

    def _response_cache_key(self, model: str, request_messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        payload = json.dumps(
            {
                "model": model,
                "messages": request_messages,
                "max_tokens": max_tokens,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"response:{digest}"

    def _reference_excerpt(self, text: str) -> str:
        cleaned = " ".join(text.strip().split())
        return cleaned if cleaned else "无"

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

    def _chapter_parallel_worker_limit(self) -> int:
        try:
            configured = int(getattr(self.settings, "chapter_parallel_max_workers", 4) or 4)
        except (TypeError, ValueError):
            configured = 4
        return min(max(configured, 1), 6)

    def _chapter_parallel_min_batch_size(self) -> int:
        try:
            configured = int(getattr(self.settings, "chapter_parallel_min_batch_size", 2) or 2)
        except (TypeError, ValueError):
            configured = 2
        return max(configured, 2)

    def _should_parallel_chapter_draft(self, spec: dict[str, Any], pair_plans: list[dict[str, Any]]) -> bool:
        if not bool(getattr(self.settings, "chapter_parallel_draft_enabled", True)):
            return False
        if len(pair_plans) < self._chapter_parallel_min_batch_size():
            return False
        if self._chapter_parallel_worker_limit() <= 1:
            return False
        # 风格仿写更依赖逐章语气承接，默认继续使用顺序路径。
        if str(spec.get("creative_mode") or spec.get("mode") or "").strip() == TaskMode.STYLE_REMIX.value:
            return False
        return True

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
