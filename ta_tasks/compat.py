"""Single home for Qt5/Qt6 and QGIS 3.22-4.x differences.

Rule: no other module may import QAction or reference Qgis message-level enums directly.
"""
from qgis.core import Qgis

try:  # Qt6 (QGIS 4): QAction lives in QtGui
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 (QGIS 3.x): QAction lives in QtWidgets
    from qgis.PyQt.QtWidgets import QAction

# QGIS 4 only has the scoped enum; QGIS 3.x has both, so prefer scoped and fall back.
MessageLevel = getattr(Qgis, "MessageLevel", Qgis)

__all__ = ["QAction", "MessageLevel"]
