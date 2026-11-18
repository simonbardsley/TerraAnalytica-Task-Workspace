"""QGIS shell state capture/restore engine (M2) - Qt-free.

The engine talks to a ``ShellBackend``; ``qgis_shell.QtShellBackend`` is the real
one and tests use a fake. Restore runs in deterministic phases with a pre-restore
snapshot, edit-session protection and rollback.
"""
from __future__ import annotations

import base64
import copy
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .display import Rect, clamp_rect, classify_display, is_adequately_visible
from .logging_utils import get_logger

log = get_logger("shell")

SHELL_STATE_VERSION = 1
# Toolbars that must not be hidden while an edit session is open (QGIS object names).
PROTECTED_WHEN_EDITING = ("mDigitizeToolBar", "mAdvancedDigitizeToolBar")


@dataclass
class DockRecord:
    name: str
    visible: bool = True
    floating: bool = False
    area: str = "left"
    geometry: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    tabified_with: list[str] = field(default_factory=list)


@dataclass
class ToolbarRecord:
    name: str
    visible: bool = True
    area: str = "top"
    break_before: bool = False


@dataclass
class ShellSnapshot:
    version: int = SHELL_STATE_VERSION
    main_state_b64: str = ""           # QMainWindow.saveState(), base64
    docks: list[DockRecord] = field(default_factory=list)
    toolbars: list[ToolbarRecord] = field(default_factory=list)
    screens: list[list[int]] = field(default_factory=list)
    display_class: str = ""

    @property
    def main_state(self) -> bytes:
        return base64.b64decode(self.main_state_b64) if self.main_state_b64 else b""

    def to_dict(self) -> dict:
        return {
            "version": self.version, "main_state_b64": self.main_state_b64,
            "docks": [vars(d).copy() for d in self.docks],
            "toolbars": [vars(t).copy() for t in self.toolbars],
            "screens": copy.deepcopy(self.screens), "display_class": self.display_class,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ShellSnapshot:
        def pick(klass, raw):
            names = klass.__dataclass_fields__.keys()
            return klass(**{k: v for k, v in raw.items() if k in names})
        return cls(
            version=int(d.get("version", SHELL_STATE_VERSION)),
            main_state_b64=d.get("main_state_b64", ""),
            docks=[pick(DockRecord, x) for x in d.get("docks", [])],
            toolbars=[pick(ToolbarRecord, x) for x in d.get("toolbars", [])],
            screens=copy.deepcopy(d.get("screens", [])), display_class=d.get("display_class", ""),
        )


class ShellBackend(Protocol):
    def screens(self) -> list[Rect]: ...
    def save_main_state(self) -> bytes: ...
    def restore_main_state(self, state: bytes) -> bool: ...
    def list_docks(self) -> list[DockRecord]: ...
    def list_toolbars(self) -> list[ToolbarRecord]: ...
    def apply_dock(self, rec: DockRecord) -> None: ...
    def apply_toolbar(self, rec: ToolbarRecord) -> None: ...
    def has_open_edit_sessions(self) -> bool: ...


@dataclass
class ShellRestoreReport:
    ok: bool = True
    rolled_back: bool = False
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    pre_snapshot: ShellSnapshot | None = None


Validator = Callable[["ShellBackend"], list[str]]


class ShellEngine:
    def __init__(self, backend: ShellBackend, essential_docks: Sequence[str] = ()):
        self.backend = backend
        self.essential_docks = tuple(essential_docks)

    # -------------------------------------------------------------- capture
    def capture(self) -> ShellSnapshot:
        screens = self.backend.screens()
        return ShellSnapshot(
            main_state_b64=base64.b64encode(self.backend.save_main_state()).decode("ascii"),
            docks=self.backend.list_docks(), toolbars=self.backend.list_toolbars(),
            screens=[s.to_list() for s in screens], display_class=classify_display(screens).value,
        )

    # -------------------------------------------------------------- validity
    def default_problems(self, backend: ShellBackend | None = None) -> list[str]:
        """Post-restore sanity: essential docks visible, nothing stranded off-screen."""
        b = backend or self.backend
        screens, problems = b.screens(), []
        docks = {d.name: d for d in b.list_docks()}
        for name in self.essential_docks:
            d = docks.get(name)
            if d is not None and not d.visible:
                problems.append(f"essential panel '{name}' is hidden")
        for d in docks.values():
            if d.visible and d.floating and not is_adequately_visible(Rect.from_list(d.geometry), screens):
                problems.append(f"floating panel '{d.name}' is off-screen")
        return problems

    # --------------------------------------------------------------- restore
    def _apply(self, snap: ShellSnapshot, protect_edits: bool, report: ShellRestoreReport) -> None:
        b, screens = self.backend, self.backend.screens()
        if snap.main_state and not b.restore_main_state(snap.main_state):
            report.warnings.append("QMainWindow rejected saved state; applying per-panel state only")
        present_docks = {d.name for d in b.list_docks()}
        for rec in snap.docks:
            if rec.name not in present_docks:
                report.missing.append(rec.name)
                continue
            rec = copy.deepcopy(rec)
            if rec.floating and rec.visible:
                rec.geometry = clamp_rect(Rect.from_list(rec.geometry), screens).to_list()
            b.apply_dock(rec)
        present_tb = {t.name for t in b.list_toolbars()}
        editing = protect_edits and b.has_open_edit_sessions()
        for rec in snap.toolbars:
            if rec.name not in present_tb:
                report.missing.append(rec.name)
                continue
            if editing and rec.name in PROTECTED_WHEN_EDITING and not rec.visible:
                rec = copy.deepcopy(rec)
                rec.visible = True
                report.warnings.append(f"Kept '{rec.name}' visible: an edit session is open")
            b.apply_toolbar(rec)

    def rollback(self, pre: ShellSnapshot) -> ShellRestoreReport:
        rb = ShellRestoreReport()
        self._apply(pre, protect_edits=False, report=rb)
        return rb

    def restore(self, snapshot: ShellSnapshot, validator: Callable[[], list[str]] | None = None,
                rollback_on_failure: bool = True
                ) -> ShellRestoreReport:
        report = ShellRestoreReport()
        if snapshot.version > SHELL_STATE_VERSION:
            report.ok = False
            report.warnings.append(f"Shell state v{snapshot.version} is newer than supported; not restored")
            return report
        report.pre_snapshot = self.capture()           # phase: snapshot for rollback
        try:
            self._apply(snapshot, protect_edits=True, report=report)
            problems = (validator or self.default_problems)()
        except Exception as exc:  # noqa: BLE001
            log.exception("Shell restore failed")
            problems = [f"restore raised {type(exc).__name__}: {exc}"]
        if problems:
            report.ok = False
            report.warnings.extend(problems)
            if not rollback_on_failure:
                report.warnings.append("Automatic layout rollback is disabled in Task Workspace settings")
                return report
            try:
                self.rollback(report.pre_snapshot)
                report.rolled_back = True
                report.warnings.append("Layout rolled back to pre-restore state")
            except Exception as exc:  # noqa: BLE001 - never let rollback crash QGIS
                log.exception("Rollback failed")
                report.warnings.append(f"Rollback FAILED ({type(exc).__name__}: {exc}); "
                                       "use View > Panels to recover the layout")
        return report
