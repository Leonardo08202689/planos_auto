"""Ejecutar: QT_QPA_PLATFORM=offscreen /usr/bin/python3 tests/comprobar_mapitas.py"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    QgsApplication, QgsPrintLayout, QgsProject, QgsReadWriteContext,
    QgsRectangle, QgsVectorLayer,
)
from core.mapitas import configurar_mapitas


def comprobar():
    project = QgsProject()
    layout = QgsPrintLayout(project)
    doc = QDomDocument()
    plantilla = Path(__file__).resolve().parents[1] / "plantillas/Plantilla_Corporativa.qpt"
    assert doc.setContent(plantilla.read_text())
    layout.loadFromTemplate(doc, QgsReadWriteContext())
    mapa = layout.itemById("Mapa 4")
    tam = mapa.sizeWithUnits()
    pos = mapa.positionWithUnits()
    capa = QgsVectorLayer("Polygon?crs=EPSG:4326", "municipio", "memory")
    config = {"mapitas_layout": {"Mapa 4": {"nivel": "municipal"}}}
    # Municipio alto, ancho y casi cuadrado, con margen ya incluido.
    for extent in (
        QgsRectangle(-111.6, 27.4, -110.5, 29.1),
        QgsRectangle(-112.5, 27.4, -109.5, 28.2),
        QgsRectangle(-111.5, 27.5, -110.5, 28.5),
    ):
        refs = {"capas_municipal": [capa], "ext_municipal": extent}
        configurar_mapitas(layout, "mapa_principal", config, refs, logging.getLogger(__name__))
        visible = mapa.extent()
        assert visible.contains(extent), (visible.toString(), extent.toString())
        assert mapa.sizeWithUnits() == tam
        assert mapa.positionWithUnits() == pos
    print("OK: municipio completo para distintas proporciones, sin mover ni redimensionar el recuadro.")


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.initQgis()
    comprobar()
