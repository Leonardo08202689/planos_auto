"""
core/exportar.py — Exportación de composiciones a PNG y/o PDF.
"""

import os

from qgis.core import QgsLayoutExporter
from qgis.PyQt.QtCore import QCoreApplication

from .utils import sanitizar_nombre


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
    Exporta 'layout_comp' a los formatos indicados ('png', 'pdf').
    Devuelve {formato: ruta} solo con las exportaciones exitosas.
    """
    QCoreApplication.processEvents()

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

    if "pdf" in formatos:
        cfg_pdf     = QgsLayoutExporter.PdfExportSettings()
        cfg_pdf.dpi = dpi
        ruta = os.path.join(output_dir, f"{base}.pdf")
        if exportador.exportToPdf(ruta, cfg_pdf) == QgsLayoutExporter.Success:
            rutas["pdf"] = ruta
            log.info(f" ✓ PDF exportado: {os.path.basename(ruta)}")
        else:
            log.error(f" ✗ Falló exportación PDF: {ruta}")

    return rutas


def exportar_png(layout_comp, cfg_capa, feature_id, output_dir, dpi, log) -> bool:
    """Compatibilidad: exporta solo PNG. Preferir exportar_plano()."""
    return bool(
        exportar_plano(layout_comp, cfg_capa, feature_id, output_dir, dpi, ["png"], log)
    )
