import json
import os
import threading
from pathlib import Path
from typing import Any

_RUNTIME_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "runtime_settings.json"
_RUNTIME_SETTINGS_LOCK = threading.Lock()


def _ensure_dir() -> None:
    _RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_runtime_settings() -> dict[str, Any]:
    """读取运行时设置 JSON 文件。"""
    with _RUNTIME_SETTINGS_LOCK:
        return _read_runtime_settings_unlocked()


def save_runtime_settings(settings: dict[str, Any]) -> None:
    """保存运行时设置到 JSON 文件。"""
    with _RUNTIME_SETTINGS_LOCK:
        _write_runtime_settings_unlocked(settings)


def _read_runtime_settings_unlocked() -> dict[str, Any]:
    if not _RUNTIME_SETTINGS_PATH.exists():
        return {}
    try:
        with open(_RUNTIME_SETTINGS_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"运行时设置文件 JSON 损坏：{_RUNTIME_SETTINGS_PATH}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"运行时设置文件格式不正确：{_RUNTIME_SETTINGS_PATH}")
    return payload


def _write_runtime_settings_unlocked(settings: dict[str, Any]) -> None:
    _ensure_dir()
    tmp_path = _RUNTIME_SETTINGS_PATH.with_suffix(_RUNTIME_SETTINGS_PATH.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, _RUNTIME_SETTINGS_PATH)


def get_model_protocol_overrides() -> dict[str, str]:
    """获取模型协议覆盖配置。"""
    overrides = get_runtime_settings().get("model_protocol_overrides", {})
    return overrides if isinstance(overrides, dict) else {}


def set_model_protocol_override(model_id: str, protocol: str) -> None:
    """设置某个模型的协议覆盖。"""
    with _RUNTIME_SETTINGS_LOCK:
        settings = _read_runtime_settings_unlocked()
        overrides = settings.setdefault("model_protocol_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
            settings["model_protocol_overrides"] = overrides
        overrides[model_id] = protocol
        _write_runtime_settings_unlocked(settings)


def remove_model_protocol_override(model_id: str) -> None:
    """删除某个模型的协议覆盖。"""
    with _RUNTIME_SETTINGS_LOCK:
        settings = _read_runtime_settings_unlocked()
        overrides = settings.get("model_protocol_overrides", {})
        if not isinstance(overrides, dict):
            return
        if model_id in overrides:
            del overrides[model_id]
            _write_runtime_settings_unlocked(settings)
