"""QGIS-backed layer catalogue (M7). Converts live layers to ``LayerInfo`` (hash only, never the raw source).

Interactive layer-role checks are recorded using RELEASE_CHECKLIST.md.
"""
from __future__ import annotations

from qgis.core import QgsProject

from .twm.layers import LayerInfo


class QgsLayerCatalogue:
    def __init__(self, iface=None):
        self._iface = iface

    @staticmethod
    def layer_info(layer) -> LayerInfo:
        provider_fn = getattr(layer, "providerType", None)
        provider = provider_fn() if callable(provider_fn) else ""
        return LayerInfo.from_raw(layer.id(), layer.name(), provider or "", layer.source())

    def list_layers(self) -> list[LayerInfo]:
        return [self.layer_info(lyr) for lyr in QgsProject.instance().mapLayers().values()]

    def active_layer(self):
        return self._iface.activeLayer() if self._iface is not None else None
