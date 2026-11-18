import ast
import configparser
import unittest
from pathlib import Path


_PARENT = Path(__file__).resolve().parents[1]
ROOT = _PARENT if (_PARENT / "metadata.txt").exists() else _PARENT / "ta_tasks"


class QgisUiContractTests(unittest.TestCase):
    def test_sources_parse(self):
        for name in ("plugin.py", "task_manager.py", "task_help.py", "ta_style.py"):
            ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)

    def test_metadata_matches_manager_release(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(ROOT / "metadata.txt", encoding="utf-8")
        self.assertEqual(parser["general"]["version"], "0.8.1")
        self.assertEqual(parser["general"]["icon"], "resources/icons/task_workspace.svg")
        self.assertEqual(parser["general"]["license"], "GPL-2.0-only")

    def test_plugin_exposes_dock_menu_and_first_run(self):
        plugin = (ROOT / "plugin.py").read_text(encoding="utf-8")
        manager = (ROOT / "task_manager.py").read_text(encoding="utf-8")
        self.assertIn("addDockWidget", plugin)
        self.assertIn("addPluginToMenu", plugin)
        self.assertIn("Save QGIS project to begin", manager)
        self.assertIn("writeProject", plugin)
        self.assertIn("fileNameChanged", plugin)
        self.assertIn('QLabel("TERRAANALYTICA")', manager)
        self.assertIn('QLabel("Task Workspace")', manager)
        self.assertIn('QLabel("Organise work. Restore your workspace.")', manager)
        self.assertIn('header.setObjectName("taTasksHeader")', manager)
        self.assertIn("changeEvent", manager)
        for tab in ("Overview", "Workspace", "Tools", "Context", "Workflow", "History", "Settings"):
            self.assertIn(f'"{tab}"', manager)
        self.assertIn("_build_workflow", manager)
        self.assertIn("Save task details", manager)
        self.assertIn("Capture selected state", manager)
        self.assertIn("Save settings", manager)
        self.assertIn('setObjectName("taTasksHelpButton")', manager)
        self.assertIn("TaskWorkspaceHelpDialog", manager)
        self.assertIn('"tasks.record_tool_use"', plugin)
        self.assertIn("Assign selected", manager)
        self.assertIn("Clear learning", manager)

    def test_release_documentation_is_bundled(self):
        for name in ("LICENSE", "README.md", "HELP.md", "CHANGELOG.md"):
            self.assertTrue((ROOT / name).is_file(), name)
        licence = (ROOT / "LICENSE").read_text(encoding="utf-8")
        help_text = (ROOT / "HELP.md").read_text(encoding="utf-8")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", licence)
        self.assertIn("Version 2, June 1991", licence)
        self.assertIn("Compact toolbar", help_text)
        self.assertIn("Beta limitations", help_text)

    def test_adaptive_theme_defines_readable_light_and_dark_text(self):
        theme = (ROOT / "ta_style.py").read_text(encoding="utf-8")
        self.assertIn("palette().window().color().lightness()", theme)
        self.assertIn('text, secondary, border = "#F2F2F0"', theme)
        self.assertIn('text, secondary, border = "#202326"', theme)
        self.assertIn("QWidget#taTasksRoot QLabel", theme)
        self.assertIn("QWidget#taTasksRoot QFrame#taTasksHeader", theme)
        self.assertIn("QFrame#taTasksHeader QLabel#taTasksWordmark", theme)
        self.assertIn("QFrame#taTasksHeader QLabel#taTasksTitle", theme)
        self.assertIn("QFrame#taTasksHeader QLabel#taTasksSubtitle", theme)
        self.assertIn("QToolButton#taTasksHelpButton", theme)


if __name__ == "__main__":
    unittest.main()
