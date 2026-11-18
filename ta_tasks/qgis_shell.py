"""Real Qt/QGIS backend for ShellEngine (M2 spike).

UNTESTED INSIDE QGIS in this build - verify with docs/MANUAL_QGIS_CHECKLIST.md.
Known risks (milestones s20): Qt layout state varies across QGIS/Qt versions, and
"visible" for background tabs in a tabbed dock group is version-dependent. We trust
QMainWindow.saveState()/restoreState() for tab grouping and only reconcile
visibility/floating/geometry afterwards.
"""
from __future__ import annotations

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QByteArray, Qt
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import QDockWidget, QToolBar

from .twm.display import Rect
from .twm.shell_state import DockRecord, ToolbarRecord

STATE_VERSION = 1  # passed to saveState/restoreState so incompatible layouts are rejected by Qt

_DOCK_AREAS = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea, "right": Qt.DockWidgetArea.RightDockWidgetArea,
    "top": Qt.DockWidgetArea.TopDockWidgetArea, "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
}
_TB_AREAS = {
    "left": Qt.ToolBarArea.LeftToolBarArea, "right": Qt.ToolBarArea.RightToolBarArea,
    "top": Qt.ToolBarArea.TopToolBarArea, "bottom": Qt.ToolBarArea.BottomToolBarArea,
}


def _area_name(mapping: dict, area) -> str:
    return next((k for k, v in mapping.items() if v == area), "left")


class QtShellBackend:
    def __init__(self, iface):
        self._win = iface.mainWindow()

    # -- environment
    def screens(self) -> list[Rect]:
        out = []
        for s in QGuiApplication.screens():
            g = s.availableGeometry()
            out.append(Rect(g.x(), g.y(), g.width(), g.height()))
        return out

    def has_open_edit_sessions(self) -> bool:
        return any(isinstance(lyr, QgsVectorLayer) and lyr.isEditable()
                   for lyr in QgsProject.instance().mapLayers().values())

    # -- whole-window state
    def save_main_state(self) -> bytes:
        return bytes(self._win.saveState(STATE_VERSION).data())

    def restore_main_state(self, state: bytes) -> bool:
        return bool(self._win.restoreState(QByteArray(state), STATE_VERSION))

    # -- enumeration
    def _docks(self) -> list[QDockWidget]:
        return [d for d in self._win.findChildren(QDockWidget) if d.objectName()]

    def _toolbars(self) -> list[QToolBar]:
        return [t for t in self._win.findChildren(QToolBar) if t.objectName()]

    def list_docks(self) -> list[DockRecord]:
        out = []
        for d in self._docks():
            g = d.geometry()
            out.append(DockRecord(
                name=d.objectName(), visible=d.isVisibleTo(self._win), floating=d.isFloating(),
                area=_area_name(_DOCK_AREAS, self._win.dockWidgetArea(d)),
                geometry=[g.x(), g.y(), g.width(), g.height()],
                tabified_with=[o.objectName() for o in self._win.tabifiedDockWidgets(d)],
            ))
        return out

    def list_toolbars(self) -> list[ToolbarRecord]:
        return [ToolbarRecord(
                    name=t.objectName(), visible=t.isVisibleTo(self._win),
                    area=_area_name(_TB_AREAS, self._win.toolBarArea(t)),
                    break_before=self._win.toolBarBreak(t))
                for t in self._toolbars()]

    # -- application
    def apply_dock(self, rec: DockRecord) -> None:
        dock = next((d for d in self._docks() if d.objectName() == rec.name), None)
        if dock is None:
            return
        if dock.isFloating() != rec.floating:
            dock.setFloating(rec.floating)
        if rec.floating and rec.visible and rec.geometry[2] > 0:
            dock.setGeometry(*rec.geometry)
        if dock.isVisibleTo(self._win) != rec.visible:
            dock.setVisible(rec.visible)

    def apply_toolbar(self, rec: ToolbarRecord) -> None:
        tb = next((t for t in self._toolbars() if t.objectName() == rec.name), None)
        if tb is not None and tb.isVisibleTo(self._win) != rec.visible:
            tb.setVisible(rec.visible)
