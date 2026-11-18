"""Task Registry (M1): CRUD, ordering, workflow links, current-task selection."""
from __future__ import annotations

from typing import Iterable

from .events import EventBus, Events
from .layers import validate_association, validate_role_name
from .logging_utils import get_logger
from .persistence import JsonProjectStore, ProjectStore, ReadOnlyError
from .schemas import (
    DisplayClass,
    LayerRef,
    ProcessingMode,
    Project,
    RoleSpec,
    Task,
    TaskStatus,
    WorkspaceProfile,
    available_processing_modes,
    slugify,
    unique_id,
    utc_now_iso,
)

log = get_logger("registry")


class RegistryError(ValueError):
    pass


class TaskRegistry:
    def __init__(self, project: Project, store: ProjectStore | None = None,
                 bus: EventBus | None = None, read_only: bool = False,
                 warnings: Iterable[str] = ()):
        self.project = project
        self.store = store
        self.bus = bus or EventBus()
        self.read_only = read_only
        self.warnings = list(warnings) + self.processing_warnings()

    # ------------------------------------------------------------ open/create
    @classmethod
    def open_or_create(cls, store: ProjectStore, project_name: str = "Untitled Project",
                       bus: EventBus | None = None) -> TaskRegistry:
        if store.exists():
            res = store.load()
            return cls(res.project, store, bus, res.read_only, res.warnings)
        project = Project(id=slugify(project_name, "project"), name=project_name)
        reg = cls(project, store, bus)
        reg._commit("init project")
        return reg

    @classmethod
    def for_path(cls, path, project_name: str = "Untitled Project", bus=None) -> TaskRegistry:
        return cls.open_or_create(JsonProjectStore(path), project_name, bus)

    # -------------------------------------------------------------- internals
    def _commit(self, reason: str = "update") -> None:
        if self.read_only:
            raise ReadOnlyError("Registry is read-only (newer schema).")
        self.project.modified = utc_now_iso()
        if self.store is not None:
            self.store.save(self.project, read_only=self.read_only, reason=reason)

    def _require(self, task_id: str) -> Task:
        task = self.project.get_task(task_id)
        if task is None:
            raise RegistryError(f"Unknown task '{task_id}'")
        return task

    def _guard(self) -> None:
        if self.read_only:
            raise ReadOnlyError("Registry is read-only (newer schema).")

    # ------------------------------------------------------------------- CRUD
    @property
    def tasks(self) -> list[Task]:
        return sorted(self.project.tasks, key=lambda t: t.order)

    def get(self, task_id: str) -> Task:
        return self._require(task_id)

    @property
    def current(self) -> Task | None:
        cid = self.project.current_task_id
        return self.project.get_task(cid) if cid else None

    def create_task(self, name: str, type: str = "general", description: str = "",
                    inputs: Iterable[str] = (), outputs: Iterable[str] = (),
                    labs: Iterable[str] = (), preferred_tools: Iterable[str] = (),
                    task_id: str | None = None) -> Task:
        self._guard()
        if not name.strip():
            raise RegistryError("Task name must not be empty")
        tid = task_id or unique_id(slugify(name, "task"), (t.id for t in self.project.tasks))
        if self.project.get_task(tid):
            raise RegistryError(f"Task id '{tid}' already exists")
        task = Task(
            id=tid, name=name.strip(), type=type, description=description,
            order=max((t.order for t in self.project.tasks), default=-1) + 1,
            inputs=[RoleSpec(validate_role_name(r)) for r in inputs],
            outputs=[RoleSpec(validate_role_name(r)) for r in outputs],
            labs=list(labs), preferred_tools=list(preferred_tools),
        )
        self.project.tasks.append(task)
        if self.project.current_task_id is None:
            self.project.current_task_id = task.id
        self._commit(f"create_task {task.id}")
        return task

    _EDITABLE = {"name", "type", "description", "status", "processing", "labs", "preferred_tools", "notes"}

    def update_task(self, task_id: str, **changes) -> Task:
        self._guard()
        task = self._require(task_id)
        bad = set(changes) - self._EDITABLE
        if bad:
            raise RegistryError(f"Cannot update field(s): {', '.join(sorted(bad))}")
        converted: dict = {}
        for key, value in changes.items():          # validate everything first: no partial updates
            if key == "status":
                value = TaskStatus(value)
            if key == "processing":
                value = ProcessingMode(value)
                self._require_selectable(value)
            if key == "name" and not str(value).strip():
                raise RegistryError("Task name must not be empty")
            converted[key] = value
        for key, value in converted.items():
            setattr(task, key, value)
        self._commit(f"update_task {task_id} ({', '.join(sorted(changes))})")
        return task

    def replace_roles(self, task_id: str, inputs: Iterable[str], outputs: Iterable[str]) -> Task:
        """Replace declared roles atomically while preserving valid bindings."""
        self._guard()
        task = self._require(task_id)
        in_roles = list(dict.fromkeys(validate_role_name(x) for x in inputs if str(x).strip()))
        out_roles = list(dict.fromkeys(validate_role_name(x) for x in outputs if str(x).strip()))
        if set(in_roles) & set(out_roles):
            raise RegistryError("A role cannot be both an input and an output")
        task.inputs = [RoleSpec(role) for role in in_roles]
        task.outputs = [RoleSpec(role) for role in out_roles]
        allowed = set(in_roles) | set(out_roles)
        task.role_bindings = {k: v for k, v in task.role_bindings.items() if k in allowed}
        self._commit(f"replace_roles {task_id}")
        return task

    def replace_links(self, task_id: str, predecessor_ids: Iterable[str]) -> Task:
        """Replace incoming task dependencies using the cycle-safe link API."""
        self._guard()
        task = self._require(task_id)
        wanted = list(dict.fromkeys(str(x) for x in predecessor_ids))
        for predecessor_id in wanted:
            self._require(predecessor_id)
            if predecessor_id == task_id:
                raise RegistryError("A task cannot precede itself")
        old = list(task.predecessors)
        for predecessor_id in old:
            self.unlink(predecessor_id, task_id)
        try:
            for predecessor_id in wanted:
                self.link(predecessor_id, task_id)
        except Exception:
            for predecessor_id in list(task.predecessors):
                self.unlink(predecessor_id, task_id)
            for predecessor_id in old:
                self.link(predecessor_id, task_id)
            raise
        return task

    def replace_associations(self, task_id: str, kind: str, item_ids: Iterable[str]) -> Task:
        self._guard()
        task = self._require(task_id)
        values = []
        for item_id in item_ids:
            _, value = validate_association(kind, item_id)
            if value not in values:
                values.append(value)
        if values:
            task.associations[kind] = values
        else:
            task.associations.pop(kind, None)
        self._commit(f"replace_associations {task_id}:{kind}")
        return task

    def update_settings(self, **changes):
        self._guard()
        settings = self.project.settings
        bad = set(changes) - settings._KNOWN
        if bad:
            raise RegistryError(f"Unknown setting(s): {', '.join(sorted(bad))}")
        for key, value in changes.items():
            if not isinstance(value, bool):
                raise RegistryError(f"Setting '{key}' must be true or false")
        for key, value in changes.items():
            setattr(settings, key, value)
        self._commit("update project settings")
        return settings

    @staticmethod
    def _require_selectable(mode: ProcessingMode) -> None:
        """'inherit' is not a processing type (it means "use the project default"), so it is always allowed."""
        if mode != ProcessingMode.INHERIT and mode not in available_processing_modes():
            allowed = ", ".join(m.value for m in available_processing_modes())
            raise RegistryError(f"Processing mode '{mode.value}' is not available yet; only {allowed} can be selected")

    def effective_processing(self, task: Task) -> ProcessingMode:
        """Resolve a task's mode against the project default. Never returns a disabled mode: anything not
        currently selectable (e.g. 'cloud' from a hand-edited or newer file) is treated as LOCAL, the safe
        mode in which data does not leave the machine."""
        mode = self.project.default_processing if task.processing == ProcessingMode.INHERIT else task.processing
        return mode if mode in available_processing_modes() else ProcessingMode.LOCAL

    def processing_warnings(self) -> list[str]:
        out = []
        if self.project.default_processing not in available_processing_modes():
            out.append(f"Project default processing '{self.project.default_processing.value}' is not available "
                       "yet; running locally")
        for t in self.project.tasks:
            if t.processing != ProcessingMode.INHERIT and t.processing not in available_processing_modes():
                out.append(f"Task '{t.name}' requests '{t.processing.value}' processing, which is not available "
                           "yet; running locally")
        return out

    def set_default_processing(self, mode: ProcessingMode | str) -> None:
        self._guard()
        mode = ProcessingMode(mode)
        if mode == ProcessingMode.INHERIT:
            raise RegistryError("The project default cannot be 'inherit'")
        self._require_selectable(mode)
        self.project.default_processing = mode
        self._commit(f"set_default_processing {mode.value}")

    def delete_task(self, task_id: str) -> None:
        self._guard()
        self._require(task_id)
        self.project.tasks = [t for t in self.project.tasks if t.id != task_id]
        for t in self.project.tasks:
            t.predecessors = [x for x in t.predecessors if x != task_id]
            t.successors = [x for x in t.successors if x != task_id]
        self.project.profiles = [p for p in self.project.profiles if p.task_id != task_id]
        if self.project.current_task_id == task_id:
            remaining = self.tasks
            self.project.current_task_id = remaining[0].id if remaining else None
        self._commit(f"delete_task {task_id}")

    def reorder(self, task_ids: list[str]) -> None:
        self._guard()
        if sorted(task_ids) != sorted(t.id for t in self.project.tasks):
            raise RegistryError("reorder() requires a permutation of all task ids")
        for i, tid in enumerate(task_ids):
            self._require(tid).order = i
        self._commit("reorder tasks")

    # ------------------------------------------------------------------ links
    def _reachable(self, start: str, target: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self._require(cur).successors)
        return False

    def link(self, predecessor_id: str, successor_id: str) -> None:
        self._guard()
        pred, succ = self._require(predecessor_id), self._require(successor_id)
        if predecessor_id == successor_id:
            raise RegistryError("A task cannot precede itself")
        if successor_id in pred.successors:
            return
        if self._reachable(successor_id, predecessor_id):
            raise RegistryError(f"Link {predecessor_id} -> {successor_id} would create a cycle")
        pred.successors.append(successor_id)
        succ.predecessors.append(predecessor_id)
        self._commit(f"link {predecessor_id} -> {successor_id}")

    def unlink(self, predecessor_id: str, successor_id: str) -> None:
        self._guard()
        pred, succ = self._require(predecessor_id), self._require(successor_id)
        pred.successors = [x for x in pred.successors if x != successor_id]
        succ.predecessors = [x for x in succ.predecessors if x != predecessor_id]
        self._commit(f"unlink {predecessor_id} -> {successor_id}")

    # -------------------------------------------------- roles + associations (M7)
    def add_role(self, task_id: str, role: str, direction: str, required: bool = True) -> None:
        self._guard()
        task = self._require(task_id)
        validate_role_name(role)
        if direction not in ("input", "output"):
            raise RegistryError("direction must be 'input' or 'output'")
        specs = task.inputs if direction == "input" else task.outputs
        if any(s.role == role for s in specs):
            raise RegistryError(f"Role '{role}' is already declared as an {direction}")
        specs.append(RoleSpec(role, required=required))
        self._commit(f"add_role {task_id}:{role} ({direction})")
        self.bus.publish(Events.ROLE_BINDING_CHANGED, task_id=task_id, role=role)

    def bind_role(self, task_id: str, role: str, layer, replace: bool = False) -> LayerRef:
        """Bind a live layer (``LayerInfo``) to a role. ``replace`` drops existing bindings for the role."""
        self._guard()
        task = self._require(task_id)
        validate_role_name(role)
        ref = layer.to_ref(role)
        bindings = [] if replace else list(task.role_bindings.get(role, []))
        if any(b.layer_id == ref.layer_id for b in bindings):
            return next(b for b in bindings if b.layer_id == ref.layer_id)
        bindings.append(ref)
        task.role_bindings[role] = bindings
        self._commit(f"bind_role {task_id}:{role}")
        self.bus.publish(Events.ROLE_BINDING_CHANGED, task_id=task_id, role=role)
        return ref

    def unbind_role(self, task_id: str, role: str, layer_id: str | None = None) -> int:
        self._guard()
        task = self._require(task_id)
        current = task.role_bindings.get(role, [])
        keep = [b for b in current if layer_id is not None and b.layer_id != layer_id]
        removed = len(current) - len(keep)
        if removed:
            if keep:
                task.role_bindings[role] = keep
            else:
                task.role_bindings.pop(role, None)
            self._commit(f"unbind_role {task_id}:{role}")
            self.bus.publish(Events.ROLE_BINDING_CHANGED, task_id=task_id, role=role)
        return removed

    def heal_binding(self, task_id: str, role: str, old: LayerRef, new: LayerRef) -> bool:
        """Replace a stale binding with a refreshed one (used after a confirmed or high-confidence match)."""
        self._guard()
        task = self._require(task_id)
        bindings = task.role_bindings.get(role, [])
        for i, b in enumerate(bindings):
            if b.layer_id == old.layer_id and b.source_hash == old.source_hash:
                bindings[i] = new
                self._commit(f"heal_binding {task_id}:{role}")
                self.bus.publish(Events.ROLE_BINDING_CHANGED, task_id=task_id, role=role)
                return True
        return False

    def associate(self, task_id: str, kind: str, item_id: str) -> None:
        self._guard()
        task = self._require(task_id)
        kind, item_id = validate_association(kind, item_id)
        items = task.associations.setdefault(kind, [])
        if item_id not in items:
            items.append(item_id)
            self._commit(f"associate {task_id}:{kind}")

    def dissociate(self, task_id: str, kind: str, item_id: str) -> bool:
        self._guard()
        task = self._require(task_id)
        items = task.associations.get(kind, [])
        if item_id not in items:
            return False
        items.remove(item_id)
        if not items:
            task.associations.pop(kind, None)
        self._commit(f"dissociate {task_id}:{kind}")
        return True

    # ---------------------------------------------------------------- current
    def set_current(self, task_id: str) -> Task:
        self._guard()
        task = self._require(task_id)
        old = self.project.current_task_id
        self.bus.publish(Events.TASK_ABOUT_TO_CHANGE, old_task_id=old, new_task_id=task_id)
        self.project.current_task_id = task_id
        self._commit(f"set_current {task_id}")
        self.bus.publish(Events.TASK_CHANGED, old_task_id=old, task=task)
        return task

    def neighbour(self, delta: int) -> Task | None:
        """Task ``delta`` positions from current (wraps) WITHOUT changing selection."""
        ordered = self.tasks
        if not ordered:
            return None
        ids = [t.id for t in ordered]
        idx = ids.index(self.project.current_task_id) if self.project.current_task_id in ids else 0
        return ordered[(idx + delta) % len(ids)]

    def step(self, delta: int) -> Task | None:
        nxt = self.neighbour(delta)
        return self.set_current(nxt.id) if nxt else None

    # --------------------------------------------------------------- profiles
    def save_profile(self, profile: WorkspaceProfile) -> WorkspaceProfile:
        self._guard()
        self._require(profile.task_id)
        existing = next((p for p in self.project.profiles if p.id == profile.id), None)
        if existing:
            self.project.profiles[self.project.profiles.index(existing)] = profile
        else:
            self.project.profiles.append(profile)
        self._commit(f"save_profile {profile.id}")
        return profile

    def new_profile(self, task_id: str, display_class: DisplayClass, name: str = "") -> WorkspaceProfile:
        self._require(task_id)
        pid = unique_id(f"{task_id}-{display_class.value}", (p.id for p in self.project.profiles))
        return WorkspaceProfile(id=pid, task_id=task_id,
                                name=name or display_class.value.replace("_", " ").title(),
                                display_class=display_class)

    def rename_profile(self, profile_id: str, name: str) -> WorkspaceProfile:
        self._guard()
        profile = next((p for p in self.project.profiles if p.id == profile_id), None)
        if profile is None:
            raise RegistryError(f"Unknown profile '{profile_id}'")
        if not name.strip():
            raise RegistryError("Profile name must not be empty")
        profile.name = name.strip()
        self._commit(f"rename_profile {profile_id}")
        return profile

    def delete_profile(self, profile_id: str) -> None:
        self._guard()
        before = len(self.project.profiles)
        self.project.profiles = [p for p in self.project.profiles if p.id != profile_id]
        if len(self.project.profiles) == before:
            raise RegistryError(f"Unknown profile '{profile_id}'")
        self._commit(f"delete_profile {profile_id}")
