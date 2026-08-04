"""
generar_planos.py — Orquestador principal del generador de planos.

Importa todos los módulos de core/ y ejecuta el loop de composiciones.
La configuración llega desde main.py (o directamente como dict).
"""

import os
import traceback

import processing
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayoutItemMap,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from datetime import datetime

from core.capas      import (
    cargar_capa_extra,
    cargar_capa_postgis,
    cargar_raster_postgis,
    cargar_recortar_gpkg,
    cargar_recortar_shapefile,
    extraer_vertices_poligono,
    recortar_y_reproyectar,
    resolver_capa_poligono,
)
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
    aplicar_etiquetas_poligonos_grandes,
    aplicar_opacidad_capa,
    aplicar_renderer_categorizado,
    capa_legend_ubicacion_actual,
    construir_simbolo_patron,
)
from core.utils      import (
    color_para_categoria,
    crear_logger,
    formato_escala,
    sanitizar_nombre,
    titulo_capa,
)


# =============================================================================
# PROCESO PRINCIPAL
# =============================================================================

_MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _mayus(texto: str) -> str:
    """Títulos y subtítulos del plano siempre en mayúsculas, sin importar
    cómo se haya escrito en la config o venga de la BD (nomgeo_*)."""
    return texto.upper() if texto else texto


def _aplicar_etiquetas_globales(comp, ids, cfg, cfg_capa, log, capas_ref=None):
    set_label_text(comp, ids.get("lbl_proyecto", ""), _mayus(cfg.get("nombre_proyecto", "")), log)
    set_label_text(comp, ids.get("lbl_licencia", ""), _mayus(cfg.get("tipo_tramite", "")),    log)
    set_label_text(comp, ids.get("lbl_plano", ""),    _mayus(cfg_capa.get("nombre_plano", "")), log)

    if capas_ref:
        set_label_text(comp, ids.get("lbl_estado", ""),    _mayus(capas_ref.get("nomgeo_estado", "")),    log)
        set_label_text(comp, ids.get("lbl_municipio", ""), _mayus(capas_ref.get("nomgeo_municipio", "")), log)

    escala = cfg_capa.get("escala", 0)
    if escala:
        set_label_text(comp, ids.get("lbl_escala", ""), formato_escala(escala), log)

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
    poly_layer = resolver_capa_poligono(project, cfg["capa_poligono"], log)
    if not poly_layer:
        log.error(f"✗ Capa '{cfg['capa_poligono']}' no encontrada.")
        return

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

    # ── Limpiar composiciones de corridas anteriores ──────────────────────────
    # Cada corrida borra las capas de la corrida previa, así que cualquier
    # 'Comp_*' que no se regenere queda apuntando a capas muertas: QGIS
    # renderiza el mapa principal vacío y rellena los mapitas con TODAS las
    # capas visibles del proyecto (fallback cuando el layer set queda vacío).
    for layout_previo in list(project.layoutManager().layouts()):
        if layout_previo.name().startswith("Comp_"):
            project.layoutManager().removeLayout(layout_previo)

    # ── Grupo de capas en el panel ────────────────────────────────────────────
    root_tree = project.layerTreeRoot()
    grupo_mia = root_tree.findGroup("Planos Generados")
    if grupo_mia:
        for nodo_capa in grupo_mia.findLayers():
            project.removeMapLayer(nodo_capa.layerId())
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
    # Nombre de capa interno distinto del de 'capa_poligono' (aunque ambos
    # muestren "Área del Proyecto" en la leyenda vía nombre_leyenda): si
    # coincidieran, tras la primera corrida quedarían dos capas con el mismo
    # nombre en el proyecto y el diálogo (que busca la capa de polígono por
    # nombre para validar la selección) podría encontrar esta en su lugar,
    # que nunca tiene features seleccionados.
    centroid_geom = feature_poligono.geometry().centroid()
    punto_layer   = QgsVectorLayer(
        f"Point?crs={crs_origen.authid()}", "Punto_Proyecto", "memory"
    )
    punto_layer.setCustomProperty("nombre_leyenda", "Área del Proyecto")
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
    # PROCESAMIENTO DE UN PLANO
    # =========================================================================
    def _procesar_plano(cfg_capa_raw: dict):
        """
        Genera un plano. Devuelve el dict de resultado para el índice HTML,
        o None si la entrada no es un plano (comentario o filtrada).
        """
        # Ignorar entradas de comentario (_grupo, etc.)
        if not cfg_capa_raw.get("nombre_plano"):
            return None

        # Filtro para regenerar solo algunos planos (main.py → SOLO_CAPAS)
        if solo_capas and cfg_capa_raw.get("nombre_capa") not in solo_capas:
            return None

        # Aplicar defaults_capa
        cfg_capa = dict(cfg.get("defaults_capa", {}))
        cfg_capa.update(cfg_capa_raw)

        def _fallo():
            return {
                "nombre_plano": cfg_capa["nombre_plano"],
                "escala":       cfg_capa.get("escala"),
                "png":          None,
                "exito":        False,
            }

        es_vertices  = cfg_capa.get("tipo") == "vertices"
        es_raster    = cfg_capa.get("tipo") == "raster"
        es_rutas     = cfg_capa.get("tipo") == "rutas_acceso"
        es_combinada = cfg_capa.get("tipo") == "capas_combinadas"
        nombre_comp = f"Comp_{cfg_capa['nombre_capa']}"
        grupo_plano = grupo_mia.insertGroup(0, cfg_capa["nombre_plano"])

        log.info(f"\n{'─' * 55}")
        log.info(f" Procesando: {nombre_comp}")
        log.info(f"{'─' * 55}")

        ids          = resolver_ids(cfg, cfg_capa)
        layout_actual = cfg_capa.get("layout_nombre", cfg["layout_nombre"])

        # ── a. Cargar datos ───────────────────────────────────────────────────
        if not es_vertices and not es_raster and not es_rutas and not es_combinada:
            if cfg_capa.get("origen") == "proyecto":
                capas_proy = project.mapLayersByName(cfg_capa["nombre_capa"])
                if not capas_proy:
                    log.warning(
                        f" → Capa '{cfg_capa['nombre_capa']}' no encontrada en el proyecto, se omite."
                    )
                    return _fallo()
                capa_pg = capas_proy[0]
            else:
                capa_pg = cargar_capa_postgis(cfg_capa, cfg["pg"], bbox_wkt, log)
                if not capa_pg:
                    return _fallo()
                count = capa_pg.featureCount()
                if count == 0:
                    log.warning(
                        f" → Sin datos para '{cfg_capa['nombre_capa']}' (featureCount=0), se omite."
                    )
                    return _fallo()
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
            return _fallo()

        nueva_comp = plantilla_base.clone()
        nueva_comp.setName(nombre_comp)
        project.layoutManager().addLayout(nueva_comp)

        # ── Mapitas de localización automáticos ───────────────────────────────
        if capas_ref:
            configurar_mapitas(nueva_comp, ids["mapa"], cfg_mapitas, capas_ref, log, layout_actual)

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
            return _fallo()

        escala_capa = cfg_capa.get("escala")
        if not escala_capa:
            escala_capa = 5000
            log.warning(" → 'escala' no definida en la config; usando 1:5 000.")
        # La etiqueta lbl_escala debe reflejar la escala realmente usada
        cfg_capa["escala"] = escala_capa

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
            capa_vertices.setName(titulo_capa(cfg_capa))
            project.addMapLayer(capa_vertices, False)
            grupo_plano.insertLayer(0, capa_vertices)

            capas_visibles = [r for r in [_ref(capa_vertices), _ref(poly_layer)] if r]
            if basemap_id:
                r = project.mapLayer(basemap_id)
                if r:
                    capas_visibles.append(r)

            map_item.setKeepLayerSet(True)
            map_item.setLayers(capas_visibles)
            map_item.invalidateCache()
            map_item.refresh()

            reenlazar_barra_escala(nueva_comp, map_item, log, unidades_por_segmento=50)
            configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 100), log)
            actualizar_leyenda(nueva_comp, ids, poly_layer, capa_vertices, log=log)
            _aplicar_etiquetas_globales(nueva_comp, ids, cfg, cfg_capa, log, capas_ref)
            nueva_comp.refresh()
            rutas = exportar_plano(
                nueva_comp, cfg_capa, feature_poligono.id(),
                output_dir, cfg["dpi"], formatos, log,
            )
            return {
                "nombre_plano": cfg_capa["nombre_plano"],
                "escala":       escala_capa,
                "png":          rutas.get("png"),
                "exito":        bool(rutas),
            }

        # ── Flujo especial: Plano con capa ráster (p. ej. localización) ────────
        if es_raster:
            if cfg_capa.get("tabla_postgis_raster"):
                capa_raster = cargar_raster_postgis(
                    cfg_capa["tabla_postgis_raster"], cfg["pg"], log
                )
                if not capa_raster:
                    return _fallo()
                capa_raster.setName(titulo_capa(cfg_capa))
            else:
                ruta_raster = cfg_capa["ruta_raster"]
                capa_raster = QgsRasterLayer(ruta_raster, titulo_capa(cfg_capa))
                if not capa_raster.isValid():
                    log.warning(f" → Ráster no válido: {ruta_raster}")
                    return _fallo()

            project.addMapLayer(capa_raster, False)
            grupo_plano.insertLayer(0, capa_raster)
            aplicar_opacidad_capa(capa_raster, cfg_capa.get("opacidad", 1.0), log)

            # Capas extra de referencia (caminos, carreteras, calles, etc.) sobre el ráster
            capas_extra_obj = []
            extra_cfg = cfg_capa.get("capas_extra") or {}
            grupo_extra = extra_cfg.get("grupo_leyenda")
            for spec in extra_cfg.get("capas", []):
                c = cargar_capa_extra(
                    spec, extra_cfg, cfg["pg"], crs_origen, extent_en_escala, bbox_wkt, log
                )
                if not c:
                    continue
                c.setName(spec.get("nombre") or spec.get("capa") or spec.get("tabla_postgis"))
                color = spec.get("color", "70,130,220,220")
                if spec.get("tipo_geom") == "area":
                    simbolo = QgsFillSymbol.createSimple({
                        "color": color, "outline_color": "40,80,150,255", "outline_width": "0.3",
                    })
                else:
                    simbolo = QgsLineSymbol.createSimple({
                        "color": color, "line_width": spec.get("ancho_linea", "0.6"),
                    })
                c.setRenderer(QgsSingleSymbolRenderer(simbolo))
                if spec.get("campo_etiqueta"):
                    aplicar_etiquetas_pal(c, spec["campo_etiqueta"], log)
                if grupo_extra:
                    c.setCustomProperty("grupo_leyenda", grupo_extra)
                project.addMapLayer(c, False)
                grupo_plano.insertLayer(0, c)
                capas_extra_obj.append(c)

            usar_punto      = cfg_capa.get("marcador", "punto") == "punto"
            capa_referencia = punto_layer if usar_punto else poly_layer

            capas_visibles = [
                r for r in [
                    _ref(capa_referencia),
                    *[_ref(c) for c in capas_extra_obj],
                    _ref(capa_raster),
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

            reenlazar_barra_escala(
                nueva_comp, map_item, log,
                unidades_por_segmento=cfg_capa.get("barra_escala_segmento"),
            )
            configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 1000), log)
            # La estrella del proyecto y las capas extra en la leyenda; el ráster no lleva simbología.
            actualizar_leyenda(nueva_comp, ids, capa_referencia, *capas_extra_obj, log=log)
            _aplicar_etiquetas_globales(nueva_comp, ids, cfg, cfg_capa, log, capas_ref)
            nueva_comp.refresh()
            rutas = exportar_plano(
                nueva_comp, cfg_capa, feature_poligono.id(),
                output_dir, cfg["dpi"], formatos, log,
            )
            return {
                "nombre_plano": cfg_capa["nombre_plano"],
                "escala":       escala_capa,
                "png":          rutas.get("png"),
                "exito":        bool(rutas),
            }

        # ── Flujo especial: Figura de varias capas combinadas (p. ej. ANP) ──────
        # A diferencia del flujo normal (una tabla temática por plano), aquí se
        # superponen varias tablas PostGIS y/o shapefiles en una sola composición,
        # todas centradas en el polígono a la escala dada (a diferencia de
        # 'rutas_acceso', que ajusta el extent al conjunto de capas).
        if es_combinada:
            capas_obj = []

            for spec in cfg_capa.get("capas_postgis", []):
                cfg_tabla = dict(cfg.get("defaults_capa", {}))
                cfg_tabla.update(spec)
                cfg_tabla.setdefault("nombre_capa", spec["tabla_postgis"])
                capa_pg_i = cargar_capa_postgis(cfg_tabla, cfg["pg"], bbox_wkt, log)
                if not capa_pg_i:
                    continue
                capa_r = recortar_y_reproyectar(
                    capa_pg_i, crs_origen, extent_en_escala, log,
                    nombre_log=spec.get("nombre", spec["tabla_postgis"]),
                )
                if not capa_r:
                    continue
                capa_r.setName(spec.get("nombre", spec["tabla_postgis"]))
                capa_r.setRenderer(QgsSingleSymbolRenderer(construir_simbolo_patron(
                    spec.get("color", "120,180,120,220"),
                    spec.get("color_borde", "60,100,60,255"),
                    spec.get("patron", "solid"),
                    spec.get("estilo_borde", "solid"),
                )))
                if spec.get("campo_etiqueta"):
                    aplicar_etiquetas_poligonos_grandes(capa_r, spec["campo_etiqueta"], log)
                capas_obj.append(capa_r)

            for spec in cfg_capa.get("capas_shapefile", []):
                capa_shp = cargar_recortar_shapefile(spec["ruta"], crs_origen, extent_en_escala, log)
                if not capa_shp:
                    continue
                capa_shp.setName(spec.get("nombre", capa_shp.name()))
                capa_shp.setRenderer(QgsSingleSymbolRenderer(construir_simbolo_patron(
                    spec.get("color", "120,180,120,220"),
                    spec.get("color_borde", "60,100,60,255"),
                    spec.get("patron", "solid"),
                    spec.get("estilo_borde", "solid"),
                )))
                if spec.get("campo_etiqueta"):
                    aplicar_etiquetas_poligonos_grandes(capa_shp, spec["campo_etiqueta"], log)
                capas_obj.append(capa_shp)

            if not capas_obj:
                log.error(" ✗ No se pudo cargar ninguna capa de la figura combinada.")
                return _fallo()

            for c in capas_obj:
                project.addMapLayer(c, False)
                grupo_plano.insertLayer(0, c)

            usar_punto      = cfg_capa.get("marcador", "punto") == "punto"
            capa_referencia = punto_layer if usar_punto else poly_layer

            capas_visibles = [
                r for r in [_ref(capa_referencia), *[_ref(c) for c in capas_obj]] if r
            ]
            if basemap_id:
                r = project.mapLayer(basemap_id)
                if r:
                    capas_visibles.append(r)

            map_item.setKeepLayerSet(True)
            map_item.setLayers(capas_visibles)
            map_item.invalidateCache()
            map_item.refresh()

            reenlazar_barra_escala(
                nueva_comp, map_item, log,
                unidades_por_segmento=cfg_capa.get("barra_escala_segmento"),
            )
            configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 50000), log)
            actualizar_leyenda(nueva_comp, ids, capa_referencia, *capas_obj, log=log)
            _aplicar_etiquetas_globales(nueva_comp, ids, cfg, cfg_capa, log, capas_ref)
            nueva_comp.refresh()
            rutas = exportar_plano(
                nueva_comp, cfg_capa, feature_poligono.id(),
                output_dir, cfg["dpi"], formatos, log,
            )
            return {
                "nombre_plano": cfg_capa["nombre_plano"],
                "escala":       escala_capa,
                "png":          rutas.get("png"),
                "exito":        bool(rutas),
            }

        # ── Flujo especial: Figura de Rutas de Acceso (varias capas de un GPKG) ─
        # A diferencia de los demás planos, el extent NO se centra en el polígono
        # con una escala fija: las rutas se extienden mucho más allá del predio,
        # así que el extent se calcula del conjunto de capas cargadas.
        if es_rutas:
            # 'ruta_gpkg' debe venir pre-generada en la config (modo manual):
            # calcularla aquí en vivo (OSMnx) bloquea QGIS varios minutos y no
            # se puede cancelar desde el diálogo, así que se quitó ese modo.
            # Para generar el GPKG usa herramientas/rutas_cli.py aparte y
            # apunta 'ruta_gpkg' al archivo resultante.
            ruta_gpkg = cfg_capa["ruta_gpkg"]
            nombres_rutas  = cfg_capa.get("capas_rutas", ["Ruta_1", "Ruta_2", "Ruta_3"])
            nombre_destino = cfg_capa.get("capa_destino", "Destino")
            nombre_entrada = cfg_capa.get("capa_entrada", "Puntos_Entrada")

            def _capa_gpkg(nombre_layer):
                c = QgsVectorLayer(f"{ruta_gpkg}|layername={nombre_layer}", nombre_layer, "ogr")
                if not c.isValid():
                    log.warning(f" → Capa '{nombre_layer}' no válida en el GPKG, se omite.")
                    return None
                return c

            capas_ruta = []
            for i, nombre_ruta in enumerate(nombres_rutas):
                c = _capa_gpkg(nombre_ruta)
                if not c:
                    continue
                c.setName(nombre_ruta.replace("_", " "))
                simbolo = QgsLineSymbol.createSimple({
                    "color": color_para_categoria(i, nombre_ruta, "agua"),
                    "line_width": "0.9",
                })
                c.setRenderer(QgsSingleSymbolRenderer(simbolo))
                capas_ruta.append(c)

            capa_destino = _capa_gpkg(nombre_destino)
            if capa_destino:
                capa_destino.setName("Destino")
                capa_destino.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
                    "name": "star", "color": "220,0,0,255",
                    "outline_color": "255,255,255,255", "size": "5.0",
                })))

            capa_entrada = _capa_gpkg(nombre_entrada)
            if capa_entrada:
                capa_entrada.setName("Puntos de Entrada")
                capa_entrada.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
                    "name": "circle", "color": "40,90,200,255",
                    "outline_color": "255,255,255,255", "size": "3.5",
                })))
                aplicar_etiquetas_pal(capa_entrada, "direccion", log)

            capas_cargadas = capas_ruta + [c for c in (capa_destino, capa_entrada) if c]
            if not capas_cargadas:
                log.error(" ✗ No se pudo cargar ninguna capa de rutas de acceso.")
                return _fallo()

            for c in capas_cargadas:
                project.addMapLayer(c, False)
                grupo_plano.insertLayer(0, c)

            # Centrado en el punto del proyecto a una escala fija y prudente
            # (no se ajusta el zoom al extent de las rutas): un auto-fit
            # variaba mucho de un proyecto a otro y a veces recortaba el
            # inicio/fin de las rutas; a 1:50 000 se ve siempre el mismo
            # alcance alrededor del punto, suficiente para ver dónde
            # empiezan y terminan.
            escala_capa = cfg_capa.get("escala") or 50000
            cfg_capa["escala"] = escala_capa

            frame_size = map_item.sizeWithUnits()
            frame_pos  = map_item.positionWithUnits()
            map_item.setCrs(crs_origen)
            map_item.setExtent(bbox_nativo)
            map_item.setScale(escala_capa)
            map_item.attemptResize(frame_size)
            map_item.attemptMove(frame_pos)

            capas_visibles = [c for c in (capa_destino, capa_entrada) if c] + capas_ruta
            capas_visibles = [_ref(c) for c in capas_visibles if _ref(c)]
            if basemap_id:
                r = project.mapLayer(basemap_id)
                if r:
                    capas_visibles.append(r)

            map_item.setKeepLayerSet(True)
            map_item.setLayers(capas_visibles)
            map_item.invalidateCache()
            map_item.refresh()

            reenlazar_barra_escala(
                nueva_comp, map_item, log,
                unidades_por_segmento=cfg_capa.get("barra_escala_segmento"),
            )
            configurar_grid_mapa(map_item, cfg_capa.get("grid_intervalo", 2500), log)
            actualizar_leyenda(nueva_comp, ids, *capas_ruta, capa_destino, capa_entrada, log=log)
            _aplicar_etiquetas_globales(nueva_comp, ids, cfg, cfg_capa, log, capas_ref)
            nueva_comp.refresh()
            rutas = exportar_plano(
                nueva_comp, cfg_capa, feature_poligono.id(),
                output_dir, cfg["dpi"], formatos, log,
            )
            return {
                "nombre_plano": cfg_capa["nombre_plano"],
                "escala":       escala_capa,
                "png":          rutas.get("png"),
                "exito":        bool(rutas),
            }

        # ── d0. Sanear geometrías de origen ─────────────────────────────────────
        # Se hace ANTES del pre-filtro bbox: 'native:extractbyextent' evalúa el
        # predicado espacial vía GEOS y truena si algún feature de origen trae
        # geometría inválida (p. ej. anillos autointersectados).
        res_fix_src = processing.run("native:fixgeometries", {
            "INPUT": capa_pg, "OUTPUT": "memory:",
        })
        capa_pg = res_fix_src["OUTPUT"]

        # ── d. Pre-filtro por bbox en el CRS de la capa fuente ────────────────
        # Reduce las capas amplias (sin_bbox_filter) al área visible ANTES de
        # sanear y reproyectar, que son los pasos caros.
        crs_capa = capa_pg.crs()
        if crs_capa.authid() != crs_origen.authid():
            transf_pre  = QgsCoordinateTransform(crs_origen, crs_capa, project)
            rect_fuente = transf_pre.transformBoundingBox(extent_en_escala)
        else:
            rect_fuente = extent_en_escala
        # Margen del 2% contra imprecisiones de la transformación del bbox
        rect_fuente = rect_fuente.buffered(
            max(rect_fuente.width(), rect_fuente.height()) * 0.02
        )
        extent_str = (
            f"{rect_fuente.xMinimum()},{rect_fuente.xMaximum()},"
            f"{rect_fuente.yMinimum()},{rect_fuente.yMaximum()} "
            f"[{crs_capa.authid()}]"
        )
        res_pre = processing.run("native:extractbyextent", {
            "INPUT": capa_pg, "EXTENT": extent_str, "CLIP": False,
            "OUTPUT": "memory:",
        })
        capa_candidatos = res_pre["OUTPUT"]
        log.info(f" → Pre-filtro bbox: {capa_candidatos.featureCount()} candidato(s).")

        # ── e. Sanear geometrías (solo candidatos) ────────────────────────────
        log.info(" → Saneando geometrías (fixgeometries)...")
        res_fix = processing.run("native:fixgeometries", {
            "INPUT": capa_candidatos, "OUTPUT": "memory:",
        })

        # ── f. Reproyectar ────────────────────────────────────────────────────
        res_reproj    = processing.run("native:reprojectlayer", {
            "INPUT": res_fix["OUTPUT"], "TARGET_CRS": crs_origen, "OUTPUT": "memory:",
        })
        capa_reproyectada = res_reproj["OUTPUT"]

        # ── g. Recorte preciso al extent visible ──────────────────────────────
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

        res_clip      = processing.run("native:clip", {
            "INPUT": capa_reproyectada, "OVERLAY": layer_extent, "OUTPUT": "memory:",
        })
        capa_recortada = res_clip["OUTPUT"]
        capa_recortada.setName(titulo_capa(cfg_capa))

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
                capa_recortada, campo_cat, log, cfg_capa.get("paleta", "default"),
                cfg_capa.get("campo_legenda_extra", ""),
            )
        elif capa_pg.renderer():
            capa_recortada.setRenderer(capa_pg.renderer().clone())

        aplicar_opacidad_capa(capa_recortada, cfg_capa.get("opacidad", 0.6), log)

        # ── h2. Leyenda: opcionalmente solo la categoría del proyecto ─────────
        # Para capas de zonificación regional (p. ej. UAB) el mapa muestra las
        # regiones vecinas como contexto, pero la leyenda solo debe nombrar la
        # región donde realmente cae el proyecto, no todas las visibles.
        capa_para_leyenda = capa_recortada
        if campo_cat and cfg_capa.get("leyenda_solo_ubicacion"):
            capa_filtrada = capa_legend_ubicacion_actual(
                capa_recortada, campo_cat, centroid_geom, log,
            )
            if capa_filtrada:
                project.addMapLayer(capa_filtrada, False)
                capa_para_leyenda = capa_filtrada

        # Agrupar las categorías bajo un grupo con nombre propio en la
        # leyenda (p. ej. "HIDROLOGÍA SUPERFICIAL" → "SUBCUENCA"), en vez
        # de listarlas sueltas bajo el nombre técnico de la capa.
        grupo_leyenda = cfg_capa.get("grupo_leyenda_categoria")
        if grupo_leyenda:
            capa_para_leyenda.setCustomProperty("grupo_leyenda", grupo_leyenda)
        nombre_leyenda_cat = cfg_capa.get("nombre_leyenda_categoria")
        if nombre_leyenda_cat:
            capa_para_leyenda.setCustomProperty("nombre_leyenda", nombre_leyenda_cat)

        # ── i. Centroides y etiquetas ─────────────────────────────────────────
        log.info(" → Extrayendo centroides temáticos...")
        res_cent       = processing.run("native:centroids", {
            "INPUT": capa_recortada, "ALL_PARTS": True, "OUTPUT": "memory:",
        })
        capa_centroides = res_cent["OUTPUT"]
        capa_centroides.setName(f"centroides_{cfg_capa['nombre_capa']}")

        expr_etq = cfg_capa.get("campo_etiqueta_expresion")
        if expr_etq:
            aplicar_etiquetas_pal(capa_centroides, expr_etq, log, ocultar_simbolo=True, es_expresion=True)
        else:
            campo_etq = cfg_capa.get("campo_etiqueta", campo_cat)
            aplicar_etiquetas_pal(capa_centroides, campo_etq, log, ocultar_simbolo=True)

        project.addMapLayer(capa_recortada,  False)
        project.addMapLayer(capa_centroides, False)
        grupo_plano.insertLayer(0, capa_recortada)
        grupo_plano.insertLayer(0, capa_centroides)

        # ── i2. Capas extra de referencia (ríos, canales, cuerpos de agua, etc.) ─
        # Fuentes locales grandes (GeoPackage) que se recortan al mismo extent
        # del plano; se dibujan encima de la capa temática principal.
        capas_extra_obj = []
        extra_cfg = cfg_capa.get("capas_extra") or {}
        grupo_extra = extra_cfg.get("grupo_leyenda")
        for spec in extra_cfg.get("capas", []):
            c = cargar_capa_extra(
                spec, extra_cfg, cfg["pg"], crs_origen, extent_en_escala, bbox_wkt, log
            )
            if not c:
                continue
            c.setName(spec.get("nombre") or spec.get("capa") or spec.get("tabla_postgis"))
            color = spec.get("color", "70,130,220,220")
            if spec.get("tipo_geom") == "area":
                simbolo = QgsFillSymbol.createSimple({
                    "color": color, "outline_color": "40,80,150,255", "outline_width": "0.3",
                })
            else:
                simbolo = QgsLineSymbol.createSimple({"color": color, "line_width": "0.6"})
            c.setRenderer(QgsSingleSymbolRenderer(simbolo))
            if grupo_extra:
                c.setCustomProperty("grupo_leyenda", grupo_extra)
            project.addMapLayer(c, False)
            grupo_plano.insertLayer(0, c)
            capas_extra_obj.append(c)

        # ── j. Configurar map_item ────────────────────────────────────────────
        usar_punto      = cfg_capa.get("marcador", "poligono") == "punto"
        capa_referencia = punto_layer if usar_punto else poly_layer

        capas_visibles = [
            r for r in [
                _ref(capa_referencia),
                _ref(capa_centroides),
                *[_ref(c) for c in capas_extra_obj],
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
        actualizar_leyenda(nueva_comp, ids, capa_referencia, capa_para_leyenda, *capas_extra_obj, log=log)
        _aplicar_etiquetas_globales(nueva_comp, ids, cfg, cfg_capa, log, capas_ref)
        nueva_comp.refresh()

        # ── k. Exportación ─────────────────────────────────────────────────────
        rutas = exportar_plano(
            nueva_comp, cfg_capa, feature_poligono.id(),
            output_dir, cfg["dpi"], formatos, log,
        )
        return {
            "nombre_plano": cfg_capa["nombre_plano"],
            "escala":       escala_capa,
            "png":          rutas.get("png"),
            "exito":        bool(rutas),
        }

    # =========================================================================
    # LOOP PRINCIPAL — un error en un plano no aborta los demás
    # =========================================================================
    for cfg_capa_raw in cfg["capas"]:
        try:
            resultado = _procesar_plano(cfg_capa_raw)
        except Exception:
            nombre = cfg_capa_raw.get("nombre_plano", "(sin nombre)")
            log.error(
                f" ✗ Error inesperado en '{nombre}'; se continúa con el siguiente:\n"
                f"{traceback.format_exc()}"
            )
            resultado = {
                "nombre_plano": nombre,
                "escala":       cfg_capa_raw.get("escala"),
                "png":          None,
                "exito":        False,
            }
        if resultado:
            resultados.append(resultado)

    # ── Índice HTML con miniaturas de todos los planos ────────────────────────
    if resultados:
        generar_indice_html(resultados, output_dir, cfg["nombre_proyecto"], log)

    n_ok     = sum(1 for r in resultados if r.get("exito"))
    fallidos = [r["nombre_plano"] for r in resultados if not r.get("exito")]

    log.info(f"\n{'=' * 65}")
    log.info("✓ PROCESO TERMINADO — Revisa tu panel de Diseños en QGIS")
    log.info(f"  Planos exitosos: {n_ok}/{len(resultados)}")
    if fallidos:
        log.warning(f"  Fallidos u omitidos: {', '.join(fallidos)}")
    log.info(f"  Ruta de salida: {output_dir}")
    log.info(f"  Índice: {os.path.join(output_dir, 'index_planos.html')}")
    log.info("=" * 65)
