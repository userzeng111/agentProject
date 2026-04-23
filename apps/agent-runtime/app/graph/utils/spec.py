from __future__ import annotations

from typing import Any


def build_normalized_spec(
    payload: dict[str, Any],
    *,
    novel_skill_service: Any | None = None,
    style_profile_service: Any | None = None,
) -> dict[str, Any]:
    requested_target_words = int(
        payload.get("chapter_word_min", payload.get("target_words", 1800)) or 1800
    )
    style = str(payload.get("style", "")).strip()
    style_profile_id = str(payload.get("style_profile_id", "")).strip()
    creative_mode = _resolve_creative_mode(payload)
    novel_size = _resolve_novel_size(payload)
    chapter_count_range = _chapter_count_range(payload, novel_size)
    chapter_word_min = max(requested_target_words, 600)
    chapter_word_max = max(int(chapter_word_min * 1.3), chapter_word_min)
    runtime_context: dict[str, Any] = {}
    if novel_skill_service is not None and hasattr(novel_skill_service, "build_runtime_context"):
        runtime_context = novel_skill_service.build_runtime_context(
            mode=creative_mode,
            style_profile_id=style_profile_id,
            custom_style=style,
        )
    else:
        runtime_profile = None
        if (
            style_profile_service is not None
            and creative_mode in {"fanfic", "style_remix"}
            and style_profile_id
        ):
            runtime_profile = style_profile_service.build_runtime_profile(style_profile_id, style)
        runtime_context = {
            "workflow_guidance": "",
            "style_profile_id": style_profile_id,
            "style_profile_name": str((runtime_profile or {}).get("name") or ""),
            "style_profile": runtime_profile or {},
            "canon_guidance": str((runtime_profile or {}).get("canon_summary") or ""),
            "style_guidance": (
                str((runtime_profile or {}).get("style_summary") or style)
                if creative_mode == "style_remix"
                else style
            ),
            "active_package_ids": [],
        }
    return {
        "mode": payload["mode"],
        "creative_mode": creative_mode,
        "novel_size": novel_size,
        "prompt": str(payload.get("prompt", "")).strip(),
        "genre": str(payload.get("genre", "")).strip(),
        "style": style,
        "workflow_guidance": str(runtime_context.get("workflow_guidance") or ""),
        "style_profile_id": str(runtime_context.get("style_profile_id") or style_profile_id),
        "style_profile_name": str(runtime_context.get("style_profile_name") or ""),
        "style_profile": runtime_context.get("style_profile") or {},
        "canon_guidance": str(runtime_context.get("canon_guidance") or ""),
        "style_guidance": str(runtime_context.get("style_guidance") or style),
        "novel_skill_packages": list(runtime_context.get("active_package_ids") or []),
        "requested_target_words": requested_target_words,
        "target_words": chapter_word_min,
        "chapter_word_min": chapter_word_min,
        "chapter_word_max": chapter_word_max,
        "chapter_word_range_text": f"{chapter_word_min} 到 {chapter_word_max}",
        "target_chapter_count": chapter_count_range["target"],
        "chapter_count_min": chapter_count_range["min"],
        "chapter_count_max": chapter_count_range["max"],
        "chapter_count_range": {
            "min": chapter_count_range["min"],
            "max": chapter_count_range["max"],
        },
        "chapter_count_range_text": _chapter_count_range_text(chapter_count_range),
        "audience": str(payload.get("audience", "")).strip(),
        "banned": str(payload.get("banned", "")).strip(),
        "title_hint": str(payload.get("title_hint", "")).strip(),
        "model_id": str(payload.get("model_id", payload.get("model", ""))).strip(),
    }


def _chapter_batch_size(spec: dict[str, Any], *, completed_count: int, total_chapters: int) -> int:
    remaining = max(total_chapters - completed_count, 0)
    if remaining <= 0:
        return 0
    default_batch_size = 2
    if _is_style_remix(spec) and total_chapters > 2:
        default_batch_size = 2 if completed_count == 0 else 1
    return min(default_batch_size, remaining)


def _resolve_creative_mode(payload: dict[str, Any]) -> str:
    creative_mode = str(payload.get("creative_mode") or "").strip()
    if creative_mode:
        return creative_mode
    mode = str(payload.get("mode") or "").strip()
    if mode == "fanfic":
        return "fanfic"
    if mode == "style_remix":
        return "style_remix"
    return "original"


def _resolve_novel_size(payload: dict[str, Any]) -> str:
    novel_size = str(payload.get("novel_size") or "").strip()
    if novel_size:
        return novel_size
    mode = str(payload.get("mode") or "").strip()
    if mode == "short_story":
        return "short"
    if mode == "fanfic":
        return "medium"
    return "long"


def _default_target_chapter_count(novel_size: str) -> int:
    if novel_size == "short":
        return 8
    if novel_size == "medium":
        return 80
    return 400


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _chapter_count_range(payload: dict[str, Any], novel_size: str) -> dict[str, int]:
    target = _positive_int(payload.get("target_chapter_count")) or _default_target_chapter_count(novel_size)
    lower = _positive_int(payload.get("chapter_count_min")) or max(1, int(target * 0.9))
    upper = _positive_int(payload.get("chapter_count_max")) or max(lower, int(-(-target * 11 // 10)))
    return {"target": target, "min": lower, "max": upper}


def _chapter_count_range_text(chapter_count_range: dict[str, int | None]) -> str:
    lower = int(chapter_count_range.get("min") or 1)
    upper = chapter_count_range.get("max")
    if upper is None:
        return f"{lower} 章及以上"
    return f"{lower} 到 {int(upper)} 章"


def _is_style_remix(spec: dict[str, Any]) -> bool:
    return str(spec.get("creative_mode") or spec.get("mode") or "").strip() == "style_remix"
