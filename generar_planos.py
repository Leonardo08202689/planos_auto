# =============================================================================
# GENERADOR AUTOMÁTICO DE PLANOS — LICENCIA AMBIENTAL INTEGRAL
# Empresa: SINERGIA Consultores en Ingeniería Ambiental
#
# Metodología basada en:
#   "Optimización Cartográfica y Automatización Geoespacial en QGIS"
#
# Mejoras aplicadas:
#   § 3   native:centroids(ALL_PARTS=True) sobre capa temática → etiquetas estables
#   § 4   native:fixgeometries antes del clip → seguridad topológica
#   § 5   setOpacity() a nivel de CAPA (no símbolo) → sin artefactos de borde
#   § 6   QgsCategorizedSymbolRenderer con colores por valores únicos
#   § 7   PAL labeling anclado a centroides temáticos (no al polígono base)
#
# FIXES v4:
#   - Clonar PRIMERO, luego calcular extent desde el clon → plantilla nunca
#     se modifica → los ítems bloqueados (mapitas de esquina) no se mueven
#     y el mapa principal no baja de posición.
#   - Barra de escala fijada en METROS con sufijo correcto.
#
# FIXES v5:
#   - Grid configurable por capa (grid_intervalo en metros).
#   - Logo corporativo reasignado por ruta desde CONFIG → elimina la X.
#   - Frame del mapa protegido contra desbordamiento del grid.
#
# FIXES v6:
#   - Mapitas de referencia (esquina superior derecha) protegidos con
#     setKeepLayerSet(True) y setKeepLayerStyles(True) inmediatamente
#     después de clonar → no heredan el satélite ni las capas temáticas
#     y mantienen el estilo verde vectorial de la plantilla.
#
# FIXES v7:
#   - TypeError con QgsRasterLayer en setLayers() corregido: todas las
#     capas se recuperan del registro del proyecto por ID antes de
#     pasarlas a setLayers() → sin errores de tipo en capas raster.
#   - poly_layer al frente de capas_visibles → polígono siempre encima.
#   - punto_layer (estrella roja) eliminado del mapa principal.
# =============================================================================

import os
import re
import unicodedata
import logging
from datetime import datetime
from random import seed, randrange

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsLayoutExporter,
    QgsLayoutItemLegend,
    QgsLayoutItemScaleBar,
    QgsLayoutItemMapGrid,   # v5: grid configurable
    QgsLayoutItemPicture,   # v5: logo corporativo
    QgsLayoutItemMap,       # v6: proteger mapitas de referencia
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
    seed(hash(str(valor)) % (2**32))
    return QColor(randrange(60, 220), randrange(60, 220), randrange(60, 220))


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
    nfkd = unicodedata.normalize("NFKD", texto)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("ASCII")
    limpio = re.sub(r"[^\w\-]", "_", ascii_text)
    return re.sub(r"_+", "_", limpio).strip("_")


def cargar_o_importar_layout(project, layout_nombre, log):
    layout = project.layoutManager().layoutByName(layout_nombre)
    if layout:
        return layout

    script_dir = "/home/leonardo/Codigos/Planos_auto"
    qpt_path   = os.path.join(script_dir, f"{layout_nombre}.qpt")
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
    "mes_año":         "Mayo 2026",
    "coordenadas":     "COORDENADAS UTM WGS84, R12",
    "output_base":     "/home/leonardo/planos_salida/prueba",

    # v5: ruta al logo corporativo (corrige la X en el plano)
    # Pon aquí la ruta real de tu imagen .png o .svg
    "logo_ruta": "/home/leonardo/Codigos/Planos_auto/logo_sinergia.jpg",

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
        # v5: ID del ítem de imagen del logo en el QPT
        # Verifica el ID en QGIS: clic en el logo → panel Propiedades del ítem → campo "ID del ítem"
        "logo":         "logo_empresa",
    },

    "dpi": 200,

    "capas": [
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
            "fuente": "Conjunto de Datos Vectorial Edafológico. Escala 1:250 000 Serie III. INEGI.",
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
            "fuente": "Continúo Nacional de Geología de la República Mexicana escala 1:250,000.",
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
            "fuente": "Conjunto de Datos Nacionales de Unidades Climáticas, Escala 1:1 000 000, INEGI.",
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
            "fuente": "Conjunto de datos vectoriales de uso del suelo y vegetación. Escala 1:250 000. Serie VII.",
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
            "marcador":        "punto",   # ← muestra estrella roja en vez de polígono
            "fuente": "Red hidrográfica, Subcuencas hidrográficas de México, Escala 1:50000.",
        },
    ],
}

# =============================================================================
# SECCIÓN 2 — FUNCIONES DE CONTROL
# =============================================================================

def crear_logger(output_dir: str) -> logging.Logger:
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = logging.getLogger("Composiciones")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
    fh = logging.FileHandler(
        os.path.join(output_dir, f"log_{ts}.txt"), encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def cargar_capa_postgis(cfg_capa: dict, pg: dict, bbox_wkt: str, log):
    filtro_sql = (
        f"ST_Intersects({cfg_capa['geom_col']}, "
        f"ST_Transform(ST_Buffer(ST_GeomFromText('{bbox_wkt}', 4326), 0.05), "
        f"ST_SRID({cfg_capa['geom_col']})))"
    )
    uri = (
        f"dbname='{pg['dbname']}' host={pg['host']} port={pg['port']} "
        f"user='{pg['user']}' password='{pg['password']}' sslmode=disable "
        f"key='{cfg_capa.get('key', 'gid')}' "
        f"type={cfg_capa['tipo_geom']} "
        f"table=\"{pg['schema']}\".\"{cfg_capa['tabla_postgis']}\" "
        f"({cfg_capa['geom_col']}) sql={filtro_sql}"
    )
    capa = QgsVectorLayer(uri, cfg_capa["nombre_capa"] + "_raw", "postgres")
    if not capa.isValid():
        log.error(f"   ✗ Capa PostGIS inválida: {cfg_capa['tabla_postgis']}")
        return None
    return capa


def aplicar_estilo_poligono(poly_layer):
    """Borde rojo sin relleno para el polígono de trabajo."""
    simbolo = QgsFillSymbol.createSimple({
        "color":         "0,0,0,0",
        "outline_color": "220,0,0,255",
        "outline_width": "0.8",
        "outline_style": "solid",
    })
    poly_layer.setRenderer(QgsSingleSymbolRenderer(simbolo))
    poly_layer.triggerRepaint()


def aplicar_renderer_categorizado(capa, campo: str, log) -> bool:
    """
    § 6 doc — QgsCategorizedSymbolRenderer.
    Usa capa.fields().lookupField() (case-insensitive) en vez del deprecado
    proveedor.fieldNameIndex(), que falla en capas de memoria.
    """
    idx_campo = capa.fields().lookupField(campo)
    if idx_campo == -1:
        campos_disponibles = [f.name() for f in capa.fields()]
        log.warning(
            f"   → Campo '{campo}' no encontrado. "
            f"Campos disponibles: {campos_disponibles}"
        )
        return False

    valores_unicos = sorted(
        [v for v in capa.dataProvider().uniqueValues(idx_campo) if v is not None],
        key=str,
    )
    if not valores_unicos:
        log.warning(f"   → Sin valores únicos en '{campo}'.")
        return False

    categorias = []
    for i, valor in enumerate(valores_unicos):
        simbolo = QgsSymbol.defaultSymbol(capa.geometryType())
        color = _color_para_categoria(i, valor)
        simbolo.setColor(color)
        if simbolo.symbolLayerCount() > 0:
            simbolo.symbolLayer(0).setStrokeColor(QColor(80, 80, 80, 180))
            simbolo.symbolLayer(0).setStrokeWidth(0.2)
        categorias.append(QgsRendererCategory(valor, simbolo, str(valor)))

    capa.setRenderer(QgsCategorizedSymbolRenderer(campo, categorias))
    log.info(f"   ✓ Renderer categorizado: {len(categorias)} categorías en '{campo}'")
    return True


def aplicar_opacidad_capa(capa, opacidad: float, log):
    """§ 5 doc — Opacidad a nivel de CAPA, no de símbolo."""
    capa.setOpacity(opacidad)
    capa.triggerRepaint()
    log.info(f"   ✓ Opacidad de capa: {int(opacidad * 100)}%")


def aplicar_etiquetas_pal(capa_centroides, campo: str, log):
    """§ 7 doc — Motor PAL anclado a centroides temáticos."""
    if not campo:
        return

    pal = QgsPalLayerSettings()
    pal.fieldName = campo
    pal.enabled   = True
    pal.placement = QgsPalLayerSettings.OverPoint

    fmt    = QgsTextFormat()
    font   = QFont("Arial", 7, QFont.Bold)
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
    log.info(f"   ✓ Etiquetas PAL configuradas en campo '{campo}'")


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
    """
    Reconecta cada barra de escala al map_item del clon y FIJA las unidades
    en METROS con sufijo ' m'.
    """
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
        log.info(f"   ✓ Barra(s) de escala en METROS re-enlazada(s): {encontradas}")
    else:
        log.warning("   → No se encontró barra de escala en la composición.")


def configurar_grid_mapa(map_item, intervalo_m: float, log):
    """
    v5 — Ajusta el intervalo del grid del mapa principal en metros.
    Reutiliza el primer grid existente o crea uno nuevo si no hay ninguno.
    Esto evita que un grid denso (ej. 500 m a escala 1:35000) desborde
    el frame del mapa.
    """
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
    log.info(f"   ✓ Grid configurado: {intervalo_m:,.0f} m")


def fijar_logo(layout_comp, id_logo: str, logo_ruta: str, log):
    """
    v5 — Reasigna la imagen del logo corporativo por ID de ítem.
    Elimina la X que aparece cuando el QPT guarda una ruta absoluta
    que ya no existe en el equipo actual.
    """
    if not id_logo:
        return
    if not logo_ruta:
        log.warning("   → logo_ruta no configurado en CONFIG.")
        return
    if not os.path.exists(logo_ruta):
        log.warning(f"   → Archivo de logo no encontrado: {logo_ruta}")
        return

    item = layout_comp.itemById(id_logo)
    if item and isinstance(item, QgsLayoutItemPicture):
        item.setPicturePath(logo_ruta)
        item.refreshPicture()
        item.refresh()
        log.info(f"   ✓ Logo actualizado: {os.path.basename(logo_ruta)}")
    else:
        log.warning(
            f"   → Ítem de logo '{id_logo}' no encontrado o no es una imagen. "
            f"Verifica el ID en las propiedades del ítem en QGIS."
        )


def set_label_text(layout_comp, item_id: str, texto: str):
    item = layout_comp.itemById(item_id)
    if item:
        item.setText(texto)


def capturar_layers_mapitas(plantilla, id_mapa_principal: str) -> dict:
    """
    v6 — Lee las capas que tienen los mapitas de referencia en la
    PLANTILLA ORIGINAL (antes de clonar).  Devuelve un dict
    {item_id: [lista_de_capas]}.

    Esto es necesario porque los mapitas de la plantilla pueden tener
    keepLayerSet=False (siguen las capas del proyecto); en cuanto
    añadimos el satélite y las capas temáticas al proyecto, un clon
    recién creado los hereda todos.  Guardando aquí las capas de la
    plantilla podemos restaurarlas en el clon.
    """
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
    """
    v7 — Restaura las capas originales de la plantilla en cada mapita
    del CLON y congela su layer set.  Las referencias se resuelven
    desde el registro del proyecto para evitar TypeError con capas
    raster en setLayers().
    """
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
        log.info(f"   ✓ Mapitas de referencia protegidos: {protegidos}")


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
    feature_poligono = seleccionados[0]

    aplicar_estilo_poligono(poly_layer)
    log.info(" ✓ Estilo del polígono de trabajo aplicado.")

    # --- Plantilla base ---
    # IMPORTANTE: la plantilla NO se modifica en ningún momento del proceso.
    # Clonar primero y operar solo sobre el clon evita que los ítems bloqueados
    # (mapitas de esquina) se muevan y que el mapa principal cambie de posición.
    plantilla_base = cargar_o_importar_layout(project, cfg["layout_nombre"], log)
    if not plantilla_base:
        log.error("✗ Plantilla base corporativa no disponible.")
        return

    # ── SNAPSHOT DE MAPITAS — debe hacerse ANTES de añadir cualquier capa ──
    # Si se hace después, los mapitas con keepLayerSet=False ya tienen el
    # satélite en su lista y el snapshot lo incluiría.
    ids = cfg["ids"]
    layers_mapitas = capturar_layers_mapitas(plantilla_base, ids["mapa"])
    log.info(f" ✓ Snapshot de mapitas capturado: {len(layers_mapitas)} ítem(s).")

    # 1. Grupo contenedor en el panel de capas
    root_tree = project.layerTreeRoot()
    grupo_mia = root_tree.findGroup("Planos Generados")
    if grupo_mia:
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
    crs_origen   = poly_layer.crs()
    bbox_nativo  = feature_poligono.geometry().boundingBox()
    transf_4326  = QgsCoordinateTransform(
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

    # Guardar el ID del satélite antes del loop para recuperarlo
    # de forma segura desde el registro en cada iteración.
    # La referencia directa (basemap_layer) puede invalidarse durante
    # el procesamiento y lanzar RuntimeError en C++.
    basemap_id = basemap_layer.id() if basemap_layer else None

    for cfg_capa in cfg["capas"]:  # noqa
        nombre_comp = f"Comp_{cfg_capa['nombre_capa']}"
        log.info(f"\n{'─' * 55}")
        log.info(f" Procesando: {nombre_comp}")
        log.info(f"{'─' * 55}")

        # ── 5a. Cargar desde PostGIS ─────────────────────────────────────────
        capa_pg = cargar_capa_postgis(cfg_capa, cfg["pg"], bbox_wkt, log)
        if not capa_pg or capa_pg.featureCount() == 0:
            log.warning(f"   → Sin datos para '{cfg_capa['nombre_capa']}', se omite.")
            continue

        # ── 5b. § 4 doc — Clonar composición PRIMERO ────────────────────────
        # Al clonar ANTES de cualquier modificación, la plantilla queda
        # intacta → los ítems bloqueados no se mueven en ninguna iteración.
        comp_existente = project.layoutManager().layoutByName(nombre_comp)
        if comp_existente:
            project.layoutManager().removeLayout(comp_existente)

        nueva_comp = plantilla_base.clone()
        nueva_comp.setName(nombre_comp)
        project.layoutManager().addLayout(nueva_comp)

        # ── v6: Proteger mapitas de referencia INMEDIATAMENTE tras clonar ────
        # Restaura las capas de la plantilla original y congela el layer set
        # para que no hereden el satélite ni las capas temáticas.
        proteger_mapas_referencia(nueva_comp, ids["mapa"], layers_mapitas, project, log)

        # ── 5c. Calcular extent desde el map_item del CLON (no de la plantilla)
        map_item = nueva_comp.itemById(ids["mapa"])
        if not map_item:
            log.warning(f"   → Item de mapa '{ids['mapa']}' no encontrado.")
            continue

        # v5: guardar tamaño original del frame ANTES de setExtent/setScale
        # para restaurarlo después y evitar desbordamiento del grid
        frame_size_original = map_item.sizeWithUnits()
        frame_pos_original  = map_item.positionWithUnits()

        map_item.setCrs(crs_origen)
        map_item.setExtent(bbox_nativo)
        map_item.setScale(cfg_capa["escala"])

        # v5: restaurar frame al tamaño de la plantilla
        map_item.attemptResize(frame_size_original)
        map_item.attemptMove(frame_pos_original)

        extent_en_escala = map_item.extent()   # extent real a esta escala

        # ── 5d. Sanear geometrías (§4 doc) ───────────────────────────────────
        log.info("   → Saneando geometrías (fixgeometries)...")
        res_fix = processing.run("native:fixgeometries", {
            "INPUT":  capa_pg,
            "OUTPUT": "memory:",
        })

        # Máscara de recorte basada en el extent calculado del clon
        layer_extent = QgsVectorLayer(
            f"Polygon?crs={crs_origen.authid()}", "extent_tmp", "memory"
        )
        f_ext = QgsFeature()
        f_ext.setGeometry(QgsGeometry.fromRect(extent_en_escala))
        layer_extent.dataProvider().addFeatures([f_ext])

        # ── 5e. Reproyectar y recortar ────────────────────────────────────────
        res_reproj = processing.run("native:reprojectlayer", {
            "INPUT":      res_fix["OUTPUT"],
            "TARGET_CRS": crs_origen,
            "OUTPUT":     "memory:",
        })
        res_clip = processing.run("native:clip", {
            "INPUT":   res_reproj["OUTPUT"],
            "OVERLAY": layer_extent,
            "OUTPUT":  "memory:",
        })
        capa_recortada = res_clip["OUTPUT"]
        capa_recortada.setName(cfg_capa["nombre_capa"])

        # ── 5f. § 6 doc — Renderer categorizado ─────────────────────────────
        campo_cat = cfg_capa.get("campo_categoria", "")
        if campo_cat:
            aplicar_renderer_categorizado(capa_recortada, campo_cat, log)

        # ── 5g. § 5 doc — Opacidad a nivel de CAPA ───────────────────────────
        aplicar_opacidad_capa(capa_recortada, cfg_capa.get("opacidad", 0.6), log)

        # ── 5h. § 3 doc — Centroides temáticos con native:centroids ─────────
        log.info("   → Extrayendo centroides temáticos (ALL_PARTS=True)...")
        res_cent = processing.run("native:centroids", {
            "INPUT":     capa_recortada,
            "ALL_PARTS": True,
            "OUTPUT":    "memory:",
        })
        capa_centroides = res_cent["OUTPUT"]
        capa_centroides.setName(f"centroides_{cfg_capa['nombre_capa']}")

        # ── 5i. § 7 doc — Etiquetas PAL ancladas a los centroides ─────────────
        campo_etq = cfg_capa.get("campo_etiqueta", campo_cat)
        aplicar_etiquetas_pal(capa_centroides, campo_etq, log)

        # Añadir capas al proyecto y al grupo
        project.addMapLayer(capa_recortada,  False)
        project.addMapLayer(capa_centroides, False)
        grupo_mia.insertLayer(0, capa_recortada)
        grupo_mia.insertLayer(0, capa_centroides)

        # ── 5j. Configurar el map_item del clon ──────────────────────────────
        # "marcador": "punto"   → muestra estrella roja (hidrología, escalas grandes)
        # "marcador": "poligono"→ muestra borde rojo del polígono (resto de planos)
        # Las referencias se resuelven desde el registro del proyecto para
        # evitar TypeError con QgsRasterLayer en setLayers() (fix v7).
        def _ref(capa):
            return project.mapLayer(capa.id()) if capa else None

        usar_punto = cfg_capa.get("marcador", "poligono") == "punto"
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

        # ── 5k. Barra de escala en METROS ────────────────────────────────────
        reenlazar_barra_escala(nueva_comp, map_item, log)

        # ── 5l. v5 — Grid configurable por capa ──────────────────────────────
        configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 500), log)

        # ── 5m. Leyenda y textos del cuadro de datos ─────────────────────────
        actualizar_leyenda(nueva_comp, ids, capa_recortada, poly_layer)

        set_label_text(nueva_comp, ids["lbl_proyecto"], cfg["nombre_proyecto"])
        set_label_text(nueva_comp, ids["lbl_licencia"], cfg["tipo_tramite"])
        set_label_text(nueva_comp, ids["lbl_plano"],    cfg_capa["nombre_plano"])
        set_label_text(
            nueva_comp, ids["lbl_escala"],
            f"Escala 1:{cfg_capa['escala']:,}".replace(",", " ")
        )
        set_label_text(nueva_comp, ids["lbl_fecha"],    f"Fecha: {cfg['mes_año']}")
        set_label_text(nueva_comp, ids.get("lbl_fuente",   ""), cfg_capa.get("fuente",    ""))
        set_label_text(nueva_comp, ids.get("lbl_coordsys", ""), cfg.get("coordenadas",    ""))

        # ── 5n. v5 — Logo corporativo ─────────────────────────────────────────
        fijar_logo(nueva_comp, ids.get("logo", ""), cfg.get("logo_ruta", ""), log)

        nueva_comp.refresh()

        # ── 5o. Exportar a PNG ───────────────────────────────────────────────
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
            log.info(f"   ✓ PNG exportado: {os.path.basename(ruta_png)}")
        else:
            log.error(f"   ✗ Falló exportación (código {res_img}): {ruta_png}")

    log.info(f"\n{'=' * 65}")
    log.info("✓ PROCESO TERMINADO — Revisa tu panel de Diseños en QGIS")
    log.info(f"  Ruta de imágenes: {output_dir}")
    log.info("=" * 65)


# Ejecutar proceso
generar_composiciones(CONFIG)