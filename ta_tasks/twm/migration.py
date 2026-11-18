"""Explicit schema migration framework (spec s14.2). Starts empty at v1.

Register a step with ``@migration(from_version)``; each step returns a *new*
dict at ``from_version + 1``. Steps should be reversible where practical, and
must preserve unknown fields.
"""
from __future__ import annotations

import copy
from typing import Callable

from .schemas import SCHEMA_VERSION, SchemaError, SchemaTooNew

_STEPS: dict[int, Callable[[dict], dict]] = {}


def migration(from_version: int):
    def deco(fn: Callable[[dict], dict]):
        _STEPS[from_version] = fn
        return fn

    return deco


@migration(1)
def _v1_to_v2(data: dict) -> dict:
    """Add explicit project settings and per-profile capture selections."""
    out = copy.deepcopy(data)
    project = out.setdefault("project", {})
    project.setdefault("settings", {})
    for profile in out.get("workspace_profiles", []):
        profile.setdefault("capture_options", {})
    return out


def migrate(data: dict) -> dict:
    """Upgrade ``data`` to SCHEMA_VERSION. Raises SchemaTooNew if newer."""
    ver = data.get("schema_version")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        raise SchemaError("document.schema_version: missing or not a positive integer")
    if ver > SCHEMA_VERSION:
        raise SchemaTooNew(ver)
    out = copy.deepcopy(data)
    while ver < SCHEMA_VERSION:
        step = _STEPS.get(ver)
        if step is None:
            raise SchemaError(f"No migration registered from schema v{ver}")
        out = step(out)
        out["schema_version"] = ver = ver + 1
    return out
