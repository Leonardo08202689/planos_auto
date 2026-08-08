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
_LEYENDA_ESCALA_MINIMA    = 0.5
_LEYENDA_PASO_ESCALA      = 0.92
_LEYENDA_FUENTE_MIN_PT    = 6.0
_LEYENDA_SIMBOLO_MIN_MM   = 3.0
_LEYENDA_MAX_COLUMNAS     = 5
_LEYENDA_MARGEN_TEXTO_PCT = 0.06  # colchón: minimumSize() subestima el ancho real del texto
_LEYENDA_MARGEN_TEXTO_MM  = 1.0
_MM_POR_PT                = 0.352778


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


_LABEL_MARGEN_PCT     = 0.06  # colchón: la caja del ítem QGIS suele traer un
                              # pequeño padding interno que QFontMetricsF no ve
_LABEL_PASO_CRECER    = 1.06
_LABEL_ESCALA_MAX     = 1.8   # tope relativo al tamaño de la plantilla, para
                              # no deformar el diseño del recuadro de datos
_LABEL_FUENTE_MIN_PT  = 5.0


def _medir_texto_envuelto_mm(texto: str, fuente, ancho_max_mm: float):
    """(ancho_usado_mm, alto_mm) que ocupará 'texto' envuelto por palabras a
    lo sumo al ancho dado, con métricas de la fuente (1 pt ≈ 0.3528 mm)."""
    from qgis.PyQt.QtGui import QFontMetricsF
    fm = QFontMetricsF(fuente)
    max_w_pt = ancho_max_mm / _MM_POR_PT
    lineas = []
    for parrafo in (texto or "").splitlines() or [""]:
        palabras = parrafo.split()
        if not palabras:
            lineas.append("")
            continue
        actual = palabras[0]
        for p in palabras[1:]:
            candidata = f"{actual} {p}"
            if fm.horizontalAdvance(candidata) > max_w_pt:
                lineas.append(actual)
                actual = p
            else:
                actual = candidata
        lineas.append(actual)
    ancho_pt = max((fm.horizontalAdvance(linea) for linea in lineas), default=0.0)
    alto_mm  = len(lineas) * fm.lineSpacing() * _MM_POR_PT
    return ancho_pt * _MM_POR_PT, alto_mm


def _ajustar_fuente_al_cuadro(item) -> None:
    """Ajusta la letra del label a la caja fija que le dio la plantilla:

    - Si el texto (envuelto al ancho del label) se desborda de la caja,
      reduce la fuente hasta que quepa — evita que un título largo se
      derrame sobre el label vecino (p. ej. la fecha).
    - Si el texto cabe con espacio de sobra (caso típico: nombres cortos
      del proyecto/plano en una caja del tamaño de la plantilla, pensada
      para textos más largos), agranda la fuente hasta llenar mejor la
      caja, sin pasar de un tope relativo al tamaño original para no
      deformar el diseño del recuadro de datos."""
    if not isinstance(item, QgsLayoutItemLabel):
        return
    try:
        fmt = item.textFormat()
    except AttributeError:  # QGIS viejo sin textFormat()
        return
    box = item.sizeWithUnits()
    texto = item.currentText()
    if box.width() <= 0 or box.height() <= 0 or not texto:
        return

    tam_orig = fmt.size() if fmt.size() > 0 else 9.0
    max_w = box.width()  * (1 - _LABEL_MARGEN_PCT)
    max_h = box.height() * (1 - _LABEL_MARGEN_PCT * 0.5)

    def cabe(tam: float) -> bool:
        fuente = fmt.toQFont()
        fuente.setPointSizeF(tam)
        ancho, alto = _medir_texto_envuelto_mm(texto, fuente, box.width())
        return ancho <= max_w and alto <= max_h

    tam = tam_orig
    if cabe(tam):
        # Espacio de sobra: crecer hasta llenar la caja o llegar al tope.
        tope = tam_orig * _LABEL_ESCALA_MAX
        while tam < tope and cabe(tam * _LABEL_PASO_CRECER):
            tam *= _LABEL_PASO_CRECER
        tam = min(tam, tope)
    else:
        # Se desborda al tamaño de la plantilla: encoger hasta que quepa.
        while tam > _LABEL_FUENTE_MIN_PT and not cabe(tam):
            tam /= _LABEL_PASO_CRECER
        tam = max(tam, _LABEL_FUENTE_MIN_PT)

    if abs(tam - fmt.size()) > 0.05:
        fmt.setSize(tam)
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
            _ajustar_fuente_al_cuadro(item)
    elif log:
        log.debug(f" → Ítem '{item_id}' no encontrado.")
