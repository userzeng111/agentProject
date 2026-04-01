from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.context.manager import ContextManager
from app.context.models import ModelContextProfile, ReferenceMaterial
from app.llm.model_catalog import ModelCatalogService
from app.llm.story_engine import StoryEngine

try:
    from langgraph.checkpoint.memory import MemorySaver
except ImportError:  # pragma: no cover
    from langgraph.checkpoint.memory import InMemorySaver as MemorySaver


class WorkflowState(TypedDict, total=False):
    task_id: str
    input_payload: dict[str, Any]
    reference_text: str
    source_assets: list[dict[str, Any]]
    normalized_spec: dict[str, Any]
    outline_context_packet: dict[str, Any]
    outline_context_snapshot: dict[str, Any]
    story_plan: dict[str, Any]
    approved: bool
    review_comment: str
    draft_context_packet: dict[str, Any]
    draft_context_snapshot: dict[str, Any]
    draft_conversation_seed: list[dict[str, str]]
    draft_result: dict[str, Any]
    cancelled: bool


def build_graph(
    engine: StoryEngine,
    context_manager: ContextManager | None = None,
    model_catalog: ModelCatalogService | None = None,
    history_loader: Callable[[str, str, str], list[dict[str, str]]] | None = None,
):
    active_context_manager = context_manager or ContextManager()
    active_model_catalog = model_catalog
    active_history_loader = history_loader

    def normalize_request(state: WorkflowState) -> WorkflowState:
        payload = state["input_payload"]
        return {
            "normalized_spec": {
                "mode": payload["mode"],
                "prompt": payload["prompt"].strip(),
                "genre": payload.get("genre", "").strip(),
                "style": payload.get("style", "").strip(),
                "target_words": payload.get("target_words", 1800),
                "audience": payload.get("audience", "").strip(),
                "banned": payload.get("banned", "").strip(),
                "title_hint": payload.get("title_hint", "").strip(),
                "model_id": payload.get("model_id", payload.get("model", "")).strip(),
            }
        }

    def prepare_outline_context(state: WorkflowState) -> WorkflowState:
        snapshot = active_context_manager.build_snapshot(
            task_id=state["task_id"],
            stage="planning",
            instruction=_outline_instruction(state["normalized_spec"]),
            model_profile=_resolve_model_profile(
                active_model_catalog,
                state["normalized_spec"].get("model_id"),
            ),
            references=_build_references(state),
            memory_items=[],
        )
        return {
            "outline_context_packet": snapshot.packet.model_dump(mode="json"),
            "outline_context_snapshot": snapshot.model_dump(mode="json"),
        }

    def plan_story(state: WorkflowState) -> WorkflowState:
        story_plan = engine.build_story_plan(
            state["normalized_spec"],
            state.get("reference_text", ""),
            context_packet=state.get("outline_context_packet"),
            model=state["normalized_spec"].get("model_id"),
        )
        return {"story_plan": story_plan.model_dump()}

    def review_outline(state: WorkflowState) -> WorkflowState:
        review = interrupt(
            {
                "type": "outline_review",
                "version": "v1",
                "summary": "请确认大纲是否可以进入正文起草。",
                "story_plan": state["story_plan"],
                "risk_flags": [
                    "这是 demo 版本，大纲以稳定展示工作流为优先。",
                    "若上传了参考小说，系统只提炼风味和设定气质，不直接复刻原文。",
                ],
            }
        )
        approved = bool(review.get("approved")) if isinstance(review, dict) else bool(review)
        comment = review.get("comment", "") if isinstance(review, dict) else ""
        return {"approved": approved, "review_comment": comment}

    def prepare_draft_context(state: WorkflowState) -> WorkflowState:
        snapshot = active_context_manager.build_snapshot(
            task_id=state["task_id"],
            stage="drafting",
            instruction=_draft_instruction(state["normalized_spec"], state.get("story_plan")),
            model_profile=_resolve_model_profile(
                active_model_catalog,
                state["normalized_spec"].get("model_id"),
            ),
            references=_build_references(state),
            memory_items=_draft_memory_items(state),
        )
        return {
            "draft_context_packet": snapshot.packet.model_dump(mode="json"),
            "draft_context_snapshot": snapshot.model_dump(mode="json"),
            "draft_conversation_seed": _draft_conversation_seed(
                state,
                history_loader=active_history_loader,
            ),
        }

    def draft_story(state: WorkflowState) -> WorkflowState:
        draft_result = engine.generate_draft(
            state["normalized_spec"],
            state["story_plan"],
            state.get("reference_text", ""),
            context_packet=state.get("draft_context_packet"),
            model=state["normalized_spec"].get("model_id"),
            progress_callback=getattr(engine, "progress_callback", None),
            initial_conversation_history=state.get("draft_conversation_seed"),
        )
        return {"draft_result": draft_result.model_dump(), "cancelled": False}

    def cancel_task(state: WorkflowState) -> WorkflowState:
        return {"cancelled": True}

    def route_after_review(state: WorkflowState) -> str:
        return "draft_story" if state.get("approved") else "cancel_task"

    graph = StateGraph(WorkflowState)
    graph.add_node("normalize_request", normalize_request)
    graph.add_node("prepare_outline_context", prepare_outline_context)
    graph.add_node("plan_story", plan_story)
    graph.add_node("review_outline", review_outline)
    graph.add_node("prepare_draft_context", prepare_draft_context)
    graph.add_node("draft_story", draft_story)
    graph.add_node("cancel_task", cancel_task)

    graph.add_edge(START, "normalize_request")
    graph.add_edge("normalize_request", "prepare_outline_context")
    graph.add_edge("prepare_outline_context", "plan_story")
    graph.add_edge("plan_story", "review_outline")
    graph.add_conditional_edges(
        "review_outline",
        route_after_review,
        {"draft_story": "prepare_draft_context", "cancel_task": "cancel_task"},
    )
    graph.add_edge("prepare_draft_context", "draft_story")
    graph.add_edge("draft_story", END)
    graph.add_edge("cancel_task", END)

    return graph.compile(checkpointer=MemorySaver())


def _resolve_model_profile(
    model_catalog: ModelCatalogService | None,
    model_id: str | None,
) -> ModelContextProfile:
    fallback_model_id = (model_id or "").strip() or "gpt-5.4"
    if model_catalog is None:
        return ModelContextProfile(
            model_id=fallback_model_id,
            provider="openai_compatible",
            max_input_tokens=128000,
            max_output_tokens=8192,
            reserved_output_tokens=2048,
        )
    profile = model_catalog.get_model_profile(fallback_model_id)
    capabilities = profile.get("capabilities") if isinstance(profile.get("capabilities"), dict) else {}
    context_window = capabilities.get("context_window") if isinstance(capabilities.get("context_window"), dict) else {}
    return ModelContextProfile(
        model_id=str(profile.get("id") or fallback_model_id),
        provider=str(profile.get("provider") or "openai_compatible"),
        max_input_tokens=int(context_window.get("max_input_tokens") or 128000),
        max_output_tokens=int(context_window.get("max_output_tokens") or 8192),
        reserved_output_tokens=min(
            int(context_window.get("max_output_tokens") or 2048),
            int(context_window.get("max_input_tokens") or 128000),
        ),
        supports_runtime_cache=bool(
            (capabilities.get("cache") or {}).get("runtime_context_cache", True)
            if isinstance(capabilities.get("cache"), dict)
            else True
        ),
        profile_version=str((profile.get("metadata") or {}).get("profile_version") or "v1")
        if isinstance(profile.get("metadata"), dict)
        else "v1",
    )


def _build_references(state: WorkflowState) -> list[ReferenceMaterial]:
    source_assets = state.get("source_assets") or []
    references: list[ReferenceMaterial] = []
    for index, asset in enumerate(source_assets):
        if not isinstance(asset, dict):
            continue
        content = str(asset.get("content") or "").strip()
        if not content:
            continue
        references.append(
            ReferenceMaterial(
                source_id=str(asset.get("id") or f"source-{index + 1}"),
                title=str(asset.get("filename") or f"参考素材 {index + 1}"),
                content=content,
                priority=max(100 - index, 1),
                metadata={"media_type": asset.get("media_type")},
            )
        )
    if references:
        return references
    reference_text = str(state.get("reference_text") or "").strip()
    if not reference_text:
        return []
    return [
        ReferenceMaterial(
            source_id="reference-text",
            title="参考素材",
            content=reference_text,
            priority=50,
        )
    ]


def _outline_instruction(spec: dict[str, Any]) -> str:
    return (
        f"模式：{spec.get('mode', '')}\n"
        f"题材：{spec.get('genre', '')}\n"
        f"风格：{spec.get('style', '')}\n"
        f"目标字数：{spec.get('target_words', '')}\n"
        f"受众：{spec.get('audience', '')}\n"
        f"禁忌：{spec.get('banned', '')}\n"
        f"标题倾向：{spec.get('title_hint', '')}\n"
        f"创作要求：{spec.get('prompt', '')}"
    ).strip()


def _draft_instruction(spec: dict[str, Any], story_plan: dict[str, Any] | None) -> str:
    title = ""
    logline = ""
    if isinstance(story_plan, dict):
        title = str(story_plan.get("working_title") or "")
        logline = str(story_plan.get("logline") or "")
    return (
        f"模式：{spec.get('mode', '')}\n"
        f"作品标题：{title}\n"
        f"一句话梗概：{logline}\n"
        f"风格要求：{spec.get('style', '')}\n"
        f"禁忌要求：{spec.get('banned', '')}\n"
        f"正文任务：基于既定大纲连续起草小说正文。"
    ).strip()


def _draft_memory_items(state: WorkflowState) -> list[str]:
    story_plan = state.get("story_plan")
    if not isinstance(story_plan, dict):
        return []
    memory_items: list[str] = []
    for note in story_plan.get("world_notes") or []:
        memory_items.append(f"世界观：{note}")
    for note in story_plan.get("character_notes") or []:
        memory_items.append(f"人物：{note}")
    for chapter in story_plan.get("chapter_plan") or []:
        if not isinstance(chapter, dict):
            continue
        memory_items.append(
            f"章节计划：第{chapter.get('number')}章 {chapter.get('title')} - {chapter.get('goal')}"
        )
    return memory_items


def _draft_conversation_seed(
    state: WorkflowState,
    history_loader: Callable[[str, str, str], list[dict[str, str]]] | None = None,
) -> list[dict[str, str]]:
    story_plan = state.get("story_plan")
    normalized_spec = state.get("normalized_spec") or {}
    approval_comment = str(state.get("review_comment") or "").strip()
    followup = approval_comment or "q2: 大纲已确认，请基于这版大纲继续生成正文。"
    planning_history = _load_planning_history(state, history_loader)
    if planning_history:
        return planning_history + [
            {
                "role": "user",
                "content": followup if followup.startswith("q") else f"q2: {followup}",
            }
        ]

    if not isinstance(story_plan, dict):
        return []

    return [
        {
            "role": "system",
            "content": "你是一个中文小说创作助手，需要沿着既有问答上下文继续完成正文写作。",
        },
        {
            "role": "user",
            "content": (
                "q1: 请先根据以下需求生成小说大纲。\n"
                f"创作要求：{normalized_spec.get('prompt', '')}\n"
                f"题材：{normalized_spec.get('genre', '')}\n"
                f"风格：{normalized_spec.get('style', '')}"
            ).strip(),
        },
        {
            "role": "assistant",
            "content": f"a1: {json.dumps(story_plan, ensure_ascii=False)}",
        },
        {
            "role": "user",
            "content": followup if followup.startswith("q") else f"q2: {followup}",
        },
    ]


def _load_planning_history(
    state: WorkflowState,
    history_loader: Callable[[str, str, str], list[dict[str, str]]] | None = None,
) -> list[dict[str, str]]:
    if history_loader is None:
        return []
    task_id = str(state.get("task_id") or "").strip()
    if not task_id:
        return []
    try:
        history = history_loader(task_id, "planning", "outline-history")
    except FileNotFoundError:
        return []
    except Exception:
        return []
    normalized: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip() or "user"
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized
