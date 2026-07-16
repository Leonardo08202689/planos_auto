"""
generar_planos.py — Orquestador principal del generador de planos.

Importa todos los módulos de core/ y ejecuta el loop de composiciones.
La configuración llega desde main.py (o directamente como dict).
"""

import os

import processing
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsLayoutItemMap,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from datetime import datetime

from core.capas      import cargar_capa_postgis, extraer_vertices_poligono
from core.composicion import (
    actualizar_leyenda,
    cargar_o_importar_layout,
    configurar_grid_mapa,
    fijar_logo,
    reenlazar_barra_escala,
    resolver_ids,
    set_label_text,
    validar_extent,
)
from core.exportar   import exportar_plano
from core.mapitas    import configurar_mapitas, preparar_capas_referencia
from core.reportes   import generar_indice_html
from core.simbologia import (
    aplicar_estilo_poligono,
    aplicar_estilo_vertices,
    aplicar_etiquetas_pal,
    aplicar_opacidad_capa,
    aplicar_renderer_categorizado,
)
from core.utils      import crear_logger, sanitizar_nombre


# =============================================================================
# PROCESO PRINCIPAL
# =============================================================================

_MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _aplicar_etiquetas_globales(comp, ids, cfg, cfg_capa, log):
    set_label_text(comp, ids.get("lbl_proyecto", ""), cfg.get("nombre_proyecto", ""), log)
    set_label_text(comp, ids.get("lbl_licencia", ""), cfg.get("tipo_tramite", ""),    log)
    set_label_text(comp, ids.get("lbl_plano", ""),    cfg_capa.get("nombre_plano", ""), log)
    
    escala = cfg_capa.get("escala", 0)
    if escala:
        set_label_text(comp, ids.get("lbl_escala", ""), f"Escala 1:{escala:,}".replace(",", " "), log)
    
    ahora = datetime.now()
    fecha = cfg.get("fecha_plano") or f"{_MESES_ES[ahora.month - 1]} {ahora.year}"
    set_label_text(comp, ids.get("lbl_fecha", ""), f"Fecha: {fecha}", log)
    
    set_label_text(comp, ids.get("lbl_fuente", ""), cfg_capa.get("fuente", ""), log)
    set_label_text(comp, ids.get("lbl_coordsys", ""), cfg.get("coordenadas", ""), log)
    fijar_logo(comp, ids.get("logo", ""), cfg.get("logo_ruta", ""), log)


def generar_composiciones(cfg: dict) -> None:
    """
    Genera una composición por cada entrada en cfg['capas'],
    la exporta a PNG y la registra en el panel de QGIS.

    Parámetros
    ----------
    cfg : dict
        Configuración completa (fusión de global.json + proyecto.json +
        variables de entorno). Ver main.py para la construcción del dict.
    """
    nombre_carpeta = sanitizar_nombre(cfg["nombre_proyecto"])[:50]
    output_dir     = os.path.join(cfg["output_base"], nombre_carpeta)
    os.makedirs(output_dir, exist_ok=True)
    log = crear_logger(output_dir)

    log.info("=" * 65)
    log.info("INICIANDO GENERACIÓN DE COMPOSICIONES E INYECCIÓN DE CAPAS")
    log.info("=" * 65)

    project      = QgsProject.instance()
    plantillas_dir = cfg.get("plantillas_dir", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "plantillas"
    ))

    # ── Capa polígono de trabajo ──────────────────────────────────────────────
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

    # ── Grupo de capas en el panel ────────────────────────────────────────────
    root_tree = project.layerTreeRoot()
    grupo_mia = root_tree.findGroup("Planos Generados")
    if grupo_mia:
        for child in grupo_mia.children():
            if hasattr(child, "layerId"):
                project.removeMapLayer(child.layerId())
        grupo_mia.removeAllChildren()
        log.info(" → Limpiando grupo 'Planos Generados' previo...")
    else:
        grupo_mia = root_tree.addGroup("Planos Generados")

    # ── Mapa base satelital XYZ ───────────────────────────────────────────────
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

    # ── BBox del polígono en EPSG:4326 ────────────────────────────────────────
    crs_origen  = poly_layer.crs()
    bbox_nativo = feature_poligono.geometry().boundingBox()
    transf_4326 = QgsCoordinateTransform(
        crs_origen, QgsCoordinateReferenceSystem("EPSG:4326"), project
    )
    bbox_wkt = transf_4326.transformBoundingBox(bbox_nativo).asWktPolygon()

    # ── Punto centroide (estrella roja) ───────────────────────────────────────
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
        """Resuelve una referencia de capa desde el proyecto."""
        return project.mapLayer(capa.id()) if capa else None

    # ── Capas de referencia para mapitas (se preparan UNA vez) ─────────────────
    cfg_mapitas = cfg.get("mapitas", {})
    capas_ref: dict = {}
    if cfg_mapitas:
        log.info(" → Preparando capas de referencia para mapitas...")
        capas_ref = preparar_capas_referencia(
            centroid_geom, crs_origen, cfg["pg"], cfg_mapitas, project, log
        )

    # ── Cache de plantillas (evita re-importar el mismo QPT) ──────────────────
    cache_plantillas: dict = {}

    def obtener_plantilla(layout_nombre: str):
        if layout_nombre not in cache_plantillas:
            p = cargar_o_importar_layout(project, layout_nombre, plantillas_dir, log)
            if not p:
                return None
            cache_plantillas[layout_nombre] = p
        return cache_plantillas[layout_nombre]

    formatos   = cfg.get("formatos", ["png"])
    solo_capas = cfg.get("solo_capas") or []
    resultados: list = []

    # =========================================================================
    # LOOP PRINCIPAL — una iteración por capa/plano
    # =========================================================================
    for cfg_capa_raw in cfg["capas"]:
        # Ignorar entradas de comentario (_grupo, etc.)
        if not cfg_capa_raw.get("nombre_plano"):
            continue

        # Filtro para regenerar solo algunos planos (main.py → SOLO_CAPAS)
        if solo_capas and cfg_capa_raw.get("nombre_capa") not in solo_capas:
            continue

        # Aplicar defaults_capa
        cfg_capa = dict(cfg.get("defaults_capa", {}))
        cfg_capa.update(cfg_capa_raw)

        es_vertices = cfg_capa.get("tipo") == "vertices"
        nombre_comp = f"Comp_{cfg_capa['nombre_capa']}"

        log.info(f"\n{'─' * 55}")
        log.info(f" Procesando: {nombre_comp}")
        log.info(f"{'─' * 55}")

        ids          = resolver_ids(cfg, cfg_capa)
        layout_actual = cfg_capa.get("layout_nombre", cfg["layout_nombre"])

        # ── a. Cargar datos ───────────────────────────────────────────────────
        if not es_vertices:
            if cfg_capa.get("origen") == "proyecto":
                capas_proy = project.mapLayersByName(cfg_capa["nombre_capa"])
                if not capas_proy:
                    log.warning(
                        f" → Capa '{cfg_capa['nombre_capa']}' no encontrada en el proyecto, se omite."
                    )
                    continue
                capa_pg = capas_proy[0]
            else:
                capa_pg = cargar_capa_postgis(cfg_capa, cfg["pg"], bbox_wkt, log)
                if not capa_pg:
                    continue
                count = capa_pg.featureCount()
                if count == 0:
                    log.warning(
                        f" → Sin datos para '{cfg_capa['nombre_capa']}' (featureCount=0), se omite."
                    )
                    continue
                elif count == -1:
                    log.info(
                        f" → featureCount no disponible para '{cfg_capa['nombre_capa']}' (PostGIS), continuando..."
                    )
                else:
                    log.info(f" → {count} feature(s) en '{cfg_capa['nombre_capa']}'.")

        # ── b. Clonar composición ─────────────────────────────────────────────
        comp_existente = project.layoutManager().layoutByName(nombre_comp)
        if comp_existente:
            project.layoutManager().removeLayout(comp_existente)

        plantilla_base = obtener_plantilla(layout_actual)
        if not plantilla_base:
            log.warning(f" → Plantilla '{layout_actual}' no disponible, se omite.")
            continue

        nueva_comp = plantilla_base.clone()
        nueva_comp.setName(nombre_comp)
        project.layoutManager().addLayout(nueva_comp)

        # ── Mapitas de localización automáticos ───────────────────────────────
        if capas_ref:
            configurar_mapitas(nueva_comp, ids["mapa"], cfg_mapitas, capas_ref, log)

        # ── c. Calcular extent en escala ──────────────────────────────────────
        map_item = nueva_comp.itemById(ids["mapa"])
        if not map_item:
            ids_disp = [
                item.id() for item in nueva_comp.items()
                if isinstance(item, QgsLayoutItemMap)
            ]
            log.warning(
                f" → Mapa '{ids['mapa']}' no encontrado en '{layout_actual}'. "
                f"IDs disponibles: {ids_disp}. "
                f"Ajusta 'ids_override → mapa' en la config."
            )
            continue

        escala_capa = cfg_capa.get("escala")
        if not escala_capa:
            escala_capa = 5000
            log.warning(" → 'escala' no definida en la config; usando 1:5 000.")

        frame_size = map_item.sizeWithUnits()
        frame_pos  = map_item.positionWithUnits()
        map_item.setCrs(crs_origen)
        map_item.setExtent(bbox_nativo)
        map_item.setScale(escala_capa)
        map_item.attemptResize(frame_size)
        map_item.attemptMove(frame_pos)

        extent_en_escala = map_item.extent()
        validar_extent(extent_en_escala, cfg_capa["nombre_capa"], log, escala_capa)

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
            _aplicar_etiquetas_globales(nueva_comp, ids, cfg, cfg_capa, log)
            nueva_comp.refresh()
            rutas = exportar_plano(
                nueva_comp, cfg_capa, feature_poligono.id(),
                output_dir, cfg["dpi"], formatos, log,
            )
            resultados.append({
                "nombre_plano": cfg_capa["nombre_plano"],
                "escala":       escala_capa,
                "png":          rutas.get("png"),
                "exito":        bool(rutas),
            })
            continue

        # ── d. Sanear geometrías ──────────────────────────────────────────────
        log.info(" → Saneando geometrías (fixgeometries)...")
        res_fix = processing.run("native:fixgeometries", {
            "INPUT": capa_pg, "OUTPUT": "memory:",
        })

        # ── e. Reproyectar ────────────────────────────────────────────────────
        res_reproj    = processing.run("native:reprojectlayer", {
            "INPUT": res_fix["OUTPUT"], "TARGET_CRS": crs_origen, "OUTPUT": "memory:",
        })
        capa_reproyectada = res_reproj["OUTPUT"]

        # ── f. Máscara de recorte (en el CRS real de la capa reproyectada) ────
        crs_reproyectada = capa_reproyectada.crs()
        if crs_reproyectada.authid() != crs_origen.authid():
            log.info(
                f" → Reproyectando extent de clip: "
                f"{crs_origen.authid()} → {crs_reproyectada.authid()}"
            )
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

        # ── g. Recortar ───────────────────────────────────────────────────────
        res_clip      = processing.run("native:clip", {
            "INPUT": capa_reproyectada, "OVERLAY": layer_extent, "OUTPUT": "memory:",
        })
        capa_recortada = res_clip["OUTPUT"]
        capa_recortada.setName(cfg_capa["nombre_capa"])

        n_clip, n_orig = capa_recortada.featureCount(), capa_pg.featureCount()
        if n_orig > 0 and n_clip == n_orig:
            log.warning(
                f" ⚠ El clip NO redujo features ({n_clip}/{n_orig}). "
                f"Revisa CRS e ids_override."
            )
        elif n_clip == 0:
            log.warning(
                f" ⚠ Clip vacío para '{cfg_capa['nombre_capa']}'. "
                f"Revisa escala y CRS."
            )
        else:
            log.info(f" → Clip: {n_clip} feature(s).")

        # ── h. Simbología ─────────────────────────────────────────────────────
        campo_cat  = cfg_capa.get("campo_categoria", "")
        estilo_qml = cfg_capa.get("estilo_qml")
        qml_ruta = os.path.join(cfg.get("estilos_dir", ""), estilo_qml) if estilo_qml else None

        if qml_ruta and os.path.exists(qml_ruta):
            capa_recortada.loadNamedStyle(qml_ruta)
            log.info(f" ✓ Estilo QML aplicado: {estilo_qml}")
        elif campo_cat:
            aplicar_renderer_categorizado(
                capa_recortada, campo_cat, log, cfg_capa.get("paleta", "default")
            )
        elif capa_pg.renderer():
            capa_recortada.setRenderer(capa_pg.renderer().clone())

        aplicar_opacidad_capa(capa_recortada, cfg_capa.get("opacidad", 0.6), log)

        # ── i. Centroides y etiquetas ─────────────────────────────────────────
        log.info(" → Extrayendo centroides temáticos...")
        res_cent       = processing.run("native:centroids", {
            "INPUT": capa_recortada, "ALL_PARTS": True, "OUTPUT": "memory:",
        })
        capa_centroides = res_cent["OUTPUT"]
        capa_centroides.setName(f"centroides_{cfg_capa['nombre_capa']}")

        campo_etq = cfg_capa.get("campo_etiqueta", campo_cat)
        aplicar_etiquetas_pal(capa_centroides, campo_etq, log)

        project.addMapLayer(capa_recortada,  False)
        project.addMapLayer(capa_centroides, False)
        grupo_mia.insertLayer(0, capa_recortada)
        grupo_mia.insertLayer(0, capa_centroides)

        # ── j. Configurar map_item ────────────────────────────────────────────
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

        reenlazar_barra_escala(nueva_comp, map_item, log)
        configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 500), log)
        actualizar_leyenda(nueva_comp, ids, capa_recortada, poly_layer)
        _aplicar_etiquetas_globales(nueva_comp, ids, cfg, cfg_capa, log)
        nueva_comp.refresh()

        # ── k. Exportación ─────────────────────────────────────────────────────
        rutas = exportar_plano(
            nueva_comp, cfg_capa, feature_poligono.id(),
            output_dir, cfg["dpi"], formatos, log,
        )
        resultados.append({
            "nombre_plano": cfg_capa["nombre_plano"],
            "escala":       escala_capa,
            "png":          rutas.get("png"),
            "exito":        bool(rutas),
        })

    # ── Índice HTML con miniaturas de todos los planos ────────────────────────
    if resultados:
        generar_indice_html(resultados, output_dir, cfg["nombre_proyecto"], log)

    log.info(f"\n{'=' * 65}")
    log.info("✓ PROCESO TERMINADO — Revisa tu panel de Diseños en QGIS")
    log.info(f"  Ruta de salida: {output_dir}")
    log.info(f"  Índice: {os.path.join(output_dir, 'index_planos.html')}")
    log.info("=" * 65)