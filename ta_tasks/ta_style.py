"""Adaptive TerraAnalytica light/dark styling for TA Tasks."""

from __future__ import annotations

from qgis.PyQt.QtWidgets import QApplication


TA_GOLD = "#E3B54C"
TA_GOLD_HOVER = "#F0C967"
TA_CHARCOAL = "#202326"


def is_dark_theme(application=None) -> bool:
    """Follow the active QGIS/Qt application palette."""
    app = application or QApplication.instance()
    if app is None:
        return False
    try:
        return int(app.palette().window().color().lightness()) < 128
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def stylesheet(application=None) -> str:
    """Return a readable TA stylesheet matched to QGIS light or dark mode."""
    if is_dark_theme(application):
        background, panel, elevated = "#202326", "#292D30", "#151719"
        text, secondary, border = "#F2F2F0", "#B9BDC0", "#5D6268"
    else:
        background, panel, elevated = "#FFFFFF", "#F4F2EC", "#FFFFFF"
        text, secondary, border = "#202326", "#5D6268", "#C8C5BD"

    return f"""
        QWidget#taTasksRoot {{ background: {background}; color: {text}; }}
        QWidget#taTasksRoot QLabel {{ color: {text}; background: transparent; }}
        QWidget#taTasksRoot QFrame#taTasksHeader {{ background-color: {TA_CHARCOAL}; border: 0; }}
        QWidget#taTasksRoot QFrame#taTasksHeader QWidget#taTasksTitleBox {{
            background: transparent; border: 0;
        }}
        QWidget#taTasksRoot QFrame#taTasksHeader QLabel#taTasksWordmark {{
            color: {TA_GOLD}; background: transparent; font-size: 10px; font-weight: 700;
        }}
        QWidget#taTasksRoot QFrame#taTasksHeader QLabel#taTasksTitle {{
            color: #FFFFFF; background: transparent; font-size: 17px; font-weight: 700;
        }}
        QWidget#taTasksRoot QFrame#taTasksHeader QLabel#taTasksSubtitle {{
            color: #B9BDC0; background: transparent; font-size: 10px;
        }}
        QWidget#taTasksRoot QFrame#taTasksHeader QToolButton#taTasksHelpButton {{
            color: #F2F2F0; background: #292D30; border: 1px solid #5D6268;
            border-radius: 4px; font-size: 14px; font-weight: 700;
        }}
        QWidget#taTasksRoot QFrame#taTasksHeader QToolButton#taTasksHelpButton:hover {{
            border-color: {TA_GOLD};
        }}
        QWidget#taTasksRoot QFrame#taTasksHeader QToolButton#taTasksHelpButton:pressed {{
            color: {TA_CHARCOAL}; background: {TA_GOLD}; border-color: {TA_GOLD};
        }}
        QLabel#taTasksExplainer {{ color: {secondary}; padding: 3px 2px 7px 2px; }}
        QWidget#taTasksRoot QTabWidget::pane {{ border: 1px solid {border};
                                                background: {background}; }}
        QWidget#taTasksRoot QTabBar::tab {{ color: {secondary}; background: {panel};
                                            border: 1px solid {border}; padding: 6px 9px; }}
        QWidget#taTasksRoot QTabBar::tab:selected {{ color: {TA_CHARCOAL};
                                                     background: {TA_GOLD};
                                                     border-color: {TA_GOLD};
                                                     font-weight: 700; }}
        QWidget#taTasksRoot QPushButton {{ color: {text}; background: {panel};
                                          border: 1px solid {border}; border-radius: 4px;
                                          padding: 6px 9px; }}
        QWidget#taTasksRoot QPushButton:hover {{ border-color: {TA_GOLD}; }}
        QWidget#taTasksRoot QPushButton:pressed {{ color: {TA_CHARCOAL};
                                                  background: {TA_GOLD}; }}
        QWidget#taTasksRoot QListWidget,
        QWidget#taTasksRoot QTextBrowser,
        QWidget#taTasksRoot QTextEdit,
        QWidget#taTasksRoot QLineEdit,
        QWidget#taTasksRoot QComboBox {{ color: {text}; background: {elevated};
                                           border: 1px solid {border};
                                           selection-color: {TA_CHARCOAL};
                                           selection-background-color: {TA_GOLD}; }}
        QWidget#taTasksRoot QCheckBox {{ color: {text}; background: transparent; spacing: 6px; }}
        QWidget#taTasksRoot QComboBox QAbstractItemView {{ color: {text}; background: {elevated};
                                                          selection-color: {TA_CHARCOAL};
                                                          selection-background-color: {TA_GOLD}; }}
        QWidget#taTasksRoot QListWidget::item {{ color: {text}; background: {elevated}; }}
        QWidget#taTasksRoot QListWidget::item:selected {{ color: {TA_CHARCOAL};
                                                         background: {TA_GOLD}; }}
        QWidget#taTasksRoot QToolTip {{ color: {text}; background: {panel};
                                       border: 1px solid {TA_GOLD}; }}
    """
