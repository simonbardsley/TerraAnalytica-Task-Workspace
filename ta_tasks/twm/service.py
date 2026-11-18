"""Task / Workspace Manager service: ties registry + shell engine + participants.

restore_task() follows spec s6.4 (phases 1-10). Layer-role resolution (phase 8) is M7.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .display import classify_display, nearest_profile
from .events import EventBus, Events
from .layers import LayerCatalogue, RoleResolutionReport, resolve_task_roles
from .logging_utils import get_logger
from .participants.api import Issue, ParticipantRegistry, RestoreResult
from .persistence import ReadOnlyError
from .registry import TaskRegistry
from .schemas import WorkspaceProfile, utc_now_iso
from .shell_state import ShellEngine, ShellSnapshot
from .usage import ToolUsageStore, validate_tool_id

log = get_logger("service")


@dataclass
class CaptureOptions:
    """Explicit capture selection (spec s6.3). Transient state is OFF by default."""

    panels_and_docks: bool = True
    toolbars: bool = True
    participants: bool = True
    feature_selections: bool = False   # not implemented in v0.1; flag reserved
    edit_sessions: bool = False        # never captured
    scratch_content: bool = False      # not implemented in v0.1; flag reserved


@dataclass
class TaskRestoreReport:
    task_id: str
    profile_id: str | None = None
    ok: bool = True
    rolled_back: bool = False
    warnings: list[str] = field(default_factory=list)
    participant_results: dict[str, RestoreResult] = field(default_factory=dict)
    role_report: RoleResolutionReport | None = None


class TaskWorkspaceService:
    def __init__(self, registry: TaskRegistry, shell: ShellEngine,
                 participants: ParticipantRegistry | None = None, bus: EventBus | None = None,
                 layers: LayerCatalogue | None = None, usage: ToolUsageStore | None = None):
        self.registry = registry
        self.layers = layers
        self.last_role_report: RoleResolutionReport | None = None
        self.shell = shell
        self.bus = bus or registry.bus
        self.participants = participants or ParticipantRegistry(self.bus)
        self.usage = usage
        self._usage_unsubscribe = usage.attach(self.bus) if usage is not None else None

    def close(self) -> None:
        """Detach project-scoped listeners before opening another QGIS project."""
        if self._usage_unsubscribe is not None:
            self._usage_unsubscribe()
            self._usage_unsubscribe = None

    # -------------------------------------------------------------- context
    def build_context(self, task=None) -> dict:
        """Minimal task context (full ContextEnvelope arrives in M9)."""
        t = task or self.registry.current
        if t is None:
            return {}
        context = {
            "project_id": self.registry.project.id, "project_name": self.registry.project.name,
            "task_id": t.id, "task_name": t.name, "task_type": t.type,
            "description": t.description, "status": t.status.value,
            "processing_mode": self.registry.effective_processing(t).value,
            "inputs": [r.role for r in t.inputs], "outputs": [r.role for r in t.outputs],
            "labs": list(t.labs), "preferred_tools": list(t.preferred_tools),
            "roles": (self.last_role_report.statuses()
                      if self.last_role_report and self.last_role_report.task_id == t.id else {}),
        }
        if self.usage is not None:
            context["tools"] = {
                "assigned": list(t.preferred_tools),
                "suggested": [u.tool_id for u in self.usage.ranked(t.id)
                              if u.tool_id not in t.preferred_tools],
                "recent": [u.tool_id for u in self.usage.recent(t.id)],
            }
        return context

    def record_tool_use(self, tool_id: str, task_id: str | None = None) -> bool:
        """Publish a minimal tool event. Arguments and outputs are deliberately not accepted."""
        task = self.registry.get(task_id) if task_id else self.registry.current
        if task is None:
            raise ValueError("No current task")
        if self.usage is None:
            return False
        tool_id = validate_tool_id(tool_id)
        self.bus.publish(Events.TOOL_USED, task_id=task.id, tool_id=tool_id)
        return True

    # -------------------------------------------------------------- capture
    def capture_current_workspace(self, profile_id: str | None = None,
                                  options: CaptureOptions | None = None) -> WorkspaceProfile:
        options = options or CaptureOptions()
        task = self.registry.current
        if task is None:
            raise ValueError("No current task to capture into")
        self.bus.publish(Events.WORKSPACE_CAPTURE_STARTED, task_id=task.id)
        snap = self.shell.capture()
        if not options.panels_and_docks:
            snap.main_state_b64, snap.docks = "", []
        if not options.toolbars:
            snap.toolbars = []
        display_class = classify_display(self.shell.backend.screens())
        profile = None
        if profile_id:
            profile = next((p for p in self.registry.project.profiles_for(task.id) if p.id == profile_id), None)
        if profile is None:
            profile = next((p for p in self.registry.project.profiles_for(task.id)
                            if p.display_class == display_class), None)
        if profile is None:
            profile = self.registry.new_profile(task.id, display_class)
        profile.display_class = display_class
        profile.capture_options = {
            "panels_and_docks": options.panels_and_docks,
            "toolbars": options.toolbars,
            "participants": options.participants,
        }
        profile.shell = snap.to_dict()
        profile.captured_at = utc_now_iso()
        issues: list[Issue] = []
        profile.participants = {}
        if options.participants:
            profile.participants, issues = self.participants.capture_all()
        self.registry.save_profile(profile)
        for i in issues:
            self.bus.publish(Events.WORKSPACE_RESTORE_WARNING, task_id=task.id, issue=i)
        self.bus.publish(Events.WORKSPACE_CAPTURED, task_id=task.id, profile_id=profile.id)
        return profile

    # -------------------------------------------------------------- restore
    def restore_task(self, task_id: str, profile_id: str | None = None) -> TaskRestoreReport:
        report = TaskRestoreReport(task_id=task_id)
        task = self.registry.get(task_id)                                   # 1 validate
        self.bus.publish(Events.WORKSPACE_RESTORE_STARTED, task_id=task_id)
        screens = self.shell.backend.screens()                              # 2 environment
        profiles = self.registry.project.profiles_for(task_id)
        profile = (next((p for p in profiles if p.id == profile_id), None) if profile_id
                   else nearest_profile(profiles, classify_display(screens)))
        if profile is None:
            report.warnings.append("No captured workspace for this task; activated task context only")
        else:
            report.profile_id = profile.id
            missing = [pid for pid in profile.participants if pid not in self.participants]  # 3 resolve
            for pid in missing:
                report.warnings.append(f"Participant '{pid}' unavailable")   # 4 non-blocking warnings
            shell_rep = self.shell.restore(
                ShellSnapshot.from_dict(profile.shell),
                rollback_on_failure=self.registry.project.settings.recovery_enabled,
            )  # 5-6 snapshot+restore
            report.warnings.extend(shell_rep.warnings)
            if shell_rep.missing:
                report.warnings.append("Missing panels/toolbars: " + ", ".join(sorted(set(shell_rep.missing))))
            if shell_rep.rolled_back:
                report.ok, report.rolled_back = False, True
                self.bus.publish(Events.WORKSPACE_ROLLBACK, task_id=task_id, warnings=shell_rep.warnings)
            else:
                ctx = self.build_context(task)
                report.participant_results = self.participants.restore_all(profile.participants, ctx)  # 7
                for pid, res in report.participant_results.items():
                    for issue in res.issues:
                        report.warnings.append(f"[{pid}] {issue.message}")
        if not report.rolled_back and self.layers is not None:               # 8 layer roles (M7)
            self._resolve_roles(task, report)
        if not report.rolled_back:                                           # 9 activate + broadcast
            self.registry.set_current(task_id)
            ctx = self.build_context()
            if self.registry.project.settings.share_task_context:
                self.participants.broadcast_context(ctx)
            self.bus.publish(Events.CONTEXT_CHANGED, context=ctx)
        for w in report.warnings:
            self.bus.publish(Events.WORKSPACE_RESTORE_WARNING, task_id=task_id, message=w)
        if report.ok:
            self.bus.publish(Events.WORKSPACE_RESTORED, task_id=task_id, profile_id=report.profile_id)
        return report                                                        # 10 provenance: M11

    def check_roles(self, task_id: str | None = None) -> RoleResolutionReport:
        """Resolve roles without changing anything (no healing, no events)."""
        if self.layers is None:
            raise RuntimeError("No layer catalogue configured")
        task = self.registry.get(task_id) if task_id else self.registry.current
        if task is None:
            raise ValueError("No task")
        return resolve_task_roles(task, self.layers.list_layers())

    def _resolve_roles(self, task, report: TaskRestoreReport) -> None:
        rep = resolve_task_roles(task, self.layers.list_layers())
        self.last_role_report = report.role_report = rep
        healed = 0
        for role, old, new in rep.healable():
            try:
                healed += bool(self.registry.heal_binding(task.id, role, old, new))
            except ReadOnlyError:
                report.warnings.append("Role bindings refreshed in memory only (project is read-only)")
                break
        warnings = rep.warnings()
        report.warnings.extend(warnings)
        self.bus.publish(Events.ROLES_RESOLVED, task_id=task.id,
                         message=f"{len(warnings)} role warning(s), {healed} binding(s) refreshed")

    def switch_task(self, task_id: str, restore: bool = True) -> TaskRestoreReport:
        if restore:
            return self.restore_task(task_id)
        self.registry.set_current(task_id)
        return TaskRestoreReport(task_id=task_id)
