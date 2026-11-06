"""A content-addressed JSON cache for expensive calls.

Each entry is keyed by the SHA-256 of its namespace and its input, so a rerun repeats only the calls
whose inputs changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

JsonValue = Any


def cache_key(namespace: str, payload: JsonValue) -> str:
    canonical = json.dumps({"namespace": namespace, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JsonCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, namespace: str, payload: JsonValue) -> Path:
        key = cache_key(namespace, payload)
        return self._root / namespace / key[:2] / f"{key}.json"

    def get(self, namespace: str, payload: JsonValue) -> JsonValue | None:
        path = self._path(namespace, payload)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, namespace: str, payload: JsonValue, value: JsonValue) -> None:
        path = self._path(namespace, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    async def get_or_compute(
        self, namespace: str, payload: JsonValue, compute: Callable[[], Awaitable[JsonValue]]
    ) -> JsonValue:
        cached = self.get(namespace, payload)
        if cached is not None:
            return cached
        value = await compute()
        self.put(namespace, payload, value)
        return value
