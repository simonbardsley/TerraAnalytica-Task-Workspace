"""Scrollable, bundled help window for TA Task Workspace."""
from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from .ta_style import stylesheet


def _close_button():
    scoped = getattr(QDialogButtonBox, "StandardButton", None)
    return getattr(scoped, "Close") if scoped is not None else QDialogButtonBox.Close


def _window_flag():
    scoped = getattr(Qt, "WindowType", None)
    return getattr(scoped, "Window") if scoped is not None else Qt.Window


class TaskWorkspaceHelpDialog(QDialog):
    """Display the same guide bundled for repository and offline users."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taTasksRoot")
        self.setWindowTitle("TA Task Workspace — Help and Use Cases")
        self.setMinimumSize(680, 560)
        self.resize(780, 700)
        self.setWindowFlag(_window_flag(), True)

        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        guide = Path(__file__).with_name("HELP.md").read_text(encoding="utf-8")
        if hasattr(browser, "setMarkdown"):
            browser.setMarkdown(guide)
        else:
            browser.setPlainText(guide)
        layout.addWidget(browser, 1)

        buttons = QDialogButtonBox(_close_button(), parent=self)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.setStyleSheet(stylesheet())
