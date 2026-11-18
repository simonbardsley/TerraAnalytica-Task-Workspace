"""TA Tasks - TerraAnalytica Task / Workspace Manager (TWM) QGIS plugin."""


def classFactory(iface):  # noqa: N802 (QGIS entry-point naming)
    from .plugin import TATasksPlugin

    return TATasksPlugin(iface)
