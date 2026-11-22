"""QGIS integration for the TerraAnalytica Task Workspace manager."""
from __future__ import annotations

from pathlib import Path

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QComboBox, QInputDialog, QLabel, QToolBar

from .compat import MessageLevel, QAction
from .qgis_layers import QgsLayerCatalogue
from .qgis_shell import QtShellBackend
from .twm.events import EventBus
from .twm.gitstore import GitCommandError, GitUnavailableError, open_git_registry
from .twm.layers import STANDARD_ROLES
from .twm.logging_utils import get_logger
from .twm.participants import ParticipantRegistry
from .twm.persistence import StoreCorruptError
from .twm.registry import TaskRegistry
from .twm.service import TaskWorkspaceService
from .twm.shell_state import ShellEngine
from .twm.usage import ToolUsageStore, UsageError
from .task_manager import TaskManagerDock


def _right_dock_area():
    return Qt.DockWidgetArea.RightDockWidgetArea

log = get_logger("plugin")


class TATasksPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.bus = EventBus()
        self.participants = ParticipantRegistry(self.bus)
        self.service: TaskWorkspaceService | None = None
        self.toolbar: QToolBar | None = None
        self.combo: QComboBox | None = None
        self._actions: list[QAction] = []
        self.store = None
        self.catalogue = QgsLayerCatalogue(iface)
        self.manager: TaskManagerDock | None = None
        self.manager_action: QAction | None = None

    def ta_capabilities(self):
        """Public optional hooks for other TerraAnalytica plugins."""
        return {"tasks.record_tool_use": self._record_external_tool_use}

    def _record_external_tool_use(self, tool_id):
        """Record only a stable tool ID against the current task."""
        if self.service is None or self.service.registry.current is None:
            return False
        try:
            recorded = self.service.record_tool_use(str(tool_id))
        except (ValueError, UsageError):
            return False
        if recorded and self.manager is not None:
            self.manager.refresh_tools()
        return recorded

    # -- QGIS lifecycle
    def initGui(self):  # noqa: N802
        self.toolbar = self.iface.addToolBar("TA Task Workspace")
        self.toolbar.setObjectName("TATasksToolbar")
        self.toolbar.setToolTip("Organise work into tasks and restore each task's QGIS workspace")
        self.toolbar.addWidget(self._label("TA Tasks"))
        self.combo = QComboBox()
        self.combo.setToolTip("Current task")
        self.combo.setMinimumWidth(180)
        self.combo.currentIndexChanged.connect(self._task_selected)
        self.toolbar.addWidget(self.combo)
        self._add("◀", "Previous task", lambda: self._step(-1))
        self._add("▶", "Next task", lambda: self._step(1))
        self._add("Restore", "Restore this task's workspace", self._restore)
        self._add("Capture", "Capture current workspace into this task", self._capture)
        self._add("+ Task", "New task", self._new_task)
        self._add("Bind layer", "Bind the active layer to a role for this task", self._bind_layer)
        self._add("Roles", "Check that this task's layer roles resolve", self._check_roles)
        self._add("Task Workspace", "Open TA Task Workspace — organise tasks and capture or restore QGIS layouts",
                  self._show_manager, icon=self._plugin_icon())
        self._add("Verify", "Check history and audit-log integrity", self._verify)
        self.manager = TaskManagerDock(self, self.iface.mainWindow())
        self.iface.addDockWidget(_right_dock_area(), self.manager)
        self.manager.hide()
        self.manager_action = QAction(self._plugin_icon(), "TA Task Workspace…", self.iface.mainWindow())
        self.manager_action.setToolTip(
            "Organise project work into tasks and capture or restore each task's QGIS workspace"
        )
        self.manager_action.setStatusTip(self.manager_action.toolTip())
        self.manager_action.triggered.connect(self._show_manager)
        self.iface.addPluginToMenu("TerraAnalytica", self.manager_action)
        QgsProject.instance().readProject.connect(self._open_project)
        QgsProject.instance().cleared.connect(self._open_project)
        # An untitled project's home path becomes available only after its first save.
        # QGIS does not emit readProject in that path, so listen to both save-time
        # signals where available (QGIS 3 and 4 expose a slightly different set).
        self._connect_project_signal("writeProject")
        self._connect_project_signal("fileNameChanged")
        self._open_project()
        self._show_manager()

    def unload(self):
        self._flush()
        if self.service is not None:
            self.service.close()
        try:
            QgsProject.instance().readProject.disconnect(self._open_project)
        except TypeError:
            pass
        try:
            QgsProject.instance().cleared.disconnect(self._open_project)
        except TypeError:
            pass
        self._disconnect_project_signal("writeProject")
        self._disconnect_project_signal("fileNameChanged")
        if self.manager_action is not None:
            self.iface.removePluginMenu("TerraAnalytica", self.manager_action)
        if self.manager is not None:
            self.iface.removeDockWidget(self.manager)
            self.manager.deleteLater()
        if self.toolbar:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar.deleteLater()

    # -- helpers
    def _label(self, text):
        lbl = QLabel(f" {text} ")
        lbl.setStyleSheet("font-weight:600;")
        return lbl

    def _plugin_icon(self):
        return QIcon(str(Path(__file__).parent / "resources" / "icons" / "task_workspace.svg"))

    def _add(self, text, tip, slot, icon=None):
        act = QAction(icon, text, self.iface.mainWindow()) if icon is not None else QAction(
            text, self.iface.mainWindow()
        )
        act.setToolTip(tip)
        act.setStatusTip(tip)
        act.triggered.connect(lambda _checked=False: slot())
        self.toolbar.addAction(act)
        self._actions.append(act)

    def _msg(self, text, level=MessageLevel.Info):
        self.iface.messageBar().pushMessage("TA Task Workspace", text, level=level, duration=6)

    def _connect_project_signal(self, name):
        signal = getattr(QgsProject.instance(), name, None)
        if signal is not None:
            try:
                signal.connect(self._open_project)
            except (AttributeError, TypeError):
                pass

    def _disconnect_project_signal(self, name):
        signal = getattr(QgsProject.instance(), name, None)
        if signal is not None:
            try:
                signal.disconnect(self._open_project)
            except (AttributeError, TypeError):
                pass

    @staticmethod
    def _project_directory(project):
        """Return the saved project directory across QGIS 3.x and 4.x."""
        home = project.homePath()
        if home:
            return Path(home)
        for accessor in ("absoluteFilePath", "fileName"):
            value = getattr(project, accessor, lambda: "")()
            if value:
                return Path(value).expanduser().resolve().parent
        return None

    def _open_project(self, *_):
        project = QgsProject.instance()
        home = self._project_directory(project)
        if home is None:
            self.service = None
            self._refresh()
            return
        directory = home / "ta_tasks"
        name = project.baseName() or "Project"
        self._flush()
        if self.service is not None:
            self.service.close()
        try:
            reg, self.store = open_git_registry(directory, name, self.bus)
        except GitUnavailableError:
            # Degrading silently would drop history + audit trail, so say so loudly.
            self._msg("git was not found: task history and audit log are DISABLED for this session. "
                      "Install git and restart QGIS.", MessageLevel.Critical)
            self.store = None
            reg = TaskRegistry.for_path(directory / "project.json", name, self.bus)
        except (StoreCorruptError, GitCommandError) as exc:
            self._msg(f"Task data unreadable, not modified: {exc}", MessageLevel.Critical)
            self.service = None
            self._refresh()
            return
        for w in reg.warnings:
            self._msg(w, MessageLevel.Warning)
        shell = ShellEngine(QtShellBackend(self.iface), essential_docks=("Layers",))
        try:
            usage = ToolUsageStore(directory / "usage.json", enabled=reg.project.settings.usage_learning)
        except UsageError as exc:
            usage = None
            self._msg(str(exc) + "; usage learning disabled until the file is repaired or cleared.",
                      MessageLevel.Warning)
        self.service = TaskWorkspaceService(reg, shell, self.participants, self.bus,
                                            layers=self.catalogue, usage=usage)
        self._refresh()

    def _refresh(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        if self.service:
            for t in self.service.registry.tasks:
                self.combo.addItem(t.name, t.id)
            cur = self.service.registry.project.current_task_id
            if cur:
                self.combo.setCurrentIndex(max(0, self.combo.findData(cur)))
        self.combo.blockSignals(False)
        if self.manager is not None:
            self.manager.refresh()

    def _flush(self):
        if self.store is not None:
            try:
                self.store.flush("audit log update")
            except Exception:  # noqa: BLE001 - never block QGIS shutdown
                log.exception("Could not commit pending audit entries")

    def _verify(self):
        if self.store is None:
            self._msg("No git-backed store active.", MessageLevel.Warning)
            return
        self._flush()
        rep = self.store.verify()
        if rep.ok and not rep.warnings:
            self._msg("History and audit log verified OK.", MessageLevel.Success)
        else:
            self._msg("; ".join(rep.problems + rep.warnings),
                      MessageLevel.Critical if rep.problems else MessageLevel.Warning)

    def _need_service(self) -> bool:
        if self.service is None:
            self._msg("Save the QGIS project first - tasks are stored beside it.", MessageLevel.Warning)
        return self.service is not None

    def _show_manager(self):
        if self.manager is not None:
            self.manager.refresh()
            self.manager.show()
            self.manager.raise_()

    def _save_project_as(self):
        action = getattr(self.iface, "actionSaveProjectAs", lambda: None)()
        if action is not None:
            action.trigger()
        else:
            self._msg("Use Project → Save As, then reopen Task Manager.", MessageLevel.Warning)

    def _select_task_id(self, task_id):
        if not self._need_service():
            return
        rep = self.service.restore_task(task_id)
        if rep.warnings:
            self._msg("; ".join(rep.warnings), MessageLevel.Warning)
        self._flush()
        self._refresh()

    # -- actions
    def _new_task(self):
        if not self._need_service():
            return
        name, ok = QInputDialog.getText(self.iface.mainWindow(), "New task", "Task name:")
        if ok and name.strip():
            self.service.registry.create_task(name)
            self._refresh()

    def _capture(self):
        if self._need_service() and self.service.registry.current:
            profile_id = self.manager._selected_profile_id() if self.manager is not None else None
            options = self.manager.capture_options() if self.manager is not None else None
            prof = self.service.capture_current_workspace(profile_id, options)
            self._flush()
            self._msg(f"Captured workspace ({prof.display_class.value}).")

    def _restore(self):
        if not self._need_service() or self.combo.currentData() is None:
            return
        rep = self.service.restore_task(self.combo.currentData())
        if rep.rolled_back:
            self._msg("Restore produced an unusable layout and was rolled back: " + "; ".join(rep.warnings),
                      MessageLevel.Warning)
        elif rep.warnings:
            self._msg("; ".join(rep.warnings), MessageLevel.Warning)
        self._flush()
        self._refresh()

    def _task_selected(self, index):
        """A deliberate combo selection switches and restores the selected task."""
        if index < 0 or not self._need_service():
            return
        task_id = self.combo.itemData(index)
        if task_id and task_id != self.service.registry.project.current_task_id:
            self.service.restore_task(task_id)
            self._flush()
            self._refresh()

    def _bind_layer(self):
        if not self._need_service():
            return
        task = self.service.registry.current
        layer = self.catalogue.active_layer()
        if task is None or layer is None:
            self._msg("Select a task and an active layer first.", MessageLevel.Warning)
            return
        declared = [s.role for s in (*task.inputs, *task.outputs)]
        roles = list(dict.fromkeys([*declared, *STANDARD_ROLES]))
        role, ok = QInputDialog.getItem(self.iface.mainWindow(), "Bind layer to role",
                                        f"Role for '{layer.name()}':", roles, 0, True)
        if not ok or not role.strip():
            return
        try:
            self.service.registry.bind_role(task.id, role.strip(), self.catalogue.layer_info(layer))
        except ValueError as exc:  # invalid role name, secret-like text, etc.
            self._msg(str(exc), MessageLevel.Warning)
            return
        self._flush()
        self._msg(f"Bound '{layer.name()}' to role '{role.strip()}'.", MessageLevel.Success)

    def _check_roles(self):
        if not self._need_service() or self.service.registry.current is None:
            return
        rep = self.service.check_roles()
        warnings = rep.warnings()
        if warnings:
            self._msg("; ".join(warnings), MessageLevel.Warning)
        else:
            self._msg("All layer roles resolved.", MessageLevel.Success)

    def _step(self, delta):
        if self._need_service():
            nxt = self.service.registry.neighbour(delta)
            if nxt:
                self.service.restore_task(nxt.id)
                self._refresh()
