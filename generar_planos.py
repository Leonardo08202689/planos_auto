# =============================================================================
# GENERADOR AUTOMÁTICO DE PLANOS — LICENCIA AMBIENTAL INTEGRAL
# Empresa: SINERGIA Consultores en Ingeniería Ambiental
#
# FIXES v8:
# - featureCount() == -1 ya no omite capas PostGIS.
# - Nuevo flag "sin_bbox_filter": True para capas de cobertura estatal/nacional.
# - cargar_capa_postgis() construye la URI sin cláusula sql= cuando aplica.
#
# FIXES v9 (ACTUAL):
# - Soporte de "ids_override" por capa en CONFIG → permite que Plantilla_figuras
#   use un ID de mapa diferente al de Plantilla_Corporativa sin tocar la lógica global.
# - Log de extent_en_escala y CRS del map_item para diagnóstico de planos vacíos.
# - Fix CRS clip: la máscara de recorte (layer_extent) se crea en el CRS de la
#   capa reproyectada, no en crs_origen, evitando clips silenciosos cuando difieren.
# - Validación de extent: si el extent es mayor que 5° (~555 km) en cualquier eje,
#   se emite WARNING indicando posible desconfiguración del map_item.
# - Campo 'nombre' corregido para POET (campo real: 'uga'), AICA ('nombre'),
#   RHP ('nombre'), RTP ('nombre') según log anterior.
# =============================================================================

import os
import re
import hashlib
import unicodedata
import logging
from datetime import datetime

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsLayoutExporter,
    QgsLayoutItemLegend,
    QgsLayoutItemScaleBar,
    QgsLayoutItemMapGrid,
    QgsLayoutItemPicture,
    QgsLayoutItemMap,
    QgsUnitTypes,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsFeature,
    QgsMarkerSymbol,
    QgsFillSymbol,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsSymbol,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
)

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor, QFont
import processing

# =============================================================================
# SECCIÓN 0 — UTILIDADES
# =============================================================================

_PALETA_CARTOGRAFICA = [
    "#e6b89c", "#9ed8db", "#b5d8b7", "#f5c48a", "#aec6e8",
    "#d4a5c9", "#f7e59a", "#b2d3a8", "#f4a261", "#84c5f4",
    "#cdb4db", "#caffbf", "#ffd6a5", "#a8dadc", "#f1c0e8",
    "#b9fbc0", "#ffcfd2", "#8ecae6", "#e9c46a", "#f4a0b5",
]


def _color_para_categoria(indice: int, valor: str) -> QColor:
    if indice < len(_PALETA_CARTOGRAFICA):
        return QColor(_PALETA_CARTOGRAFICA[indice])
    digest = int(hashlib.md5(str(valor).encode()).hexdigest(), 16)
    r = (digest >> 16) % 160 + 60
    g = (digest >>  8) % 160 + 60
    b = (digest      ) % 160 + 60
    return QColor(r, g, b)


def leer_env(ruta: str) -> dict:
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
    nfkd      = unicodedata.normalize("NFKD", texto)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("ASCII")
    limpio    = re.sub(r"[^\w\-]", "_", ascii_text)
    return re.sub(r"_+", "_", limpio).strip("_")


_ID_SEGURO = re.compile(r"^\w+$")

def _valida_id(nombre: str, ctx: str):
    if not _ID_SEGURO.match(nombre):
        raise ValueError(f"Identificador inseguro en {ctx}: '{nombre}'")


try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    script_dir = os.path.join(os.path.expanduser("~"), "Codigos", "Planos_auto")


def cargar_o_importar_layout(project, layout_nombre, log):
    layout = project.layoutManager().layoutByName(layout_nombre)
    if layout:
        return layout

    qpt_path = os.path.join(script_dir, f"{layout_nombre}.qpt")
    if not os.path.exists(qpt_path):
        qpt_path = os.path.join(os.getcwd(), f"{layout_nombre}.qpt")

    if os.path.exists(qpt_path):
        log.info(" → Cargando plantilla base desde archivo QPT...")
        try:
            from qgis.core import QgsPrintLayout, QgsReadWriteContext
            from qgis.PyQt.QtXml import QDomDocument
            nuevo_layout = QgsPrintLayout(project)
            with open(qpt_path, "r", encoding="utf-8") as f:
                contenido = f.read()
            doc = QDomDocument()
            if not doc.setContent(contenido):
                log.error(" ✗ No se pudo parsear el archivo QPT.")
                return None
            context = QgsReadWriteContext()
            if not nuevo_layout.loadFromTemplate(doc, context):
                log.error(" ✗ loadFromTemplate falló.")
                return None
            nuevo_layout.setName(layout_nombre)
            project.layoutManager().addLayout(nuevo_layout)
            return nuevo_layout
        except Exception as e:
            log.error(f" ✗ Error al importar QPT: {e}")
            return None
    return None


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
# SECCIÓN 1 — CONFIGURACIÓN
# =============================================================================

CONFIG = {
    "nombre_proyecto": "SONITRONIES S DE RL DE CV DEPARTAMENTO CONCISE",
    "tipo_tramite":    "Licencia Ambiental Integral",
    "mes_año":         datetime.now().strftime("%B %Y").capitalize(),
    "coordenadas":     "COORDENADAS UTM WGS84, R12",
    "output_base":     _ENV.get("OUTPUT_BASE", os.path.join(os.path.expanduser("~"), "planos_salida", "prueba")),
    "logo_ruta":       _ENV.get("LOGO_RUTA",   os.path.join(script_dir, "logo_sinergia.jpg")),

    "pg": {
        "host":     _ENV.get("PG_HOST",     "localhost"),
        "port":     _ENV.get("PG_PORT",     "5432"),
        "dbname":   _ENV.get("PG_DBNAME",   "gis_empresa"),
        "schema":   _ENV.get("PG_SCHEMA",   "proyectos"),
        "user":     _ENV.get("PG_USER",     "postgres"),
        "password": _ENV.get("PG_PASSWORD", ""),
    },

    "capa_poligono": "poligono_trabajo",
    "layout_nombre": "Plantilla_Corporativa",

    # IDs globales (Plantilla_Corporativa).
    # Para plantillas distintas usa "ids_override" por capa.
    "ids": {
        "mapa":         "mapa_principal",
        "leyenda":      "leyenda_principal",
        "lbl_proyecto": "lbl_proyecto",
        "lbl_licencia": "lbl_licencia",
        "lbl_plano":    "lbl_tipo_plano",
        "lbl_escala":   "lbl_escala",
        "lbl_fecha":    "lbl_fecha",
        "lbl_fuente":   "lbl_fuente",
        "lbl_coordsys": "lbl_coordsys",
        "logo":         "logo_empresa",
    },

    "dpi": 200,

    "capas": [
        # ── PLANOS CORPORATIVOS ───────────────────────────────────────────────
        {
            "tabla_postgis":   "suelos_edafologia_v3",
            "nombre_plano":    "Plano. Tipos de Suelos",
            "nombre_capa":     "Tipo_de_Suelo",
            "escala":          5000,
            "geom_col":        "geom",
            "tipo_geom":       "Polygon",
            "key":             "ogc_fid",
            "campo_categoria": "Grupo1",
            "campo_etiqueta":  "Grupo1",
            "opacidad":        0.6,
            "grid_intervalo":  300,
            "fuente":          "Conjunto de Datos Vectorial Edafológico. Escala 1:250 000 Serie III. INEGI.",
        },
        {
            "tabla_postgis":   "Geologia",
            "nombre_plano":    "Plano. Tipos de Roca",
            "nombre_capa":     "Tipos_de_Roca",
            "escala":          5000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "id",
            "campo_categoria": "tipo_roca",
            "campo_etiqueta":  "tipo_roca",
            "opacidad":        0.6,
            "grid_intervalo":  300,
            "fuente":          "Continúo Nacional de Geología de la República Mexicana escala 1:250,000.",
        },
        {
            "tabla_postgis":   "Clima",
            "nombre_plano":    "Plano. Tipos de Clima",
            "nombre_capa":     "Clima",
            "escala":          5000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "id",
            "campo_categoria": "etiqueta_clima",
            "campo_etiqueta":  "etiqueta_clima",
            "opacidad":        0.6,
            "grid_intervalo":  300,
            "fuente":          "Conjunto de Datos Nacionales de Unidades Climáticas, Escala 1:1 000 000, INEGI.",
        },
        {
            "tabla_postgis":   "Vegetacion",
            "nombre_plano":    "Plano. Tipo de Vegetación",
            "nombre_capa":     "Vegetacion",
            "escala":          5000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "gid",
            "campo_categoria": "descripcio",
            "campo_etiqueta":  "descripcio",
            "opacidad":        0.6,
            "grid_intervalo":  300,
            "fuente":          "Conjunto de datos vectoriales de uso del suelo y vegetación. Escala 1:250 000. Serie VII.",
        },
        {
            "tabla_postgis":   "hidrologia_superficial",
            "nombre_plano":    "Plano. Hidrología Superficial",
            "nombre_capa":     "Hidrologia_Superficial",
            "escala":          35000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "gid",
            "campo_categoria": "subcuenca",
            "campo_etiqueta":  "subcuenca",
            "opacidad":        0.55,
            "grid_intervalo":  2500,
            "marcador":        "punto",
            "fuente":          "Red hidrográfica, Subcuencas hidrográficas de México, Escala 1:50000.",
        },
        {
            "tipo":            "vertices",
            "nombre_plano":    "Plano. Plano de Vértices",
            "nombre_capa":     "Vertices_Proyecto",
            "escala":          2000,
            "opacidad":        1.0,
            "grid_intervalo":  100,
            "fuente":          "Vértices del polígono del proyecto.",
        },

        # ── FIGURAS (Plantilla_figuras) ───────────────────────────────────────
        # ids_override: sobreescribe los IDs globales para esta plantilla.
        # Si el ID de mapa en Plantilla_figuras.qpt es diferente a "mapa_principal",
        # cámbialo aquí. Abre el diseño en QGIS → clic en el mapa →
        # Propiedades del ítem → "ID del ítem".
        #
        # sin_bbox_filter: True → carga toda la tabla sin filtro ST_Intersects
        # (necesario para capas de cobertura estatal/nacional).
        #
        # Campos corregidos según log_20260602_113312:
        #   poet_sonora           → 'uga'    (no 'nombre')
        #   aica_nacional         → 'nombre' (no 'nom_aica')
        #   regiones_hidrologicas → 'nombre' (no 'nom_reg')
        #   regiones_terrestres   → 'nombre' (no 'nom_reg')
        {
            "tabla_postgis":   "poet_sonora",
            "nombre_plano":    "Figura. POET Sonora",
            "nombre_capa":     "POET",
            "escala":          50000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "gid",
            "campo_categoria": "uga",      # ← corregido (antes: 'nombre')
            "campo_etiqueta":  "uga",
            "opacidad":        0.6,
            "grid_intervalo":  2500,
            "layout_nombre":   "Plantilla_figuras",
            "sin_bbox_filter": True,
            # ↓ Ajusta "mapa_principal" al ID real del mapa en Plantilla_figuras.qpt
            "ids_override":    {"mapa": "mapa_principal"},
            "fuente":          "Programa de Ordenamiento Ecológico Territorial del Estado de Sonora.",
        },
        {
            "tabla_postgis":   "aica_nacional",
            "nombre_plano":    "Figura. Áreas de Importancia para la Conservación de Aves",
            "nombre_capa":     "AICA",
            "escala":          1000000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "gid",
            "campo_categoria": "nombre",   # ← corregido (antes: 'nom_aica')
            "campo_etiqueta":  "nombre",
            "opacidad":        0.6,
            "grid_intervalo":  50000,
            "layout_nombre":   "Plantilla_figuras",
            "ids_override":    {"mapa": "mapa_principal"},
            "fuente":          "Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO).",
        },
        {
            "tabla_postgis":   "anp_estatales",
            "nombre_plano":    "Figura. Áreas Naturales Protegidas Estatales",
            "nombre_capa":     "ANP_Estatales",
            "escala":          2000000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "gid",
            "campo_categoria": "nombre",
            "campo_etiqueta":  "nombre",
            "opacidad":        0.6,
            "grid_intervalo":  100000,
            "layout_nombre":   "Plantilla_figuras",
            "sin_bbox_filter": True,
            "ids_override":    {"mapa": "mapa_principal"},
            "fuente":          "Comisión de Ecología y Desarrollo Sustentable del Estado de Sonora (CEDES).",
        },
        {
            "tabla_postgis":   "regiones_hidrologicas_prioritarias",
            "nombre_plano":    "Figura. Regiones Hidrológicas Prioritarias",
            "nombre_capa":     "RHP",
            "escala":          10000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "gid",
            "campo_categoria": "nombre",   # ← corregido (antes: 'nom_reg')
            "campo_etiqueta":  "nombre",
            "opacidad":        0.6,
            "grid_intervalo":  300,
            "layout_nombre":   "Plantilla_figuras",
            "ids_override":    {"mapa": "mapa_principal"},
            "fuente":          "Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO).",
        },
        {
            "tabla_postgis":   "regiones_terrestres_prioritarias",
            "nombre_plano":    "Figura. Regiones Terrestres Prioritarias",
            "nombre_capa":     "RTP",
            "escala":          1000000,
            "geom_col":        "geom",
            "tipo_geom":       "MultiPolygon",
            "key":             "gid",
            "campo_categoria": "nombre",   # ← corregido (antes: 'nom_reg')
            "campo_etiqueta":  "nombre",
            "opacidad":        0.6,
            "grid_intervalo":  50000,
            "layout_nombre":   "Plantilla_figuras",
            "sin_bbox_filter": True,
            "ids_override":    {"mapa": "mapa_principal"},
            "fuente":          "Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO).",
        },
    ],
}

# =============================================================================
# SECCIÓN 2 — FUNCIONES DE CONTROL
# =============================================================================

def crear_logger(output_dir: str) -> logging.Logger:
    os.makedirs(output_dir, exist_ok=True)
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = logging.getLogger("Composiciones")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
    fh  = logging.FileHandler(os.path.join(output_dir, f"log_{ts}.txt"), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def cargar_capa_postgis(cfg_capa: dict, pg: dict, bbox_wkt: str, log):
    _valida_id(cfg_capa['geom_col'],      "geom_col")
    _valida_id(cfg_capa['tabla_postgis'], "tabla_postgis")
    _valida_id(pg['schema'],              "schema")

    if cfg_capa.get("sin_bbox_filter", False):
        filtro_sql = ""
        log.info(f"   → Cargando '{cfg_capa['tabla_postgis']}' SIN filtro bbox (cobertura amplia).")
    else:
        filtro_sql = (
            f"ST_Intersects({cfg_capa['geom_col']}, "
            f"ST_Transform("
            f"ST_Buffer("
            f"ST_Transform(ST_GeomFromText('{bbox_wkt}', 4326), 32612), "
            f"5500"
            f"), "
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


def aplicar_estilo_poligono(poly_layer):
    simbolo = QgsFillSymbol.createSimple({
        "color":         "0,0,0,0",
        "outline_color": "220,0,0,255",
        "outline_width": "0.8",
        "outline_style": "solid",
    })
    poly_layer.setRenderer(QgsSingleSymbolRenderer(simbolo))


def extraer_vertices_poligono(feature_poligono, crs, log):
    from qgis.core import QgsField
    from qgis.PyQt.QtCore import QVariant

    geom = feature_poligono.geometry()
    if geom.isMultipart():
        poligono = geom.asMultiPolygon()[0]
    else:
        poligono = geom.asPolygon()

    anillo = poligono[0]
    if len(anillo) > 1 and anillo[0] == anillo[-1]:
        anillo = anillo[:-1]

    capa_vertices = QgsVectorLayer(f"Point?crs={crs.authid()}", "Vertices_Proyecto", "memory")
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


def aplicar_estilo_vertices(capa_vertices, log):
    simbolo = QgsMarkerSymbol.createSimple({
        "name":          "circle",
        "color":         "255,255,0,220",
        "outline_color": "80,80,80,255",
        "outline_width": "0.4",
        "size":          "4.0",
    })
    capa_vertices.setRenderer(QgsSingleSymbolRenderer(simbolo))

    pal       = QgsPalLayerSettings()
    pal.fieldName = "num_vertice"
    pal.enabled   = True
    pal.placement = QgsPalLayerSettings.OverPoint

    fmt  = QgsTextFormat()
    font = QFont("Arial", 8, QFont.Bold)
    fmt.setFont(font)
    fmt.setSize(8)
    fmt.setColor(QColor(30, 30, 30))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.2)
    buffer.setColor(QColor(255, 255, 255, 220))
    fmt.setBuffer(buffer)
    pal.setFormat(fmt)
    pal.xOffset = 0.0
    pal.yOffset = -2.5

    capa_vertices.setLabelsEnabled(True)
    capa_vertices.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    capa_vertices.triggerRepaint()
    log.info(" ✓ Estilo de vértices aplicado (círculos amarillos numerados).")


def aplicar_renderer_categorizado(capa, campo: str, log) -> bool:
    idx_campo = capa.fields().lookupField(campo)
    if idx_campo == -1:
        campos_disponibles = [f.name() for f in capa.fields()]
        log.warning(f" → Campo '{campo}' no encontrado. Campos disponibles: {campos_disponibles}")
        return False

    valores_unicos = sorted(
        [v for v in capa.dataProvider().uniqueValues(idx_campo) if v is not None],
        key=str,
    )
    if not valores_unicos:
        log.warning(f" → Sin valores únicos en '{campo}'.")
        return False

    categorias = []
    for i, valor in enumerate(valores_unicos):
        simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
        color   = _color_para_categoria(i, valor)
        simbolo.setColor(color)
        if simbolo.symbolLayerCount() > 0:
            sl = simbolo.symbolLayer(0)
            if hasattr(sl, 'setStrokeColor'):
                sl.setStrokeColor(QColor(80, 80, 80, 180))
            if hasattr(sl, 'setStrokeWidth'):
                sl.setStrokeWidth(0.2)
        categorias.append(QgsRendererCategory(valor, simbolo, str(valor)))

    capa.setRenderer(QgsCategorizedSymbolRenderer(campo, categorias))
    log.info(f" ✓ Renderer categorizado: {len(categorias)} categorías en '{campo}'")
    return True


def aplicar_opacidad_capa(capa, opacidad: float, log):
    capa.setOpacity(opacidad)
    capa.triggerRepaint()
    log.info(f" ✓ Opacidad de capa: {int(opacidad * 100)}%")


def aplicar_etiquetas_pal(capa_centroides, campo: str, log):
    if not campo:
        return

    pal           = QgsPalLayerSettings()
    pal.fieldName = campo
    pal.enabled   = True
    pal.placement = QgsPalLayerSettings.OverPoint

    fmt  = QgsTextFormat()
    font = QFont("Arial", 7, QFont.Bold)
    fmt.setFont(font)
    fmt.setSize(7)
    fmt.setColor(QColor(30, 30, 30))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setColor(QColor(255, 255, 255, 200))
    fmt.setBuffer(buffer)
    pal.setFormat(fmt)

    pal.scaleVisibility = True
    pal.minimumScale    = 100000
    pal.maximumScale    = 500

    capa_centroides.setLabelsEnabled(True)
    capa_centroides.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    capa_centroides.triggerRepaint()
    log.info(f" ✓ Etiquetas PAL configuradas en campo '{campo}'")


def actualizar_leyenda(layout_comp, ids: dict, capa_tematica, capa_poligono):
    leyenda = layout_comp.itemById(ids["leyenda"])
    if leyenda and isinstance(leyenda, QgsLayoutItemLegend):
        leyenda.setAutoUpdateModel(False)
        root = leyenda.model().rootGroup()
        root.removeAllChildren()
        root.addLayer(capa_tematica)
        if capa_poligono:
            root.addLayer(capa_poligono)
        leyenda.adjustBoxSize()
        leyenda.refresh()


def reenlazar_barra_escala(layout_comp, map_item, log):
    encontradas = 0
    for item in layout_comp.items():
        if isinstance(item, QgsLayoutItemScaleBar):
            item.setLinkedMap(map_item)
            item.setUnits(QgsUnitTypes.DistanceMeters)
            item.setUnitLabel("m")
            item.refreshItemSize()
            item.refresh()
            encontradas += 1
    if encontradas:
        log.info(f" ✓ Barra(s) de escala en METROS re-enlazada(s): {encontradas}")
    else:
        log.warning(" → No se encontró barra de escala en la composición.")


def configurar_grid_mapa(map_item, intervalo_m: float, log):
    grids = map_item.grids()
    if grids.size() > 0:
        grid = grids.grid(0)
    else:
        grid = QgsLayoutItemMapGrid("Grid", map_item)
        grids.addGrid(grid)

    grid.setIntervalX(intervalo_m)
    grid.setIntervalY(intervalo_m)
    grid.setUnits(QgsLayoutItemMapGrid.MapUnit)
    grid.setEnabled(True)
    map_item.refresh()
    log.info(f" ✓ Grid configurado: {intervalo_m:,.0f} m")


def fijar_logo(layout_comp, id_logo: str, logo_ruta: str, log):
    if not id_logo:
        return
    if not logo_ruta:
        log.warning(" → logo_ruta no configurado en CONFIG.")
        return
    if not os.path.exists(logo_ruta):
        log.warning(f" → Archivo de logo no encontrado: {logo_ruta}")
        return

    item = layout_comp.itemById(id_logo)
    if item and isinstance(item, QgsLayoutItemPicture):
        item.setPicturePath(logo_ruta)
        item.refreshPicture()
        item.refresh()
        log.info(f" ✓ Logo actualizado: {os.path.basename(logo_ruta)}")
    else:
        log.warning(
            f" → Ítem de logo '{id_logo}' no encontrado o no es una imagen. "
            f"Verifica el ID en las propiedades del ítem en QGIS."
        )


def set_label_text(layout_comp, item_id: str, texto: str, log=None):
    if not item_id:
        return
    item = layout_comp.itemById(item_id)
    if item:
        item.setText(texto)
    elif log:
        log.debug(f" → Ítem de texto '{item_id}' no encontrado en la composición.")


def capturar_layers_mapitas(plantilla, id_mapa_principal: str) -> dict:
    snapshot = {}
    for item in plantilla.items():
        if not isinstance(item, QgsLayoutItemMap):
            continue
        if item.id() == id_mapa_principal:
            continue
        snapshot[item.id()] = list(item.layers())
    return snapshot


def proteger_mapas_referencia(layout_comp, id_mapa_principal: str,
                               layers_plantilla: dict, project, log):
    protegidos = 0
    for item in layout_comp.items():
        if not isinstance(item, QgsLayoutItemMap):
            continue
        if item.id() == id_mapa_principal:
            continue
        capas_originales = [
            project.mapLayer(l.id())
            for l in layers_plantilla.get(item.id(), [])
            if project.mapLayer(l.id())
        ]
        if capas_originales:
            item.setLayers(capas_originales)
            item.setKeepLayerSet(True)
            item.setKeepLayerStyles(True)
            item.invalidateCache()
            protegidos += 1
    if protegidos:
        log.info(f" ✓ Mapitas de referencia protegidos: {protegidos}")


# v9: resuelve los IDs efectivos para la composición, combinando
# los globales con los ids_override de la capa (si existen).
def resolver_ids(cfg_global: dict, cfg_capa: dict) -> dict:
    ids_efectivos = dict(cfg_global["ids"])
    ids_efectivos.update(cfg_capa.get("ids_override", {}))
    return ids_efectivos


# v9: diagnóstico de extent — detecta map_item mal configurado.
# Un extent > ~555 km en cualquier eje (≈ 5° o 500 000 m en UTM)
# sugiere que el map_item no se centró en el polígono del proyecto.
def validar_extent(extent, nombre_capa, log):
    ancho = extent.width()
    alto  = extent.height()
    umbral = 500_000  # metros en UTM; ajustar si el CRS es geográfico
    if ancho > umbral or alto > umbral:
        log.warning(
            f" ⚠ extent_en_escala MUY GRANDE para '{nombre_capa}': "
            f"{ancho:,.0f} x {alto:,.0f} unidades. "
            f"Verifica que el ID de mapa en ids_override sea correcto."
        )
    else:
        log.info(
            f" → extent_en_escala: {ancho:,.0f} x {alto:,.0f} unidades "
            f"(CRS: {extent.__class__.__name__})"
        )


# =============================================================================
# PROCESO PRINCIPAL
# =============================================================================

def generar_composiciones(cfg: dict):
    nombre_carpeta = sanitizar_nombre(cfg["nombre_proyecto"])[:50]
    output_dir     = os.path.join(cfg["output_base"], nombre_carpeta)
    os.makedirs(output_dir, exist_ok=True)
    log = crear_logger(output_dir)

    log.info("=" * 65)
    log.info("INICIANDO GENERACIÓN DE COMPOSICIONES E INYECCIÓN DE CAPAS")
    log.info("=" * 65)

    project = QgsProject.instance()

    # --- Capa polígono de trabajo ---
    capas_poly = project.mapLayersByName(cfg["capa_poligono"])
    if not capas_poly:
        log.error(f"✗ Capa '{cfg['capa_poligono']}' no encontrada.")
        return
    poly_layer = capas_poly[0]

    seleccionados = list(poly_layer.selectedFeatures())
    if not seleccionados:
        log.error("✗ Por favor, selecciona el polígono de trabajo en el mapa.")
        return
    if len(seleccionados) > 1:
        log.warning(
            f"⚠ {len(seleccionados)} polígonos seleccionados; "
            f"se usará solo el primero (ID={seleccionados[0].id()})."
        )
    feature_poligono = seleccionados[0]

    aplicar_estilo_poligono(poly_layer)
    log.info(" ✓ Estilo del polígono de trabajo aplicado.")

    cache_plantillas = {}

    def obtener_plantilla_y_mapitas(layout_nombre: str, id_mapa: str):
        key = (layout_nombre, id_mapa)
        if key not in cache_plantillas:
            p_base = cargar_o_importar_layout(project, layout_nombre, log)
            if not p_base:
                log.error(f"✗ Plantilla '{layout_nombre}' no disponible.")
                return None, None
            m_layers = capturar_layers_mapitas(p_base, id_mapa)
            log.info(f" ✓ Snapshot de mapitas capturado para '{layout_nombre}': {len(m_layers)} ítem(s).")
            cache_plantillas[key] = (p_base, m_layers)
        return cache_plantillas[key]

    # 1. Grupo contenedor en el panel de capas
    root_tree = project.layerTreeRoot()
    grupo_mia = root_tree.findGroup("Planos Generados")
    if grupo_mia:
        for child in grupo_mia.children():
            if hasattr(child, 'layerId'):
                project.removeMapLayer(child.layerId())
        grupo_mia.removeAllChildren()
        log.info(" → Limpiando grupo 'Planos Generados' previo...")
    else:
        grupo_mia = root_tree.addGroup("Planos Generados")

    # 2. Mapa base satelital XYZ
    mapa_base = project.mapLayersByName("Google Satellite")
    if mapa_base:
        basemap_layer = mapa_base[0]
        log.info(" → Reutilizando fondo satelital existente.")
    else:
        url_basemap = (
            "type=xyz"
            "&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D%7Bx%7D%26y%3D%7By%7D%26z%3D%7Bz%7D"
            "&zmax=21&zmin=0"
        )
        basemap_layer = QgsRasterLayer(url_basemap, "Google Satellite", "wms")
        if basemap_layer.isValid():
            project.addMapLayer(basemap_layer, False)
            grupo_mia.addLayer(basemap_layer)
            log.info(" ✓ Fondo satelital añadido al grupo.")
        else:
            basemap_layer = None
            log.warning(" → Fondo satelital no disponible.")

    # 3. BBox del polígono seleccionado
    crs_origen  = poly_layer.crs()
    bbox_nativo = feature_poligono.geometry().boundingBox()
    transf_4326 = QgsCoordinateTransform(
        crs_origen, QgsCoordinateReferenceSystem("EPSG:4326"), project
    )
    bbox_wkt = transf_4326.transformBoundingBox(bbox_nativo).asWktPolygon()

    # 4. Punto centroide del proyecto (marcador estrella roja)
    centroid_geom = feature_poligono.geometry().centroid()
    punto_layer   = QgsVectorLayer(
        f"Point?crs={crs_origen.authid()}", "Centroide_Proyecto", "memory"
    )
    f_punto = QgsFeature()
    f_punto.setGeometry(centroid_geom)
    punto_layer.dataProvider().addFeatures([f_punto])
    simbolo_punto = QgsMarkerSymbol.createSimple({
        "name":          "star",
        "color":         "220,0,0,255",
        "outline_color": "255,255,255,255",
        "size":          "5.0",
    })
    punto_layer.renderer().setSymbol(simbolo_punto)
    project.addMapLayer(punto_layer, False)
    grupo_mia.addLayer(punto_layer)

    basemap_id = basemap_layer.id() if basemap_layer else None

    def _ref(capa):
        return project.mapLayer(capa.id()) if capa else None

    # =========================================================================
    # LOOP PRINCIPAL
    # =========================================================================
    for cfg_capa in cfg["capas"]:
        es_vertices = cfg_capa.get("tipo") == "vertices"
        nombre_comp = f"Comp_{cfg_capa['nombre_capa']}"

        log.info(f"\n{'─' * 55}")
        log.info(f" Procesando: {nombre_comp}...")
        log.info(f"{'─' * 55}")

        # v9: resolver IDs efectivos (global + override por capa)
        ids = resolver_ids(cfg, cfg_capa)

        # ── 5a. Cargar datos ──────────────────────────────────────────────────
        if not es_vertices:
            if cfg_capa.get("origen") == "proyecto":
                capas_proyecto = project.mapLayersByName(cfg_capa["nombre_capa"])
                if not capas_proyecto:
                    log.warning(f" → Capa del proyecto '{cfg_capa['nombre_capa']}' no encontrada, se omite.")
                    continue
                capa_pg = capas_proyecto[0]
            else:
                capa_pg = cargar_capa_postgis(cfg_capa, cfg["pg"], bbox_wkt, log)
                if not capa_pg:
                    log.warning(f" → Capa PostGIS inválida para '{cfg_capa['nombre_capa']}', se omite.")
                    continue

                # v8: featureCount -1 = conteo no disponible, NO vacío
                count = capa_pg.featureCount()
                if count == 0:
                    log.warning(f" → Sin datos para '{cfg_capa['nombre_capa']}' (featureCount=0), se omite.")
                    continue
                elif count == -1:
                    log.info(f" → featureCount no disponible para '{cfg_capa['nombre_capa']}' (count=-1), continuando...")
                else:
                    log.info(f" → {count} feature(s) encontrados en '{cfg_capa['nombre_capa']}'.")

        # ── 5b. Clonar composición PRIMERO ────────────────────────────────────
        comp_existente = project.layoutManager().layoutByName(nombre_comp)
        if comp_existente:
            project.layoutManager().removeLayout(comp_existente)

        layout_actual = cfg_capa.get("layout_nombre", cfg["layout_nombre"])
        plantilla_base_capa, layers_mapitas_capa = obtener_plantilla_y_mapitas(layout_actual, ids["mapa"])
        if not plantilla_base_capa:
            log.warning(f" → Plantilla '{layout_actual}' no disponible, se omite.")
            continue

        nueva_comp = plantilla_base_capa.clone()
        nueva_comp.setName(nombre_comp)
        project.layoutManager().addLayout(nueva_comp)

        # v6: proteger mapitas de referencia inmediatamente tras clonar
        proteger_mapas_referencia(nueva_comp, ids["mapa"], layers_mapitas_capa, project, log)

        # ── 5c. Calcular extent desde el map_item del CLON ────────────────────
        map_item = nueva_comp.itemById(ids["mapa"])
        if not map_item:
            # v9: listar todos los IDs de ítems de mapa disponibles para diagnóstico
            ids_mapas_disponibles = [
                item.id() for item in nueva_comp.items()
                if isinstance(item, QgsLayoutItemMap)
            ]
            log.warning(
                f" → Item de mapa '{ids['mapa']}' no encontrado en '{layout_actual}'. "
                f"IDs de mapas disponibles: {ids_mapas_disponibles}. "
                f"Ajusta 'ids_override' → 'mapa' en la CONFIG para esta capa."
            )
            continue

        frame_size_original = map_item.sizeWithUnits()
        frame_pos_original  = map_item.positionWithUnits()

        map_item.setCrs(crs_origen)
        map_item.setExtent(bbox_nativo)
        map_item.setScale(cfg_capa["escala"])

        map_item.attemptResize(frame_size_original)
        map_item.attemptMove(frame_pos_original)

        extent_en_escala = map_item.extent()

        # v9: diagnóstico de extent — detecta map_item mal configurado
        validar_extent(extent_en_escala, cfg_capa["nombre_capa"], log)

        # ── Flujo especial: Plano de Vértices ─────────────────────────────────
        if es_vertices:
            capa_vertices = extraer_vertices_poligono(feature_poligono, crs_origen, log)
            aplicar_estilo_vertices(capa_vertices, log)
            capa_vertices.setName(cfg_capa["nombre_capa"])

            project.addMapLayer(capa_vertices, False)
            grupo_mia.insertLayer(0, capa_vertices)

            capas_visibles = [r for r in [_ref(capa_vertices), _ref(poly_layer)] if r]
            if basemap_id:
                r = project.mapLayer(basemap_id)
                if r:
                    capas_visibles.append(r)

            map_item.setKeepLayerSet(True)
            map_item.setLayers(capas_visibles)
            map_item.invalidateCache()
            map_item.refresh()

            reenlazar_barra_escala(nueva_comp, map_item, log)
            configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 100), log)
            actualizar_leyenda(nueva_comp, ids, capa_vertices, poly_layer)

            set_label_text(nueva_comp, ids["lbl_proyecto"],          cfg["nombre_proyecto"],  log)
            set_label_text(nueva_comp, ids["lbl_licencia"],          cfg["tipo_tramite"],      log)
            set_label_text(nueva_comp, ids["lbl_plano"],             cfg_capa["nombre_plano"], log)
            set_label_text(nueva_comp, ids["lbl_escala"],
                           f"Escala 1:{cfg_capa['escala']:,}".replace(",", " "), log)
            set_label_text(nueva_comp, ids["lbl_fecha"],             f"Fecha: {cfg['mes_año']}", log)
            set_label_text(nueva_comp, ids.get("lbl_fuente",   ""),  cfg_capa.get("fuente", ""), log)
            set_label_text(nueva_comp, ids.get("lbl_coordsys", ""),  cfg.get("coordenadas", ""), log)

            fijar_logo(nueva_comp, ids.get("logo", ""), cfg.get("logo_ruta", ""), log)
            nueva_comp.refresh()

            QCoreApplication.processEvents()
            ruta_png = os.path.join(
                output_dir,
                f"{sanitizar_nombre(cfg_capa['nombre_plano'])}_ID{feature_poligono.id()}.png",
            )
            exportador = QgsLayoutExporter(nueva_comp)
            config_img = QgsLayoutExporter.ImageExportSettings()
            config_img.dpi = cfg["dpi"]
            res_img = exportador.exportToImage(ruta_png, config_img)
            if res_img == QgsLayoutExporter.Success:
                log.info(f" ✓ PNG exportado: {os.path.basename(ruta_png)}")
            else:
                log.error(f" ✗ Falló exportación (código {res_img}): {ruta_png}")
            continue  # saltar flujo PostGIS

        # ── 5d. Sanear geometrías ─────────────────────────────────────────────
        log.info(" → Saneando geometrías (fixgeometries)...")
        res_fix = processing.run("native:fixgeometries", {
            "INPUT":  capa_pg,
            "OUTPUT": "memory:",
        })

        # ── 5e. Reproyectar ───────────────────────────────────────────────────
        res_reproj = processing.run("native:reprojectlayer", {
            "INPUT":      res_fix["OUTPUT"],
            "TARGET_CRS": crs_origen,
            "OUTPUT":     "memory:",
        })
        capa_reproyectada = res_reproj["OUTPUT"]

        # v9: Fix CRS clip — crear la máscara en el CRS de la capa reproyectada.
        # Si hay discrepancia entre crs_origen y el CRS real de la capa reproyectada,
        # reproyectar el extent antes de crear la máscara evita clips silenciosos
        # donde se devuelven todas las geometrías sin recortar.
        crs_reproyectada = capa_reproyectada.crs()
        if crs_reproyectada.authid() != crs_origen.authid():
            log.info(f" → Reproyectando extent de clip: {crs_origen.authid()} → {crs_reproyectada.authid()}")
            transf_clip = QgsCoordinateTransform(crs_origen, crs_reproyectada, project)
            rect_clip   = transf_clip.transformBoundingBox(extent_en_escala)
        else:
            rect_clip = extent_en_escala

        layer_extent = QgsVectorLayer(
            f"Polygon?crs={crs_reproyectada.authid()}", "extent_tmp", "memory"
        )
        f_ext = QgsFeature()
        f_ext.setGeometry(QgsGeometry.fromRect(rect_clip))
        layer_extent.dataProvider().addFeatures([f_ext])

        # ── 5f. Recortar ──────────────────────────────────────────────────────
        res_clip = processing.run("native:clip", {
            "INPUT":   capa_reproyectada,
            "OVERLAY": layer_extent,
            "OUTPUT":  "memory:",
        })
        capa_recortada = res_clip["OUTPUT"]
        capa_recortada.setName(cfg_capa["nombre_capa"])

        # v9: verificar que el clip realmente redujo las features
        n_clip = capa_recortada.featureCount()
        n_orig = capa_pg.featureCount()
        if n_orig > 0 and n_clip == n_orig:
            log.warning(
                f" ⚠ El clip NO redujo features ({n_clip}/{n_orig}). "
                f"Es posible que el extent no intersecte correctamente la capa. "
                f"Revisa el CRS y el ID de mapa en ids_override."
            )
        elif n_clip == 0:
            log.warning(f" ⚠ Clip resultó vacío para '{cfg_capa['nombre_capa']}'. Revisa escala y CRS.")
        else:
            log.info(f" → Clip: {n_clip} feature(s) resultantes.")

        # ── 5g. Renderer y simbología ─────────────────────────────────────────
        campo_cat = cfg_capa.get("campo_categoria", "")
        if campo_cat:
            aplicar_renderer_categorizado(capa_recortada, campo_cat, log)
        elif capa_pg.renderer():
            capa_recortada.setRenderer(capa_pg.renderer().clone())

        # ── 5h. Opacidad ──────────────────────────────────────────────────────
        aplicar_opacidad_capa(capa_recortada, cfg_capa.get("opacidad", 0.6), log)

        # ── 5i. Centroides temáticos ──────────────────────────────────────────
        log.info(" → Extrayendo centroides temáticos (ALL_PARTS=True)...")
        res_cent = processing.run("native:centroids", {
            "INPUT":     capa_recortada,
            "ALL_PARTS": True,
            "OUTPUT":    "memory:",
        })
        capa_centroides = res_cent["OUTPUT"]
        capa_centroides.setName(f"centroides_{cfg_capa['nombre_capa']}")

        # ── 5j. Etiquetas PAL ─────────────────────────────────────────────────
        campo_etq = cfg_capa.get("campo_etiqueta", campo_cat)
        aplicar_etiquetas_pal(capa_centroides, campo_etq, log)

        project.addMapLayer(capa_recortada,  False)
        project.addMapLayer(capa_centroides, False)
        grupo_mia.insertLayer(0, capa_recortada)
        grupo_mia.insertLayer(0, capa_centroides)

        # ── 5k. Configurar map_item ───────────────────────────────────────────
        usar_punto      = cfg_capa.get("marcador", "poligono") == "punto"
        capa_referencia = punto_layer if usar_punto else poly_layer

        capas_visibles = [
            r for r in [
                _ref(capa_referencia),
                _ref(capa_centroides),
                _ref(capa_recortada),
            ] if r
        ]
        if basemap_id:
            r = project.mapLayer(basemap_id)
            if r:
                capas_visibles.append(r)

        map_item.setKeepLayerSet(True)
        map_item.setLayers(capas_visibles)
        map_item.invalidateCache()
        map_item.refresh()

        # ── 5l. Barra de escala ───────────────────────────────────────────────
        reenlazar_barra_escala(nueva_comp, map_item, log)

        # ── 5m. Grid ─────────────────────────────────────────────────────────
        configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 500), log)

        # ── 5n. Leyenda y textos ──────────────────────────────────────────────
        actualizar_leyenda(nueva_comp, ids, capa_recortada, poly_layer)

        set_label_text(nueva_comp, ids["lbl_proyecto"],          cfg["nombre_proyecto"],  log)
        set_label_text(nueva_comp, ids["lbl_licencia"],          cfg["tipo_tramite"],      log)
        set_label_text(nueva_comp, ids["lbl_plano"],             cfg_capa["nombre_plano"], log)
        set_label_text(nueva_comp, ids["lbl_escala"],
                       f"Escala 1:{cfg_capa['escala']:,}".replace(",", " "), log)
        set_label_text(nueva_comp, ids["lbl_fecha"],             f"Fecha: {cfg['mes_año']}", log)
        set_label_text(nueva_comp, ids.get("lbl_fuente",   ""),  cfg_capa.get("fuente", ""), log)
        set_label_text(nueva_comp, ids.get("lbl_coordsys", ""),  cfg.get("coordenadas", ""), log)

        # ── 5o. Logo ──────────────────────────────────────────────────────────
        fijar_logo(nueva_comp, ids.get("logo", ""), cfg.get("logo_ruta", ""), log)

        nueva_comp.refresh()

        # ── 5p. Exportar a PNG ────────────────────────────────────────────────
        QCoreApplication.processEvents()

        ruta_png = os.path.join(
            output_dir,
            f"{sanitizar_nombre(cfg_capa['nombre_plano'])}_ID{feature_poligono.id()}.png",
        )
        exportador = QgsLayoutExporter(nueva_comp)
        config_img = QgsLayoutExporter.ImageExportSettings()
        config_img.dpi = cfg["dpi"]

        res_img = exportador.exportToImage(ruta_png, config_img)
        if res_img == QgsLayoutExporter.Success:
            log.info(f" ✓ PNG exportado: {os.path.basename(ruta_png)}")
        else:
            log.error(f" ✗ Falló exportación (código {res_img}): {ruta_png}")

    log.info(f"\n{'=' * 65}")
    log.info("✓ PROCESO TERMINADO — Revisa tu panel de Diseños en QGIS")
    log.info(f"  Ruta de imágenes: {output_dir}")
    log.info("=" * 65)


# Ejecutar proceso
generar_composiciones(CONFIG)