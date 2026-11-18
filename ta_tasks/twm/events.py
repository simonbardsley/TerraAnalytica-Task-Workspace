"""Event names (spec s20) and a small in-process event bus (M0)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from .logging_utils import get_logger

log = get_logger("events")


class Events:
    TASK_ABOUT_TO_CHANGE = "task.about_to_change"
    TASK_CHANGED = "task.changed"
    WORKSPACE_CAPTURE_STARTED = "workspace.capture_started"
    WORKSPACE_CAPTURED = "workspace.captured"
    WORKSPACE_RESTORE_STARTED = "workspace.restore_started"
    WORKSPACE_RESTORE_WARNING = "workspace.restore_warning"
    WORKSPACE_RESTORED = "workspace.restored"
    WORKSPACE_ROLLBACK = "workspace.rollback"
    CONTEXT_CHANGED = "context.changed"
    PARTICIPANT_REGISTERED = "participant.registered"
    PARTICIPANT_UNAVAILABLE = "participant.unavailable"
    ROLES_RESOLVED = "roles.resolved"
    ROLE_BINDING_CHANGED = "role.binding_changed"
    TOOL_USED = "tool.used"
    WORKFLOW_PROGRESS_CHANGED = "workflow.progress_changed"


Handler = Callable[..., None]


class EventBus:
    """Synchronous pub/sub. A failing subscriber never breaks the publisher."""

    WILDCARD = "*"

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> Callable[[], None]:
        self._subs[event].append(handler)

        def unsubscribe() -> None:
            if handler in self._subs[event]:
                self._subs[event].remove(handler)

        return unsubscribe

    def publish(self, event: str, **payload: Any) -> None:
        for handler in list(self._subs.get(event, ())) + list(self._subs.get(self.WILDCARD, ())):
            try:
                handler(event=event, **payload)
            except Exception:  # noqa: BLE001 - isolation is the point
                log.exception("Subscriber failed for %s", event)
