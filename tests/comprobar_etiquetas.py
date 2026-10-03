"""Ejecutar: QT_QPA_PLATFORM=offscreen /usr/bin/python3 tests/comprobar_etiquetas.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.PyQt.QtXml import QDomDocument
from qgis.core import (
    QgsApplication, QgsLayoutItemLabel, QgsLayoutSize, QgsPrintLayout, QgsProject,
    QgsReadWriteContext,
)
from core.composicion import (
    _ajustar_fuente_al_cuadro, _medir_texto_envuelto_mm, set_label_text,
    unificar_etiquetas_mapitas,
)


def comprobar():
    project = QgsProject()
    layout = QgsPrintLayout(project)
    item = QgsLayoutItemLabel(layout)
    layout.addLayoutItem(item)
    item.setId("titulo")
    item.attemptResize(QgsLayoutSize(71, 9))
    item.setMarginX(1)
    item.setMarginY(1)
    caja = item.rect()
    for original in (6, 18):
        fmt = item.textFormat()
        fmt.setSize(original)
        item.setTextFormat(fmt)
        for texto in ("EL CAJÓN", "LICENCIA AMBIENTAL INTEGRAL", "PLANO. TIPOS DE SUELOS"):
            set_label_text(layout, "titulo", texto)
            assert item.textFormat().size() == 9, texto
            assert item.rect() == caja

    for texto in ("PROYECTO CON UN NOMBRE MUY LARGO " * 12, "X" * 150):
        item.setText(texto)
        _ajustar_fuente_al_cuadro(item)
        fmt = item.textFormat()
        assert 0 < fmt.size() < 9
        fuente = fmt.toQFont()
        fuente.setPointSizeF(fmt.size())
        max_w = (caja.width() - 2 * item.marginX()) * 0.94
        max_h = (caja.height() - 2 * item.marginY()) * 0.97
        ancho, alto = _medir_texto_envuelto_mm(texto, fuente, max_w)
        assert ancho <= max_w and alto <= max_h
        assert item.rect() == caja

    set_label_text(layout, "titulo", "EL CAJÓN")
    assert item.textFormat().size() == 9
    set_label_text(layout, "titulo", "Fuente: Servicio Geológico Mexicano (SGM).", tam_fuente=6)
    assert item.textFormat().size() == 6
    plantilla = QgsPrintLayout(project)
    doc = QDomDocument()
    ruta = Path(__file__).resolve().parents[1] / "plantillas/Plantilla_Corporativa.qpt"
    assert doc.setContent(ruta.read_text())
    plantilla.loadFromTemplate(doc, QgsReadWriteContext())
    ids = {"lbl_estado": "lbl_estado", "lbl_municipio": "lbl_municipio"}
    for municipio in ("GUAYMAS", "MUNICIPIO CON UN NOMBRE MUY LARGO"):
        set_label_text(plantilla, "lbl_estado", "SONORA")
        set_label_text(plantilla, "lbl_municipio", municipio)
        unificar_etiquetas_mapitas(plantilla, ids)
        etiquetas = [i for i in plantilla.items() if isinstance(i, QgsLayoutItemLabel)
                     and (i.id() in ids.values() or i.text() == "Republica Mexicana")]
        assert len(etiquetas) == 4
        assert len({i.textFormat().size() for i in etiquetas}) == 1
        for etiqueta in etiquetas:
            fuente = etiqueta.textFormat().toQFont()
            fuente.setPointSizeF(etiqueta.textFormat().size())
            ancho_max = (etiqueta.rect().width() - 2 * etiqueta.marginX()) * .94
            alto_max = (etiqueta.rect().height() - 2 * etiqueta.marginY()) * .97
            ancho, alto = _medir_texto_envuelto_mm(etiqueta.currentText(), fuente, ancho_max)
            assert ancho <= ancho_max and alto <= alto_max
    print("OK: tamaño uniforme, textos largos dentro de la caja y tamaño restaurado.")


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.initQgis()
    comprobar()
