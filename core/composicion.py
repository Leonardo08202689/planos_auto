"""
core/composicion.py — Gestión de layouts QGIS: carga de plantillas,
                       leyenda, barra de escala, grid, logo y etiquetas.
"""

import math
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsLayoutItem,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemMapGrid,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLayoutUtils,
    QgsLegendRenderer,
    QgsLegendStyle,
    QgsLineSymbol,
    QgsRenderContext,
    QgsScaleBarSettings,
    QgsTextFormat,
    QgsUnitTypes,
)

# ---------------------------------------------------------------------------
# Carga de plantillas QPT
# ---------------------------------------------------------------------------

def cargar_o_importar_layout(project, layout_nombre: str, plantillas_dir: str, log):
    """
    Importa el layout maestro desde el QPT, reemplazando cualquier versión
    previa cacheada en el proyecto, para que los cambios al .qpt siempre
    se reflejen (si el archivo no se encuentra, reutiliza el layout ya
    cargado en el proyecto como respaldo).
    """
    layout_previo = project.layoutManager().layoutByName(layout_nombre)

    candidatos = [
        os.path.join(plantillas_dir, f"{layout_nombre}.qpt"),
        os.path.join(os.getcwd(),    f"{layout_nombre}.qpt"),
    ]
    qpt_path = next((p for p in candidatos if os.path.exists(p)), None)

    if not qpt_path:
        if layout_previo:
            log.warning(
                f" → '{layout_nombre}.qpt' no encontrado; "
                f"se reutiliza el layout ya cargado en el proyecto."
            )
            return layout_previo
        log.error(
            f" ✗ '{layout_nombre}.qpt' no encontrado. "
            f"Buscado en: {candidatos}"
        )
        return None

    if layout_previo:
        project.layoutManager().removeLayout(layout_previo)

    log.debug(f" → Importando plantilla desde: {qpt_path}")
    try:
        from qgis.core import QgsPrintLayout, QgsReadWriteContext
        from qgis.PyQt.QtXml import QDomDocument

        nuevo_layout = QgsPrintLayout(project)
        with open(qpt_path, "r", encoding="utf-8") as fh:
            contenido = fh.read()
        doc = QDomDocument()
        if not doc.setContent(contenido):
            log.error(" ✗ No se pudo parsear el QPT.")
            return None
        if not nuevo_layout.loadFromTemplate(doc, QgsReadWriteContext()):
            log.error(" ✗ loadFromTemplate falló.")
            return None
        nuevo_layout.setName(layout_nombre)
        project.layoutManager().addLayout(nuevo_layout)
        return nuevo_layout
    except Exception as exc:
        log.error(f" ✗ Error al importar QPT: {exc}")
        return None


# ---------------------------------------------------------------------------
# IDs y validación de extent
# ---------------------------------------------------------------------------

def resolver_ids(cfg_global: dict, cfg_capa: dict) -> dict:
    """Combina IDs globales con los ids_override específicos de la capa."""
    ids = dict(cfg_global["ids"])
    ids.update(cfg_capa.get("ids_override", {}))
    return ids


def validar_extent(extent, nombre_capa: str, log, escala: float = 0) -> None:
    """
    Advierte si el extent del map_item es anormalmente grande para la
    escala configurada (equivaldría a un papel de más de 1 m de lado),
    lo que indica un ID de mapa incorrecto.
    """
    ancho, alto = extent.width(), extent.height()
    umbral = escala if escala else 500_000
    if ancho > umbral or alto > umbral:
        log.warning(
            f" ⚠ Extent MUY GRANDE para '{nombre_capa}': "
            f"{ancho:,.0f} × {alto:,.0f} u. "
            f"Verifica 'ids_override → mapa'."
        )
    else:
        log.debug(f" → extent_en_escala: {ancho:,.0f} × {alto:,.0f} u.")


# ---------------------------------------------------------------------------
# Actualizar elementos del layout
# ---------------------------------------------------------------------------

_ESTILOS_LEYENDA = (
    QgsLegendStyle.Title,
    QgsLegendStyle.Group,
    QgsLegendStyle.Subgroup,
    QgsLegendStyle.Symbol,
    QgsLegendStyle.SymbolLabel,
)
_LEYENDA_ESCALA_MINIMA    = 0.5
_LEYENDA_PASO_ESCALA      = 0.92
_LEYENDA_FUENTE_MIN_PT    = 6.0
_LEYENDA_SIMBOLO_MIN_MM   = 3.0
_LEYENDA_MAX_COLUMNAS     = 5
_LEYENDA_MARGEN_TEXTO_PCT = 0.06  # colchón: minimumSize() subestima el ancho real del texto
_LEYENDA_MARGEN_TEXTO_MM  = 1.0


def _medir_leyenda(leyenda):
    """Tamaño (ancho, alto) que necesita el contenido actual de la leyenda,
    con un colchón de seguridad: QgsRenderContext() por defecto no reproduce
    el contexto real de exportación (DPI/escala) del layout, así que
    QgsLegendRenderer.minimumSize() subestima el ancho real del texto
    renderizado. Sin colchón, un contenido que en teoría "cabe" se saldría
    un poco de la caja en el PNG final."""
    renderer = QgsLegendRenderer(leyenda.model(), leyenda.legendSettings())
    tam = renderer.minimumSize(QgsRenderContext())
    ancho = tam.width()  * (1 + _LEYENDA_MARGEN_TEXTO_PCT) + _LEYENDA_MARGEN_TEXTO_MM
    alto  = tam.height() * (1 + _LEYENDA_MARGEN_TEXTO_PCT * 0.3)
    return ancho, alto


def _ajustar_fuente_a_tamano_reservado(leyenda, tam_reservado, log=None) -> None:
    """El bloque de simbología SIEMPRE mide lo mismo que en la plantilla: los
    QPT traen 'resizeToContents' desactivado a propósito porque el tamaño y
    la posición del bloque son parte del diseño del plano, no algo que deba
    variar con el contenido. Por eso esta función nunca llama a
    attemptResize()/attemptMove() sobre la leyenda — solo ajusta letra y
    símbolos, y únicamente cuando el contenido real (muchas categorías o
    nombres largos) no cabría en ese tamaño fijo, para que la simbología
    nunca se salga del marco. Con contenido normal no se toca nada: la
    leyenda queda con la tipografía tal cual la definió la plantilla."""
    max_w, max_h = tam_reservado.width(), tam_reservado.height()
    if max_w <= 0 or max_h <= 0:
        return

    ancho, alto = _medir_leyenda(leyenda)
    if ancho <= max_w and alto <= max_h:
        return  # cabe con la tipografía de la plantilla, no se toca nada

    # 1) Antes de encoger letra: repartir en más columnas, aprovechando el
    #    ancho fijo de la caja (leyendas tipo franja horizontal bajo el mapa).
    cols = max(1, leyenda.columnCount())
    while alto > max_h and cols < _LEYENDA_MAX_COLUMNAS:
        cols += 1
        leyenda.setColumnCount(cols)
        leyenda.setSplitLayer(True)
        ancho, alto = _medir_leyenda(leyenda)
    if ancho <= max_w and alto <= max_h:
        return

    fuentes_orig    = {est: QFont(leyenda.styleFont(est)) for est in _ESTILOS_LEYENDA}
    ancho_sim_orig  = leyenda.symbolWidth()
    alto_sim_orig   = leyenda.symbolHeight()

    escala = 1.0
    while escala > _LEYENDA_ESCALA_MINIMA:
        escala *= _LEYENDA_PASO_ESCALA
        for estilo, fuente_orig in fuentes_orig.items():
            fuente = QFont(fuente_orig)
            pt_orig = fuente_orig.pointSizeF() if fuente_orig.pointSizeF() > 0 else 9.0
            fuente.setPointSizeF(max(_LEYENDA_FUENTE_MIN_PT, pt_orig * escala))
            leyenda.setStyleFont(estilo, fuente)
        leyenda.setSymbolWidth(max(_LEYENDA_SIMBOLO_MIN_MM, ancho_sim_orig * escala))
        leyenda.setSymbolHeight(max(_LEYENDA_SIMBOLO_MIN_MM, alto_sim_orig * escala))

        ancho, alto = _medir_leyenda(leyenda)
        if ancho <= max_w and alto <= max_h:
            return

    if log:
        log.warning(
            " ⚠ La leyenda tiene demasiadas categorías/nombres largos y no "
            "cabe en el tamaño reservado por la plantilla aun al tamaño "
            "mínimo de letra. Revísala manualmente."
        )


def actualizar_leyenda(layout_comp, ids: dict, *capas, log=None, centrar_horizontal: bool = False) -> None:
    """Reconstruye la leyenda con las capas dadas, en el orden recibido.
    Las capas None se ignoran (permite pasar un slot opcional sin filtrar antes).

    Una capa con la propiedad personalizada 'grupo_leyenda' se anida dentro
    de un grupo con ese nombre (creado la primera vez que se usa) en vez de
    ir directo a la raíz; 'nombre_leyenda' sigue renombrando el nodo de la
    capa misma dentro de ese grupo.

    El bloque de simbología conserva siempre el tamaño y la posición
    definidos en la plantilla QPT (ver _ajustar_fuente_a_tamano_reservado).

    'centrar_horizontal=True' reparte las columnas de forma pareja
    (equalColumnWidth) cuando hay varias — pensado para plantillas donde la
    leyenda es una franja de ancho completo bajo el mapa (p. ej.
    Plantilla_Figurasv2)."""
    leyenda = layout_comp.itemById(ids["leyenda"])
    if not (leyenda and isinstance(leyenda, QgsLayoutItemLegend)):
        return
    # Los ítems con "positionLock" en el QPT hacen que setStyleFont()/
    # setColumnCount() no muevan la caja, pero por si acaso alguna versión
    # de QGIS reacciona distinto, se destraba antes de tocar la leyenda.
    leyenda.setLocked(False)
    leyenda.setAutoUpdateModel(False)
    # Tamaño y posición tal cual los definió la plantilla: se capturan aquí
    # y se restauran al final, sin importar qué le pase al contenido.
    tam_reservado = leyenda.sizeWithUnits()
    pos_reservada = leyenda.positionWithUnits()
    # Título siempre centrado y en negritas, independiente de la plantilla
    leyenda.setTitleAlignment(Qt.AlignHCenter)
    f_titulo = QFont(leyenda.styleFont(QgsLegendStyle.Title))
    f_titulo.setBold(True)
    leyenda.setStyleFont(QgsLegendStyle.Title, f_titulo)
    root = leyenda.model().rootGroup()
    root.removeAllChildren()
    grupos = {}
    for capa in capas:
        if not capa:
            continue
        contenedor = root
        nombre_grupo = capa.customProperty("grupo_leyenda")
        if nombre_grupo:
            contenedor = grupos.get(nombre_grupo)
            if contenedor is None:
                contenedor = root.addGroup(nombre_grupo)
                grupos[nombre_grupo] = contenedor
        nodo = contenedor.addLayer(capa)
        nombre_custom = capa.customProperty("nombre_leyenda")
        if nombre_custom:
            nodo.setName(nombre_custom)
    _ajustar_fuente_a_tamano_reservado(leyenda, tam_reservado, log)
    if centrar_horizontal and leyenda.columnCount() > 1:
        leyenda.setEqualColumnWidth(True)
    # Restaurar tamaño y posición del QPT por si algo los movió de lado.
    leyenda.attemptResize(tam_reservado)
    leyenda.attemptMove(pos_reservada)
    leyenda.refresh()


def reenlazar_barra_escala(layout_comp, map_item, log) -> None:
    """Ajusta barra y ambos ejes del grid a la misma distancia que cabe."""
    grid = map_item.grids().grid(0)
    if grid is None or grid.intervalX() <= 0:
        return
    extent = QgsCoordinateTransform(
        map_item.crs(), grid.crs(), map_item.layout().project(),
    ).transformBoundingBox(map_item.extent())
    magnitud = 10 ** math.floor(math.log10(max(extent.width(), extent.height()) / 10))
    # Contar también los cuadros parciales de ambos bordes.
    candidatos = sorted({
        n / 2 * magnitud * factor
        for factor in (0.1, 1, 10)
        for n in range(2, 21)
        if all(
            math.ceil(fin / (n / 2 * magnitud * factor))
            - math.floor(inicio / (n / 2 * magnitud * factor)) <= 10
            for inicio, fin in (
                (extent.xMinimum(), extent.xMaximum()),
                (extent.yMinimum(), extent.yMaximum()),
            )
        )
    })
    distancia_grid = min(candidatos, key=lambda paso: abs(paso - grid.intervalX()))
    paneles = [i for i in layout_comp.items() if isinstance(i, QgsLayoutItemLegend)]
    barras = []
    n = 0
    for item in layout_comp.items():
        if isinstance(item, QgsLayoutItemScaleBar):
            centro = item.sceneBoundingRect().center().x()
            ancho_disponible = item.rect().width()
            if paneles:
                panel = min(paneles, key=lambda p: abs(p.sceneBoundingRect().center().x() - centro))
                centro = panel.sceneBoundingRect().center().x()
                ancho_disponible = panel.rect().width()
            ancho_disponible = max(1.0, ancho_disponible - 6.0)
            unidades_por_segmento = distancia_grid / 2
            y = item.pos().y()
            item.setLinkedMap(map_item)
            item.setUnits(QgsUnitTypes.DistanceMeters)
            item.setUnitLabel("m")
            item.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeFixed)
            item.setNumberOfSegments(2)
            item.setNumberOfSegmentsLeft(0)
            item.setUnitsPerSegment(unidades_por_segmento)
            item.refreshItemSize()
            item.resizeToMinimumWidth()
            # Reducir solo a distancias redondas que no excedan 10 cuadros.
            for paso in reversed([p for p in candidatos if p <= distancia_grid]):
                unidades_por_segmento = paso / 2
                item.setUnitsPerSegment(unidades_por_segmento)
                item.refreshItemSize()
                item.resizeToMinimumWidth()
                if item.rect().width() <= ancho_disponible:
                    break
            else:
                log.warning(" → El panel es demasiado estrecho para las etiquetas de la barra de escala.")
            distancia_grid = min(distancia_grid, unidades_por_segmento * 2)
            barras.append((item, centro, y))
            n += 1
    if n:
        grid.setIntervalX(distancia_grid)
        grid.setIntervalY(distancia_grid)
        map_item.refresh()
        for item, centro, y in barras:
            item.setUnitsPerSegment(distancia_grid / 2)
            item.refreshItemSize()
            item.resizeToMinimumWidth()
            item.attemptMove(QgsLayoutPoint(
                centro - item.rect().width() / 2, y,
                QgsUnitTypes.LayoutMillimeters,
            ), useReferencePoint=False)
            item.refresh()
        log.debug(
            f" ✓ Barra(s) de escala re-enlazada(s): {n} "
            f"(barra y cuadro del grid: {distancia_grid:g} m)"
        )
    else:
        log.warning(" → No se encontró barra de escala.")


def configurar_grid_mapa(map_item, log) -> None:
    """Conserva coordenadas métricas y muestra unas cinco líneas por eje."""
    grids = map_item.grids()
    grid = grids.grid(0) if grids.size() > 0 else QgsLayoutItemMapGrid("Grid", map_item)
    if grids.size() == 0:
        grids.addGrid(grid)
    crs = grid.crs()
    if not crs.isValid() or crs.mapUnits() != QgsUnitTypes.DistanceMeters:
        crs = map_item.crs()
    if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
        # Sin CRS métrico en la plantilla, usar la zona UTM del encuadre.
        centro = QgsCoordinateTransform(
            map_item.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
            map_item.layout().project(),
        ).transform(map_item.extent().center())
        zona = min(60, max(1, int((centro.x() + 180) / 6) + 1))
        crs = QgsCoordinateReferenceSystem(f"EPSG:{(32600 if centro.y() >= 0 else 32700) + zona}")
    extent = map_item.extent()
    if crs != map_item.crs():
        extent = QgsCoordinateTransform(
            map_item.crs(), crs, map_item.layout().project(),
        ).transformBoundingBox(extent)
    if extent.width() <= 0 or extent.height() <= 0:
        return
    # Elegir distancias redondas cercanas a cinco divisiones (100, 150, 200…).
    intervalos = []
    for lado in (extent.width(), extent.height()):
        magnitud = 10 ** math.floor(math.log10(lado / 5))
        candidatos = [n * magnitud for n in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10)]
        intervalos.append(min(candidatos, key=lambda paso: abs(lado / paso - 5)))
    grid.setCrs(crs)
    grid.setAnnotationFormat(QgsLayoutItemMapGrid.Decimal)
    grid.setAnnotationPrecision(0)
    grid.setIntervalX(intervalos[0])
    grid.setIntervalY(intervalos[1])
    grid.setOffsetX(0)
    grid.setOffsetY(0)
    grid.setUnits(QgsLayoutItemMapGrid.MapUnit)
    grid.setEnabled(True)

    # Grids que la plantilla dejó sin estilizar (sin coordenadas en los
    # bordes) reciben un estilo por defecto: líneas gris claro y coordenadas
    # a los lados. Los grids ya configurados en el QPT no se tocan.
    if not grid.annotationEnabled():
        grid.setStyle(QgsLayoutItemMapGrid.Solid)
        grid.setLineSymbol(QgsLineSymbol.createSimple({
            "color": "175,175,175,160", "line_width": "0.15",
        }))
        grid.setAnnotationEnabled(True)
        grid.setAnnotationPrecision(0)
        grid.setAnnotationFrameDistance(0.8)
        grid.setAnnotationDirection(
            QgsLayoutItemMapGrid.Vertical, QgsLayoutItemMapGrid.Left
        )
        grid.setAnnotationDirection(
            QgsLayoutItemMapGrid.Vertical, QgsLayoutItemMapGrid.Right
        )
        fmt = QgsTextFormat()
        fmt.setFont(QFont("Arial", 6))
        fmt.setSize(6.0)
        fmt.setColor(QColor(70, 70, 70))
        try:
            grid.setAnnotationTextFormat(fmt)
        except AttributeError:  # QGIS < 3.16
            grid.setAnnotationFont(QFont("Arial", 6))
        log.debug(" → Grid sin estilo en la plantilla: gris claro + coordenadas.")

    map_item.refresh()
    log.debug(f" ✓ Grid automático (~5 líneas/eje): X={intervalos[0]:g}, Y={intervalos[1]:g}")


_PISTAS_FLECHA_NORTE = ("north", "norte", "arrow", "brujula", "brújula", "compass", "rosa")


def asegurar_estrella_norte(layout_comp, map_item, log) -> None:
    """Garantiza que el plano tenga flecha de norte: si ninguna imagen del
    layout parece serlo (por id o por ruta del archivo), añade la flecha
    estándar de QGIS (la misma NorthArrow_06 de Plantilla_Corporativa) en la
    esquina superior derecha del mapa principal."""
    for item in layout_comp.items():
        if isinstance(item, QgsLayoutItemPicture):
            pista = f"{item.id()} {item.picturePath()}".lower()
            if any(s in pista for s in _PISTAS_FLECHA_NORTE):
                return  # ya hay una
    if not map_item:
        return

    ruta = ""
    for base in QgsApplication.svgPaths():
        cand = os.path.join(base, "arrows", "NorthArrow_06.svg")
        if os.path.exists(cand):
            ruta = cand
            break
    if not ruta:
        ruta = ":/images/north_arrows/layout_default_north_arrow.svg"

    flecha = QgsLayoutItemPicture(layout_comp)
    flecha.setId("estrella_norte")
    flecha.setPicturePath(ruta)
    layout_comp.addLayoutItem(flecha)

    lado = 12.0
    pos  = map_item.positionWithUnits()
    tam  = map_item.sizeWithUnits()
    flecha.attemptResize(QgsLayoutSize(lado, lado, QgsUnitTypes.LayoutMillimeters))
    flecha.attemptMove(QgsLayoutPoint(
        pos.x() + tam.width() - lado - 4.0, pos.y() + 4.0,
        QgsUnitTypes.LayoutMillimeters,
    ))
    try:
        flecha.setLinkedMap(map_item)
        flecha.setNorthMode(QgsLayoutItemPicture.GridNorth)
    except AttributeError:
        pass
    flecha.setZValue(50)
    log.debug(" ✓ Estrella del norte añadida al layout.")


def fijar_logo(layout_comp, id_logo: str, logo_ruta: str, log) -> None:
    if not id_logo:
        return
    if not logo_ruta or not os.path.exists(logo_ruta):
        log.warning(f" → Logo no encontrado: {logo_ruta}")
        return
    item = layout_comp.itemById(id_logo)
    if item and isinstance(item, QgsLayoutItemPicture):
        item.setPicturePath(logo_ruta)
        item.refreshPicture()
        item.refresh()
        log.debug(f" ✓ Logo: {os.path.basename(logo_ruta)}")
    else:
        log.warning(f" → Ítem de logo '{id_logo}' no encontrado o no es imagen.")


_LABEL_MARGEN_PCT     = 0.06  # colchón adicional dentro de la caja
_LABEL_FUENTE_PT      = 9.0
_LABEL_PASO_REDUCIR   = 1.06


def _medir_texto_envuelto_mm(texto: str, fuente, ancho_max_mm: float):
    """(ancho_usado_mm, alto_mm) que ocupará 'texto' envuelto por palabras a
    lo sumo al ancho dado, con métricas QGIS en milímetros."""
    lineas = []
    for parrafo in (texto or "").splitlines() or [""]:
        palabras = parrafo.split()
        if not palabras:
            lineas.append("")
            continue
        actual = palabras[0]
        for p in palabras[1:]:
            candidata = f"{actual} {p}"
            if QgsLayoutUtils.textWidthMM(fuente, candidata) > ancho_max_mm:
                lineas.append(actual)
                actual = p
            else:
                actual = candidata
        lineas.append(actual)
    ancho_mm = max((QgsLayoutUtils.textWidthMM(fuente, linea) for linea in lineas), default=0.0)
    alto_mm = len(lineas) * QgsLayoutUtils.fontHeightMM(fuente)
    return ancho_mm, alto_mm


def _ajustar_fuente_al_cuadro(item, tam_base: float = _LABEL_FUENTE_PT) -> None:
    """Usa el tamaño indicado y reduce solo si no cabe en su caja."""
    if not isinstance(item, QgsLayoutItemLabel):
        return
    try:
        fmt = item.textFormat()
    except AttributeError:  # QGIS viejo sin textFormat()
        return
    box = item.rect()
    texto = item.currentText()
    if box.width() <= 0 or box.height() <= 0 or not texto:
        return

    max_w = (box.width() - 2 * item.marginX()) * (1 - _LABEL_MARGEN_PCT)
    max_h = (box.height() - 2 * item.marginY()) * (1 - _LABEL_MARGEN_PCT * 0.5)
    if max_w <= 0 or max_h <= 0:
        return

    def cabe(tam: float) -> bool:
        fuente = fmt.toQFont()
        fuente.setPointSizeF(tam)
        ancho, alto = _medir_texto_envuelto_mm(texto, fuente, max_w)
        return ancho <= max_w and alto <= max_h

    tam = tam_base
    while not cabe(tam):
        tam /= _LABEL_PASO_REDUCIR

    fmt.setSizeUnit(QgsUnitTypes.RenderPoints)
    fmt.setSize(tam)
    item.setTextFormat(fmt)


def unificar_etiquetas_mapitas(layout_comp, ids: dict) -> None:
    """Usa el mismo tamaño para estado, municipio y país en los insertos."""
    etiquetas = [
        item for item in layout_comp.items()
        if isinstance(item, QgsLayoutItemLabel)
        and (
            item.id() in {ids.get("lbl_estado", "lbl_estado"), ids.get("lbl_municipio", "lbl_municipio")}
            or item.text().strip().casefold() in {"republica mexicana", "república mexicana"}
        )
    ]
    for item in etiquetas:
        _ajustar_fuente_al_cuadro(item)
    tam = min((item.textFormat().size() for item in etiquetas), default=_LABEL_FUENTE_PT)
    for item in etiquetas:
        fmt = item.textFormat()
        fmt.setSize(tam)
        item.setTextFormat(fmt)


def set_label_text(layout_comp, item_id: str, texto: str, log=None,
                   tam_fuente: float = _LABEL_FUENTE_PT) -> None:
    """Asigna 'texto' a TODOS los ítems con id == item_id (puede haber más de uno,
    p. ej. la misma etiqueta de municipio repetida en varios insertos)."""
    if not item_id:
        return
    items = [
        i for i in layout_comp.items()
        if isinstance(i, QgsLayoutItem) and i.id() == item_id
    ]
    if items:
        for item in items:
            item.setText(texto)
            _ajustar_fuente_al_cuadro(item, tam_fuente)
    elif log:
        log.debug(f" → Ítem '{item_id}' no encontrado.")
