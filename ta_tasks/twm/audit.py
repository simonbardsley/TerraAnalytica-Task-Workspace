"""Append-only, hash-chained audit log (JSON Lines).

Each entry carries ``prev`` (hash of the previous entry) and its own ``hash``, so
edits, deletions or re-ordering are *detectable* by ``verify()``.

Honest limit: this is tamper-EVIDENT, not tamper-PROOF. Someone with write access
to the whole directory can rebuild the chain. The git store pins the chain head in
each commit trailer, and signed commits / an off-machine copy strengthen this.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .events import EventBus
from .logging_utils import get_logger
from .schemas import utc_now_iso
from .security import scrub_secrets

log = get_logger("audit")

GENESIS = "0" * 64
# Payload keys that are safe, small identifiers worth recording.
_KEEP = ("task_id", "old_task_id", "new_task_id", "profile_id", "participant_id", "role",
         "tool_id", "message")


def _canonical(entry: dict) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(entry_without_hash: dict) -> str:
    return hashlib.sha256(_canonical(entry_without_hash)).hexdigest()


def current_actor() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "unknown"


@dataclass
class VerifyResult:
    ok: bool
    problems: list[str]
    entries: int
    head: str


class AuditLog:
    def __init__(self, path: str | os.PathLike, actor: str | None = None):
        self.path = Path(path)
        self.actor = actor or current_actor()
        self._seq, self._head = self._tail()

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, GENESIS
        last = None
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if last is None:
            return 0, GENESIS
        try:
            e = json.loads(last)
            return int(e["seq"]), str(e["hash"])
        except (ValueError, KeyError, TypeError):
            log.error("Audit log tail unreadable; verify() will report details")
            return 0, GENESIS

    @property
    def head(self) -> str:
        return self._head

    def append(self, event: str, **data: Any) -> dict:
        simple = (str, int, float, bool, type(None), list, dict)
        safe = scrub_secrets({k: v for k, v in data.items() if isinstance(v, simple)})
        entry = {"seq": self._seq + 1, "ts": utc_now_iso(), "actor": self.actor,
                 "event": event, "data": safe, "prev": self._head}
        entry["hash"] = _digest(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._seq, self._head = entry["seq"], entry["hash"]
        return entry

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        return out

    def verify(self) -> VerifyResult:
        problems: list[str] = []
        prev, n = GENESIS, 0
        try:
            entries = self.entries()
        except ValueError as exc:
            return VerifyResult(False, [f"unparseable line: {exc}"], 0, GENESIS)
        for i, e in enumerate(entries, start=1):
            n = i
            body = {k: v for k, v in e.items() if k != "hash"}
            if e.get("seq") != i:
                problems.append(f"entry {i}: sequence number is {e.get('seq')} (gap or reorder)")
            if e.get("prev") != prev:
                problems.append(f"entry {i}: prev-hash mismatch (entry removed or altered)")
            if e.get("hash") != _digest(body):
                problems.append(f"entry {i}: content hash mismatch (entry edited)")
            prev = e.get("hash", "")
        return VerifyResult(not problems, problems, n, prev or GENESIS)

    # ------------------------------------------------------------ bus wiring
    def attach(self, bus: EventBus) -> None:
        """Record every TWM event as a compact, secret-free audit entry."""
        def handler(event: str, **payload: Any) -> None:
            data = {k: payload[k] for k in _KEEP if k in payload}
            task = payload.get("task")
            if task is not None and hasattr(task, "id"):
                data.setdefault("task_id", task.id)
            self.append(event, **data)

        bus.subscribe(EventBus.WILDCARD, handler)
