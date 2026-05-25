# =============================================================================
#  GENERADOR AUTOMÁTICO DE PLANOS — LICENCIA AMBIENTAL INTEGRAL
#  Empresa: SINERGIA Consultores en Ingeniería Ambiental
#
#  Uso: Consola Python de QGIS → pega y ejecuta.
#       Antes de correr: selecciona el polígono en "poligono_trabajo".
#
#  Capas generadas:
#    1. Plano. Tipos de Suelos        → 1:5 000
#    2. Plano. Tipos de Roca          → 1:5 000
#    3. Plano. Tipos de Clima         → 1:5 000
#    4. Plano. Tipo de Vegetación     → 1:5 000
#    5. Plano. Hidrología Superficial → 1:35 000
# =============================================================================

import os
import re
import unicodedata
import logging
from datetime import datetime

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsLayoutExporter,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsRectangle,
)
import processing


# =============================================================================
#  SECCIÓN 0 — UTILIDADES
# =============================================================================

def leer_env(ruta: str) -> dict:
    """Lee un archivo .env simple (KEY=VALUE). Ignora comentarios y vacías."""
    env = {}
    if not os.path.exists(ruta):
        return env
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                env[clave.strip()] = valor.strip().strip("\"'")
    return env


def sanitizar_nombre(texto: str) -> str:
    """Elimina acentos y caracteres especiales para nombres de archivo."""
    nfkd = unicodedata.normalize("NFKD", texto)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("ASCII")
    limpio = re.sub(r"[^\w\-]", "_", ascii_text)
    return re.sub(r"_+", "_", limpio).strip("_")


def cargar_o_importar_layout(project, layout_nombre, log):
    """Carga el layout si ya existe, o lo importa desde un archivo .qpt."""
    layout = project.layoutManager().layoutByName(layout_nombre)
    if layout:
        return layout

    script_dir = "/home/leonardo/Codigos/Planos_auto"
    qpt_path = os.path.join(script_dir, f"{layout_nombre}.qpt")

    if not os.path.exists(qpt_path):
        qpt_path = os.path.join(os.getcwd(), f"{layout_nombre}.qpt")

    if os.path.exists(qpt_path):
        log.info(f"  → Importando layout '{layout_nombre}' desde '{qpt_path}'...")
        try:
            from qgis.core import QgsPrintLayout, QgsReadWriteContext
            from qgis.PyQt.QtXml import QDomDocument

            nuevo_layout = QgsPrintLayout(project)
            with open(qpt_path, "r", encoding="utf-8") as f:
                contenido = f.read()

            doc = QDomDocument()
            if not doc.setContent(contenido):
                log.error(f"  ✗ Error al parsear el XML de '{qpt_path}'")
                return None

            context = QgsReadWriteContext()
            if not nuevo_layout.loadFromTemplate(doc, context):
                log.error(f"  ✗ Falló al cargar la plantilla desde '{qpt_path}'")
                return None

            nuevo_layout.setName(layout_nombre)
            project.layoutManager().addLayout(nuevo_layout)
            log.info(f"  ✓ Layout '{layout_nombre}' importado con éxito.")
            return nuevo_layout
        except Exception as e:
            log.error(f"  ✗ Error al importar plantilla QPT: {e}")
            return None
    else:
        log.error(f"  ✗ Layout '{layout_nombre}' no encontrado.")
        return None


# ── Leer credenciales de .env ────────────────────────────────────────────────
_ENV_PATHS = [
    os.path.join(os.path.expanduser("~"), "Codigos", "Planos_auto", ".env"),
    os.path.join(os.path.expanduser("~"), ".env_planos"),
]
_ENV = {}
for _p in _ENV_PATHS:
    _ENV = leer_env(_p)
    if _ENV:
        break


# =============================================================================
#  SECCIÓN 1 — CONFIGURACIÓN
# =============================================================================

CONFIG = {
    "nombre_proyecto":  "SONITRONIES S DE RL DE CV DEPARTAMENTO CONCISE",
    "tipo_tramite":     "Licencia Ambiental Integral",
    "mes_año":          "Mayo 2026",
    "coordenadas":      "COORDENADAS UTM WGS84, R12",
    "output_base":      "/home/leonardo/planos_salida/",

    "pg": {
        "host":     _ENV.get("PG_HOST",     "localhost"),
        "port":     _ENV.get("PG_PORT",     "5432"),
        "dbname":   _ENV.get("PG_DBNAME",   "gis_empresa"),
        "schema":   _ENV.get("PG_SCHEMA",   "proyectos"),
        "user":     _ENV.get("PG_USER",     "postgres"),
        "password": _ENV.get("PG_PASSWORD", ""),
    },

    "capa_poligono":    "poligono_trabajo",
    "layout_nombre":    "Plantilla_Corporativa",

    "ids": {
        "mapa":          "mapa_principal",
        "leyenda":       "leyenda_principal",
        "lbl_proyecto":  "lbl_proyecto",
        "lbl_licencia":  "lbl_licencia",
        "lbl_plano":     "lbl_tipo_plano",
        "lbl_escala":    "lbl_escala",
        "lbl_fecha":     "lbl_fecha",
        "lbl_fuente":    "lbl_fuente",
        "lbl_coordsys":  "lbl_coordsys",
    },

    "dpi": 200,

    "capas": [
        {
            "tabla_postgis": "Suelos_edafologia",
            "nombre_plano":  "Plano. Tipos de Suelos",
            "nombre_capa":   "Tipo de Suelo",
            "escala":        5000,
            "geom_col":      "geom",
            "tipo_geom":     "MultiPolygon",
            "key":           "gid",
            "fuente": "Conjunto de Datos Vectorial Edafológico, Escala 1:250 000 Serie II Continuo Nacional H12-8 Hermosillo",
        },
        {
            "tabla_postgis": "Geologia",
            "nombre_plano":  "Plano. Tipos de Roca",
            "nombre_capa":   "Tipos de Roca",
            "escala":        5000,
            "geom_col":      "geom",
            "tipo_geom":     "MultiPolygon",
            "key":           "gid",
            "fuente": "Conjunto de datos vectoriales Geológicos serie I. Hermosillo 1:250 000",
        },
        {
            "tabla_postgis": "Clima",
            "nombre_plano":  "Plano. Tipos de Clima",
            "nombre_capa":   "Clima",
            "escala":        5000,
            "geom_col":      "geom",
            "tipo_geom":     "MultiPolygon",
            "key":           "gid",
            "fuente": "Conjunto de Datos Nacionales de Unidades Climáticas, Escala 1:1 000 000, INEGI.",
        },
        {
            "tabla_postgis": "Vegetacion",
            "nombre_plano":  "Plano. Tipo de Vegetación",
            "nombre_capa":   "Vegetación",
            "escala":        5000,
            "geom_col":      "geom",
            "tipo_geom":     "MultiPolygon",
            "key":           "gid",
            "fuente": "Conjunto de datos vectoriales de uso del suelo y vegetación escala 1:250 000 serie V Conjunto Nacional Hermosillo",
        },
        {
            "tabla_postgis": "hidrologia_superficial",
            "nombre_plano":  "Plano. Hidrología Superficial",
            "nombre_capa":   "Hidrología Superficial",
            "escala":        35000,
            "geom_col":      "geom",
            "tipo_geom":     "MultiPolygon",
            "key":           "gid",
            "fuente": "Conjunto de datos vectoriales de la carta de Aguas superficiales. Escala 1:250 000. Serie I. Hermosillo",
        },
    ],
}


# =============================================================================
#  SECCIÓN 2 — VALIDACIÓN Y LOGGER
# =============================================================================

def crear_logger(output_dir: str) -> logging.Logger:
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger = logging.getLogger("MIA_Planos")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")

    fh = logging.FileHandler(os.path.join(output_dir, f"log_{ts}.txt"), encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


# =============================================================================
#  SECCIÓN 3 — CONEXIÓN POSTGIS (FILTRADA POR BUFFER AMPLIO PARA LLENAR EL PLANO)
# =============================================================================

def uri_postgis(pg: dict, tabla: str, geom_col: str, tipo_geom: str, bbox_wkt: str, key: str = "gid") -> str:
    """
    Construye la URI de conexión. Aplica un buffer dinámico expandido en la base
    de datos para asegurar que traiga suficiente cartografía periférica y no salgan marcos blancos.
    """
    filtro_sql = (
        f"ST_Intersects({geom_col}, "
        f"ST_Transform(ST_Buffer(ST_GeomFromText('{bbox_wkt}', 4326), 0.05), ST_SRID({geom_col})))"
    )
    return (
        f"dbname='{pg['dbname']}' host={pg['host']} port={pg['port']} "
        f"user='{pg['user']}' password='{pg['password']}' sslmode=disable key='{key}' "  # ← FIX: key dinámica
        f"type={tipo_geom} table=\"{pg['schema']}\".\"{tabla}\" ({geom_col}) sql={filtro_sql}"
    )


def cargar_capa_postgis(cfg_capa: dict, pg: dict, bbox_wkt: str, log):
    uri = uri_postgis(
        pg,
        cfg_capa["tabla_postgis"],
        cfg_capa["geom_col"],
        cfg_capa["tipo_geom"],
        bbox_wkt,
        key=cfg_capa.get("key", "gid"),  # ← FIX: usa la key de cada capa, por defecto "gid"
    )
    capa = QgsVectorLayer(uri, cfg_capa["nombre_capa"], "postgres")

    if not capa.isValid():
        log.error(f"  ✗ Error al cargar tabla '{cfg_capa['tabla_postgis']}' desde PostGIS.")
        return None

    log.info(f"  ✓ Cargada '{cfg_capa['nombre_capa']}': {capa.featureCount()} features capturados en la zona")
    return capa


# =============================================================================
#  SECCIÓN 4 — CONFIGURAR LAYOUT Y EXPORTAR PDF (FÓRMULA AUTOMÁTICA CORREGIDA)
# =============================================================================

def actualizar_label(layout, item_id: str, texto: str) -> None:
    item = layout.itemById(item_id)
    if item:
        item.setText(texto)


def exportar_pdf(layout, cfg_capa: dict, cfg: dict, bbox_nativo: QgsRectangle,
                 capa_tematica: QgsVectorLayer, id_feature: int, output_dir: str, log) -> bool:
    ids = cfg["ids"]
    map_item = layout.itemById(ids["mapa"])
    if not map_item:
        log.error(f"  ✗ Elemento de mapa '{ids['mapa']}' no encontrado en el diseño.")
        return False

    was_locked = map_item.keepLayerSet()
    original_layers = map_item.layers()

    # Configuración de capas visibles en este plano
    project_layers = list(QgsProject.instance().mapLayers().values())
    capas_mapa = [capa_tematica] + [l for l in project_layers if l.id() != capa_tematica.id()]
    map_item.setKeepLayerSet(True)
    map_item.setLayers(capas_mapa)

    # [CORRECCIÓN CRÍTICA DE CÁMARA]: Delegar a QGIS el cálculo exacto del Extent y Escala
    map_item.setCrs(capa_tematica.crs())
    map_item.setExtent(bbox_nativo)
    map_item.setScale(cfg_capa["escala"])
    map_item.refresh()

    # Actualizar textos del cajetín
    actualizar_label(layout, ids["lbl_proyecto"], cfg["nombre_proyecto"])
    actualizar_label(layout, ids["lbl_licencia"], cfg["tipo_tramite"])
    actualizar_label(layout, ids["lbl_plano"],    cfg_capa["nombre_plano"])
    actualizar_label(layout, ids["lbl_escala"],   f"Escala 1:{cfg_capa['escala']:,}".replace(",", " "))
    actualizar_label(layout, ids["lbl_fecha"],    f"Fecha: {cfg['mes_año']}")
    actualizar_label(layout, ids.get("lbl_fuente", ""),   cfg_capa["fuente"])
    actualizar_label(layout, ids.get("lbl_coordsys", ""), cfg.get("coordenadas", ""))

    leyenda = layout.itemById(ids["leyenda"])
    if leyenda:
        leyenda.refresh()

    nombre_archivo = sanitizar_nombre(cfg_capa["nombre_plano"])
    fecha_str = datetime.now().strftime("%Y%m")
    ruta_pdf = os.path.join(output_dir, f"{nombre_archivo}_ID{id_feature}_{fecha_str}.pdf")

    exportador = QgsLayoutExporter(layout)
    config_pdf = QgsLayoutExporter.PdfExportSettings()
    config_pdf.dpi = cfg.get("dpi", 200)

    resultado = exportador.exportToPdf(ruta_pdf, config_pdf)

    map_item.setKeepLayerSet(was_locked)
    if was_locked:
        map_item.setLayers(original_layers)

    if resultado == QgsLayoutExporter.Success:
        log.info(f"  ✓ PDF Guardado → {os.path.basename(ruta_pdf)}")
        return True
    else:
        log.error(f"  ✗ Error al exportar PDF (Código {resultado})")
        return False


# =============================================================================
#  SECCIÓN 5 — PROCESO PRINCIPAL
# =============================================================================

def generar_planos_MIA(cfg: dict) -> None:
    nombre_carpeta = sanitizar_nombre(cfg["nombre_proyecto"])[:50]
    output_dir = os.path.join(cfg["output_base"], nombre_carpeta)
    os.makedirs(output_dir, exist_ok=True)

    log = crear_logger(output_dir)
    log.info("=" * 65)
    log.info(f"PROYECTO : {cfg['nombre_proyecto']}")
    log.info(f"TRÁMITE  : {cfg['tipo_tramite']}")
    log.info(f"SALIDA   : {output_dir}")
    log.info("=" * 65)

    project = QgsProject.instance()
    capas_poly = project.mapLayersByName(cfg["capa_poligono"])
    if not capas_poly:
        log.error(f"✗ Capa '{cfg['capa_poligono']}' no se encuentra cargada en QGIS.")
        return

    poly_layer = capas_poly[0]
    seleccionados = list(poly_layer.selectedFeatures())

    if not seleccionados:
        log.error("✗ Por favor, selecciona el polígono del proyecto en el mapa antes de correr el script.")
        return

    layout = cargar_o_importar_layout(project, cfg["layout_nombre"], log)
    if not layout:
        return

    crs_origen = poly_layer.crs()
    crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    transf_4326 = QgsCoordinateTransform(crs_origen, crs_wgs84, project)

    stats = {"ok": 0, "error": 0, "omitido": 0}

    for feature in seleccionados:
        log.info(f"\nProcesando Polígono ID: {feature.id()}")

        geom = feature.geometry()
        bbox_nativo = geom.boundingBox()
        bbox_4326 = transf_4326.transformBoundingBox(bbox_nativo)
        bbox_wkt = bbox_4326.asWktPolygon()

        capas_temporales = []

        try:
            for cfg_capa in cfg["capas"]:
                log.info(f"\n  [{cfg_capa['nombre_plano']}]  Escala 1:{cfg_capa['escala']:,}")

                # 5a. Descargar datos regionales desde la Base de Datos
                capa_pg = cargar_capa_postgis(cfg_capa, cfg["pg"], bbox_wkt, log)
                if capa_pg is None or capa_pg.featureCount() == 0:
                    log.warning(f"    → Capa regional sin datos en esta coordenada. Se genera plano de control vacío.")
                    if capa_pg is None:
                        stats["omitido"] += 1
                        continue

                # 5b. Reproyectar al vuelo para igualar las coordenadas del plano
                try:
                    res_reproj = processing.run("native:reprojectlayer", {
                        "INPUT": capa_pg,
                        "TARGET_CRS": crs_origen,
                        "OUTPUT": "memory:"
                    })
                    capa_visual = res_reproj["OUTPUT"]
                except Exception as e:
                    log.error(f"    ✗ Error en reproyección interna: {e}")
                    stats["error"] += 1
                    continue

                capa_visual.setName(f"{cfg_capa['nombre_capa']} [Visual]")

                # Aplicar simbología si existe en el proyecto local
                originales = project.mapLayersByName(cfg_capa["nombre_capa"])
                if originales:
                    capa_visual.setRenderer(originales[0].renderer().clone())

                project.addMapLayer(capa_visual, False)
                capas_temporales.append(capa_visual)

                # 5c. Exportar el plano con la información de fondo regional completa (sin clipping)
                exito = exportar_pdf(
                    layout, cfg_capa, cfg,
                    bbox_nativo, capa_visual,
                    feature.id(), output_dir, log,
                )

                if exito:
                    stats["ok"] += 1
                else:
                    stats["error"] += 1

                project.removeMapLayer(capa_visual.id())
                capas_temporales.remove(capa_visual)

        finally:
            for capa_tmp in capas_temporales:
                try:
                    project.removeMapLayer(capa_tmp.id())
                except Exception:
                    pass

    log.info(f"\n{'=' * 65}")
    log.info("✓ PROCESO COMPLETADO CON ÉXITO")
    log.info(f"  Planos generados: {stats['ok']}")
    log.info(f"  Errores de mapa : {stats['error']}")
    log.info(f"  Carpeta destino : {output_dir}")
    log.info(f"{'=' * 65}")


# =============================================================================
#  EJECUTAR SCRIPT
# =============================================================================
generar_planos_MIA(CONFIG)