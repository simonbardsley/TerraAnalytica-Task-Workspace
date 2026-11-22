"""Versioned data contracts (M0): Project, Task, WorkspaceProfile, LayerRef.

Design rules (spec s1, s14):
* A Task says *what* the user is doing; a WorkspaceProfile says *how* the UI is
  configured. Task objects hold no UI state; profiles live in Project.profiles.
* Every persisted object round-trips losslessly. Unknown fields are preserved
  in ``extra`` and written back on save.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

SCHEMA_VERSION = 2
KIND = "ta_task_project"


class SchemaError(ValueError):
    """Raised when persisted data does not satisfy the schema."""


class SchemaTooNew(SchemaError):
    def __init__(self, found: int):
        super().__init__(f"Schema version {found} is newer than supported ({SCHEMA_VERSION})")
        self.found = found


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    ARCHIVED = "archived"


class ProcessingMode(str, Enum):
    """Where a task's heavy processing runs. Tasks may inherit the project default."""

    INHERIT = "inherit"   # task level only; resolves to Project.default_processing
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


# FEATURE GATE: the only processing mode that may be *selected* at this stage. Cloud and hybrid exist in
# the data model for forward compatibility but are disabled; widen this tuple when they are implemented.
AVAILABLE_PROCESSING_MODES: tuple = (ProcessingMode.LOCAL,)


def available_processing_modes() -> tuple:
    """Modes a user may select now (read at call time so tests can widen the gate)."""
    return AVAILABLE_PROCESSING_MODES


class DisplayClass(str, Enum):
    SINGLE_COMPACT = "single_compact"
    SINGLE_STANDARD = "single_standard"
    SINGLE_ULTRAWIDE = "single_ultrawide"
    DUAL_MONITOR = "dual_monitor"
    MULTI_MONITOR = "multi_monitor"


# Free-text task types are accepted; these are the built-ins used by templates.
KNOWN_TASK_TYPES = frozenset(
    {
        "general", "data_preparation", "remote_sensing_analysis", "preprocessing",
        "classification", "accuracy_assessment", "labelling", "model_training",
        "cartography", "field_capture", "reporting",
    }
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or fallback


def unique_id(base: str, existing) -> str:
    existing = set(existing)
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


# ---------------------------------------------------------------- validation
def _str(d: dict, key: str, ctx: str, default: str = "", required: bool = False) -> str:
    if key not in d:
        if required:
            raise SchemaError(f"{ctx}: missing required field '{key}'")
        return default
    v = d[key]
    if not isinstance(v, str) or (required and not v.strip()):
        raise SchemaError(f"{ctx}.{key}: expected non-empty string, got {v!r}")
    return v


def _list(d: dict, key: str, ctx: str) -> list:
    v = d.get(key, [])
    if not isinstance(v, list):
        raise SchemaError(f"{ctx}.{key}: expected list, got {type(v).__name__}")
    return v


def _dict(d: dict, key: str, ctx: str) -> dict:
    v = d.get(key, {})
    if not isinstance(v, dict):
        raise SchemaError(f"{ctx}.{key}: expected object, got {type(v).__name__}")
    return v


def _enum(cls, value: Any, ctx: str):
    try:
        return cls(value)
    except ValueError as exc:
        allowed = ", ".join(e.value for e in cls)
        raise SchemaError(f"{ctx}: {value!r} is not one of [{allowed}]") from exc


def _split(d: dict, known: set[str]) -> dict:
    return {k: copy.deepcopy(v) for k, v in d.items() if k not in known}


def _obj(v: Any, ctx: str) -> dict:
    if not isinstance(v, dict):
        raise SchemaError(f"{ctx}: expected object, got {type(v).__name__}")
    return v


# ------------------------------------------------------------------ objects
@dataclass
class LayerRef:
    """Stable layer reference: UUID primary, fallbacks for brittle moves (spec s7.3)."""

    layer_id: str = ""
    provider: str = ""
    source_hash: str = ""
    name: str = ""
    role: str = ""
    extra: dict = field(default_factory=dict)

    _KNOWN = {"layer_id", "provider", "source_hash", "name", "role"}

    @classmethod
    def from_dict(cls, d: dict, ctx: str = "layer_ref") -> LayerRef:
        d = _obj(d, ctx)
        return cls(
            layer_id=_str(d, "layer_id", ctx), provider=_str(d, "provider", ctx),
            source_hash=_str(d, "source_hash", ctx), name=_str(d, "name", ctx),
            role=_str(d, "role", ctx), extra=_split(d, cls._KNOWN),
        )

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update(layer_id=self.layer_id, provider=self.provider,
                   source_hash=self.source_hash, name=self.name, role=self.role)
        return out


@dataclass
class RoleSpec:
    """Declared semantic input/output of a task (e.g. multispectral_imagery)."""

    role: str
    required: bool = True
    description: str = ""
    extra: dict = field(default_factory=dict)

    _KNOWN = {"role", "required", "description"}

    @classmethod
    def from_dict(cls, d: dict, ctx: str = "role_spec") -> RoleSpec:
        d = _obj(d, ctx)
        req = d.get("required", True)
        if not isinstance(req, bool):
            raise SchemaError(f"{ctx}.required: expected bool")
        return cls(role=_str(d, "role", ctx, required=True), required=req,
                   description=_str(d, "description", ctx), extra=_split(d, cls._KNOWN))

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update(role=self.role, required=self.required, description=self.description)
        return out


@dataclass
class Task:
    """Semantic chunk of work. Contains NO UI state (see WorkspaceProfile)."""

    id: str
    name: str
    type: str = "general"
    description: str = ""
    status: TaskStatus = TaskStatus.NOT_STARTED
    order: int = 0
    predecessors: list[str] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)
    inputs: list[RoleSpec] = field(default_factory=list)
    outputs: list[RoleSpec] = field(default_factory=list)
    labs: list[str] = field(default_factory=list)
    preferred_tools: list[str] = field(default_factory=list)
    processing: ProcessingMode = ProcessingMode.INHERIT
    role_bindings: dict[str, list[LayerRef]] = field(default_factory=dict)
    associations: dict[str, list[str]] = field(default_factory=dict)  # notebook/plot/map/model
    notes: str = ""
    extra: dict = field(default_factory=dict)

    _KNOWN = {"id", "name", "type", "description", "status", "order", "predecessors",
              "successors", "inputs", "outputs", "labs", "preferred_tools",
              "processing", "role_bindings", "associations", "notes"}

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        d = _obj(d, "task")
        tid = _str(d, "id", "task", required=True)
        ctx = f"task[{tid}]"
        order = d.get("order", 0)
        if not isinstance(order, int) or isinstance(order, bool):
            raise SchemaError(f"{ctx}.order: expected int")
        bindings_raw = _dict(d, "role_bindings", ctx)
        assoc_raw = _dict(d, "associations", ctx)
        return cls(
            id=tid, name=_str(d, "name", ctx, required=True),
            type=_str(d, "type", ctx, "general"), description=_str(d, "description", ctx),
            status=_enum(TaskStatus, d.get("status", "not_started"), f"{ctx}.status"),
            order=order,
            predecessors=[str(x) for x in _list(d, "predecessors", ctx)],
            successors=[str(x) for x in _list(d, "successors", ctx)],
            inputs=[RoleSpec.from_dict(x, f"{ctx}.inputs") for x in _list(d, "inputs", ctx)],
            outputs=[RoleSpec.from_dict(x, f"{ctx}.outputs") for x in _list(d, "outputs", ctx)],
            labs=[str(x) for x in _list(d, "labs", ctx)],
            preferred_tools=[str(x) for x in _list(d, "preferred_tools", ctx)],
            processing=_enum(ProcessingMode, d.get("processing", "inherit"), f"{ctx}.processing"),
            role_bindings={k: [LayerRef.from_dict(r, f"{ctx}.role_bindings.{k}") for r in v]
                           for k, v in bindings_raw.items() if isinstance(v, list)},
            associations={k: [str(i) for i in v] for k, v in assoc_raw.items() if isinstance(v, list)},
            notes=_str(d, "notes", ctx), extra=_split(d, cls._KNOWN),
        )

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update(
            id=self.id, name=self.name, type=self.type, description=self.description,
            status=self.status.value, order=self.order,
            predecessors=list(self.predecessors), successors=list(self.successors),
            inputs=[r.to_dict() for r in self.inputs], outputs=[r.to_dict() for r in self.outputs],
            labs=list(self.labs), preferred_tools=list(self.preferred_tools),
            processing=self.processing.value,
            role_bindings={k: [r.to_dict() for r in v] for k, v in self.role_bindings.items()},
            associations={k: list(v) for k, v in self.associations.items()},
            notes=self.notes,
        )
        return out


@dataclass
class ProjectSettings:
    """Project-local privacy, learning, capture, auto-save and recovery policy."""

    share_task_context: bool = True
    usage_learning: bool = True
    auto_save_edits: bool = True
    recovery_enabled: bool = True
    capture_panels: bool = True
    capture_toolbars: bool = True
    capture_participants: bool = True
    extra: dict = field(default_factory=dict)

    _KNOWN = {"share_task_context", "usage_learning", "auto_save_edits", "recovery_enabled",
              "capture_panels", "capture_toolbars", "capture_participants"}

    @classmethod
    def from_dict(cls, value: dict) -> ProjectSettings:
        value = _obj(value, "project.settings")
        kwargs = {}
        for name in cls._KNOWN:
            item = value.get(name, True)
            if not isinstance(item, bool):
                raise SchemaError(f"project.settings.{name}: expected bool")
            kwargs[name] = item
        return cls(**kwargs, extra=_split(value, cls._KNOWN))

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        for name in self._KNOWN:
            out[name] = getattr(self, name)
        return out


@dataclass
class WorkspaceProfile:
    """How QGIS + TA Labs are configured for a task on a given display class."""

    id: str
    task_id: str
    name: str = ""
    display_class: DisplayClass = DisplayClass.SINGLE_STANDARD
    capture_policy: str = "standard"
    capture_options: dict[str, bool] = field(default_factory=dict)
    shell: dict = field(default_factory=dict)  # ShellSnapshot.to_dict()
    participants: dict[str, dict] = field(default_factory=dict)  # pid -> {schema_version, state}
    captured_at: str = ""
    extra: dict = field(default_factory=dict)

    _KNOWN = {"id", "task_id", "name", "display_class", "capture_policy", "capture_options", "shell",
              "participants", "captured_at"}

    @classmethod
    def from_dict(cls, d: dict) -> WorkspaceProfile:
        d = _obj(d, "workspace_profile")
        pid = _str(d, "id", "workspace_profile", required=True)
        ctx = f"workspace_profile[{pid}]"
        parts = _dict(d, "participants", ctx)
        profile = cls(
            id=pid, task_id=_str(d, "task_id", ctx, required=True), name=_str(d, "name", ctx),
            display_class=_enum(DisplayClass, d.get("display_class", "single_standard"),
                                f"{ctx}.display_class"),
            capture_policy=_str(d, "capture_policy", ctx, "standard"),
            capture_options={k: bool(v) for k, v in _dict(d, "capture_options", ctx).items()
                             if isinstance(v, bool)},
            participants={k: copy.deepcopy(v) for k, v in parts.items() if isinstance(v, dict)},
            captured_at=_str(d, "captured_at", ctx), extra=_split(d, cls._KNOWN),
        )
        # This is serialised QGIS workspace layout data.
        profile.shell = copy.deepcopy(_dict(d, "shell", ctx))
        return profile

    def to_dict(self) -> dict:
        out = copy.deepcopy(self.extra)
        out.update({
            "id": self.id, "task_id": self.task_id, "name": self.name,
            "display_class": self.display_class.value, "capture_policy": self.capture_policy,
            "capture_options": copy.deepcopy(self.capture_options),
            "shell": copy.deepcopy(self.shell), "participants": copy.deepcopy(self.participants),
            "captured_at": self.captured_at,
        })
        return out


@dataclass
class Project:
    id: str
    name: str
    tasks: list[Task] = field(default_factory=list)
    profiles: list[WorkspaceProfile] = field(default_factory=list)
    current_task_id: str | None = None
    default_processing: ProcessingMode = ProcessingMode.LOCAL
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    created: str = field(default_factory=utc_now_iso)
    modified: str = field(default_factory=utc_now_iso)
    extra: dict = field(default_factory=dict)       # unknown keys inside "project"
    root_extra: dict = field(default_factory=dict)  # unknown top-level keys
    schema_version: int = SCHEMA_VERSION

    _PROJ_KNOWN = {"id", "name", "current_task_id", "default_processing", "settings", "created", "modified"}
    _ROOT_KNOWN = {"schema_version", "kind", "project", "tasks", "workspace_profiles"}

    # -- lookups
    def get_task(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def profiles_for(self, task_id: str) -> list[WorkspaceProfile]:
        return [p for p in self.profiles if p.task_id == task_id]

    def problems(self) -> list[str]:
        """Referential-integrity problems; empty list means valid."""
        out: list[str] = []
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            out.append("duplicate task ids")
        known = set(ids)
        for t in self.tasks:
            for link in (*t.predecessors, *t.successors):
                if link not in known:
                    out.append(f"task '{t.id}' links to unknown task '{link}'")
        pids = [p.id for p in self.profiles]
        if len(pids) != len(set(pids)):
            out.append("duplicate workspace profile ids")
        for p in self.profiles:
            if p.task_id not in known:
                out.append(f"profile '{p.id}' references unknown task '{p.task_id}'")
        if self.current_task_id is not None and self.current_task_id not in known:
            out.append(f"current_task_id '{self.current_task_id}' is not a known task")
        return out

    @classmethod
    def from_dict(cls, data: dict, allow_newer: bool = False) -> Project:
        data = _obj(data, "document")
        ver = data.get("schema_version")
        if not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
            raise SchemaError("document.schema_version: missing or not a positive integer")
        if ver > SCHEMA_VERSION and not allow_newer:
            raise SchemaTooNew(ver)
        if data.get("kind", KIND) != KIND:
            raise SchemaError(f"document.kind: expected '{KIND}', got {data.get('kind')!r}")
        proj = _obj(data.get("project"), "document.project")
        project = cls(
            id=_str(proj, "id", "project", required=True),
            name=_str(proj, "name", "project", required=True),
            tasks=[Task.from_dict(t) for t in _list(data, "tasks", "document")],
            profiles=[WorkspaceProfile.from_dict(p) for p in _list(data, "workspace_profiles", "document")],
            current_task_id=proj.get("current_task_id"),
            default_processing=_enum(ProcessingMode, proj.get("default_processing", "local"),
                                     "project.default_processing"),
            settings=ProjectSettings.from_dict(proj.get("settings", {})),
            created=_str(proj, "created", "project", utc_now_iso()),
            modified=_str(proj, "modified", "project", utc_now_iso()),
            extra=_split(proj, cls._PROJ_KNOWN), root_extra=_split(data, cls._ROOT_KNOWN),
            schema_version=ver,
        )
        if project.default_processing == ProcessingMode.INHERIT:
            raise SchemaError("project.default_processing: 'inherit' is only valid on a task")
        if project.current_task_id is not None and not isinstance(project.current_task_id, str):
            raise SchemaError("project.current_task_id: expected string or null")
        bad = project.problems()
        if bad:
            raise SchemaError("; ".join(bad))
        return project

    def to_dict(self) -> dict:
        proj = copy.deepcopy(self.extra)
        proj.update(id=self.id, name=self.name, current_task_id=self.current_task_id,
                    default_processing=self.default_processing.value, settings=self.settings.to_dict(),
                    created=self.created, modified=self.modified)
        out = copy.deepcopy(self.root_extra)
        out.update(schema_version=self.schema_version, kind=KIND, project=proj,
                   tasks=[t.to_dict() for t in sorted(self.tasks, key=lambda t: t.order)],
                   workspace_profiles=[p.to_dict() for p in self.profiles])
        return out
