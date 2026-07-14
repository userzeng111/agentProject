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


def resolve_spa_static_file(static_dir: Path, request_path: str) -> Path | None:
    """解析 SPA 静态文件，项目动态路径回退到静态导出的项目页壳。"""
    normalized_path = (request_path or "").strip().lstrip("/")
    if not normalized_path:
        return None

    candidate = resolve_static_file(static_dir, normalized_path)
    if candidate is not None:
        return candidate

    index_candidate = resolve_static_file(static_dir, f"{normalized_path.strip('/')}/index.html")
    if index_candidate is not None:
        return index_candidate

    segments = normalized_path.split("/")
    if len(segments) >= 2 and segments[0] == "p":
        return resolve_static_file(static_dir, "p/__placeholder__/index.html")

    return None
