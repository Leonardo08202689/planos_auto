"""Ejecutar: QT_QPA_PLATFORM=offscreen /usr/bin/python3 tests/comprobar_grid_escala.py"""

import logging
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsLayoutItemLegend,
    QgsLayoutItemScaleBar, QgsPrintLayout, QgsProject, QgsReadWriteContext,
    QgsRectangle,
)
from core.composicion import configurar_grid_mapa, reenlazar_barra_escala


def comprobar():
    project = QgsProject()
    log = logging.getLogger(__name__)
    plantillas = Path(__file__).resolve().parents[1] / "plantillas"
    for plantilla in plantillas.glob("*.qpt"):
        layout = QgsPrintLayout(project)
        doc = QDomDocument()
        assert doc.setContent(plantilla.read_text())
        layout.loadFromTemplate(doc, QgsReadWriteContext())
        mapa = layout.itemById("mapa_principal") or layout.itemById("Mapa 1")
        utm = QgsCoordinateReferenceSystem("EPSG:32612")
        for codigo, ancho in (("EPSG:32612", 500), ("EPSG:32612", 1700),
                              ("EPSG:32612", 10000), ("EPSG:32612", 300000),
                              ("EPSG:4326", 1700)):
            mapa.setCrs(QgsCoordinateReferenceSystem(codigo))
            encuadre = QgsRectangle(492813, 3117441, 492813 + ancho, 3117441 + ancho * .7)
            if mapa.crs() != utm:
                encuadre = QgsCoordinateTransform(utm, mapa.crs(), project).transformBoundingBox(encuadre)
            mapa.zoomToExtent(encuadre)
            configurar_grid_mapa(mapa, log)
            grid = mapa.grids().grid(0)
            assert grid.crs() == utm
            assert grid.annotationPrecision() == 0
            extent = QgsCoordinateTransform(mapa.crs(), grid.crs(), project).transformBoundingBox(mapa.extent())
            for inicio, fin, paso in (
                (extent.xMinimum(), extent.xMaximum(), grid.intervalX()),
                (extent.yMinimum(), extent.yMaximum(), grid.intervalY()),
            ):
                base = paso / 10 ** math.floor(math.log10(paso))
                assert any(abs(base - n) < 1e-8 for n in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8))
                lineas = math.floor(fin / paso) - math.ceil(inicio / paso) + 1
                assert 4 <= lineas <= 6, (plantilla.name, lineas)
            reenlazar_barra_escala(layout, mapa, log)
            leyenda = next(i for i in layout.items() if isinstance(i, QgsLayoutItemLegend))
            for barra in layout.items():
                if isinstance(barra, QgsLayoutItemScaleBar):
                    assert barra.numberOfSegmentsLeft() == 0
                    assert barra.numberOfSegments() == 2
                    total = barra.unitsPerSegment() * 2
                    assert total > 0
                    for inicio, fin in ((extent.xMinimum(), extent.xMaximum()),
                                        (extent.yMinimum(), extent.yMaximum())):
                        assert math.ceil(fin / total) - math.floor(inicio / total) <= 10
                    base = total / 10 ** math.floor(math.log10(total))
                    assert abs(base * 2 - round(base * 2)) < 1e-8
                    assert abs(total - grid.intervalX()) < 1e-8
                    assert abs(total - grid.intervalY()) < 1e-8
                    assert barra.rect().width() <= leyenda.rect().width() - 6 + 1e-8
                    limites = barra.sceneBoundingRect()
                    panel = leyenda.sceneBoundingRect()
                    assert limites.left() >= panel.left() + 2.9
                    assert limites.right() <= panel.right() - 2.9
                    assert abs(barra.sceneBoundingRect().center().x() - leyenda.sceneBoundingRect().center().x()) < .01
        if plantilla.name == "Plantilla_Corporativa.qpt":
            mapa.setCrs(utm)
            mapa.zoomToExtent(QgsRectangle(492001, 3117001, 494201, 3118601))
            configurar_grid_mapa(mapa, log)
            grid.setIntervalX(200)
            grid.setIntervalY(200)
            reenlazar_barra_escala(layout, mapa, log)
            assert grid.intervalX() == grid.intervalY() == 250
            barra = next(i for i in layout.items() if isinstance(i, QgsLayoutItemScaleBar))
            assert barra.unitsPerSegment() * 2 == 250
        print(plantilla.name, "OK: grid y barras existentes verificados a distintas escalas")


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.initQgis()
    comprobar()
