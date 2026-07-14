from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from app.observability import get_logger

logger = get_logger(__name__)


@runtime_checkable
class CacheStore(Protocol):
    """缓存存储统一接口协议。"""

    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...
    def clear(self) -> None: ...
    def cleanup(self) -> None: ...


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class InMemoryCacheStore:
    def __init__(self, ttl_seconds: int = 300, time_func: Callable[[], float] | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self.time_func = time_func or time.monotonic
        self._entries: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self.time_func():
            self._entries.pop(key, None)
            return None
        return copy.deepcopy(entry.value)

    def set(self, key: str, value: Any) -> None:
        expires_at = self.time_func() + self.ttl_seconds
        self._entries[key] = _CacheEntry(value=copy.deepcopy(value), expires_at=expires_at)

    def clear(self) -> None:
        self._entries.clear()

    def cleanup(self) -> None:
        now = self.time_func()
        expired_keys = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired_keys:
            self._entries.pop(key, None)


class FileBackedCacheStore:
    def __init__(
        self,
        root_dir: str | Path,
        ttl_seconds: int = 300,
        time_func: Callable[[], float] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.time_func = time_func or time.monotonic

    def get(self, key: str) -> Any | None:
        path = self._path_for_key(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取磁盘缓存失败: path=%s error=%s", path, exc)
            return None
        expires_at = float(payload.get("expires_at") or 0.0)
        if expires_at <= self.time_func():
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("清理过期磁盘缓存失败: path=%s error=%s", path, exc)
            return None
        return copy.deepcopy(payload.get("value"))

    def set(self, key: str, value: Any) -> None:
        path = self._path_for_key(key)
        serialized = self._serialize(value)
        payload = {
            "key": key,
            "expires_at": self.time_func() + self.ttl_seconds,
            "value": serialized,
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("写入磁盘缓存失败: path=%s error=%s", path, exc)

    def clear(self) -> None:
        for item in self.root_dir.glob("*.json"):
            try:
                item.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("清理磁盘缓存失败: path=%s error=%s", item, exc)

    def cleanup(self) -> None:
        for item in self.root_dir.glob("*.json"):
            try:
                payload = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取磁盘缓存失败，尝试删除: path=%s error=%s", item, exc)
                try:
                    item.unlink(missing_ok=True)
                except OSError as unlink_exc:
                    logger.warning("删除损坏磁盘缓存失败: path=%s error=%s", item, unlink_exc)
                continue
            if float(payload.get("expires_at") or 0.0) <= self.time_func():
                try:
                    item.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("清理过期磁盘缓存失败: path=%s error=%s", item, exc)

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root_dir / f"{digest}.json"

    def _serialize(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value


class LayeredCacheStore:
    def __init__(self, stores: list[CacheStore]) -> None:
        self.stores = stores

    def get(self, key: str) -> Any | None:
        cached_value: Any | None = None
        for index, store in enumerate(self.stores):
            try:
                cached_value = store.get(key)
            except Exception as exc:
                logger.warning("缓存层读取失败: layer=%d key=%s error=%s", index, key, exc)
                continue
            if cached_value is None:
                continue
            logger.debug("缓存命中: layer=%d key=%s", index, key)
            for warm_store in self.stores[:index]:
                try:
                    warm_store.set(key, cached_value)
                except Exception as exc:
                    logger.warning("缓存回填失败: layer=%d key=%s error=%s", index, key, exc)
            return cached_value
        return None

    def set(self, key: str, value: Any) -> None:
        for index, store in enumerate(self.stores):
            try:
                store.set(key, value)
            except Exception as exc:
                logger.warning("缓存写入失败: layer=%d key=%s error=%s", index, key, exc)

    def clear(self) -> None:
        for store in self.stores:
            try:
                store.clear()
            except Exception as exc:
                logger.warning("缓存清空失败: store=%s error=%s", type(store).__name__, exc)

    def cleanup(self) -> None:
        for store in self.stores:
            try:
                store.cleanup()
            except Exception as exc:
                logger.warning("缓存清理失败: store=%s error=%s", type(store).__name__, exc)
