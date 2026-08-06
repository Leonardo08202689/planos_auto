"""
core/composicion.py — Gestión de layouts QGIS: carga de plantillas,
                       leyenda, barra de escala, grid, logo y etiquetas.
"""

import os

from qgis.PyQt.QtGui import QFont

from qgis.core import (
    QgsLayoutItem,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemMapGrid,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsLegendStyle,
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
    if max_w <= 0 or max_h <= 0:
        return

    tam = leyenda.sizeWithUnits()
    if tam.width() <= max_w and tam.height() <= max_h:
        return  # ya cabe, no se toca nada

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

        leyenda.adjustBoxSize()
        tam = leyenda.sizeWithUnits()
        if tam.width() <= max_w and tam.height() <= max_h:
            return

    if log:
        log.warning(
            " ⚠ La leyenda tiene demasiadas categorías/nombres largos y no "
            "cabe en la página aun al tamaño mínimo de letra. Revísala manualmente."
        )


def actualizar_leyenda(layout_comp, ids: dict, *capas, log=None) -> None:
    """Reconstruye la leyenda con las capas dadas, en el orden recibido.
    Las capas None se ignoran (permite pasar un slot opcional sin filtrar antes).

    Una capa con la propiedad personalizada 'grupo_leyenda' se anida dentro
    de un grupo con ese nombre (creado la primera vez que se usa) en vez de
    ir directo a la raíz; 'nombre_leyenda' sigue renombrando el nodo de la
    capa misma dentro de ese grupo."""
    leyenda = layout_comp.itemById(ids["leyenda"])
    if not (leyenda and isinstance(leyenda, QgsLayoutItemLegend)):
        return
    leyenda.setAutoUpdateModel(False)
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
    leyenda.adjustBoxSize()
    _ajustar_leyenda_a_pagina(leyenda, layout_comp, log)
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
    map_item.refresh()
    log.debug(f" ✓ Grid: {intervalo_m:,.0f} m")


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
    elif log:
        log.debug(f" → Ítem '{item_id}' no encontrado.")
