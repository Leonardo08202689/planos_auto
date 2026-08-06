"""
core/capas.py — Carga y procesamiento de capas vectoriales PostGIS y de
                 archivo (GeoPackage/OGR).
"""

from qgis.core import (
    QgsCoordinateTransform,
    QgsDataSourceUri,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsField,
    QgsProcessingContext,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .utils import valida_id


def resolver_capa_poligono(project: QgsProject, nombre: str, log=None):
    """
    Busca la capa de polígono de trabajo por nombre. Si hay más de una capa
    con ese nombre en el proyecto (p. ej. una capa auxiliar del propio plugin
    que por error comparta el nombre) se queda con la que sea de geometría
    de polígono, en vez de tomar ciegamente la primera coincidencia.
    """
    candidatas = project.mapLayersByName(nombre)
    if not candidatas:
        return None
    poligonos = [
        c for c in candidatas
        if hasattr(c, "geometryType") and c.geometryType() == QgsWkbTypes.PolygonGeometry
    ]
    if poligonos:
        if len(poligonos) > 1 and log:
            log.warning(
                f" → Hay {len(poligonos)} capas de polígono llamadas "
                f"'{nombre}'; se usará la primera."
            )
        return poligonos[0]
    if log:
        log.warning(
            f" → Ninguna de las capas llamadas '{nombre}' es de polígono; "
            f"se usará la primera de todos modos."
        )
    return candidatas[0]


def cargar_capa_postgis(cfg_capa: dict, pg: dict, bbox_wkt: str, log):
    """
    Carga una capa vectorial desde PostGIS, filtrando opcionalmente
    por intersección con el bbox del proyecto.

    Retorna QgsVectorLayer o None si falla.
    """
    key = cfg_capa.get("key", "gid")
    valida_id(cfg_capa["geom_col"],      "geom_col")
    valida_id(cfg_capa["tabla_postgis"], "tabla_postgis")
    valida_id(pg["schema"],              "schema")
    valida_id(key,                       "key")

    if cfg_capa.get("sin_bbox_filter", False):
        filtro_sql = ""
        log.debug(
            f"   → Cargando '{cfg_capa['tabla_postgis']}' "
            f"SIN filtro bbox (cobertura amplia)."
        )
    else:
        # Buffer de 5.5 km sobre geography: metros reales en cualquier zona UTM
        filtro_sql = (
            f"ST_Intersects({cfg_capa['geom_col']}, "
            f"ST_Transform("
            f"ST_Buffer("
            f"ST_GeomFromText('{bbox_wkt}', 4326)::geography, "
            f"5500"
            f")::geometry, "
            f"ST_SRID({cfg_capa['geom_col']})))"
        )

    uri = QgsDataSourceUri()
    # sslmode va como argumento de setConnection: setSslMode() no existe
    # en los bindings de QGIS 3.28
    uri.setConnection(pg["host"], str(pg["port"]), pg["dbname"],
                      pg["user"], pg["password"], QgsDataSourceUri.SslDisable)
    uri.setDataSource(pg["schema"], cfg_capa["tabla_postgis"],
                      cfg_capa["geom_col"], filtro_sql, key)
    wkb = QgsWkbTypes.parseType(cfg_capa["tipo_geom"])
    if wkb != QgsWkbTypes.Unknown:
        uri.setWkbType(wkb)

    capa = QgsVectorLayer(uri.uri(), cfg_capa["nombre_capa"] + "_raw", "postgres")
    if not capa.isValid():
        log.error(f" ✗ Capa PostGIS inválida: {cfg_capa['tabla_postgis']}")
        return None
    return capa


def cargar_capa_extra(spec: dict, extra_cfg: dict, pg: dict, crs_destino,
                      extent_en_escala, bbox_wkt: str, log):
    """
    Carga una entrada de 'capas_extra' (referencia sobre un plano: caminos,
    ríos, etc.), recortada y reproyectada al extent dado.

    Soporta dos orígenes por entrada de 'spec':
    - 'tabla_postgis': tabla en el esquema 'cartografia_base' (o el que
      indique 'schema'), vía cargar_capa_postgis + recortar_y_reproyectar
      (mismo camino que usan las figuras que combinan varias tablas).
    - 'capa': nombre de capa dentro del GeoPackage de 'extra_cfg["ruta_gpkg"]'
      (comportamiento original, para fuentes que sigan siendo archivo).
    """
    tabla = spec.get("tabla_postgis")
    if tabla:
        cfg_tabla = {
            "tabla_postgis":   tabla,
            "geom_col":        spec.get("geom_col", "geom"),
            "tipo_geom":       "MultiPolygon" if spec.get("tipo_geom") == "area" else "MultiLineString",
            "key":             spec.get("key", "gid"),
            "nombre_capa":     spec.get("nombre", tabla),
            "sin_bbox_filter": spec.get("sin_bbox_filter", False),
        }
        pg_extra = dict(pg, schema=spec.get("schema", "cartografia_base"))
        capa_pg = cargar_capa_postgis(cfg_tabla, pg_extra, bbox_wkt, log)
        if not capa_pg:
            return None
        return recortar_y_reproyectar(
            capa_pg, crs_destino, extent_en_escala, log, nombre_log=tabla
        )

    nombre_layer = spec.get("capa")
    if not nombre_layer:
        log.warning(" → Entrada de capas_extra sin 'capa' ni 'tabla_postgis'; se omite.")
        return None
    return cargar_recortar_gpkg(
        extra_cfg["ruta_gpkg"], nombre_layer, crs_destino, extent_en_escala, log
    )


def cargar_raster_postgis(tabla: str, pg: dict, log, columna: str = "rast"):
    """
    Carga una tabla ráster de PostGIS (subida con raster2pgsql, ej. el ráster
    de Localización) como QgsRasterLayer vía el proveedor 'postgresraster'.

    Retorna QgsRasterLayer o None si falla.
    """
    valida_id(tabla,          "tabla")
    valida_id(pg["schema"],   "schema")
    valida_id(columna,        "columna")

    uri = QgsDataSourceUri()
    uri.setConnection(pg["host"], str(pg["port"]), pg["dbname"],
                      pg["user"], pg["password"], QgsDataSourceUri.SslDisable)
    uri.setDataSource(pg["schema"], tabla, columna)

    capa = QgsRasterLayer(uri.uri(False), tabla, "postgresraster")
    if not capa.isValid():
        log.warning(f" → Ráster PostGIS inválido: {pg['schema']}.{tabla}")
        return None
    return capa


def extraer_vertices_poligono(feature_poligono, crs, log):
    """
    Extrae los vértices exteriores del polígono seleccionado (todas sus
    partes, numeración continua) como una capa de puntos en memoria.
    Lanza ValueError si la geometría está vacía.
    """
    geom = feature_poligono.geometry()
    if geom is None or geom.isEmpty():
        raise ValueError("El polígono seleccionado tiene geometría vacía.")

    partes = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
    if len(partes) > 1:
        log.warning(
            f" ⚠ El polígono tiene {len(partes)} partes; "
            f"se numeran los vértices de todas de forma continua."
        )

    capa_vertices = QgsVectorLayer(
        f"Point?crs={crs.authid()}", "Vertices_Proyecto", "memory"
    )
    dp = capa_vertices.dataProvider()
    dp.addAttributes([QgsField("num_vertice", QVariant.Int)])
    capa_vertices.updateFields()

    features = []
    num = 0
    for parte in partes:
        if not parte:
            continue
        anillo = parte[0]
        # Eliminar punto de cierre duplicado
        if len(anillo) > 1 and anillo[0] == anillo[-1]:
            anillo = anillo[:-1]
        for punto in anillo:
            num += 1
            feat = QgsFeature(capa_vertices.fields())
            feat.setGeometry(QgsGeometry.fromPointXY(punto))
            feat.setAttribute("num_vertice", num)
            features.append(feat)

    if not features:
        raise ValueError("No se pudieron extraer vértices del polígono.")

    dp.addFeatures(features)
    capa_vertices.updateExtents()
    log.debug(f" ✓ {len(features)} vértices extraídos del polígono.")
    return capa_vertices


def recortar_y_reproyectar(capa, crs_destino, extent_en_escala, log,
                           margen: float = 0.02, nombre_log: str = "capa"):
    """
    Sanea, pre-filtra por bbox (índice espacial de origen), reproyecta y
    recorta 'capa' (ya cargada, de cualquier proveedor) al extent dado.

    Compartida por cargar_recortar_gpkg/cargar_recortar_shapefile y por las
    capas PostGIS de figuras combinadas (varias tablas en una composición).

    Retorna QgsVectorLayer recortado, o None si no hay features en el área
    de interés.
    """
    import processing

    crs_capa = capa.crs()
    if crs_capa.authid() != crs_destino.authid():
        transf = QgsCoordinateTransform(crs_destino, crs_capa, QgsProject.instance())
        rect_fuente = transf.transformBoundingBox(extent_en_escala)
    else:
        rect_fuente = extent_en_escala
    rect_fuente = rect_fuente.buffered(
        max(rect_fuente.width(), rect_fuente.height()) * margen
    )
    extent_str = (
        f"{rect_fuente.xMinimum()},{rect_fuente.xMaximum()},"
        f"{rect_fuente.yMinimum()},{rect_fuente.yMaximum()} [{crs_capa.authid()}]"
    )
    # Geometrías inválidas en la fuente (p. ej. shapefiles de terceros) no deben
    # abortar el pre-filtro; se omiten aquí y 'native:fixgeometries' corrige el resto.
    context = QgsProcessingContext()
    context.setInvalidGeometryCheck(QgsFeatureRequest.GeometrySkipInvalid)
    res_pre = processing.run("native:extractbyextent", {
        "INPUT": capa, "EXTENT": extent_str, "CLIP": False, "OUTPUT": "memory:",
    }, context=context)
    candidatos = res_pre["OUTPUT"]
    if candidatos.featureCount() == 0:
        log.debug(f" → '{nombre_log}': sin features en el área de interés.")
        return None

    res_fix = processing.run("native:fixgeometries", {
        "INPUT": candidatos, "OUTPUT": "memory:",
    })
    res_reproj = processing.run("native:reprojectlayer", {
        "INPUT": res_fix["OUTPUT"], "TARGET_CRS": crs_destino, "OUTPUT": "memory:",
    })

    layer_extent = QgsVectorLayer(f"Polygon?crs={crs_destino.authid()}", "extent_tmp", "memory")
    f_ext = QgsFeature()
    f_ext.setGeometry(QgsGeometry.fromRect(extent_en_escala))
    layer_extent.dataProvider().addFeatures([f_ext])

    res_clip = processing.run("native:clip", {
        "INPUT": res_reproj["OUTPUT"], "OVERLAY": layer_extent, "OUTPUT": "memory:",
    })
    capa_recortada = res_clip["OUTPUT"]
    log.debug(f" → '{nombre_log}': {capa_recortada.featureCount()} feature(s) recortado(s).")
    return capa_recortada


def cargar_recortar_gpkg(ruta_gpkg: str, nombre_layer: str, crs_destino,
                        extent_en_escala, log, margen: float = 0.02):
    """
    Carga una capa de un GeoPackage por nombre, la recorta y reproyecta al
    extent dado. Ver recortar_y_reproyectar() para el detalle del pre-filtro.

    Pensada para fuentes de referencia grandes (p. ej. cartografía topográfica
    de INEGI que cubre todo un estado), donde cargar el archivo completo sería
    impráctico.

    Retorna QgsVectorLayer recortado, o None si la capa no existe/es inválida
    o no tiene features en el área de interés.
    """
    capa = QgsVectorLayer(f"{ruta_gpkg}|layername={nombre_layer}", nombre_layer, "ogr")
    if not capa.isValid():
        log.warning(f" → Capa '{nombre_layer}' no válida en {ruta_gpkg}, se omite.")
        return None
    capa_recortada = recortar_y_reproyectar(
        capa, crs_destino, extent_en_escala, log, margen, nombre_log=nombre_layer
    )
    if capa_recortada:
        capa_recortada.setName(nombre_layer)
    return capa_recortada


def cargar_recortar_shapefile(ruta_shp: str, crs_destino, extent_en_escala, log,
                              margen: float = 0.02):
    """
    Carga un shapefile (u otra fuente OGR de una sola capa, sin 'layername'),
    lo recorta y reproyecta al extent dado. Ver cargar_recortar_gpkg() para
    fuentes tipo GeoPackage con varias capas nombradas.
    """
    import os as _os
    nombre = _os.path.splitext(_os.path.basename(ruta_shp))[0]
    capa = QgsVectorLayer(ruta_shp, nombre, "ogr")
    if not capa.isValid():
        log.warning(f" → Capa no válida: {ruta_shp}, se omite.")
        return None
    capa_recortada = recortar_y_reproyectar(
        capa, crs_destino, extent_en_escala, log, margen, nombre_log=nombre
    )
    if capa_recortada:
        capa_recortada.setName(nombre)
    return capa_recortada
