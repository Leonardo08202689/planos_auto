"""
core/simbologia.py — Renderers categorizados, etiquetas PAL y estilos
                     para polígonos y puntos de vértice.
"""

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont

from .utils import color_para_categoria, paletas_disponibles


def aplicar_estilo_poligono(poly_layer) -> None:
    """Contorno rojo translúcido sobre relleno transparente."""
    simbolo = QgsFillSymbol.createSimple({
        "color":         "0,0,0,0",
        "outline_color": "220,0,0,255",
        "outline_width": "0.8",
        "outline_style": "solid",
    })
    poly_layer.setRenderer(QgsSingleSymbolRenderer(simbolo))


def aplicar_estilo_vertices(capa_vertices, log) -> None:
    """Círculos amarillos numerados con halo blanco."""
    simbolo = QgsMarkerSymbol.createSimple({
        "name":          "circle",
        "color":         "255,255,0,220",
        "outline_color": "80,80,80,255",
        "outline_width": "0.4",
        "size":          "4.0",
    })
    capa_vertices.setRenderer(QgsSingleSymbolRenderer(simbolo))

    pal           = QgsPalLayerSettings()
    pal.fieldName = "num_vertice"
    pal.enabled   = True
    pal.placement = QgsPalLayerSettings.OverPoint

    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial", 8, QFont.Bold))
    fmt.setSize(8)
    fmt.setColor(QColor(30, 30, 30))

    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.2)
    buf.setColor(QColor(255, 255, 255, 220))
    fmt.setBuffer(buf)

    pal.setFormat(fmt)
    pal.xOffset = 0.0
    pal.yOffset = -2.5

    capa_vertices.setLabelsEnabled(True)
    capa_vertices.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    capa_vertices.triggerRepaint()
    log.info(" ✓ Estilo de vértices aplicado (círculos amarillos numerados).")


def aplicar_renderer_categorizado(capa, campo: str, log, paleta: str = "default") -> bool:
    """
    Asigna un renderer categorizado por 'campo' con la paleta temática indicada.
    Retorna True si tuvo éxito, False si el campo no existe o está vacío.
    """
    if paleta not in paletas_disponibles():
        log.warning(
            f" → Paleta '{paleta}' no existe (opciones: {paletas_disponibles()}); "
            f"usando 'default'."
        )
        paleta = "default"

    idx = capa.fields().lookupField(campo)
    if idx == -1:
        disponibles = [f.name() for f in capa.fields()]
        log.warning(
            f" → Campo '{campo}' no encontrado. "
            f"Campos disponibles: {disponibles}"
        )
        return False

    valores = sorted(
        [v for v in capa.dataProvider().uniqueValues(idx) if v is not None],
        key=str,
    )
    if not valores:
        log.warning(f" → Sin valores únicos en '{campo}'.")
        return False

    categorias = []
    for i, valor in enumerate(valores):
        simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
        simbolo.setColor(QColor(color_para_categoria(i, valor, paleta)))
        if simbolo.symbolLayerCount() > 0:
            sl = simbolo.symbolLayer(0)
            if hasattr(sl, "setStrokeColor"):
                sl.setStrokeColor(QColor(80, 80, 80, 180))
            if hasattr(sl, "setStrokeWidth"):
                sl.setStrokeWidth(0.2)
        categorias.append(QgsRendererCategory(valor, simbolo, str(valor)))

    capa.setRenderer(QgsCategorizedSymbolRenderer(campo, categorias))
    log.info(
        f" ✓ Renderer categorizado: {len(categorias)} categorías "
        f"en '{campo}' (paleta '{paleta}')"
    )
    return True


def aplicar_opacidad_capa(capa, opacidad: float, log) -> None:
    capa.setOpacity(opacidad)
    capa.triggerRepaint()
    log.info(f" ✓ Opacidad de capa: {int(opacidad * 100)}%")


def aplicar_etiquetas_pal(capa_centroides, campo: str, log) -> None:
    """Etiquetas PAL sobre centroides temáticos con halo blanco."""
    if not campo:
        return

    pal           = QgsPalLayerSettings()
    pal.fieldName = campo
    pal.enabled   = True
    pal.placement = QgsPalLayerSettings.OverPoint

    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial", 7, QFont.Bold))
    fmt.setSize(7)
    fmt.setColor(QColor(30, 30, 30))

    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor(255, 255, 255, 200))
    fmt.setBuffer(buf)
    pal.setFormat(fmt)

    pal.scaleVisibility = True
    pal.minimumScale    = 100_000
    pal.maximumScale    = 500

    capa_centroides.setLabelsEnabled(True)
    capa_centroides.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    capa_centroides.triggerRepaint()
    log.info(f" ✓ Etiquetas PAL configuradas en campo '{campo}'")
