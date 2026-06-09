"""Simple TTL in-memory cache.  Thread-safe via dict operations (GIL)."""
from __future__ import annotations

import time
from typing import Any, Optional

_STORE: dict[str, tuple[float, Any]] = {}  # key → (expire_at, value)


def get(key: str) -> Optional[Any]:
    entry = _STORE.get(key)
    if entry is None:
        return None
    expire_at, value = entry
    if time.monotonic() > expire_at:
        _STORE.pop(key, None)
        return None
    return value


def set(key: str, value: Any, ttl: float = 60.0) -> None:
    _STORE[key] = (time.monotonic() + ttl, value)


def invalidate(key: str) -> None:
    _STORE.pop(key, None)


def clear() -> None:
    _STORE.clear()


def size() -> int:
    return len(_STORE)
