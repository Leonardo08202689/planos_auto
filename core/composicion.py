"""
core/composicion.py — Gestión de layouts QGIS: carga de plantillas,
                       leyenda, barra de escala, grid, logo y etiquetas.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

from qgis.core import (
    QgsApplication,
    QgsLayoutItem,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemMapGrid,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendRenderer,
    QgsLegendStyle,
    QgsLineSymbol,
    QgsRenderContext,
    QgsTextFormat,
    QgsUnitTypes,
)

from .utils import segmento_barra_escala


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
_LEYENDA_MARGEN_PAGINA_MM = 1.5
_LEYENDA_ESCALA_MINIMA    = 0.5
_LEYENDA_PASO_ESCALA      = 0.92
_LEYENDA_FUENTE_MIN_PT    = 6.0
_LEYENDA_SIMBOLO_MIN_MM   = 3.0
_LEYENDA_MAX_COLUMNAS     = 5
_MM_POR_PT                = 0.352778


def _encoger_leyenda_a_contenido(leyenda) -> None:
    """QgsLayoutItemLegend.adjustBoxSize() no siempre encoge la caja (se
    observó que no hace nada en ciertos entornos/plantillas, dejando la
    leyenda con el tamaño original del QPT sin importar cuánto contenido
    tenga realmente). Se calcula el tamaño mínimo real con el motor interno
    de renderizado de la leyenda (QgsLegendRenderer, lo mismo que usa
    adjustBoxSize() por dentro) y se aplica directo con attemptResize(),
    que si funciona de forma confiable."""
    renderer = QgsLegendRenderer(leyenda.model(), leyenda.legendSettings())
    tam = renderer.minimumSize(QgsRenderContext())
    if tam.width() > 0 and tam.height() > 0:
        leyenda.attemptResize(
            QgsLayoutSize(tam.width(), tam.height(), QgsUnitTypes.LayoutMillimeters)
        )


def _ajustar_leyenda_a_pagina(leyenda, layout_comp, log=None) -> None:
    """Si la leyenda (por muchas categorías o nombres largos) crece más allá
    del borde de la página, reduce progresivamente fuentes y símbolos hasta
    que quepa, para que la simbología nunca se salga del plano impreso."""
    pages = layout_comp.pageCollection()
    if pages.pageCount() == 0:
        return
    pagina_idx = leyenda.page() if 0 <= leyenda.page() < pages.pageCount() else 0
    page_rect  = pages.page(pagina_idx).rect()
    pos        = leyenda.pagePos()

    max_w = page_rect.width()  - pos.x() - _LEYENDA_MARGEN_PAGINA_MM
    max_h = page_rect.height() - pos.y() - _LEYENDA_MARGEN_PAGINA_MM

    # Si hay otro elemento fijo debajo (p. ej. una franja de pie de página)
    # que se solape horizontalmente con la leyenda, ese es el límite real,
    # no el borde de la página — si no, la leyenda puede crecer y montarse
    # encima de ese elemento antes de llegar al borde.
    for item in layout_comp.items():
        if item is leyenda or not isinstance(item, QgsLayoutItem):
            continue
        item_pos  = item.pagePos()
        item_size = item.sizeWithUnits()
        solapa_x = (item_pos.x() < pos.x() + max_w) and (item_pos.x() + item_size.width() > pos.x())
        if solapa_x and item_pos.y() > pos.y():
            max_h = min(max_h, item_pos.y() - pos.y() - _LEYENDA_MARGEN_PAGINA_MM)

    if max_w <= 0 or max_h <= 0:
        return

    tam = leyenda.sizeWithUnits()
    if tam.width() <= max_w and tam.height() <= max_h:
        return  # ya cabe, no se toca nada

    # 1) Antes de encoger letra: repartir en más columnas, aprovechando el
    #    ancho disponible (leyendas tipo franja horizontal bajo el mapa).
    cols = max(1, leyenda.columnCount())
    while tam.height() > max_h and cols < _LEYENDA_MAX_COLUMNAS:
        cols += 1
        leyenda.setColumnCount(cols)
        leyenda.setSplitLayer(True)
        _encoger_leyenda_a_contenido(leyenda)
        tam = leyenda.sizeWithUnits()
    if tam.width() <= max_w and tam.height() <= max_h:
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

        _encoger_leyenda_a_contenido(leyenda)
        tam = leyenda.sizeWithUnits()
        if tam.width() <= max_w and tam.height() <= max_h:
            return

    if log:
        log.warning(
            " ⚠ La leyenda tiene demasiadas categorías/nombres largos y no "
            "cabe en la página aun al tamaño mínimo de letra. Revísala manualmente."
        )


def actualizar_leyenda(layout_comp, ids: dict, *capas, log=None, centrar_horizontal: bool = False) -> None:
    """Reconstruye la leyenda con las capas dadas, en el orden recibido.
    Las capas None se ignoran (permite pasar un slot opcional sin filtrar antes).

    Una capa con la propiedad personalizada 'grupo_leyenda' se anida dentro
    de un grupo con ese nombre (creado la primera vez que se usa) en vez de
    ir directo a la raíz; 'nombre_leyenda' sigue renombrando el nodo de la
    capa misma dentro de ese grupo.

    'centrar_horizontal=True' recentra la caja (ya encogida a su contenido)
    dentro del ancho de página — solo tiene sentido en plantillas donde la
    leyenda es una franja de ancho completo bajo el mapa (p. ej.
    Plantilla_Figurasv2). En plantillas con la leyenda como cajita flotante
    en una esquina del mapa (Plantilla_Corporativa, Plantilla_figuras),
    recentrarla la monta encima del mapa — dejar en False ahí."""
    leyenda = layout_comp.itemById(ids["leyenda"])
    if not (leyenda and isinstance(leyenda, QgsLayoutItemLegend)):
        return
    # Los ítems con "positionLock" en el QPT hacen que attemptResize()/
    # attemptMove() (usados por adjustBoxSize() y el recentrado) no hagan
    # nada — hay que destrabar antes de tocar tamaño/posición.
    leyenda.setLocked(False)
    leyenda.setAutoUpdateModel(False)
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
    _encoger_leyenda_a_contenido(leyenda)
    _ajustar_leyenda_a_pagina(leyenda, layout_comp, log)
    if centrar_horizontal:
        _centrar_leyenda_horizontal(leyenda, layout_comp)
    leyenda.refresh()


def _centrar_leyenda_horizontal(leyenda, layout_comp) -> None:
    """Sin esto, la caja queda con el ancho real del contenido pero en la
    posición X original (normalmente el margen izquierdo de una franja
    pensada para ancho completo), así que el bloque de símbolos queda pegado
    a la izquierda con toda la franja vacía a la derecha.

    Con varias columnas (suficientes categorías para repartirse en 2+, p.
    ej. RTP/ANP con muchas entradas) se estira la caja a todo el ancho
    disponible y se activa 'equalColumnWidth' para que las columnas se
    repartan parejo de borde a borde, como en la referencia de Sinergia.

    Con una sola columna (pocas entradas, p. ej. UAB) estirar a todo el
    ancho dejaría el símbolo pegado a la izquierda de una caja enorme y
    vacía a la derecha — ahí en cambio se deja la caja a su tamaño natural
    y solo se centra."""
    pages = layout_comp.pageCollection()
    if pages.pageCount() == 0:
        return
    pagina_idx = leyenda.page() if 0 <= leyenda.page() < pages.pageCount() else 0
    page_rect  = pages.page(pagina_idx).rect()
    pos        = leyenda.pagePos()
    tam        = leyenda.sizeWithUnits()

    ancho_objetivo = tam.width()
    if leyenda.columnCount() > 1:
        leyenda.setEqualColumnWidth(True)
        ancho_objetivo = page_rect.width() - 2 * _LEYENDA_MARGEN_PAGINA_MM
        if abs(ancho_objetivo - tam.width()) > 0.1:
            leyenda.attemptResize(
                QgsLayoutSize(ancho_objetivo, tam.height(), QgsUnitTypes.LayoutMillimeters)
            )

    nuevo_x = max(0.0, (page_rect.width() - ancho_objetivo) / 2)
    if abs(nuevo_x - pos.x()) < 0.1:
        return
    leyenda.attemptMove(
        QgsLayoutPoint(nuevo_x, pos.y(), QgsUnitTypes.LayoutMillimeters),
        useReferencePoint=False, page=pagina_idx,
    )


def reenlazar_barra_escala(layout_comp, map_item, log, unidades_por_segmento=None) -> None:
    # Sin valor explícito, se calcula un segmento acorde a la escala real del
    # mapa (~2 cm de papel por segmento); el segmento fijo de la plantilla
    # solo es válido para la escala con la que se diseñó el QPT.
    if not unidades_por_segmento:
        unidades_por_segmento = segmento_barra_escala(map_item.scale())
    n = 0
    for item in layout_comp.items():
        if isinstance(item, QgsLayoutItemScaleBar):
            item.setLinkedMap(map_item)
            item.setUnits(QgsUnitTypes.DistanceMeters)
            item.setUnitLabel("m")
            item.setUnitsPerSegment(unidades_por_segmento)
            item.refreshItemSize()
            item.refresh()
            n += 1
    if n:
        log.debug(
            f" ✓ Barra(s) de escala re-enlazada(s): {n} "
            f"({unidades_por_segmento:,.0f} m/segmento)"
        )
    else:
        log.warning(" → No se encontró barra de escala.")


def configurar_grid_mapa(map_item, intervalo_m: float, log) -> None:
    grids = map_item.grids()
    grid  = grids.grid(0) if grids.size() > 0 else QgsLayoutItemMapGrid("Grid", map_item)
    if grids.size() == 0:
        grids.addGrid(grid)
    grid.setIntervalX(intervalo_m)
    grid.setIntervalY(intervalo_m)
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
    log.debug(f" ✓ Grid: {intervalo_m:,.0f} m")


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


def _altura_texto_envuelto_mm(texto: str, fuente, ancho_mm: float) -> float:
    """Altura (mm) que ocupará 'texto' envuelto por palabras al ancho dado,
    aproximada con métricas de la fuente (1 pt ≈ 0.3528 mm)."""
    from qgis.PyQt.QtGui import QFontMetricsF
    fm = QFontMetricsF(fuente)
    max_w_pt = ancho_mm / _MM_POR_PT
    lineas = 0
    for parrafo in (texto or "").splitlines() or [""]:
        palabras = parrafo.split()
        if not palabras:
            lineas += 1
            continue
        actual, n = palabras[0], 1
        for p in palabras[1:]:
            candidata = f"{actual} {p}"
            if fm.horizontalAdvance(candidata) > max_w_pt:
                n += 1
                actual = p
            else:
                actual = candidata
        lineas += n
    return lineas * fm.lineSpacing() * _MM_POR_PT


def _encoger_fuente_si_desborda(item) -> None:
    """Si el texto (envuelto al ancho del label) necesita más altura de la que
    tiene la caja fija del label, reduce la fuente hasta que quepa — evita que
    un título largo se derrame sobre el label vecino (p. ej. la fecha)."""
    if not isinstance(item, QgsLayoutItemLabel):
        return
    try:
        fmt = item.textFormat()
    except AttributeError:  # QGIS viejo sin textFormat()
        return
    box = item.sizeWithUnits()
    if box.width() <= 0 or box.height() <= 0:
        return
    for _ in range(15):
        if _altura_texto_envuelto_mm(item.currentText(), fmt.toQFont(), box.width()) \
                <= box.height() + 0.2:
            return
        nuevo = fmt.size() * 0.9
        if nuevo < 5:
            return
        fmt.setSize(nuevo)
        item.setTextFormat(fmt)


def set_label_text(layout_comp, item_id: str, texto: str, log=None) -> None:
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
            _encoger_fuente_si_desborda(item)
    elif log:
        log.debug(f" → Ítem '{item_id}' no encontrado.")
