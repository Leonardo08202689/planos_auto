"""
core/simbologia.py — Renderers categorizados, etiquetas PAL y estilos
                     para polígonos y puntos de vértice.
"""

import textwrap

from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsFillSymbol,
    QgsLinePatternFillSymbolLayer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProperty,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsSymbolLayerUtils,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont

from .utils import color_para_categoria, paletas_disponibles


def _placement_over_point():
    """Valor de enum "colocar la etiqueta justo sobre el punto", compatible
    con QGIS 3.28 (QgsPalLayerSettings.OverPoint plano) y QGIS 3.34+ (donde
    ese nombre quedó ambiguo entre dos enums distintos —LabelPlacement y
    LabelPredefinedPointPosition— y hay que usar la ruta con ámbito)."""
    try:
        return Qgis.LabelPlacement.OverPoint
    except AttributeError:
        return QgsPalLayerSettings.OverPoint

_ANGULOS_PATRON = {
    "horizontal":  0,
    "vertical":    90,
    "f_diagonal":  45,
    "b_diagonal":  135,
}

# Ancho aproximado (en caracteres) antes de partir una etiqueta de categoría
# en varias líneas; calibrado para el panel más angosto (Plantilla_figuras).
_LEYENDA_ANCHO_CATEGORIA_CHARS = 28


def construir_simbolo_patron(
    color: str, color_borde: str, patron: str = "solid",
    estilo_borde: str = "solid", ancho_borde: str = "0.4",
) -> QgsFillSymbol:
    """Relleno sólido bien visible con un patrón de líneas superpuesto encima
    (no en vez del relleno), para que varias capas que se solapan se distingan
    por color Y por trama sin perder visibilidad de color.
    'patron': 'solid', 'horizontal', 'vertical', 'f_diagonal', 'b_diagonal' o 'cross'.
    """
    simbolo = QgsFillSymbol.createSimple({
        "color":         color,
        "outline_color": color_borde,
        "outline_width": ancho_borde,
        "outline_style": estilo_borde,
        "style":         "solid",
    })

    color_linea = QgsSymbolLayerUtils.decodeColor(color_borde)

    def _capa_lineas(angulo):
        capa = QgsLinePatternFillSymbolLayer()
        capa.setLineWidth(0.35)
        capa.setDistance(1.8)
        capa.setLineAngle(angulo)
        capa.setColor(color_linea)
        return capa

    if patron == "cross":
        simbolo.appendSymbolLayer(_capa_lineas(0))
        simbolo.appendSymbolLayer(_capa_lineas(90))
    elif patron in _ANGULOS_PATRON:
        simbolo.appendSymbolLayer(_capa_lineas(_ANGULOS_PATRON[patron]))

    return simbolo


def aplicar_estilo_poligono(poly_layer) -> None:
    """Contorno rojo translúcido sobre relleno transparente."""
    simbolo = QgsFillSymbol.createSimple({
        "color":         "0,0,0,0",
        "outline_color": "220,0,0,255",
        "outline_width": "0.8",
        "outline_style": "solid",
    })
    poly_layer.setRenderer(QgsSingleSymbolRenderer(simbolo))
    poly_layer.setCustomProperty("nombre_leyenda", "Área del Proyecto")


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
    pal.placement = _placement_over_point()

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


def aplicar_renderer_categorizado(
    capa, campo: str, log, paleta: str = "default", campo_legenda_extra: str = "",
) -> bool:
    """
    Asigna un renderer categorizado por 'campo' con la paleta temática indicada.
    Si 'campo_legenda_extra' se indica, la etiqueta de cada categoría en la leyenda
    muestra "valor, valor_extra" (p. ej. "12, 508-0/01" para UGA + clave) en vez de
    solo el valor de 'campo'. Asume relación 1:1 entre 'campo' y 'campo_legenda_extra'.
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

    mapa_extra = {}
    idx_extra = capa.fields().lookupField(campo_legenda_extra) if campo_legenda_extra else -1
    if idx_extra != -1:
        for f in capa.getFeatures():
            v = f[idx]
            if v not in mapa_extra:
                mapa_extra[v] = f[idx_extra]

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
        etiqueta = f"{valor}, {mapa_extra[valor]}" if valor in mapa_extra else str(valor)
        # Los nombres largos (p. ej. POET: "unidad, clave") no caben en una
        # sola línea en el panel angosto de las figuras; se parten en varias
        # líneas (la leyenda sí tiene margen vertical de sobra) en vez de
        # dejar que la caja se ensanche y se salga de la página.
        etiqueta = "\n".join(textwrap.wrap(etiqueta, _LEYENDA_ANCHO_CATEGORIA_CHARS)) or etiqueta
        categorias.append(QgsRendererCategory(valor, simbolo, etiqueta))

    capa.setRenderer(QgsCategorizedSymbolRenderer(campo, categorias))
    log.info(
        f" ✓ Renderer categorizado: {len(categorias)} categorías "
        f"en '{campo}' (paleta '{paleta}')"
    )
    return True


def capa_legend_ubicacion_actual(capa, campo: str, punto_geom, log):
    """
    Clona el renderer categorizado de 'capa' dejando una sola categoría: la
    que contiene 'punto_geom' (el centroide del proyecto). Se usa en capas de
    zonificación regional (p. ej. Unidades Ambientales Biofísicas) donde el
    mapa muestra varias regiones vecinas como contexto espacial, pero la
    leyenda solo debe nombrar la región donde realmente está el proyecto, no
    todas las que aparecen recortadas en el extent del mapa.
    Retorna una capa nueva (clon) o None si no se pudo determinar la categoría.
    """
    renderer = capa.renderer()
    if not isinstance(renderer, QgsCategorizedSymbolRenderer):
        return None

    idx = capa.fields().lookupField(campo)
    if idx == -1:
        return None

    valor_actual = None
    for f in capa.getFeatures():
        geom = f.geometry()
        if geom and not geom.isEmpty() and geom.contains(punto_geom):
            valor_actual = f[idx]
            break

    if valor_actual is None:
        log.warning(
            f" → No se detectó en qué '{campo}' cae el proyecto; "
            f"leyenda sin filtrar por ubicación."
        )
        return None

    categoria = next((c for c in renderer.categories() if c.value() == valor_actual), None)
    if not categoria:
        return None

    capa_leyenda = capa.clone()
    capa_leyenda.setRenderer(QgsCategorizedSymbolRenderer(
        campo, [QgsRendererCategory(categoria.value(), categoria.symbol().clone(), categoria.label())]
    ))
    log.info(f" ✓ Leyenda filtrada a la ubicación actual: '{categoria.label()}'")
    return capa_leyenda


def aplicar_opacidad_capa(capa, opacidad: float, log) -> None:
    capa.setOpacity(opacidad)
    capa.triggerRepaint()
    log.info(f" ✓ Opacidad de capa: {int(opacidad * 100)}%")


def aplicar_etiquetas_pal(
    capa_centroides, campo: str, log,
    ocultar_simbolo: bool = False, es_expresion: bool = False,
) -> None:
    """Etiquetas PAL con halo blanco. 'ocultar_simbolo' hace transparente el símbolo
    del punto (para capas de centroides que solo existen como ancla de la etiqueta).
    'es_expresion' trata 'campo' como expresión QGIS (p. ej. para combinar varios
    campos en una sola etiqueta) en vez de un nombre de campo simple."""
    if not campo:
        return

    if ocultar_simbolo:
        simbolo = QgsMarkerSymbol.createSimple({"color": "0,0,0,0", "outline_style": "no"})
        capa_centroides.setRenderer(QgsSingleSymbolRenderer(simbolo))

    pal              = QgsPalLayerSettings()
    pal.fieldName    = campo
    pal.isExpression = es_expresion
    pal.enabled      = True
    pal.placement    = _placement_over_point()

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

    capa_centroides.setLabelsEnabled(True)
    capa_centroides.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    capa_centroides.triggerRepaint()
    log.info(f" ✓ Etiquetas PAL configuradas en campo '{campo}'")


def aplicar_etiquetas_poligonos_grandes(
    capa, campo: str, log, fraccion_umbral: float = 0.15
) -> None:
    """Etiqueta solo los polígonos más grandes de 'capa' (área >= fraccion_umbral
    del área del polígono más grande), para figuras con muchos elementos donde
    etiquetar todo saturaría el mapa (p. ej. ANP/AICA/RTP/RHP superpuestas)."""
    if not campo:
        return

    pal           = QgsPalLayerSettings()
    pal.fieldName = campo
    pal.enabled   = True
    pal.placement = QgsPalLayerSettings.Horizontal

    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial", 8, QFont.Bold))
    fmt.setSize(8)
    fmt.setColor(QColor(20, 20, 20))

    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor(255, 255, 255, 210))
    fmt.setBuffer(buf)
    pal.setFormat(fmt)

    propiedades = pal.dataDefinedProperties()
    propiedades.setProperty(
        QgsPalLayerSettings.Show,
        QgsProperty.fromExpression(f"$area >= {fraccion_umbral} * maximum($area)"),
    )
    pal.setDataDefinedProperties(propiedades)

    capa.setLabelsEnabled(True)
    capa.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    capa.triggerRepaint()
    log.info(f" ✓ Etiquetas (solo polígonos grandes) en campo '{campo}'")
