"""Participant API (M4, spec s8). Labs register small, versioned adapters.

Isolation rules enforced here, not left to adapters:
* one participant failing never aborts the others;
* a missing participant yields a warning + ``participant.unavailable``;
* stored state newer than the adapter understands is declined, not forced;
* captured state is scrubbed of credential-like keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..events import EventBus, Events
from ..logging_utils import get_logger
from ..security import scrub_secrets

log = get_logger("participants")


@dataclass
class Issue:
    severity: str          # "info" | "warning" | "error"
    code: str
    message: str
    participant_id: str = ""


@dataclass
class RestoreResult:
    ok: bool = True
    applied: list[str] = field(default_factory=list)
    declined: list[str] = field(default_factory=list)  # fields declined as invalid/obsolete
    issues: list[Issue] = field(default_factory=list)


@runtime_checkable
class TAWorkspaceParticipant(Protocol):
    participant_id: str
    schema_version: int

    def get_workspace_state(self) -> dict: ...
    def restore_workspace_state(self, state: dict, context: dict) -> RestoreResult: ...
    def get_task_context(self) -> dict: ...
    def on_task_context_changed(self, context: dict) -> None: ...
    def validate_workspace_state(self, state: dict) -> list[Issue]: ...


class ParticipantRegistry:
    def __init__(self, bus: EventBus | None = None):
        self.bus = bus or EventBus()
        self._parts: dict[str, TAWorkspaceParticipant] = {}

    # ------------------------------------------------------------ lifecycle
    def register(self, participant: TAWorkspaceParticipant) -> None:
        if not isinstance(participant, TAWorkspaceParticipant):
            raise TypeError("Object does not implement the TAWorkspaceParticipant contract")
        pid = participant.participant_id
        if pid in self._parts:
            raise ValueError(f"Participant '{pid}' already registered")
        self._parts[pid] = participant
        self.bus.publish(Events.PARTICIPANT_REGISTERED, participant_id=pid)

    def unregister(self, participant_id: str) -> None:
        self._parts.pop(participant_id, None)

    def ids(self) -> list[str]:
        return sorted(self._parts)

    def __contains__(self, pid: str) -> bool:
        return pid in self._parts

    # -------------------------------------------------------------- capture
    def capture_all(self, only: set[str] | None = None) -> tuple[dict[str, dict], list[Issue]]:
        states: dict[str, dict] = {}
        issues: list[Issue] = []
        for pid, p in self._parts.items():
            if only is not None and pid not in only:
                continue
            try:
                states[pid] = {"schema_version": p.schema_version,
                               "state": scrub_secrets(p.get_workspace_state())}
            except Exception as exc:  # noqa: BLE001
                log.exception("Capture failed for %s", pid)
                issues.append(Issue("error", "capture_failed", f"{type(exc).__name__}: {exc}", pid))
        return states, issues

    # -------------------------------------------------------------- restore
    def restore_all(self, stored: dict[str, dict], context: dict) -> dict[str, RestoreResult]:
        results: dict[str, RestoreResult] = {}
        for pid, wrapper in stored.items():
            p = self._parts.get(pid)
            if p is None:
                self.bus.publish(Events.PARTICIPANT_UNAVAILABLE, participant_id=pid)
                results[pid] = RestoreResult(False, issues=[Issue(
                    "warning", "unavailable", f"'{pid}' is not available; its state was skipped", pid)])
                continue
            results[pid] = self._restore_one(p, wrapper, context)
        return results

    def _restore_one(self, p: TAWorkspaceParticipant, wrapper: dict, context: dict) -> RestoreResult:
        pid = p.participant_id
        try:
            stored_ver = int(wrapper.get("schema_version", 0))
            state = wrapper.get("state", {})
            if stored_ver > p.schema_version:
                return RestoreResult(False, issues=[Issue(
                    "warning", "state_too_new",
                    f"Stored state v{stored_ver} is newer than adapter v{p.schema_version}", pid)])
            issues = p.validate_workspace_state(state)
            if any(i.severity == "error" for i in issues):
                return RestoreResult(False, issues=issues)
            result = p.restore_workspace_state(state, context)
            result.issues = issues + result.issues
            return result
        except Exception as exc:  # noqa: BLE001 - participant isolation
            log.exception("Restore failed for %s", pid)
            return RestoreResult(False, issues=[Issue(
                "error", "restore_failed", f"{type(exc).__name__}: {exc}", pid)])

    # -------------------------------------------------------------- context
    def broadcast_context(self, context: dict) -> None:
        for pid, p in self._parts.items():
            try:
                p.on_task_context_changed(context)
            except Exception:  # noqa: BLE001
                log.exception("on_task_context_changed failed for %s", pid)

    def gather_context(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for pid, p in self._parts.items():
            try:
                out[pid] = scrub_secrets(p.get_task_context())
            except Exception:  # noqa: BLE001
                log.exception("get_task_context failed for %s", pid)
        return out
