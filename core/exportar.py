"""
core/exportar.py — Exportación de composiciones a PNG.
"""

import os

from qgis.core import QgsLayoutExporter
from qgis.PyQt.QtCore import QCoreApplication

from .utils import sanitizar_nombre

_FORMATOS_SOPORTADOS = {"png"}


def exportar_plano(
    layout_comp,
    cfg_capa: dict,
    feature_id: int,
    output_dir: str,
    dpi: int,
    formatos,
    log,
) -> dict:
    """
    Exporta 'layout_comp' a los formatos indicados ('png').
    Devuelve {formato: ruta} solo con las exportaciones exitosas.
    """
    QCoreApplication.processEvents()

    desconocidos = [f for f in formatos if f not in _FORMATOS_SOPORTADOS]
    if desconocidos:
        log.warning(f" → Formatos no soportados ignorados: {desconocidos}")

    base       = f"{sanitizar_nombre(cfg_capa['nombre_plano'])}_ID{feature_id}"
    exportador = QgsLayoutExporter(layout_comp)
    rutas      = {}

    if "png" in formatos:
        cfg_img     = QgsLayoutExporter.ImageExportSettings()
        cfg_img.dpi = dpi
        ruta = os.path.join(output_dir, f"{base}.png")
        if exportador.exportToImage(ruta, cfg_img) == QgsLayoutExporter.Success:
            rutas["png"] = ruta
            log.info(f" ✓ PNG exportado: {os.path.basename(ruta)}")
        else:
            log.error(f" ✗ Falló exportación PNG: {ruta}")

    return rutas
