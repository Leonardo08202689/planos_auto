"""
core/mapitas.py — Insertos de localización automáticos.

Genera tres niveles cartográficos según dónde caiga el polígono:
  - Nacional  : México + estado resaltado
  - Estatal   : Municipios del estado + municipio resaltado
  - Municipal : Municipio zoom + punto del proyecto
"""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsFeature,
    QgsGeometry,
    QgsLayoutItemMap,
    QgsMarkerSymbol,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)

CRS_REF = "EPSG:4326"


# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------

def _s_fondo():
    return QgsFillSymbol.createSimple({
        "color": "242,242,240,255",        # Gris claro limpio y opaco
        "outline_color": "180,180,180,255", # Gris medio
        "outline_width": "0.2",
    })

def _s_highlight():
    return QgsFillSymbol.createSimple({
        "color": "198,224,180,255",        # Verde pastel limpio y opaco
        "outline_color": "84,130,53,255",   # Verde oscuro para destacar contorno
        "outline_width": "0.6",
    })

def _s_punto():
    return QgsMarkerSymbol.createSimple({
        "name": "star", "color": "220,0,0,255",
        "outline_color": "255,255,255,255", "size": "4.5",
    })


# ---------------------------------------------------------------------------
# PostGIS helpers
# ---------------------------------------------------------------------------

def _capa_pg(nombre, tabla, schema, pg, filtro, log):
    from qgis.core import QgsDataSourceUri
    uri = QgsDataSourceUri()
    uri.setConnection(pg["host"], str(pg["port"]), pg["dbname"], pg["user"], pg["password"])
    # Para cartografía base de mapitas, usamos geom y ogc_fid por defecto
    uri.setDataSource(schema, tabla, "geom", filtro, "ogc_fid")
    
    c = QgsVectorLayer(uri.uri(), nombre, "postgres")
    if not c.isValid():
        log.warning(f" → No se pudo cargar '{nombre}' ({schema}.{tabla})")
        return None
    return c


def _extent_margen(capa, factor: float) -> QgsRectangle:
    from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem, QgsProject
    e = capa.extent()
    crs_dest = QgsCoordinateReferenceSystem(CRS_REF)
    if capa.crs() != crs_dest:
        tr = QgsCoordinateTransform(capa.crs(), crs_dest, QgsProject.instance())
        e = tr.transformBoundingBox(e)
    
    dx = e.width()  * factor
    dy = e.height() * factor
    return QgsRectangle(e.xMinimum()-dx, e.yMinimum()-dy,
                        e.xMaximum()+dx, e.yMaximum()+dy)


# ---------------------------------------------------------------------------
# Detección de estado y municipio por intersección espacial
# ---------------------------------------------------------------------------

def detectar_ubicacion(centroid_geom, crs_proyecto, pg: dict,
                        schema: str, project, log) -> dict:
    """Retorna {cve_ent, nomgeo_estado, cvegeo_mun, nomgeo_municipio}."""
    crs_4326 = QgsCoordinateReferenceSystem(CRS_REF)
    pt_4326  = QgsCoordinateTransform(crs_proyecto, crs_4326, project)\
                   .transform(centroid_geom.asPoint())
    wkt = f"POINT({pt_4326.x()} {pt_4326.y()})"
    res = {"cve_ent": "", "nomgeo_estado": "", "cvegeo_mun": "", "nomgeo_municipio": ""}

    for tabla, key_id, key_nom, out_id, out_nom in [
        ("mexico_estados",    "cve_ent", "nomgeo", "cve_ent",   "nomgeo_estado"),
        ("mexico_municipios", "cvegeo",  "nomgeo", "cvegeo_mun","nomgeo_municipio"),
    ]:
        c = _capa_pg(f"_dt_{tabla}", tabla, schema, pg,
                     f"ST_Contains(geom, ST_Transform(ST_GeomFromText('{wkt}', 4326), ST_SRID(geom)))", log)
        if c and c.featureCount() > 0:
            f = next(c.getFeatures())
            res[out_id]  = str(f[key_id])
            res[out_nom] = str(f[key_nom])
            log.info(f" ✓ {out_nom.replace('_',' ').title()}: {res[out_nom]}")
        else:
            log.warning(f" → No detectado: {tabla}")

    return res


# ---------------------------------------------------------------------------
# Preparar capas (ejecutar UNA VEZ antes del loop principal)
# ---------------------------------------------------------------------------

def preparar_capas_referencia(centroid_geom, crs_proyecto, pg: dict,
                               cfg_mapitas: dict, project, log) -> dict:
    """
    Carga y registra en el proyecto todas las capas de referencia.
    Devuelve un dict con capas y extents listos para asignar a los mapitas.
    """
    # Retirar capas de referencia de corridas anteriores (no viven en ningún grupo)
    for nombre in ("ref_estados", "ref_estado_hl", "ref_munis", "ref_muni_hl", "ref_punto"):
        for capa_previa in project.mapLayersByName(nombre):
            project.removeMapLayer(capa_previa.id())

    schema = cfg_mapitas.get("schema", "cartografia_base")
    ub     = detectar_ubicacion(centroid_geom, crs_proyecto, pg, schema, project, log)

    cve_ent    = ub["cve_ent"]
    cvegeo_mun = ub["cvegeo_mun"]

    if not cve_ent:
        log.warning(" → Ubicación no detectada; mapitas omitidos.")
        return {}

    def _reg(c, estilo):
        if c:
            c.setRenderer(QgsSingleSymbolRenderer(estilo))
            project.addMapLayer(c, False)
        return c

    # Capas
    c_estados   = _reg(_capa_pg("ref_estados",   "mexico_estados",    schema, pg, "",                        log), _s_fondo())
    c_estado_hl = _reg(_capa_pg("ref_estado_hl", "mexico_estados",    schema, pg, f"cve_ent='{cve_ent}'",   log), _s_highlight())
    c_munis     = _reg(_capa_pg("ref_munis",      "mexico_municipios", schema, pg, f"cve_ent='{cve_ent}'",  log), _s_fondo())
    c_muni_hl   = _reg(_capa_pg("ref_muni_hl",   "mexico_municipios", schema, pg, f"cvegeo='{cvegeo_mun}'", log), _s_highlight()) \
                  if cvegeo_mun else None

    # Punto del proyecto (estrella roja) en EPSG:4326
    crs_4326 = QgsCoordinateReferenceSystem(CRS_REF)
    pt_4326  = QgsCoordinateTransform(crs_proyecto, crs_4326, project)\
                   .transform(centroid_geom.asPoint())
    c_punto = QgsVectorLayer(f"Point?crs={CRS_REF}", "ref_punto", "memory")
    feat    = QgsFeature()
    feat.setGeometry(QgsGeometry.fromPointXY(pt_4326))
    c_punto.dataProvider().addFeatures([feat])
    c_punto.setRenderer(QgsSingleSymbolRenderer(_s_punto()))
    project.addMapLayer(c_punto, False)

    # Extents
    ext_nac  = _extent_margen(c_estados,   0.05) if c_estados   else None
    ext_est  = _extent_margen(c_munis,     0.12) if c_munis     else None
    ext_mun  = _extent_margen(c_muni_hl,   0.30) if c_muni_hl  else None

    return {
        "capas_nacional":    [c for c in [c_estado_hl, c_estados]            if c],
        "capas_estatal":     [c for c in [c_punto,     c_muni_hl,   c_munis] if c],
        "capas_municipal":   [c for c in [c_punto,     c_muni_hl]            if c],
        "ext_nacional":      ext_nac,
        "ext_estatal":       ext_est,
        "ext_municipal":     ext_mun,
        "nomgeo_estado":     ub["nomgeo_estado"],
        "nomgeo_municipio":  ub["nomgeo_municipio"],
    }


# ---------------------------------------------------------------------------
# Asignar mapitas a una composición
# ---------------------------------------------------------------------------

def configurar_mapitas(layout_comp, id_principal: str,
                        cfg_mapitas: dict, capas_ref: dict, log) -> None:
    """
    Asigna capas y extents a los mapitas de referencia de 'layout_comp'.
    Llama preparar_capas_referencia() una vez antes del loop y pasa el resultado.
    """
    if not capas_ref or not cfg_mapitas:
        return

    layout_map = cfg_mapitas.get("mapitas_layout", {})
    crs_ref    = QgsCoordinateReferenceSystem(CRS_REF)

    for item in layout_comp.items():
        if not isinstance(item, QgsLayoutItemMap):
            continue
        if item.id() == id_principal:
            continue

        nivel = layout_map.get(item.id(), {}).get("nivel", "")
        capas = capas_ref.get(f"capas_{nivel}", [])
        ext   = capas_ref.get(f"ext_{nivel}")

        if not capas or ext is None:
            log.debug(f" → Mapita '{item.id()}': nivel '{nivel}' sin datos.")
            continue

        frame_size = item.sizeWithUnits()
        frame_pos  = item.positionWithUnits()

        item.setCrs(crs_ref)
        item.setExtent(ext)
        item.setLayers(capas)
        item.attemptResize(frame_size)
        item.attemptMove(frame_pos)
        item.setKeepLayerSet(True)
        item.setKeepLayerStyles(True)
        item.invalidateCache()
        item.refresh()
        nom = capas_ref.get("nomgeo_municipio" if nivel != "nacional"
                             else "nomgeo_estado", "")
        log.info(f" ✓ Mapita '{item.id()}' ({nivel}): {nom}")
