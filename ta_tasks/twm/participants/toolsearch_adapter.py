"""First real participant spike: ToolSearch (M4 early spike).

!! PROPOSED API - the ToolSearch side is not in this repository. !!
``ToolSearchLike`` is the minimum surface TWM needs; align names with the real
ToolSearch plugin during the Codex integration pass.
"""
from __future__ import annotations

from typing import Protocol

from .api import Issue, RestoreResult


class ToolSearchLike(Protocol):
    def get_task_filter_state(self) -> dict: ...                 # e.g. {"mode": "task", "pinned": [...]}
    def apply_task_filter_state(self, state: dict) -> None: ...
    def set_task_context(self, context: dict) -> None: ...


class ToolSearchParticipant:
    participant_id = "toolsearch"
    schema_version = 1

    def __init__(self, toolsearch: ToolSearchLike):
        self._ts = toolsearch

    def get_workspace_state(self) -> dict:
        return self._ts.get_task_filter_state()

    def validate_workspace_state(self, state: dict) -> list[Issue]:
        if not isinstance(state, dict):
            return [Issue("error", "bad_state", "ToolSearch state must be an object", self.participant_id)]
        return []

    def restore_workspace_state(self, state: dict, context: dict) -> RestoreResult:
        self._ts.apply_task_filter_state(state)
        return RestoreResult(True, applied=sorted(state))

    def get_task_context(self) -> dict:
        return {}

    def on_task_context_changed(self, context: dict) -> None:
        self._ts.set_task_context(context)
