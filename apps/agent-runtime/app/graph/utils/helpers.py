from __future__ import annotations

from typing import Any

from app.context.models import ModelContextProfile, ReferenceMaterial
from app.llm.model_catalog import ModelCatalogService

from app.graph.state import WorkflowState


def _resolve_model_profile(
    model_catalog: ModelCatalogService | None,
    model_id: str | None,
) -> ModelContextProfile:
    requested_model_id = (model_id or "").strip()
    if not requested_model_id:
        raise ValueError("工作流缺少显式模型，无法构建上下文预算。")
    if model_catalog is None:
        raise ValueError("模型目录服务未配置，无法验证当前供应商模型。")
    profile = model_catalog.get_model_profile(requested_model_id)
    source = str((profile.get("metadata") or {}).get("source") or "")
    if "gateway" not in source:
        raise ValueError(f"模型 {requested_model_id} 不在当前供应商模型目录中。")
    capabilities = profile.get("capabilities") if isinstance(profile.get("capabilities"), dict) else {}
    context_window = capabilities.get("context_window") if isinstance(capabilities.get("context_window"), dict) else {}
    max_input_tokens = int(context_window.get("max_input_tokens") or 0)
    max_output_tokens = int(context_window.get("max_output_tokens") or 0)
    if max_input_tokens <= 0 or max_output_tokens <= 0:
        raise ValueError(f"模型 {requested_model_id} 未提供可用上下文窗口。")
    return ModelContextProfile(
        model_id=str(profile.get("id") or requested_model_id),
        provider=str(profile.get("provider") or "openai_compatible"),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        reserved_output_tokens=min(max_output_tokens, max_input_tokens),
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
        f"创作类型：{spec.get('creative_mode', '')}\n"
        f"篇幅规模：{spec.get('novel_size', '')}\n"
        f"题材：{spec.get('genre', '')}\n"
        f"风格：{spec.get('style', '')}\n"
        f"风格实例：{spec.get('style_profile_name', '')}\n"
        f"风格约束：{spec.get('style_guidance', '')}\n"
        f"单章字数下限：{spec.get('chapter_word_min', spec.get('target_words', ''))}\n"
        f"单章字数浮动上限：{spec.get('chapter_word_max', spec.get('target_words', ''))}\n"
        f"章节范围：{spec.get('chapter_count_range_text', '')}\n"
        f"受众：{spec.get('audience', '')}\n"
        f"禁忌：{spec.get('banned', '')}\n"
        f"标题倾向：{spec.get('title_hint', '')}\n"
        f"创作要求：{spec.get('prompt', '')}"
    ).strip()


def _chapter_pair_instruction(spec: dict[str, Any], story_plan: dict[str, Any] | None) -> str:
    title = ""
    logline = ""
    if isinstance(story_plan, dict):
        title = str(story_plan.get("working_title") or "")
        logline = str(story_plan.get("logline") or "")
    return (
        f"模式：{spec.get('mode', '')}\n"
        f"创作类型：{spec.get('creative_mode', '')}\n"
        f"篇幅规模：{spec.get('novel_size', '')}\n"
        f"作品标题：{title}\n"
        f"一句话梗概：{logline}\n"
        f"单章字数下限：{spec.get('chapter_word_min', spec.get('target_words', ''))}\n"
        f"章节范围：{spec.get('chapter_count_range_text', '')}\n"
        f"风格要求：{spec.get('style', '')}\n"
        f"风格实例：{spec.get('style_profile_name', '')}\n"
        f"风格约束：{spec.get('style_guidance', '')}\n"
        f"禁忌要求：{spec.get('banned', '')}\n"
        f"正文任务：基于既定大纲连续起草小说正文，首批可生成两章，后续批次按单章续写。"
    ).strip()


def _planned_chapter_count(story_plan: dict[str, Any] | None) -> int:
    if not isinstance(story_plan, dict):
        return 0
    chapter_plan = story_plan.get("chapter_plan")
    planned = int(story_plan.get("planned_chapter_count") or 0)
    chapter_count = len(chapter_plan) if isinstance(chapter_plan, list) else 0
    return max(planned, chapter_count)


def _normalize_story_plan(story_plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(story_plan, dict):
        return {}
    normalized = dict(story_plan)
    chapter_plan = normalized.get("chapter_plan")
    existing_planned = int(normalized.get("planned_chapter_count") or 0)
    chapter_count = len(chapter_plan) if isinstance(chapter_plan, list) else 0
    normalized["planned_chapter_count"] = max(existing_planned, chapter_count)
    return normalized


def _chapter_pair_memory_items(state: WorkflowState) -> list[str]:
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
