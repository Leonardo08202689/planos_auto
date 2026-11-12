"""
core/estilo_moderno.py — Acabado visual "moderno" de planos y figuras.

Se aplica sobre una composición ya armada (mapa, leyenda, etiquetas), justo
antes de exportarla. No cambia QUÉ datos se muestran, solo CÓMO se ven:

  Mapa
    · Proyección métrica (UTM) conservando centro y escala.
    · Satélite atenuado (copia de la capa, el original no se toca).
    · Relieve sombreado del CEM (opcional, solo a escala de detalle).
    · Capas temáticas más transparentes con borde blanco; etiquetas con halo
      en lugar de recuadro.
    · Polígono del proyecto en rojo con relleno suave.
    · Figuras estatales: todo lo que no es el estado queda velado en blanco,
      contorno del estado en negro y se resalta la unidad que contiene al
      proyecto (o la más cercana, con la distancia en la leyenda).

  Composición (según la plantilla, detectada por la forma de la página)
    · Plantilla_Corporativa (tabloide horizontal): panel lateral en un solo
      recuadro, con separadores finos, 2 mapitas, simbología alineada a la
      izquierda, bloque técnico y cuadro de título con jerarquía.
    · Figura horizontal (Plantilla_figuras): misma idea, panel angosto.
    · Figura vertical (Plantilla_Figurasv2): simbología a dos columnas en una
      franja y pie de tres columnas (logo | título | proyección y fecha).

Se activa con "estilo_moderno": {"activo": true, ...} en config/global.json.
Cualquier error se registra como advertencia y el plano se exporta igual con
el estilo de la plantilla: este módulo nunca debe tumbar una corrida.
"""

import math
import os
import re
import traceback

from qgis.PyQt.QtCore import QPointF, QSizeF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPolygonF

from qgis.core import (
    Qgis,
    QgsBilinearRasterResampler,
    QgsContrastEnhancement,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsInvertedPolygonRenderer,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemPicture,
    QgsLayoutItemPolyline,
    QgsLayoutItemScaleBar,
    QgsLayoutItemShape,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendRenderer,
    QgsLegendStyle,
    QgsLineSymbol,
    QgsMapLayerLegendUtils,
    QgsMapLayerType,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsFeatureRequest,
    QgsProperty,
    QgsSimpleLineSymbolLayer,
    QgsRasterLayer,
    QgsRectangle,
    QgsRuleBasedLabeling,
    QgsRuleBasedRenderer,
    QgsScaleBarSettings,
    QgsSingleBandGrayRenderer,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)

MM = QgsUnitTypes.LayoutMillimeters

DEFAULTS = {
    "activo": True,
    "crs_mapa": "EPSG:32612",
    "fuente_texto": "Ubuntu Sans",
    "color_acento": "#08306b",
    "opacidad_tematica": 0.5,
    # Relieve sombreado: ruta local al CEM (GeoTIFF). Si está vacía se lee
    # el CEM de la base ('cem_postgis', esquema.tabla); ambos vacíos = sin relieve.
    "cem_ruta": "",
    "cem_postgis": "cartografia_base.cem_sonora_15m",
    "relieve_escala_max": 100000,
    "relieve_exageracion": 2.0,
    "relieve_opacidad": 0.38,
    # Escala a partir de la cual una figura se trata como "estatal".
    "escala_figura_estatal": 500000,
    "fuente_cem": "Relieve sombreado: Continuo de Elevaciones Mexicano (CEM) 15 m, INEGI.",
}

_NICE_KM = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _opciones(cfg: dict) -> dict:
    em = cfg.get("estilo_moderno")
    if em is True:
        em = {}
    if not isinstance(em, dict):
        return {}
    opts = dict(DEFAULTS)
    opts.update(em)
    return opts if opts.get("activo", True) else {}


def _fmt(opts, tam, negrita=False, color="#1f1f1f", espaciado=0.0, halo=False):
    f = QgsTextFormat()
    fuente = QFont(opts["fuente_texto"])
    fuente.setBold(negrita)
    if espaciado:
        fuente.setLetterSpacing(QFont.AbsoluteSpacing, espaciado)
    f.setFont(fuente)
    f.setSize(tam)
    f.setSizeUnit(QgsUnitTypes.RenderPoints)
    f.setColor(QColor(color))
    if halo:
        b = QgsTextBufferSettings()
        b.setEnabled(True)
        b.setSize(0.9)
        b.setColor(QColor(255, 255, 255, 225))
        f.setBuffer(b)
    return f


def _km_unit():
    try:
        return Qgis.DistanceUnit.Kilometers
    except AttributeError:  # QGIS < 3.30
        return QgsUnitTypes.DistanceKilometers


def _prop(nombre):
    """QgsPalLayerSettings.Property.<nombre> en QGIS nuevos, o el enum viejo."""
    try:
        return getattr(QgsPalLayerSettings.Property, nombre)
    except AttributeError:
        return getattr(QgsPalLayerSettings, nombre)


def _placement_horizontal():
    try:
        return Qgis.LabelPlacement.Horizontal
    except AttributeError:
        return QgsPalLayerSettings.Horizontal


def _multilinea_centro():
    try:
        return Qgis.LabelMultiLineAlignment.Center
    except AttributeError:
        return QgsPalLayerSettings.MultiCenter


def _mover(item, x, y, w=None, h=None):
    item.setLocked(False)
    item.attemptMove(QgsLayoutPoint(x, y, MM), useReferencePoint=False)
    if w is not None:
        item.attemptResize(QgsLayoutSize(w, h, MM))


def _etiqueta(comp, opts, id_, texto, x, y, w, h, fmt,
              ha=Qt.AlignHCenter, va=Qt.AlignVCenter, item=None, z=10):
    if item is None:
        item = QgsLayoutItemLabel(comp)
        comp.addLayoutItem(item)
    item.setId(id_)
    item.setText(texto)
    item.setTextFormat(fmt)
    item.setHAlign(ha)
    item.setVAlign(va)
    item.setFrameEnabled(False)
    item.setBackgroundEnabled(False)
    item.setMarginX(0)
    item.setMarginY(0)
    _mover(item, x, y, w, h)
    item.setZValue(z)
    return item


def _linea(comp, id_, puntos, color="200,200,200", ancho="0.2", z=10):
    pl = QgsLayoutItemPolyline(QPolygonF([QPointF(*p) for p in puntos]), comp)
    pl.setId(id_)
    pl.setSymbol(QgsLineSymbol.createSimple({"color": color, "width": ancho}))
    comp.addLayoutItem(pl)
    pl.setZValue(z)
    return pl


def _rect(comp, id_, x, y, w, h, relleno="255,255,255,255", z=1):
    s = QgsLayoutItemShape(comp)
    s.setShapeType(QgsLayoutItemShape.Rectangle)
    s.setId(id_)
    s.setSymbol(QgsFillSymbol.createSimple({
        "color": relleno, "outline_color": "0,0,0,255", "outline_width": "0.3",
    }))
    comp.addLayoutItem(s)
    _mover(s, x, y, w, h)
    s.setZValue(z)
    return s


def _quitar(comp, item):
    if item is not None:
        comp.removeLayoutItem(item)


def _sin_prefijo(titulo: str):
    """'PLANO. TIPOS DE CLIMA' → ('PLANO', 'TIPOS DE CLIMA')."""
    t = (titulo or "").strip()
    for pref in ("PLANO.", "FIGURA."):
        if t.upper().startswith(pref):
            return pref[:-1], t[len(pref):].strip()
    return "", t


_MINUSCULAS = {"y", "e", "de", "del", "la", "las", "el", "los", "en", "a", "o"}
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def _titulo_es(texto: str) -> str:
    """'SIERRAS Y LLANURAS DEL NORTE' → 'Sierras y Llanuras del Norte'."""
    palabras = str(texto).lower().split(" ")
    return " ".join(
        p if (i and p in _MINUSCULAS) else p[:1].upper() + p[1:]
        for i, p in enumerate(palabras)
    )


def _fecha(cfg) -> str:
    if cfg.get("fecha_plano"):
        return cfg["fecha_plano"]
    from datetime import datetime
    hoy = datetime.now()
    return f"{_MESES[hoy.month - 1]} {hoy.year}"


def _rule_single(capa, etiqueta):
    """Pasa un renderer de símbolo único a uno por reglas con 1 regla, para
    que la leyenda use el mismo tipo de nodo que las demás capas y las filas
    queden alineadas entre columnas."""
    r = capa.renderer()
    if r is None or r.type() != "singleSymbol":
        return
    raiz = QgsRuleBasedRenderer.Rule(None)
    raiz.appendChild(QgsRuleBasedRenderer.Rule(r.symbol().clone(), 0, 0, "", etiqueta))
    capa.setRenderer(QgsRuleBasedRenderer(raiz))


def _escala_km(escala, mm_por_segmento=12.5):
    objetivo = escala * mm_por_segmento / 1e6
    return min(_NICE_KM, key=lambda v: abs(math.log(v / objetivo)))


def _capa_cacheada(project, nombre, fabrica):
    existentes = project.mapLayersByName(nombre)
    if existentes:
        return existentes[0]
    capa = fabrica()
    if capa is not None:
        capa.setName(nombre)
        project.addMapLayer(capa, False)
    return capa


# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------

def _satelite(project, base, variante):
    """Copia atenuada del satélite. 'detalle' conserva color; 'estatal' casi
    gris y muy claro para que dominen los temas."""
    ajustes = {
        "detalle": (-10, 12, 5),
        "estatal": (-75, 55, -30),
    }[variante]

    def fabrica():
        c = base.clone()
        sat, bri, con = ajustes
        c.hueSaturationFilter().setSaturation(sat)
        c.brightnessFilter().setBrightness(bri)
        c.brightnessFilter().setContrast(con)
        return c

    return _capa_cacheada(project, f"[estilo] Satélite {variante}", fabrica)


def _cem_postgis(opts):
    """Cadena GDAL 'PG:' al CEM guardado en PostGIS (mode=2: la tabla de
    teselas se lee como un solo ráster)."""
    tabla = opts.get("cem_postgis")
    pg = opts.get("_pg") or {}
    if not tabla or "." not in tabla or not pg.get("host"):
        return None
    esquema, nombre = tabla.split(".", 1)
    partes = [f"host={pg['host']}", f"port={pg.get('port', 5432)}",
              f"dbname={pg.get('dbname', '')}", f"user={pg.get('user', '')}"]
    if pg.get("password"):
        partes.append(f"password={pg['password']}")
    partes += [f"schema={esquema}", f"table={nombre}", "column=rast", "mode=2"]
    return "PG:" + " ".join(partes)


def _relieve(project, map_item, opts, ctx, nombre, log):
    """Recorta el CEM al encuadre (con margen), lo pasa al CRS del mapa y
    calcula un hillshade multidireccional. Devuelve la capa o None."""
    ruta = opts.get("cem_ruta")
    if ruta and not os.path.exists(ruta):
        log.warning(f" → CEM no encontrado ({ruta}); se usa el de la base.")
        ruta = None
    if not ruta:
        ruta = _cem_postgis(opts)
    if not ruta:
        return None
    import processing  # noqa: import tardío (solo dentro de QGIS)

    carpeta = os.path.join(ctx["output_dir"], "_relieve")
    os.makedirs(carpeta, exist_ok=True)
    e = QgsRectangle(map_item.extent())
    e.grow(max(e.width(), e.height()) * 0.08)
    crs = map_item.crs().authid()
    ext = f"{e.xMinimum()},{e.xMaximum()},{e.yMinimum()},{e.yMaximum()} [{crs}]"
    dem = os.path.join(carpeta, f"cem_{nombre}.tif")
    hs = os.path.join(carpeta, f"relieve_{nombre}.tif")
    try:
        processing.run("gdal:warpreproject", {
            "INPUT": ruta, "SOURCE_CRS": None, "TARGET_CRS": crs, "RESAMPLING": 1,
            "TARGET_RESOLUTION": 15, "TARGET_EXTENT": ext, "TARGET_EXTENT_CRS": crs,
            "DATA_TYPE": 0, "OUTPUT": dem,
        })
        processing.run("gdal:hillshade", {
            "INPUT": dem, "BAND": 1, "Z_FACTOR": float(opts["relieve_exageracion"]),
            "SCALE": 1, "AZIMUTH": 315, "ALTITUDE": 40, "MULTIDIRECTIONAL": True,
            "COMBINED": False, "COMPUTE_EDGES": True, "OUTPUT": hs,
        })
    except Exception as exc:  # GDAL ausente, CEM corrupto, etc.
        log.warning(f" → No se pudo calcular el relieve: {exc}")
        return None

    capa = QgsRasterLayer(hs, "Relieve sombreado")
    if not capa.isValid():
        return None
    ren = QgsSingleBandGrayRenderer(capa.dataProvider(), 1)
    ce = QgsContrastEnhancement(capa.dataProvider().dataType(1))
    ce.setMinimumValue(60)
    ce.setMaximumValue(230)
    ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
    ren.setContrastEnhancement(ce)
    ren.setOpacity(float(opts["relieve_opacidad"]))
    capa.setRenderer(ren)
    capa.setBlendMode(QPainter.CompositionMode_Multiply)
    capa.resampleFilter().setZoomedInResampler(QgsBilinearRasterResampler())
    project.addMapLayer(capa, False)
    if ctx.get("grupo_plano") is not None:
        ctx["grupo_plano"].addLayer(capa)
    return capa


def _poligono_proyecto(project, ctx):
    """Capa en memoria solo con el polígono seleccionado, en rojo con relleno
    suave (la capa del usuario no se modifica)."""
    def fabrica():
        crs = ctx["crs_origen"].authid()
        c = QgsVectorLayer(f"MultiPolygon?crs={crs}", "x", "memory")
        f = QgsFeature()
        f.setGeometry(QgsGeometry(ctx["geom_poligono"]))
        c.dataProvider().addFeatures([f])
        c.updateExtents()
        sym = QgsFillSymbol.createSimple({
            "color": "220,30,30,40", "outline_color": "200,0,0,255", "outline_width": "0.6",
        })
        c.setRenderer(QgsSingleSymbolRenderer(sym))
        _rule_single(c, "Área del proyecto")
        return c

    return _capa_cacheada(project, "[estilo] Área del proyecto", fabrica)


def _estrella_proyecto(project, ctx):
    def fabrica():
        crs = ctx["crs_origen"].authid()
        c = QgsVectorLayer(f"Point?crs={crs}", "x", "memory")
        f = QgsFeature()
        f.setGeometry(QgsGeometry(ctx["geom_poligono"]).centroid())
        c.dataProvider().addFeatures([f])
        c.updateExtents()
        c.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
            "name": "star", "color": "220,0,0,255", "outline_color": "255,255,255,255",
            "outline_width": "0.5", "size": "5.5",
        })))
        _rule_single(c, "Área del proyecto")
        return c

    return _capa_cacheada(project, "[estilo] Punto del proyecto", fabrica)


def _estado(project, ctx):
    """(máscara fuera del estado, contorno del estado) a partir de la capa de
    referencia del estado que ya cargaron los mapitas."""
    ref = (ctx.get("capas_ref") or {}).get("capas_nacional") or []
    if not ref:
        return None, None
    estado = ref[0]  # ref_estado_hl
    nombre = (ctx.get("capas_ref") or {}).get("nomgeo_estado", "") or "estatal"

    def mascara():
        c = estado.clone()
        c.setRenderer(QgsInvertedPolygonRenderer(QgsSingleSymbolRenderer(
            QgsFillSymbol.createSimple({"color": "255,255,255,175", "outline_style": "no"})
        )))
        return c

    def contorno():
        c = estado.clone()
        c.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({
            "color": "0,0,0,0", "outline_color": "40,40,40,255", "outline_width": "0.6",
        })))
        _rule_single(c, f"Límite estatal de {nombre.title()}")
        return c

    return (_capa_cacheada(project, "[estilo] Máscara fuera del estado", mascara),
            _capa_cacheada(project, "[estilo] Límite estatal", contorno))


_AGUA = re.compile(r"r[ií]o|arroyo|canal|corriente|cuerpo.*agua", re.I)
_ETIQUETA_AGUA = {
    "ríos y arroyos": "Ríos y arroyos intermitentes",
    "cuerpos de agua": "Cuerpos de agua",
    "ríos (cuerpo ancho)": "Ríos (cauce ancho)",
}
# Colores para unidades que se dibujan solo con contorno (subcuencas, etc.)
_PALETA_CONTORNO = ["8,81,156", "0,109,44", "122,1,119", "153,52,4",
                    "37,37,37", "0,90,50", "84,39,143", "140,45,4"]


def _estilo_agua(capa):
    """Ríos/arroyos en azul con halo blanco; cuerpos de agua azul claro."""
    nombre = capa.name()
    etiqueta = _ETIQUETA_AGUA.get(nombre.strip().lower(), nombre)
    if capa.geometryType() == QgsWkbTypes.LineGeometry:
        sym = QgsLineSymbol.createSimple({"line_color": "255,255,255,150", "line_width": "0.6"})
        sym.appendSymbolLayer(QgsSimpleLineSymbolLayer(QColor(0, 120, 215), 0.32))
    else:
        sym = QgsFillSymbol.createSimple({
            "color": "100,170,230,200", "outline_color": "31,120,180,255", "outline_width": "0.2",
        })
    capa.setRenderer(QgsSingleSymbolRenderer(sym))
    capa.setOpacity(1.0)
    _rule_single(capa, etiqueta)
    capa.setCustomProperty("estilo/grupo_leyenda", "HIDROGRAFÍA")
    capa.triggerRepaint()


def _unidades_contorno(capa, campo, cfg_capa, opts):
    """Unidades (p. ej. subcuencas) con contorno punteado de color propio,
    relleno muy tenue y etiqueta 'Subcuenca\nNombre' del mismo color."""
    r = capa.renderer()
    valores = [cat.value() for cat in r.categories()] if r.type() == "categorizedSymbol" else []
    if not valores or not campo or campo not in capa.fields().names():
        return False
    raiz = QgsRuleBasedRenderer.Rule(None)
    casos = []
    for i, v in enumerate(valores):
        if v in (None, ""):
            continue
        color = _PALETA_CONTORNO[i % len(_PALETA_CONTORNO)]
        v_sql = str(v).replace("'", "''")
        raiz.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple({
            "color": color + ",55", "outline_color": color + ",255",
            "outline_width": "0.8", "outline_style": "dash",
        }), 0, 0, f"\"{campo}\" = '{v_sql}'", str(v)))
        casos.append(f"WHEN \"{campo}\" = '{v_sql}' THEN '{color}'")
    capa.setRenderer(QgsRuleBasedRenderer(raiz))
    capa.setOpacity(float(opts["opacidad_tematica"]) + 0.05)

    prefijo = cfg_capa.get("prefijo_etiqueta")
    if prefijo is None:
        prefijo = "Subcuenca" if "subcuenca" in campo.lower() else ""
    ls = QgsPalLayerSettings()
    ls.isExpression = True
    ls.fieldName = (f"'{prefijo}' || '\\n' || \"{campo}\"" if prefijo else f'"{campo}"')
    ls.setFormat(_fmt(opts, 9.0, True, opts["color_acento"], halo=True))
    ls.placement = _placement_horizontal()
    ls.multilineAlign = _multilinea_centro()
    dd = ls.dataDefinedProperties()
    if casos:
        dd.setProperty(_prop("Color"), QgsProperty.fromExpression(
            "CASE " + " ".join(casos) + " END"))
    dd.setProperty(_prop("Show"), QgsProperty.fromExpression(
        f'$area = maximum($area, group_by:="{campo}")'))
    ls.setDataDefinedProperties(dd)
    capa.setLabeling(QgsVectorLayerSimpleLabeling(ls))
    capa.setLabelsEnabled(True)

    titulo = cfg_capa.get("titulo_leyenda")
    if not titulo:
        titulo = ("Subcuencas hidrológicas" if "subcuenca" in campo.lower()
                  else cfg_capa.get("nombre_leyenda_categoria") or capa.name())
    capa.setCustomProperty("estilo/titulo_leyenda", titulo.upper())
    capa.setCustomProperty("estilo/subgrupo", True)
    capa.triggerRepaint()
    return True


def _hay_en_mapa(capa, map_item, project):
    """¿La capa tiene algo dentro del encuadre? (para no listar en la
    leyenda capas vacías, p. ej. canales que no pasan por el sitio)."""
    try:
        tr = QgsCoordinateTransform(map_item.crs(), capa.crs(), project)
        rect = tr.transformBoundingBox(map_item.extent())
        req = QgsFeatureRequest().setFilterRect(rect).setLimit(1).setNoAttributes()
        return any(True for _ in capa.getFeatures(req))
    except Exception:
        return True


def _etiquetas_halo(capa, opts, tam=8.0):
    if not capa.labelsEnabled() or capa.labeling() is None:
        return
    try:
        ls = capa.labeling().settings()
    except Exception:
        return
    ls.setFormat(_fmt(opts, tam, True, halo=True))
    capa.setLabeling(QgsVectorLayerSimpleLabeling(ls))
    capa.triggerRepaint()


def _resaltar_unidad(capa, campo, ctx, opts, color, otras, log):
    """Regla 1: la unidad que contiene al proyecto o la más cercana (con su
    distancia); regla 2: las demás, solo contorno punteado."""
    if not campo or campo not in capa.fields().names():
        return None
    centro = QgsGeometry(ctx["geom_poligono"]).centroid()
    tr = QgsCoordinateTransform(ctx["crs_origen"], capa.crs(), ctx["project"])
    centro.transform(tr)
    da = QgsDistanceArea()
    da.setSourceCrs(capa.crs(), ctx["project"].transformContext())
    da.setEllipsoid("WGS84")
    mejor = None
    for f in capa.getFeatures():
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        if g.contains(centro):
            mejor = (f[campo], 0.0)
            break
        cerca = g.nearestPoint(centro)
        d = da.measureLine(centro.asPoint(), cerca.asPoint()) / 1000.0
        if mejor is None or d < mejor[1]:
            mejor = (f[campo], d)
    if mejor is None:
        return None
    valor, dist = mejor
    nombre = str(valor)
    if nombre.isupper():
        nombre = _titulo_es(nombre)
    etiqueta = (f"{nombre} (contiene al proyecto)" if dist == 0
                else f"{nombre} (a ≈{dist:.0f} km del proyecto)")
    raiz = QgsRuleBasedRenderer.Rule(None)
    valor_sql = str(valor).replace("'", "''")
    raiz.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple({
        "color": color + ",150", "outline_color": color + ",255", "outline_width": "0.5",
    }), 0, 0, f"\"{campo}\" = '{valor_sql}'", etiqueta))
    raiz.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple({
        "color": "255,255,255,0", "outline_color": "60,60,60,255",
        "outline_width": "0.3", "outline_style": "dash",
    }), 0, 0, "ELSE", otras))
    capa.setRenderer(QgsRuleBasedRenderer(raiz))
    capa.setOpacity(1.0)

    # Etiqueta: una por unidad (la parte más grande), con halo.
    ls = QgsPalLayerSettings()
    ls.isExpression = True
    ls.fieldName = f'wordwrap("{campo}", 24)'
    ls.setFormat(_fmt(opts, 6.5, True, "#2b2b2b", halo=True))
    ls.placement = _placement_horizontal()
    ls.multilineAlign = _multilinea_centro()
    dd = ls.dataDefinedProperties()
    dd.setProperty(_prop("Show"), QgsProperty.fromExpression(
        f'$area = maximum($area, group_by:="{campo}")'))
    ls.setDataDefinedProperties(dd)
    capa.setLabeling(QgsVectorLayerSimpleLabeling(ls))
    capa.setLabelsEnabled(True)
    capa.triggerRepaint()
    log.debug(f" ✓ Unidad resaltada: {etiqueta}")
    return etiqueta


_ESCALAS = [1000, 1500, 2000, 2500, 3000, 4000, 5000, 7500, 10000, 15000, 20000,
            25000, 30000, 40000, 50000, 75000, 100000, 150000, 200000, 250000, 500000]


def _asegurar_proyecto_visible(map_item, ctx, project, log, margen=0.08):
    """Que el polígono completo quepa en el mapa: centra en él y, si aun así
    no cabe, sube a la siguiente escala redonda."""
    g = ctx.get("geom_poligono")
    if g is None:
        return
    try:
        tr = QgsCoordinateTransform(ctx["crs_origen"], map_item.crs(), project)
        bb = tr.transformBoundingBox(QgsGeometry(g).boundingBox())
    except Exception:
        return
    bb.grow(max(bb.width(), bb.height()) * margen)
    ext = map_item.extent()
    if ext.contains(bb):
        return
    escala = map_item.scale()
    ancho, alto = ext.width() / escala, ext.height() / escala  # metros de terreno por unidad de escala
    nueva = next((e for e in _ESCALAS if e >= escala
                  and ancho * e >= bb.width() and alto * e >= bb.height()), None)
    if nueva is None:
        nueva = max(bb.width() / ancho, bb.height() / alto) * 1.05
    c = bb.center()
    map_item.zoomToExtent(QgsRectangle(c.x() - 1, c.y() - 1, c.x() + 1, c.y() + 1))
    map_item.setScale(nueva)
    if round(nueva) != round(escala):
        log.debug(f" → Escala ajustada a 1:{nueva:,.0f} para que quepa todo el proyecto.")


def _encuadrar_estado(map_item, contorno, project, margen=0.04):
    try:
        tr = QgsCoordinateTransform(contorno.crs(), map_item.crs(), project)
        e = tr.transformBoundingBox(contorno.extent())
    except Exception:
        return
    if e.isEmpty():
        return
    e.grow(max(e.width(), e.height()) * margen)
    map_item.zoomToExtent(e)


def _unificar_fuente(labeling, familia):
    """Cambia la familia de letra de un etiquetado (simple o por reglas)
    conservando tamaño, color, negrita y halo."""
    def _uno(ls):
        fmt = ls.format()
        f = fmt.font()
        f.setFamily(familia)
        fmt.setFont(f)
        ls.setFormat(fmt)
        return ls
    try:
        if isinstance(labeling, QgsVectorLayerSimpleLabeling):
            labeling.setSettings(_uno(QgsPalLayerSettings(labeling.settings())))
        elif isinstance(labeling, QgsRuleBasedLabeling):
            for regla in labeling.rootRule().descendants():
                if regla.settings() is not None:
                    regla.setSettings(_uno(QgsPalLayerSettings(regla.settings())))
    except Exception:
        pass


def _estilizar_mapa(comp, map_item, cfg_capa, opts, ctx, log):
    """Devuelve dict con lo que el panel necesita saber (capas para la
    leyenda, si es estatal, si hubo relieve)."""
    project = ctx["project"]
    info = {"estatal": False, "relieve": False, "capas_leyenda": [], "tematica": None}

    # 1. CRS métrico conservando centro y escala
    crs = QgsCoordinateReferenceSystem(opts["crs_mapa"])
    if crs.isValid() and map_item.crs() != crs:
        escala = map_item.scale()
        centro = QgsCoordinateTransform(map_item.crs(), crs, project).transform(
            map_item.extent().center())
        size, pos = map_item.sizeWithUnits(), map_item.positionWithUnits()
        map_item.setCrs(crs)
        map_item.zoomToExtent(QgsRectangle(centro.x() - 1, centro.y() - 1,
                                           centro.x() + 1, centro.y() + 1))
        map_item.setScale(escala)
        map_item.attemptResize(size)
        map_item.attemptMove(pos)

    escala = map_item.scale()
    estatal = escala >= float(opts["escala_figura_estatal"]) or cfg_capa.get("figura_estatal")
    info["estatal"] = bool(estatal)
    if not estatal:
        _asegurar_proyecto_visible(map_item, ctx, project, log)
        escala = map_item.scale()

    capas = list(map_item.layers())
    base = next((c for c in capas if c.name() == "Google Satellite"), None)
    poli = ctx.get("poly_layer")
    punto = ctx.get("punto_layer")

    # 2. Capas temáticas y etiquetas
    tematicas = []
    referencia_estado = []
    for c in capas:
        if c.type() != QgsMapLayerType.VectorLayer:
            continue
        if c.name().startswith("centroides_"):
            _etiquetas_halo(c, opts)
            continue
        if c in (poli, punto):
            continue
        if c.geometryType() == QgsWkbTypes.PolygonGeometry:
            r = c.renderer()
            if (r is not None and r.type() == "categorizedSymbol"
                    and cfg_capa.get("solo_contorno") and not estatal):
                campo = cfg_capa.get("campo_categoria")
                if _unidades_contorno(c, campo, cfg_capa, opts):
                    info["etiquetas_propias"] = True
                    continue
            if _AGUA.search(c.name()) and not (r is not None and r.type() == "categorizedSymbol"):
                _estilo_agua(c)
                continue
            if r is not None and r.type() == "categorizedSymbol":
                tematicas.append(c)
                contorno = cfg_capa.get("solo_contorno")
                c.setOpacity(1.0 if contorno else float(opts["opacidad_tematica"]))
                for i, cat in enumerate(r.categories()):
                    if contorno:
                        # Símbolo nuevo (los QML pueden traer varias capas de
                        # símbolo): relleno casi transparente y borde punteado.
                        base_c = QColor(cat.symbol().color())
                        borde = base_c.darker(170)
                        r.updateCategorySymbol(i, QgsFillSymbol.createSimple({
                            "color": f"{base_c.red()},{base_c.green()},{base_c.blue()},45",
                            "outline_color": f"{borde.red()},{borde.green()},{borde.blue()},255",
                            "outline_width": "0.7", "outline_style": "dash",
                        }))
                        continue
                    sl = cat.symbol().symbolLayer(0)
                    if not hasattr(sl, "setStrokeColor"):
                        continue
                    else:
                        sl.setStrokeColor(QColor(255, 255, 255, 200))
                        sl.setStrokeWidth(0.35)
            elif (r is not None and r.type() == "singleSymbol"
                  and c.name().lower().startswith("estado")):
                # Contorno estatal de la plantilla: en figuras estatales lo
                # sustituye el contorno + máscara del estilo.
                referencia_estado.append(c)
            _etiquetas_halo(c, opts)
        elif _AGUA.search(c.name()):
            _estilo_agua(c)
        else:
            _etiquetas_halo(c, opts, 7.5)
    info["tematica"] = tematicas[0] if len(tematicas) == 1 else None
    if estatal:
        capas = [c for c in capas if c not in referencia_estado]
    if info.get("etiquetas_propias"):
        # Las unidades ya se etiquetan solas: los centroides duplicarían el nombre
        capas = [c for c in capas if not c.name().startswith("centroides_")]

    # 3. Marcador del proyecto
    nuevo = []
    for c in capas:
        if c is poli:
            nuevo.append(_estrella_proyecto(project, ctx) if estatal else _poligono_proyecto(project, ctx))
        elif c is punto:
            # En planos de detalle el polígono se ve; la estrella solo en estatales
            nuevo.append(_estrella_proyecto(project, ctx) if estatal
                         else _poligono_proyecto(project, ctx))
        else:
            nuevo.append(c)
    capas = nuevo

    # 4. Fondo
    if estatal:
        mascara, contorno = _estado(project, ctx)
        capas = [c for c in capas if c is not base]
        if base is None:
            base = ctx.get("basemap")  # figuras con 'sin_basemap'
        if base is not None:
            capas.append(_satelite(project, base, "estatal"))
        if mascara is not None:
            # marcador, contorno, máscara, temas, satélite
            capas = capas[:1] + [contorno, mascara] + capas[1:]
            info["contorno"] = contorno
            # Encuadre ajustado al estado (la escala de la config suele dejar
            # mucho margen blanco alrededor).
            if cfg_capa.get("centrar_en") or cfg_capa.get("recortar_a"):
                # Solo si los datos se cargaron para todo el estado; si no,
                # se verían cortados en el rectángulo de la consulta.
                _encuadrar_estado(map_item, contorno, project)
        if info["tematica"] is not None:
            campos = info["tematica"].fields().names()
            campo = next((c for c in ("nombre", "nom", "nom_uab", "name") if c in campos), None)
            if campo is None:
                campo = cfg_capa.get("campo_etiqueta") or cfg_capa.get("campo_categoria")
                if campo == "auto":
                    campo = cfg_capa.get("campo_categoria")
            info["resaltado"] = _resaltar_unidad(
                info["tematica"], campo, ctx, opts,
                cfg_capa.get("color_resaltado", "49,130,189"),
                "Otras unidades ({})".format(
                    cfg_capa.get("titulo_capa") or info["tematica"].name()),
                log)
            if info["resaltado"]:
                # La propia capa ya etiqueta cada unidad: los centroides sobran.
                capas = [c for c in capas if not c.name().startswith("centroides_")]
    elif base is not None:
        idx = capas.index(base)
        capas[idx] = _satelite(project, base, "detalle")
        if escala <= float(opts["relieve_escala_max"]) and not cfg_capa.get("sin_relieve"):
            hs = _relieve(project, map_item, opts, ctx, cfg_capa.get("nombre_capa", "plano"), log)
            if hs is not None:
                capas.insert(idx, hs)
                info["relieve"] = True

    map_item.setLayers(capas)
    map_item.setKeepLayerSet(True)

    # 5. Retícula discreta
    if map_item.grids().size():
        g = map_item.grids().grid(0)
        fa = g.annotationTextFormat()
        tabloide = comp.pageCollection().page(0).pageSize().width() > 400
        fa.setSize(5.5 if estatal else (7 if tabloide else 6))
        fa.setFont(QFont(opts["fuente_texto"]))
        fa.setColor(QColor("#444444"))
        g.setAnnotationTextFormat(fa)
        g.setLineSymbol(QgsLineSymbol.createSimple({"color": "255,255,255,120", "width": "0.15"}))
        if estatal:
            g.setIntervalX(100000)
            g.setIntervalY(100000)

    # 6. Flecha del norte en negro
    for it in comp.items():
        if isinstance(it, QgsLayoutItemPicture) and any(
                s in f"{it.id()} {it.picturePath()}".lower() for s in ("norte", "north", "arrow")):
            it.setSvgFillColor(QColor("black"))
            it.setSvgStrokeColor(QColor("black"))
            # Tamaño fijo y discreto, anclado a la esquina superior derecha del mapa
            lado = 14.0 if comp.pageCollection().page(0).pageSize().width() > 400 else 11.0
            mp, ms = map_item.positionWithUnits(), map_item.sizeWithUnits()
            it.setResizeMode(QgsLayoutItemPicture.Zoom)
            _mover(it, mp.x() + ms.width() - lado - 5, mp.y() + 5, lado, lado)

    # 7. Una sola familia tipográfica en todas las etiquetas del mapa
    for c in capas:
        if isinstance(c, QgsVectorLayer) and c.labelsEnabled() and c.labeling() is not None:
            _unificar_fuente(c.labeling(), opts["fuente_texto"])
            c.triggerRepaint()

    map_item.invalidateCache()
    map_item.refresh()
    info["capas_leyenda"] = [c for c in capas
                             if c.type() == QgsMapLayerType.VectorLayer
                             and not c.name().startswith("centroides_")
                             and not c.name().startswith("[estilo] Máscara")
                             and (not c.customProperty("estilo/grupo_leyenda")
                                  or _hay_en_mapa(c, map_item, project))]
    return info


# ---------------------------------------------------------------------------
# Leyendas
# ---------------------------------------------------------------------------

def _estilo_leyenda(leyenda, opts, capas, titulo=None, tam=8.0, grande=False):
    leyenda.setAutoUpdateModel(False)
    raiz = leyenda.model().rootGroup()
    raiz.clear()
    # Primero las capas sueltas, luego los grupos (p. ej. HIDROGRAFÍA)
    sueltas = [c for c in capas if not c.customProperty("estilo/grupo_leyenda")]
    agrupadas = [c for c in capas if c.customProperty("estilo/grupo_leyenda")]
    grupos = {}
    for c in sueltas + agrupadas:
        _rule_single(c, c.name().replace("[estilo] ", ""))
        nombre_grupo = c.customProperty("estilo/grupo_leyenda")
        if nombre_grupo:
            if nombre_grupo not in grupos:
                grupos[nombre_grupo] = raiz.addGroup(nombre_grupo)
                QgsLegendRenderer.setNodeLegendStyle(grupos[nombre_grupo], QgsLegendStyle.Group)
            nodo = grupos[nombre_grupo].addLayer(c)
            QgsLegendRenderer.setNodeLegendStyle(nodo, QgsLegendStyle.Hidden)
            continue
        nodo = raiz.addLayer(c)
        cat = c.renderer() is not None and c.renderer().type() == "categorizedSymbol"
        sub = cat or bool(c.customProperty("estilo/subgrupo"))
        if c.customProperty("estilo/titulo_leyenda"):
            nodo.setName(c.customProperty("estilo/titulo_leyenda"))
        QgsLegendRenderer.setNodeLegendStyle(
            nodo, QgsLegendStyle.Subgroup if sub else QgsLegendStyle.Hidden)
    leyenda.setTitle(titulo or "")
    leyenda.setFrameEnabled(False)
    leyenda.setBackgroundEnabled(False)
    leyenda.setResizeToContents(False)
    leyenda.setColumnCount(1)
    leyenda.setWrapString("")
    estilos = [
        (QgsLegendStyle.Title, _fmt(opts, 13.5 if grande else 10.5, True, espaciado=0.8), 0, Qt.AlignHCenter),
        (QgsLegendStyle.Group, _fmt(opts, 9.5 if grande else 7.2, True, opts["color_acento"], 0.5), 3.5, Qt.AlignLeft),
        (QgsLegendStyle.Subgroup, _fmt(opts, 9.5 if grande else 7.2, True, opts["color_acento"], 0.5), 3.5, Qt.AlignLeft),
        (QgsLegendStyle.SymbolLabel, _fmt(opts, tam), 0, Qt.AlignLeft),
        (QgsLegendStyle.Symbol, None, 2.0, Qt.AlignLeft),
    ]
    for st, fmt, top, al in estilos:
        s = leyenda.style(st)
        if fmt is not None:
            s.setTextFormat(fmt)
        s.setMargin(QgsLegendStyle.Top, top)
        s.setAlignment(al)
        leyenda.setStyle(st, s)
    t = leyenda.style(QgsLegendStyle.Title)
    t.setMargin(QgsLegendStyle.Bottom, 3)
    leyenda.setStyle(QgsLegendStyle.Title, t)
    leyenda.setSymbolWidth(6.5)
    leyenda.setSymbolHeight(3.8)
    leyenda.setBoxSpace(0 if not titulo else 3)
    for nodo in raiz.findLayers():
        try:
            QgsMapLayerLegendUtils.setLegendNodeSymbolSize(nodo, 0, QSizeF(6.5, 3.8))
        except Exception:
            pass
        leyenda.model().refreshLayerLegend(nodo)
    leyenda.updateLegend()


# ---------------------------------------------------------------------------
# Barra de escala
# ---------------------------------------------------------------------------

def _barra(comp, map_item, opts, mm_seg=12.5, halo=False, item=None, tam=None):
    if item is None:
        item = next((i for i in comp.items() if isinstance(i, QgsLayoutItemScaleBar)), None)
    if item is None:
        item = QgsLayoutItemScaleBar(comp)
        comp.addLayoutItem(item)
    item.setLinkedMap(map_item)
    item.setStyle("Line Ticks Up" if halo else "Single Box")
    item.setUnits(_km_unit())
    item.setUnitLabel("km")
    item.setMapUnitsPerScaleBarUnit(1)
    item.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeFixed)
    item.setNumberOfSegments(2)
    item.setNumberOfSegmentsLeft(0)
    item.setUnitsPerSegment(_escala_km(map_item.scale(), mm_seg))
    try:
        from qgis.core import QgsBasicNumericFormat
        nf = QgsBasicNumericFormat()
        nf.setNumberDecimalPlaces(2)
        nf.setShowTrailingZeros(False)
        item.setNumericFormat(nf)
    except Exception:
        pass
    item.setTextFormat(_fmt(opts, tam or (6.5 if halo else 7), halo=halo))
    item.setHeight(1.6 if halo else 2.0)
    item.setBackgroundEnabled(False)
    item.setFrameEnabled(False)
    item.refreshItemSize()
    item.setZValue(12)
    return item


# ---------------------------------------------------------------------------
# Panel lateral (planos y figuras horizontales)
# ---------------------------------------------------------------------------

_IDS_EXTRA = ("marco_panel", "sep_loc", "sep1", "sep2", "sep3", "cap_nac", "cap_est",
              "lbl_plano_tag", "lbl_km", "marco_leyenda", "lbl_simbologia", "leyenda_b",
              "div1", "div2", "barra_escala_figura", "sep4", "cap_proy", "cap_esc",
              "cap_fec", "sep_ef")


def _limpiar_previos(comp):
    for it in list(comp.items()):
        if getattr(it, "id", None) and it.id() in _IDS_EXTRA:
            comp.removeLayoutItem(it)


def _panel_lateral(comp, ids, map_item, info, cfg, cfg_capa, opts, ctx, log):
    page = comp.pageCollection().page(0).pageSize()
    mp, ms = map_item.positionWithUnits(), map_item.sizeWithUnits()
    X = mp.x() + ms.width() + 0.2
    W = page.width() - mp.x() - X
    T, H = mp.y(), ms.height()
    R = X + W
    plano = page.width() > 400  # tabloide (Plantilla_Corporativa)

    _limpiar_previos(comp)
    # Etiquetas de los insertos viejos (estado/municipio/país, "Metros")
    for it in list(comp.items()):
        if isinstance(it, QgsLayoutItemLabel) and (
                it.id() in (ids.get("lbl_estado"), ids.get("lbl_municipio"))
                or it.text().strip().casefold() in ("republica mexicana", "república mexicana",
                                                     "metros", "kilómetros")):
            comp.removeLayoutItem(it)

    _rect(comp, "marco_panel", X, T, W, H)

    # Mapitas: nacional y estatal (con la estrella); el municipal sobra.
    mapitas = sorted([i for i in comp.items() if isinstance(i, QgsLayoutItemMap)
                      and i is not map_item], key=lambda m: (m.positionWithUnits().y(),
                                                             m.positionWithUnits().x()))
    ref = ctx.get("capas_ref") or {}
    estado = (ref.get("nomgeo_estado") or "").upper()
    muni = (ref.get("nomgeo_municipio") or "").upper()
    punto_ref = next((c for c in ref.get("capas_municipal", []) if c.name() == "ref_punto"), None)
    alto_loc = H * (0.175 if plano else 0.20)
    if len(mapitas) >= 2:
        nac, est = mapitas[0], mapitas[1]
        for extra in mapitas[2:]:
            comp.removeLayoutItem(extra)
        if punto_ref is not None and punto_ref not in est.layers():
            est.setLayers([punto_ref] + list(est.layers()))
        for m, x in ((nac, X), (est, X + W / 2)):
            ext = m.extent()
            _mover(m, x, T, W / 2, alto_loc)
            m.setFrameEnabled(False)
            m.zoomToExtent(ext)
            m.setZValue(5)
            m.refresh()
        _etiqueta(comp, opts, "cap_nac", "REPÚBLICA MEXICANA", X + 1, T + alto_loc - 6,
                  W / 2 - 2, 4.5, _fmt(opts, 6.5 if plano else 5.5, True, "#3a3a3a", 0.4), z=50)
        _etiqueta(comp, opts, "cap_est", f"{estado} · MPIO. {muni}".strip(" ·"),
                  X + W / 2 + 1, T + alto_loc - 6, W / 2 - 2, 4.5,
                  _fmt(opts, 6.5 if plano else 5.5, True, "#3a3a3a", 0.2), z=50)
        _linea(comp, "sep_loc", [(X + W / 2, T + 4), (X + W / 2, T + alto_loc - 4)], "215,215,215")
    elif mapitas:
        m = mapitas[0]
        if punto_ref is not None and punto_ref not in m.layers():
            m.setLayers([punto_ref] + list(m.layers()))
        ext = m.extent()
        _mover(m, X + 2, T + 2, W - 4, alto_loc - 8)
        m.setFrameEnabled(False)
        m.zoomToExtent(ext)
        m.setZValue(5)
        m.refresh()
        _etiqueta(comp, opts, "cap_est", f"{estado} · MPIO. {muni}".strip(" ·"),
                  X, T + alto_loc - 6, W, 4.5, _fmt(opts, 6.5 if plano else 5.5, True, "#3a3a3a", 0.3), z=50)

    y_sep1 = T + alto_loc + 1.5
    y_sep2 = T + H * (0.425 if plano else 0.52)
    y_sep3 = T + H * (0.60 if plano else 0.685)
    # Simbología
    leyenda = comp.itemById(ids.get("leyenda", "leyenda_principal"))
    if leyenda is not None:
        _estilo_leyenda(leyenda, opts, info["capas_leyenda"], "SIMBOLOGÍA",
                        10.5 if plano else 7.5, grande=plano)
        if plano:
            # El bloque de simbología mide lo que su contenido: sin huecos
            # cuando hay pocas categorías, con tope cuando hay muchas.
            leyenda.setResizeToContents(True)
            leyenda.updateLegend()
            leyenda.adjustBoxSize()
            alto_ley = leyenda.sizeWithUnits().height()
            leyenda.setResizeToContents(False)
            y_sep2 = min(max(y_sep1 + 1 + alto_ley + 5, T + H * 0.27), T + H * 0.52)
            y_sep3 = y_sep2 + H * 0.165
        _mover(leyenda, X, y_sep1 + 1, W, y_sep2 - y_sep1 - 2)
        leyenda.setZValue(10)
    for id_, y in (("sep1", y_sep1), ("sep2", y_sep2), ("sep3", y_sep3)):
        _linea(comp, id_, [(X + 6, y), (R - 6, y)])

    # Bloque técnico
    barra = _barra(comp, map_item, opts, 15 if plano else 12.5, tam=8 if plano else None)
    barra_w = barra.sizeWithUnits().width()
    _mover(barra, X + (W - barra_w) / 2, y_sep2 + 2.5)
    y = y_sep2 + 2.5 + barra.sizeWithUnits().height() + 1
    if plano:
        y -= 5.0  # la barra ya dice "km": sin rótulo "Kilómetros" aparte
    else:
        _etiqueta(comp, opts, "lbl_km", "Kilómetros", X, y, W, 4, _fmt(opts, 6.5, False, "#3a3a3a"))
    lbl_crs = comp.itemById(ids.get("lbl_coordsys", "lbl_coordsys"))
    zona = map_item.crs().description()
    _etiqueta(comp, opts, ids.get("lbl_coordsys", "lbl_coordsys"),
              "Coordenadas " + zona.replace("WGS 84 / ", "WGS 84 · ").replace("UTM zone", "UTM Zona"),
              X, y + 5.5, W, 5, _fmt(opts, 8.5 if plano else 6.3, True), item=lbl_crs)
    lbl_f = comp.itemById(ids.get("lbl_fuente", "lbl_fuente"))
    fuente = (cfg_capa.get("fuente") or "").strip()
    if info.get("relieve") and opts["fuente_cem"] not in fuente:
        fuente = f"{fuente} {opts['fuente_cem']}".strip()
    if fuente:
        _etiqueta(comp, opts, ids.get("lbl_fuente", "lbl_fuente"), "FUENTES: " + fuente,
                  X + 3, y + 12, W - 6, y_sep3 - (y + 12) - 1.5,
                  _fmt(opts, 7.5 if plano else 5.5, False, "#4a4a4a"),
                  ha=Qt.AlignJustify, va=Qt.AlignTop, item=lbl_f)
    elif lbl_f is not None:
        comp.removeLayoutItem(lbl_f)

    # Cuadro de título
    tag, titulo = _sin_prefijo(cfg_capa.get("nombre_plano", ""))
    alto_t = T + H - y_sep3
    if plano:
        _cuadro_titulo_plano(comp, ids, map_item, cfg, opts, X, W, R, y_sep3, alto_t, tag, titulo)
        return
    alto_t = T + H - y_sep3
    logo = comp.itemById(ids.get("logo", "logo_empresa"))
    if logo is not None:
        logo.setResizeMode(QgsLayoutItemPicture.Zoom)
        _mover(logo, X + 10, y_sep3 + alto_t * 0.08, W - 20, alto_t * 0.27)
        logo.setZValue(10)
    lic = comp.itemById(ids.get("lbl_licencia", "lbl_licencia"))
    _etiqueta(comp, opts, ids.get("lbl_licencia", "lbl_licencia"),
              (cfg.get("tipo_tramite") or "").upper(), X, y_sep3 + alto_t * 0.45, W, 5,
              _fmt(opts, 7.5 if plano else 6, True, "#6b6b6b", 0.8), item=lic)
    largo = len(titulo) > (24 if plano else 22)
    y_tag = y_sep3 + alto_t * (0.55 if largo else 0.57)
    _etiqueta(comp, opts, "lbl_plano_tag", tag, X, y_tag, W, 4,
              _fmt(opts, 8 if plano else 6.5, False, opts["color_acento"], 1.5))
    lbl_t = comp.itemById(ids.get("lbl_plano", "lbl_tipo_plano"))
    tam_t = (12 if largo else 13) if plano else (9.5 if largo else 11)
    _etiqueta(comp, opts, ids.get("lbl_plano", "lbl_tipo_plano"), titulo,
              X + 2, y_tag + 4.5, W - 4, alto_t * (0.20 if largo else 0.14),
              _fmt(opts, tam_t, True), item=lbl_t)
    lbl_p = comp.itemById(ids.get("lbl_proyecto", "lbl_proyecto"))
    nombre = (cfg.get("nombre_proyecto") or "").strip()
    _etiqueta(comp, opts, ids.get("lbl_proyecto", "lbl_proyecto"),
              f"Proyecto: {nombre}" if nombre else "", X + 2, y_sep3 + alto_t * 0.81,
              W - 4, alto_t * 0.12, _fmt(opts, 10 if plano else 6.5, False, "#4a4a4a"), item=lbl_p)
    for id_k, x in (("lbl_escala", X), ("lbl_fecha", X + W / 2)):
        it = comp.itemById(ids.get(id_k, id_k))
        if it is None:
            it = QgsLayoutItemLabel(comp)
            comp.addLayoutItem(it)
            it.setText(f"Escala 1:{int(map_item.scale()):,}".replace(",", " ")
                       if id_k == "lbl_escala" else f"Fecha: {_fecha(cfg)}")
        _etiqueta(comp, opts, ids.get(id_k, id_k), it.text(), x, T + H - 6.5, W / 2, 5,
                  _fmt(opts, 8.5 if plano else 7), item=it)


def _cuadro_titulo_plano(comp, ids, map_item, cfg, opts, X, W, R, y0, alto, tag, titulo):
    """Cuadro de título de los planos tabloide: logo, trámite, tipo y título
    al centro; abajo una ficha con rótulos pequeños (PROYECTO, ESCALA,
    FECHA) y su valor debajo, todo alineado a la izquierda."""
    gris, tinta = "#7a8594", "#1f1f1f"
    mx = 7.0                     # margen interior del panel
    xi, wi = X + mx, W - 2 * mx
    pie = y0 + alto              # borde inferior del panel

    logo = comp.itemById(ids.get("logo", "logo_empresa"))
    if logo is not None:
        logo.setResizeMode(QgsLayoutItemPicture.Zoom)
        _mover(logo, X + 12, y0 + alto * 0.05, W - 24, alto * 0.20)
        logo.setZValue(10)

    y = y0 + alto * 0.30
    lic = comp.itemById(ids.get("lbl_licencia", "lbl_licencia"))
    _etiqueta(comp, opts, ids.get("lbl_licencia", "lbl_licencia"),
              (cfg.get("tipo_tramite") or "").upper(), X, y, W, 5,
              _fmt(opts, 7.5, True, gris, 0.9), item=lic)
    _etiqueta(comp, opts, "lbl_plano_tag", tag, X, y + 8, W, 4.5,
              _fmt(opts, 8, True, opts["color_acento"], 2.0))
    lbl_t = comp.itemById(ids.get("lbl_plano", "lbl_tipo_plano"))
    largo = len(titulo) > 22
    _etiqueta(comp, opts, ids.get("lbl_plano", "lbl_tipo_plano"), titulo,
              X + 3, y + 13.5, W - 6, 13 if largo else 8,
              _fmt(opts, 13, True, tinta), item=lbl_t)

    # Ficha inferior
    y_f = pie - 30
    _linea(comp, "sep4", [(xi, y_f), (xi + wi, y_f)])
    nombre = (cfg.get("nombre_proyecto") or "").strip()
    _etiqueta(comp, opts, "cap_proy", "PROYECTO", xi, y_f + 2.5, wi, 3.5,
              _fmt(opts, 6.5, True, gris, 0.8), ha=Qt.AlignLeft)
    lbl_p = comp.itemById(ids.get("lbl_proyecto", "lbl_proyecto"))
    _etiqueta(comp, opts, ids.get("lbl_proyecto", "lbl_proyecto"), nombre,
              xi, y_f + 6.5, wi, 9, _fmt(opts, 9.5, False, tinta),
              ha=Qt.AlignLeft, va=Qt.AlignTop, item=lbl_p)
    y_e = pie - 12
    mitad = wi / 2
    for cap_id, cap, id_k, valor, x in (
            ("cap_esc", "ESCALA", "lbl_escala",
             f"1:{int(round(map_item.scale())):,}".replace(",", " "), xi),
            ("cap_fec", "FECHA", "lbl_fecha", _fecha(cfg), xi + mitad)):
        _etiqueta(comp, opts, cap_id, cap, x, y_e, mitad, 3.5,
                  _fmt(opts, 6.5, True, gris, 0.8), ha=Qt.AlignLeft)
        it = comp.itemById(ids.get(id_k, id_k))
        if it is None:
            it = QgsLayoutItemLabel(comp)
            comp.addLayoutItem(it)
        _etiqueta(comp, opts, ids.get(id_k, id_k), valor, x, y_e + 4, mitad, 5,
                  _fmt(opts, 9.5, False, tinta), ha=Qt.AlignLeft, item=it)
    _linea(comp, "sep_ef", [(xi + mitad - 3, y_e), (xi + mitad - 3, y_e + 8.5)])


# ---------------------------------------------------------------------------
# Pie de figura vertical (Plantilla_Figurasv2)
# ---------------------------------------------------------------------------

def _pie_figura(comp, ids, map_item, info, cfg, cfg_capa, opts, ctx, log):
    page = comp.pageCollection().page(0).pageSize()
    W, H = page.width(), page.height()
    k = W / 215.9  # todo se diseñó para carta vertical

    _limpiar_previos(comp)
    ext = map_item.extent()
    _mover(map_item, 6.6 * k, 10.5, W - 13.2 * k, H * 0.698)
    map_item.zoomToExtent(ext)
    map_bottom = 10.5 + H * 0.698
    Y1, Y2 = H * 0.755, H * 0.852

    barra = _barra(comp, map_item, opts, 12.5, halo=True)
    barra.setId("barra_escala_figura")
    _mover(barra, 12 * k, map_bottom - barra.sizeWithUnits().height() - 4)

    s = _rect(comp, "marco_leyenda", 0, Y1, W, Y2 - Y1, relleno="255,255,255,0", z=2)
    s.setFrameEnabled(False)
    _etiqueta(comp, opts, "lbl_simbologia", "SIMBOLOGÍA", 8 * k, Y1 + 2.5, 60, 5,
              _fmt(opts, 8.5, True, espaciado=0.8))

    leyenda = comp.itemById(ids.get("leyenda", "leyenda_principal"))
    capas = info["capas_leyenda"]
    tematica = info.get("tematica")
    izq = [c for c in capas if c is not tematica]
    der = [tematica] if tematica is not None else []
    if leyenda is not None:
        _estilo_leyenda(leyenda, opts, izq, None, 7.5)
        leyenda.setLinkedMap(map_item)
        _mover(leyenda, 8 * k, Y1 + 9, 95 * k, Y2 - Y1 - 11)
    if der:
        leg_b = QgsLayoutItemLegend(comp)
        comp.addLayoutItem(leg_b)
        leg_b.setId("leyenda_b")
        leg_b.setLinkedMap(map_item)
        _estilo_leyenda(leg_b, opts, der, None, 7.5)
        _mover(leg_b, 108 * k, Y1 + 9, W - 112 * k, Y2 - Y1 - 11)

    marco2 = comp.itemById("Marco2")
    if marco2 is not None:
        _mover(marco2, 0, Y2, W, H - Y2)
        marco2.setSymbol(QgsFillSymbol.createSimple({
            "color": "255,255,255,0", "outline_color": "30,30,30", "outline_width": "0.3"}))
    else:
        _rect(comp, "Marco2", 0, Y2, W, H - Y2, relleno="255,255,255,0", z=2)
    for id_, x in (("div1", 52 * k), ("div2", 164 * k)):
        _linea(comp, id_, [(x, Y2 + 5), (x, H - 5)], "150,150,150", "0.25")

    logo = comp.itemById(ids.get("logo", "logo_empresa"))
    if logo is not None:
        logo.setResizeMode(QgsLayoutItemPicture.Zoom)
        _mover(logo, 8 * k, Y2 + 9, 38 * k, H - Y2 - 18)
    _, titulo = _sin_prefijo(cfg_capa.get("nombre_plano", ""))
    _etiqueta(comp, opts, ids.get("lbl_licencia", "lbl_licencia"),
              (cfg.get("tipo_tramite") or "").upper(), 54 * k, Y2 + 6, 108 * k, 6,
              _fmt(opts, 7, True, "#6b6b6b", 1.0), item=comp.itemById(ids.get("lbl_licencia", "lbl_licencia")))
    _etiqueta(comp, opts, ids.get("lbl_plano", "lbl_tipo_plano"), titulo, 56 * k, Y2 + 13,
              104 * k, 14, _fmt(opts, 11, True), item=comp.itemById(ids.get("lbl_plano", "lbl_tipo_plano")))
    nombre = (cfg.get("nombre_proyecto") or "").strip()
    _etiqueta(comp, opts, ids.get("lbl_proyecto", "lbl_proyecto"),
              f"Proyecto: {nombre}" if nombre else "", 54 * k, Y2 + 29, 108 * k, 6,
              _fmt(opts, 7.5, False, "#4a4a4a"), item=comp.itemById(ids.get("lbl_proyecto", "lbl_proyecto")))
    zona = map_item.crs().description().replace("WGS 84 / ", "").replace("UTM zone", "UTM Zona")
    fecha_it = comp.itemById(ids.get("lbl_fecha", "lbl_fecha"))
    fecha = (fecha_it.text() if fecha_it else "").replace("Fecha:", "").strip()
    _etiqueta(comp, opts, ids.get("lbl_fecha", "lbl_fecha"),
              f"Proyección:\n{zona}, WGS 84\n\nFecha:\n{fecha}", 170 * k, Y2 + 6, 42 * k, H - Y2 - 12,
              _fmt(opts, 7.5, False, "#2b2b2b"), ha=Qt.AlignLeft, item=fecha_it)
    for id_k in ("lbl_escala", "lbl_fuente", "lbl_coordsys"):
        _quitar(comp, comp.itemById(ids.get(id_k, id_k)))


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def aplicar_estilo_moderno(comp, cfg, cfg_capa, ids, ctx, log) -> None:
    """Aplica el estilo si está activo en la config. Nunca lanza excepción."""
    opts = _opciones(cfg)
    if not opts:
        return
    opts["_pg"] = cfg.get("pg") or {}
    try:
        map_item = comp.itemById(ids.get("mapa", "mapa_principal"))
        if map_item is None:
            return
        info = _estilizar_mapa(comp, map_item, cfg_capa, opts, ctx, log)
        page = comp.pageCollection().page(0).pageSize()
        if page.height() > page.width():
            _pie_figura(comp, ids, map_item, info, cfg, cfg_capa, opts, ctx, log)
        else:
            _panel_lateral(comp, ids, map_item, info, cfg, cfg_capa, opts, ctx, log)
        comp.refresh()
        log.debug(" ✓ Estilo moderno aplicado.")
    except Exception:
        log.warning(" ⚠ No se pudo aplicar el estilo moderno; se exporta con la plantilla:\n"
                    f"{traceback.format_exc()}")
