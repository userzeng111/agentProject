from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


DEFAULT_MODEL_CAPABILITIES_PATH = Path(__file__).resolve().parents[2] / "data" / "model_capabilities.json"


def _settings_path(settings: Any | None = None) -> Path:
    configured = str(getattr(settings, "model_capabilities_path", "") or "").strip()
    return Path(configured) if configured else DEFAULT_MODEL_CAPABILITIES_PATH


@lru_cache(maxsize=16)
def _load_config(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"模型能力配置文件 JSON 损坏：{path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"模型能力配置文件格式不正确：{path}")
    return payload


def load_model_capabilities_config(settings: Any | None = None) -> dict[str, Any]:
    return deepcopy(_load_config(str(_settings_path(settings))))


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _model_config(payload: dict[str, Any], model_id: str | None) -> dict[str, Any]:
    models = payload.get("models")
    if not isinstance(models, dict):
        return {}
    item = models.get((model_id or "").strip())
    return item if isinstance(item, dict) else {}


def _merge_numeric(target: dict[str, Any], source: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = _positive_int(source.get(key))
        if value is not None:
            target[key] = value


def resolve_context_window(
    model_id: str | None,
    *,
    settings: Any | None = None,
    base_context_window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = load_model_capabilities_config(settings)
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    model_cfg = _model_config(payload, model_id)

    resolved: dict[str, Any] = {}
    _merge_numeric(
        resolved,
        defaults,
        (
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "recommended_prompt_budget",
            "compression_trigger_tokens",
        ),
    )
    if isinstance(base_context_window, dict):
        _merge_numeric(
            resolved,
            base_context_window,
            (
                "max_input_tokens",
                "max_output_tokens",
                "max_total_tokens",
                "recommended_prompt_budget",
                "compression_trigger_tokens",
            ),
        )
    _merge_numeric(
        resolved,
        model_cfg,
        (
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "recommended_prompt_budget",
            "compression_trigger_tokens",
        ),
    )

    max_input = _positive_int(resolved.get("max_input_tokens"))
    max_output = _positive_int(resolved.get("max_output_tokens"))
    if max_input is not None and max_output is not None:
        resolved["max_total_tokens"] = _positive_int(resolved.get("max_total_tokens")) or max_input + max_output
    return resolved


def apply_context_window_config(
    capabilities: dict[str, Any],
    model_id: str | None,
    *,
    settings: Any | None = None,
) -> dict[str, Any]:
    next_capabilities = deepcopy(capabilities)
    base_context = next_capabilities.get("context_window")
    if not isinstance(base_context, dict):
        base_context = {}
    next_capabilities["context_window"] = resolve_context_window(
        model_id,
        settings=settings,
        base_context_window=base_context,
    )
    return next_capabilities


def resolve_generation_max_tokens(model_id: str | None, *, settings: Any | None = None) -> int | None:
    payload = load_model_capabilities_config(settings)
    model_cfg = _model_config(payload, model_id)
    model_generation = model_cfg.get("generation") if isinstance(model_cfg.get("generation"), dict) else {}
    root_generation = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}

    for source in (model_generation, root_generation):
        value = _positive_int(source.get("max_tokens"))
        if value is not None:
            return value

    context = resolve_context_window(model_id, settings=settings)
    return _positive_int(context.get("max_output_tokens"))
