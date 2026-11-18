"""Local, privacy-preserving task tool usage statistics (M8).

Only aggregate counters and timestamps are stored. No arguments, layer names,
paths, user-entered text, or tool outputs are collected. The store is separate
from project definitions so clearing analytics cannot alter user-authored tasks.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .events import EventBus, Events
from .schemas import utc_now_iso

USAGE_SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class UsageError(ValueError):
    """Raised when usage data or identifiers are invalid."""


@dataclass(frozen=True)
class ToolUsage:
    tool_id: str
    count: int
    first_used: str
    last_used: str


def _identifier(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(value):
        raise UsageError(f"{label} must be a stable identifier (letters, digits, . _ : / -)")
    return value


def validate_tool_id(value: str) -> str:
    """Validate and normalize a public, privacy-safe tool identifier."""
    return _identifier(value, "tool_id")


class ToolUsageStore:
    """Atomic JSON store for aggregate, per-task tool usage.

    Collection is disabled when ``enabled`` is false. This explicit gate is
    useful for managed deployments and future cloud consent policy.
    """

    def __init__(self, path: str | os.PathLike, enabled: bool = True):
        self.path = Path(path)
        self.enabled = bool(enabled)
        self._data = self._load()

    def _empty(self) -> dict:
        return {"schema_version": USAGE_SCHEMA_VERSION, "tasks": {}}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UsageError(f"Usage statistics are unreadable: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != USAGE_SCHEMA_VERSION:
            raise UsageError("Unsupported usage statistics schema")
        if not isinstance(data.get("tasks"), dict):
            raise UsageError("Usage statistics tasks must be an object")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(self._data, indent=2, sort_keys=True, ensure_ascii=False)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def record(self, task_id: str, tool_id: str, occurred_at: str | None = None) -> bool:
        if not self.enabled:
            return False
        task_id = _identifier(task_id, "task_id")
        tool_id = _identifier(tool_id, "tool_id")
        ts = occurred_at or utc_now_iso()
        tools = self._data["tasks"].setdefault(task_id, {})
        item = tools.setdefault(tool_id, {"count": 0, "first_used": ts, "last_used": ts})
        item["count"] = int(item.get("count", 0)) + 1
        item["last_used"] = ts
        item.setdefault("first_used", ts)
        self._save()
        return True

    def ranked(self, task_id: str, limit: int = 20) -> list[ToolUsage]:
        task_id = _identifier(task_id, "task_id")
        raw = self._data["tasks"].get(task_id, {})
        rows = [ToolUsage(tool_id, int(v.get("count", 0)), str(v.get("first_used", "")),
                          str(v.get("last_used", ""))) for tool_id, v in raw.items()]
        rows.sort(key=lambda x: (x.count, x.last_used, x.tool_id), reverse=True)
        return rows[:max(0, int(limit))]

    def recent(self, task_id: str, limit: int = 20) -> list[ToolUsage]:
        rows = self.ranked(task_id, limit=1_000_000)
        rows.sort(key=lambda x: (x.last_used, x.tool_id), reverse=True)
        return rows[:max(0, int(limit))]

    def clear(self, task_id: str | None = None) -> None:
        if task_id is None:
            self._data = self._empty()
        else:
            task_id = _identifier(task_id, "task_id")
            self._data["tasks"].pop(task_id, None)
        self._save()

    def attach(self, bus: EventBus) -> callable:
        """Record well-formed ``tool.used`` events; malformed events are ignored by EventBus isolation."""
        def handler(event: str, task_id: str = "", tool_id: str = "", **_payload) -> None:
            self.record(task_id, tool_id)

        return bus.subscribe(Events.TOOL_USED, handler)
