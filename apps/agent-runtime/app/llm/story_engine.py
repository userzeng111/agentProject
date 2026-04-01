from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
import hashlib
import json
from pathlib import Path
from typing import Any

from app.context.cache_store import FileBackedCacheStore, InMemoryCacheStore, LayeredCacheStore
from langchain_core.prompts import ChatPromptTemplate

from app.domain.models import ChapterDraft, ChapterPlan, DraftResult, StoryPlan, TaskMode
from app.llm.gateway_client import GatewayClientError, OpenAICompatibleGatewayClient
from app.settings.config import Settings

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


class StoryEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gateway_client: OpenAICompatibleGatewayClient | None = None
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
                    "working_title(string), logline(string), world_notes(string[]), character_notes(string[]), "
                    "chapter_plan([{{number:int,title:string,goal:string}}])。\n"
                    "模式：{mode}\n题材：{genre}\n风格：{style}\n目标字数：{target_words}\n用户要求：{prompt}\n"
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
                    "模式：{mode}\n作品标题：{title}\n一句话梗概：{logline}\n"
                    "当前章节序号：{chapter_number}\n当前章节标题：{chapter_title}\n当前章节目标：{chapter_goal}\n"
                    "总章节规划：{chapter_titles}\n已完成章节摘要：{completed_summaries}\n"
                    "上下文记忆：{context_memory}\n参考摘要：{reference_excerpt}\n"
                    "要求：当前章节内容控制在 250 到 450 字，保留冷静克制的中文叙事风格。",
                ),
            ]
        )
        if settings.openai_api_key:
            self.gateway_client = OpenAICompatibleGatewayClient(
                base_url=settings.openai_base_url,
                api_key=settings.openai_api_key,
                model=settings.default_chat_model,
            )
        self._runtime_default_model: str | None = None

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
    ) -> StoryPlan:
        resolved_model = self.resolve_model(model or spec.get("model_id") or spec.get("model"))
        active_exchange_callback = self.exchange_callback or _exchange_callback_var.get()
        prompt_value = self.outline_prompt.invoke(
            {
                "mode": spec["mode"],
                "genre": spec.get("genre", ""),
                "style": spec.get("style", ""),
                "target_words": spec.get("target_words", 1800),
                "prompt": spec.get("prompt", ""),
                "context_memory": self._context_memory(context_packet),
                "reference_excerpt": self._context_reference(reference_text, context_packet),
            }
        )
        if self.gateway_client is not None:
            try:
                request_messages = self._prompt_to_messages(prompt_value)
                payload, _ = self._complete_json_with_cache(
                    request_messages=request_messages,
                    model=resolved_model,
                    stage="planning",
                    exchange_label="outline",
                    exchange_callback=active_exchange_callback,
                )
                return StoryPlan.model_validate(payload)
            except (GatewayClientError, ValueError):
                pass
        prompt_text = self._prompt_to_text(prompt_value)
        title_base = spec.get("title_hint") or spec.get("genre") or "未命名故事"
        title = f"{title_base}：{self._theme_tail(spec['mode'])}"
        if spec["mode"] == TaskMode.SHORT_STORY.value:
            chapters = [
                ChapterPlan(number=1, title="引子", goal="用一个意外场面快速抓住读者"),
                ChapterPlan(number=2, title="推进", goal="让主角在压力下做出选择"),
                ChapterPlan(number=3, title="收束", goal="回收情绪并落下反转或余韵"),
            ]
        else:
            chapters = [
                ChapterPlan(number=1, title="第一章：异样开局", goal="建立冲突与任务入口"),
                ChapterPlan(number=2, title="第二章：关系缠绕", goal="让人物关系和代价变得清晰"),
                ChapterPlan(number=3, title="第三章：逼近真相", goal="推动核心秘密浮出水面"),
                ChapterPlan(number=4, title="第四章：新的选择", goal="让结局落在新的命运节点上"),
            ]

        world_notes = [
            f"故事氛围基于“{spec.get('style') or '有层次的中文叙事'}”推进。",
            f"题材重心是“{spec.get('genre') or '综合幻想'}”，但冲突要落在人物选择上。",
        ]
        if reference_text:
            world_notes.append("需要吸收参考文本中的世界观质地，但避免直接复刻具体段落。")

        character_notes = [
            "主角要有明确缺口，并在故事中被迫面对它。",
            "关键配角不能只做功能人物，要在主角决策上施加真实压力。",
            "反向力量要有可以自洽的动机，而不是纯粹的脸谱化阻碍。",
        ]

        return StoryPlan(
            working_title=title,
            logline=f"围绕“{spec.get('prompt', '')[:40]}”展开，一路逼近无法回避的选择。",
            world_notes=world_notes + [f"策划提示：{prompt_text[:120]}"],
            character_notes=character_notes,
            chapter_plan=chapters,
        )

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
        draft_prompt_value = self.draft_prompt.invoke(
            {
                "mode": spec["mode"],
                "title": title,
                "logline": summary,
                "chapter_titles": " / ".join(ch["title"] for ch in story_plan["chapter_plan"]),
                "context_memory": self._context_memory(context_packet),
                "reference_excerpt": self._context_reference(reference_text, context_packet),
            }
        )
        draft_prompt_text = self._prompt_to_text(draft_prompt_value)

        chapters: list[ChapterDraft] = []
        completed_summaries: list[str] = []
        conversation_history: list[dict[str, str]] = [
            {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
            for item in (initial_conversation_history or [])
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]
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
            chapter_prompt_value = self.chapter_prompt.invoke(
                {
                    "mode": spec["mode"],
                    "title": title,
                    "logline": summary,
                    "chapter_number": item["number"],
                    "chapter_title": item["title"],
                    "chapter_goal": item["goal"],
                    "chapter_titles": " / ".join(ch["title"] for ch in story_plan["chapter_plan"]),
                    "completed_summaries": "；".join(completed_summaries) if completed_summaries else "无",
                    "context_memory": self._context_memory(context_packet),
                    "reference_excerpt": self._context_reference(reference_text, context_packet),
                }
            )
            chapter_draft: ChapterDraft | None = None
            if self.gateway_client is not None:
                try:
                    request_messages = self._conversation_request_messages(
                        conversation_history=conversation_history,
                        prompt_messages=self._prompt_to_messages(chapter_prompt_value),
                    )
                    chapter_payload, conversation_history = self._complete_json_with_cache(
                        request_messages=request_messages,
                        model=resolved_model,
                        stage="drafting",
                        exchange_label=f"chapter-{item['number']:02d}",
                        exchange_callback=active_exchange_callback,
                    )
                    chapter_draft = ChapterDraft.model_validate(chapter_payload)
                except (GatewayClientError, ValueError):
                    chapter_draft = None
            if chapter_draft is None:
                request_messages = self._conversation_request_messages(
                    conversation_history=conversation_history,
                    prompt_messages=self._prompt_to_messages(chapter_prompt_value),
                )
                chapter_draft = ChapterDraft(
                    number=item["number"],
                    title=item["title"],
                    summary=item["goal"],
                    content=self._chapter_content(
                        spec,
                        item["title"],
                        item["goal"],
                        reference_text,
                        context_packet,
                        draft_prompt_text,
                        self._prompt_to_text(chapter_prompt_value),
                    ),
                )
                conversation_history = self._append_assistant_message(
                    request_messages=request_messages,
                    response_payload=chapter_draft.model_dump(mode="json"),
                )
                self._emit_exchange(
                    callback=active_exchange_callback,
                    stage="drafting",
                    exchange_label=f"chapter-{item['number']:02d}",
                    model=resolved_model,
                    cache_hit=False,
                    request_messages=request_messages,
                    conversation_history=conversation_history,
                    response_payload=chapter_draft.model_dump(mode="json"),
                    cache_key=None,
                )
            chapters.append(chapter_draft)
            completed_summaries.append(f"{chapter_draft.title}:{chapter_draft.summary}")
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

        if spec["mode"] == TaskMode.SHORT_STORY.value and len(chapters) <= 3:
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

    def _chapter_content(
        self,
        spec: dict[str, Any],
        chapter_title: str,
        chapter_goal: str,
        reference_text: str,
        context_packet: dict[str, Any] | None,
        draft_prompt_text: str,
        prompt_text: str,
    ) -> str:
        reference_hint = self._context_reference(reference_text, context_packet)
        context_memory = self._context_memory(context_packet)
        style_hint = spec.get("style") or "克制但有张力"
        genre_hint = spec.get("genre") or "幻想"
        return (
            f"{chapter_title}\n\n"
            f"故事以{genre_hint}的外壳展开，但真正推动情节的是人物在压力下做出的选择。"
            f"这一段需要完成的任务是：{chapter_goal}。主角先被一个细小但不容忽视的异样牵住目光，"
            f"随后在对话和行动里逐渐意识到局面已经偏离原来的轨道。"
            f"叙事语气保持“{style_hint}”，句子要有节奏变化，并在段落末尾留下下一步冲动。"
            f"{'参考文本给到的气味是：' + reference_hint if reference_text else '这里不依赖外部原文，只围绕用户需求推进。'}"
            f"策划提示中反复强调“{spec.get('prompt', '')[:24]}”，所以这一段必须把这一点落到具体场面，而不是抽象概念。"
            f"{' 上下文记忆强调：' + context_memory[:80] if context_memory else ''}"
            f"为了让 demo 有完整阅读感，本段最后会抛出一个更难回答的问题，把读者推向下一节。"
            f"\n\n写作基底：{draft_prompt_text[:72]} / {prompt_text[:90]}。"
        )

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

    def _theme_tail(self, mode: str) -> str:
        if mode == TaskMode.LONG_STORY.value:
            return "长夜分章"
        if mode == TaskMode.FANFIC.value:
            return "支线回响"
        if mode == TaskMode.STYLE_REMIX.value:
            return "风格折返"
        return "短篇初稿"
