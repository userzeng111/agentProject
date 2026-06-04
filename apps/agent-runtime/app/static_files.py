from __future__ import annotations

from pathlib import Path


def resolve_static_file(static_dir: Path, request_path: str) -> Path | None:
    """解析静态文件路径。"""
    root = Path(static_dir).resolve()
    normalized_path = (request_path or "").strip().lstrip("/")
    if not normalized_path:
        return None
    candidate = (root / normalized_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None
