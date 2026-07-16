"""
core/capas.py — Carga y procesamiento de capas vectoriales PostGIS.
"""

from qgis.core import (
    QgsDataSourceUri,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .utils import valida_id


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
        log.info(
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
    log.info(f" ✓ {len(features)} vértices extraídos del polígono.")
    return capa_vertices
