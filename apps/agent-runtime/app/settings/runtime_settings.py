import json
from pathlib import Path
from typing import Any

_RUNTIME_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "runtime_settings.json"


def _ensure_dir() -> None:
    _RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_runtime_settings() -> dict[str, Any]:
    """读取运行时设置 JSON 文件。"""
    if not _RUNTIME_SETTINGS_PATH.exists():
        return {}
    try:
        with open(_RUNTIME_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_runtime_settings(settings: dict[str, Any]) -> None:
    """保存运行时设置到 JSON 文件。"""
    _ensure_dir()
    with open(_RUNTIME_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_model_protocol_overrides() -> dict[str, str]:
    """获取模型协议覆盖配置。"""
    return get_runtime_settings().get("model_protocol_overrides", {})


def set_model_protocol_override(model_id: str, protocol: str) -> None:
    """设置某个模型的协议覆盖。"""
    settings = get_runtime_settings()
    overrides = settings.setdefault("model_protocol_overrides", {})
    overrides[model_id] = protocol
    save_runtime_settings(settings)


def remove_model_protocol_override(model_id: str) -> None:
    """删除某个模型的协议覆盖。"""
    settings = get_runtime_settings()
    overrides = settings.get("model_protocol_overrides", {})
    if model_id in overrides:
        del overrides[model_id]
        save_runtime_settings(settings)
