"""
core/capas.py — Carga y procesamiento de capas vectoriales PostGIS.
"""

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from .utils import valida_id


def cargar_capa_postgis(cfg_capa: dict, pg: dict, bbox_wkt: str, log):
    """
    Carga una capa vectorial desde PostGIS, filtrando opcionalmente
    por intersección con el bbox del proyecto.

    Retorna QgsVectorLayer o None si falla.
    """
    valida_id(cfg_capa["geom_col"],      "geom_col")
    valida_id(cfg_capa["tabla_postgis"], "tabla_postgis")
    valida_id(pg["schema"],              "schema")

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

    uri = (
        f"dbname='{pg['dbname']}' host={pg['host']} port={pg['port']} "
        f"user='{pg['user']}' password='{pg['password']}' sslmode=disable "
        f"key='{cfg_capa.get('key', 'gid')}' "
        f"type={cfg_capa['tipo_geom']} "
        f"table=\"{pg['schema']}\".\"{cfg_capa['tabla_postgis']}\" "
        f"({cfg_capa['geom_col']})"
    )
    if filtro_sql:
        uri += f" sql={filtro_sql}"

    capa = QgsVectorLayer(uri, cfg_capa["nombre_capa"] + "_raw", "postgres")
    if not capa.isValid():
        log.error(f" ✗ Capa PostGIS inválida: {cfg_capa['tabla_postgis']}")
        return None
    return capa


def extraer_vertices_poligono(feature_poligono, crs, log):
    """
    Extrae los vértices del exterior del polígono seleccionado
    y los devuelve como una capa de puntos en memoria.
    """
    geom = feature_poligono.geometry()
    poligono = geom.asMultiPolygon()[0] if geom.isMultipart() else geom.asPolygon()

    anillo = poligono[0]
    # Eliminar punto de cierre duplicado
    if len(anillo) > 1 and anillo[0] == anillo[-1]:
        anillo = anillo[:-1]

    capa_vertices = QgsVectorLayer(
        f"Point?crs={crs.authid()}", "Vertices_Proyecto", "memory"
    )
    dp = capa_vertices.dataProvider()
    dp.addAttributes([QgsField("num_vertice", QVariant.Int)])
    capa_vertices.updateFields()

    features = []
    for i, punto in enumerate(anillo, start=1):
        feat = QgsFeature(capa_vertices.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(punto))
        feat.setAttribute("num_vertice", i)
        features.append(feat)

    dp.addFeatures(features)
    capa_vertices.updateExtents()
    log.info(f" ✓ {len(features)} vértices extraídos del polígono.")
    return capa_vertices
