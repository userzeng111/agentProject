from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


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
        payload = json.loads(path.read_text(encoding="utf-8"))
        expires_at = float(payload.get("expires_at") or 0.0)
        if expires_at <= self.time_func():
            path.unlink(missing_ok=True)
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
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        for item in self.root_dir.glob("*.json"):
            item.unlink(missing_ok=True)

    def cleanup(self) -> None:
        for item in self.root_dir.glob("*.json"):
            try:
                payload = json.loads(item.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                item.unlink(missing_ok=True)
                continue
            if float(payload.get("expires_at") or 0.0) <= self.time_func():
                item.unlink(missing_ok=True)

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root_dir / f"{digest}.json"

    def _serialize(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value


class LayeredCacheStore:
    def __init__(self, stores: list[Any]) -> None:
        self.stores = stores

    def get(self, key: str) -> Any | None:
        cached_value: Any | None = None
        for index, store in enumerate(self.stores):
            cached_value = store.get(key)
            if cached_value is None:
                continue
            for warm_store in self.stores[:index]:
                warm_store.set(key, cached_value)
            return cached_value
        return None

    def set(self, key: str, value: Any) -> None:
        for store in self.stores:
            store.set(key, value)

    def clear(self) -> None:
        for store in self.stores:
            if hasattr(store, "clear"):
                store.clear()

    def cleanup(self) -> None:
        for store in self.stores:
            if hasattr(store, "cleanup"):
                store.cleanup()
