"""
core/composicion.py — Gestión de layouts QGIS: carga de plantillas,
                       leyenda, barra de escala, grid, logo y etiquetas.
"""

import os

from qgis.core import (
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemMapGrid,
    QgsLayoutItemPicture,
    QgsLayoutItemScaleBar,
    QgsUnitTypes,
)


# ---------------------------------------------------------------------------
# Carga de plantillas QPT
# ---------------------------------------------------------------------------

def cargar_o_importar_layout(project, layout_nombre: str, plantillas_dir: str, log):
    """
    Busca el layout en el proyecto QGIS; si no existe, lo importa desde
    el archivo QPT ubicado en 'plantillas_dir'.
    """
    layout = project.layoutManager().layoutByName(layout_nombre)
    if layout:
        return layout

    candidatos = [
        os.path.join(plantillas_dir, f"{layout_nombre}.qpt"),
        os.path.join(os.getcwd(),    f"{layout_nombre}.qpt"),
    ]
    qpt_path = next((p for p in candidatos if os.path.exists(p)), None)

    if not qpt_path:
        log.error(
            f" ✗ '{layout_nombre}.qpt' no encontrado. "
            f"Buscado en: {candidatos}"
        )
        return None

    log.info(f" → Importando plantilla desde: {qpt_path}")
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
        log.info(f" → extent_en_escala: {ancho:,.0f} × {alto:,.0f} u.")


# ---------------------------------------------------------------------------
# Actualizar elementos del layout
# ---------------------------------------------------------------------------

def actualizar_leyenda(layout_comp, ids: dict, capa_tematica, capa_poligono) -> None:
    leyenda = layout_comp.itemById(ids["leyenda"])
    if not (leyenda and isinstance(leyenda, QgsLayoutItemLegend)):
        return
    leyenda.setAutoUpdateModel(False)
    root = leyenda.model().rootGroup()
    root.removeAllChildren()
    root.addLayer(capa_tematica)
    if capa_poligono:
        root.addLayer(capa_poligono)
    leyenda.adjustBoxSize()
    leyenda.refresh()


def reenlazar_barra_escala(layout_comp, map_item, log) -> None:
    n = 0
    for item in layout_comp.items():
        if isinstance(item, QgsLayoutItemScaleBar):
            item.setLinkedMap(map_item)
            item.setUnits(QgsUnitTypes.DistanceMeters)
            item.setUnitLabel("m")
            item.refreshItemSize()
            item.refresh()
            n += 1
    if n:
        log.info(f" ✓ Barra(s) de escala re-enlazada(s): {n}")
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
    log.info(f" ✓ Grid: {intervalo_m:,.0f} m")


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
        log.info(f" ✓ Logo: {os.path.basename(logo_ruta)}")
    else:
        log.warning(f" → Ítem de logo '{id_logo}' no encontrado o no es imagen.")


def set_label_text(layout_comp, item_id: str, texto: str, log=None) -> None:
    if not item_id:
        return
    item = layout_comp.itemById(item_id)
    if item:
        item.setText(texto)
    elif log:
        log.debug(f" → Ítem '{item_id}' no encontrado.")
