"""Run with QGIS Python against the release ZIP using a disposable Qt host.

This exercises real QGIS/Qt APIs. Interactive Plugin Manager installation,
visual checks and real QGIS window layout checks remain in RELEASE_CHECKLIST.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
from zipfile import ZipFile

from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QDockWidget, QLabel, QMainWindow
from qgis.PyQt.QtCore import Qt


class TestInterface:
    def __init__(self):
        self.window = QMainWindow()
        self.messages = []
        self.actions = []

    def mainWindow(self):
        return self.window

    def addToolBar(self, name):
        return self.window.addToolBar(name)

    def addDockWidget(self, area, dock):
        self.window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self.window.removeDockWidget(dock)

    def addPluginToMenu(self, menu, action):
        self.actions.append(action)

    def removePluginMenu(self, menu, action):
        self.actions.remove(action)

    def messageBar(self):
        return self

    def pushMessage(self, title, message, **kwargs):
        self.messages.append(message)

    def activeLayer(self):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    app = QgsApplication([], True)
    app.initQgis()
    project = QgsProject.instance()
    with tempfile.TemporaryDirectory(prefix="ta-tasks-qgis-") as directory:
        root = Path(directory)
        with ZipFile(args.archive) as archive:
            archive.extractall(root / "plugins")
        sys.path.insert(0, str(root / "plugins"))
        from ta_tasks import classFactory
        from ta_tasks.twm.service import CaptureOptions

        iface = TestInterface()
        layers = QDockWidget("Layers", iface.window)
        layers.setObjectName("Layers")
        layers.setWidget(QLabel("Synthetic layers"))
        iface.window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, layers)
        iface.window.show()
        plugin = classFactory(iface)
        plugin.initGui()
        app.processEvents()
        assert plugin.service is None
        assert not plugin.manager.save_button.isHidden()
        for suffix in ("qgz", "qgs"):
            project.clear()
            folder = root / suffix
            folder.mkdir()
            filename = folder / f"Release test ā.{suffix}"
            project.setFileName(str(filename))
            assert project.write()
            app.processEvents()
            assert plugin.service is not None, iface.messages
            assert plugin.manager.save_button.isHidden()
            registry = plugin.service.registry
            task = registry.create_task("Release smoke")
            registry.set_current(task.id)
            registry.update_task(task.id, description="Synthetic release test", notes="Saved")
            profile = plugin.service.capture_current_workspace(
                options=CaptureOptions(participants=False)
            )
            report = plugin.service.restore_task(task.id, profile.id)
            assert report.ok, report
            plugin._flush()
            project.clear()
            assert project.read(str(filename))
            app.processEvents()
            restored = plugin.service.registry.get(task.id)
            assert restored.notes == "Saved"
            assert plugin.manager.save_button.isHidden()
        plugin.unload()
        assert not iface.actions
        iface.window.close()
        project.clear()
    print(f"PASS QGIS {Qgis.QGIS_VERSION}: ZIP import, startup, first save QGZ/QGS, "
          "capture/restore, persistence, unload (disposable Qt host)")
    app.exitQgis()


if __name__ == "__main__":
    main()
