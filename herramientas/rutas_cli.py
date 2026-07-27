#!/usr/bin/env python3
"""
herramientas/rutas_cli.py — Generador de rutas de acceso vehicular (OSMnx).

Versión parametrizable del generador original (Codigos/Rutas/generador_rutas.py):
recibe el destino y la ciudad por argumentos y produce solo el GeoPackage
(+ instrucciones de manejo), sin mapas estáticos ni HTML.

NO importa nada de QGIS: se ejecuta como proceso aparte (core/rutas_acceso.py
lo invoca desde el plugin). Compatible con OSMnx 1.9 y 2.x, Python ≥ 3.9.

Uso:
    python3 rutas_cli.py --destino 31.254689 -110.964553 \
        --ciudad "Nogales, Sonora, Mexico" \
        --salida /ruta/rutas_acceso.gpkg \
        --crs EPSG:32612 --direcciones Norte,Sur,Este \
        --cache-dir /ruta/cache_rutas
"""

import argparse
import math
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")


def _ox_fn(ox, nombre):
    """Resuelve una función de OSMnx tolerando el cambio de API 1.x → 2.x
    (en 2.x varias funciones top-level se movieron a submódulos)."""
    fn = getattr(ox, nombre, None)
    if fn is not None:
        return fn
    for submod in ("routing", "distance", "speed", "geocoder"):
        mod = getattr(ox, submod, None)
        if mod is not None and hasattr(mod, nombre):
            return getattr(mod, nombre)
    raise AttributeError(f"OSMnx {ox.__version__}: no se encontró '{nombre}'")


# ─────────────────────────────────────────────────────────────────────
# Red vial
# ─────────────────────────────────────────────────────────────────────

def cargar_red(ox, ciudad, cache_dir, velocidad_fallback):
    slug = re.sub(r"[^\w]+", "_", ciudad.split(",")[0].strip()).lower()
    graphml = os.path.join(cache_dir, f"{slug}_red.graphml")

    if os.path.exists(graphml):
        print(f"Cargando red desde caché: {graphml}")
        G = ox.load_graphml(graphml)
    else:
        print(f"Descargando red vial de '{ciudad}' (puede tardar varios minutos)...")
        G = ox.graph_from_place(
            ciudad,
            network_type="drive",
            custom_filter='["highway"~"motorway|trunk|primary|secondary|tertiary"]',
        )
        os.makedirs(cache_dir, exist_ok=True)
        ox.save_graphml(G, filepath=graphml)
        print(f"Red guardada en: {graphml}")

    G = _ox_fn(ox, "add_edge_speeds")(G, fallback=velocidad_fallback)
    G = _ox_fn(ox, "add_edge_travel_times")(G)
    print(f"Red lista: {len(G.nodes):,} nodos | {len(G.edges):,} aristas")
    return G


# ─────────────────────────────────────────────────────────────────────
# Entradas cardinales (desde el centroide del límite municipal)
# ─────────────────────────────────────────────────────────────────────

def _angulo_a_cardinal(a):
    if -45 <= a < 45:
        return "Este"
    if 45 <= a < 135:
        return "Norte"
    if 135 <= a <= 180 or -180 <= a < -135:
        return "Oeste"
    return "Sur"


def detectar_entradas(ox, np, G, ciudad, crs_salida):
    limite = _ox_fn(ox, "geocode_to_gdf")(ciudad)
    centroide = limite.to_crs(crs_salida).geometry.centroid.iloc[0]

    nodos_gdf, _ = ox.graph_to_gdfs(G)
    nodos_utm = nodos_gdf.to_crs(crs_salida).copy()
    nodos_utm["dx"] = nodos_utm.geometry.x - centroide.x
    nodos_utm["dy"] = nodos_utm.geometry.y - centroide.y
    nodos_utm["angulo"] = np.degrees(np.arctan2(nodos_utm["dy"], nodos_utm["dx"]))
    nodos_utm["dist_cent"] = nodos_utm.geometry.distance(centroide)
    nodos_utm["direccion"] = nodos_utm["angulo"].apply(_angulo_a_cardinal)

    entradas_nodo, entradas_coord = {}, {}
    for direccion, grupo in nodos_utm.groupby("direccion"):
        nodo_id = grupo["dist_cent"].idxmax()
        geom = nodos_gdf.loc[nodo_id].geometry
        entradas_nodo[direccion] = nodo_id
        entradas_coord[direccion] = (geom.y, geom.x)
        print(f"Entrada {direccion}: nodo {nodo_id} ({geom.y:.4f}, {geom.x:.4f})")

    return entradas_nodo, entradas_coord


# ─────────────────────────────────────────────────────────────────────
# Nodo destino óptimo
# ─────────────────────────────────────────────────────────────────────

def encontrar_nodo_destino(ox, nx, gpd, Point, G, destino_latlon,
                           entradas_nodo, direcciones, crs_salida):
    nodos_gdf, _ = ox.graph_to_gdfs(G)
    nodos_utm = nodos_gdf.to_crs(crs_salida).copy()

    dest_punto = gpd.GeoDataFrame(
        geometry=[Point(destino_latlon[1], destino_latlon[0])], crs="EPSG:4326"
    ).to_crs(crs_salida).geometry.iloc[0]

    nodos_utm["dist_dest"] = nodos_utm.geometry.distance(dest_punto)
    candidatos = list(nodos_utm[nodos_utm["dist_dest"] < 400].index)
    print(f"Candidatos de destino a <400 m: {len(candidatos)}")

    if not candidatos:
        print("Sin candidatos cercanos; usando nodo más próximo al destino.")
        return _ox_fn(ox, "nearest_nodes")(G, destino_latlon[1], destino_latlon[0])

    mejor_nodo, mejor_costo = None, float("inf")
    for c in candidatos:
        try:
            costo = sum(
                nx.shortest_path_length(G, entradas_nodo[d], c, weight="travel_time")
                for d in direcciones if d in entradas_nodo
            )
        except Exception:
            continue
        if costo < mejor_costo:
            mejor_costo, mejor_nodo = costo, c
    if mejor_nodo is None:
        return _ox_fn(ox, "nearest_nodes")(G, destino_latlon[1], destino_latlon[0])
    return mejor_nodo


# ─────────────────────────────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────────────────────────────

def _recortar_vuelta_u(G, ruta, umbral=150):
    if not ruta or len(ruta) < 3:
        return ruta
    ruta = list(ruta)
    for _ in range(5):
        if len(ruta) < 3:
            break
        u, v, w = ruta[-3], ruta[-2], ruta[-1]
        a1 = math.atan2(G.nodes[v]["y"] - G.nodes[u]["y"], G.nodes[v]["x"] - G.nodes[u]["x"])
        a2 = math.atan2(G.nodes[w]["y"] - G.nodes[v]["y"], G.nodes[w]["x"] - G.nodes[v]["x"])
        diff = min(abs(math.degrees(a2 - a1)), 360 - abs(math.degrees(a2 - a1)))
        if diff > umbral:
            ruta.pop()
        else:
            break
    return ruta


def _edge_safe(G, u, v):
    try:
        return min(G[u][v].values(), key=lambda e: e.get("length", 0))
    except KeyError:
        try:
            return min(G[v][u].values(), key=lambda e: e.get("length", 0))
        except KeyError:
            return {}


def calcular_rutas(ox, gpd, LineString, G, entradas_nodo, nodo_dest,
                   direcciones, crs_salida):
    shortest_path = _ox_fn(ox, "shortest_path")
    rutas_info = []

    for i, direccion in enumerate(direcciones):
        if direccion not in entradas_nodo:
            print(f"Sin entrada para '{direccion}', omitida.")
            continue
        try:
            ruta = shortest_path(G, entradas_nodo[direccion], nodo_dest, weight="travel_time")
            ruta = _recortar_vuelta_u(G, ruta)
        except Exception as e:
            print(f"Sin ruta desde {direccion}: {e}")
            continue
        if not ruta or len(ruta) < 2:
            print(f"Sin ruta desde {direccion}.")
            continue

        segmentos, longitudes, tiempos = [], [], []
        for u, v in zip(ruta[:-1], ruta[1:]):
            edge = _edge_safe(G, u, v)
            geom = edge.get("geometry", LineString([
                (G.nodes[u]["x"], G.nodes[u]["y"]),
                (G.nodes[v]["x"], G.nodes[v]["y"]),
            ]))
            segmentos.append(geom)
            longitudes.append(edge.get("length", 0))
            tiempos.append(edge.get("travel_time", 0))

        nombre = f"Ruta_{i + 1}"
        gdf = gpd.GeoDataFrame({
            "ruta":       nombre,
            "direccion":  direccion,
            "segmento":   range(len(segmentos)),
            "longitud_m": longitudes,
            "tiempo_s":   tiempos,
            "geometry":   segmentos,
        }, crs="EPSG:4326").to_crs(crs_salida)

        rutas_info.append({
            "nombre": nombre, "direccion": direccion, "gdf": gdf,
            "dist_km": sum(longitudes) / 1000,
            "tiempo_min": sum(tiempos) / 60,
            "nodos": ruta,
        })
        print(f"{nombre} ({direccion}): {rutas_info[-1]['dist_km']:.2f} km | "
              f"{rutas_info[-1]['tiempo_min']:.1f} min")

    return rutas_info


# ─────────────────────────────────────────────────────────────────────
# Instrucciones de manejo
# ─────────────────────────────────────────────────────────────────────

def _nombre_calle(G, u, v):
    nombre = _edge_safe(G, u, v).get("name", None)
    if isinstance(nombre, list):
        nombre = nombre[0]
    return nombre or "calle sin nombre"


def _tipo_giro(G, u, v, w):
    a1 = math.degrees(math.atan2(G.nodes[v]["y"] - G.nodes[u]["y"], G.nodes[v]["x"] - G.nodes[u]["x"]))
    a2 = math.degrees(math.atan2(G.nodes[w]["y"] - G.nodes[v]["y"], G.nodes[w]["x"] - G.nodes[v]["x"]))
    ang = (a2 - a1 + 360) % 360
    if 30 <= ang < 150:
        return "Gire a la izquierda"
    if 210 <= ang < 330:
        return "Gire a la derecha"
    if 150 <= ang < 210:
        return "Continúe derecho"
    return "Gire en U"


def generar_instrucciones(G, rutas_info, salida_gpkg):
    base = os.path.splitext(salida_gpkg)[0]
    for r in rutas_info:
        nodos = r["nodos"]
        lineas = [f"=== {r['nombre']} — Acceso desde el {r['direccion']} ===\n"]
        calle_actual = _nombre_calle(G, nodos[0], nodos[1])
        dist_acum = 0

        for i in range(len(nodos) - 1):
            u, v = nodos[i], nodos[i + 1]
            dist_acum += _edge_safe(G, u, v).get("length", 0)
            es_ultimo = i == len(nodos) - 2
            calle_sig = _nombre_calle(G, u, v)

            if calle_sig != calle_actual or es_ultimo:
                if es_ultimo:
                    lineas.append(
                        f"  • Continúe por {calle_actual} {dist_acum/1000:.1f} km hasta el destino."
                    )
                else:
                    w = nodos[i + 2]
                    lineas.append(
                        f"  • Siga por {calle_actual} aprox. {dist_acum/1000:.1f} km → "
                        f"{_tipo_giro(G, u, v, w)} en {_nombre_calle(G, v, w)}."
                    )
                    dist_acum = 0
                    calle_actual = _nombre_calle(G, v, w)

        archivo = f"{base}_{r['nombre']}_instrucciones.txt"
        with open(archivo, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas))
        print(f"Instrucciones: {archivo}")


# ─────────────────────────────────────────────────────────────────────
# Exportar GeoPackage
# ─────────────────────────────────────────────────────────────────────

def exportar_gpkg(gpd, Point, rutas_info, entradas_coord, destino_latlon,
                  nombre_proyecto, crs_salida, salida):
    gdf_destino = gpd.GeoDataFrame(
        {"nombre": [nombre_proyecto],
         "geometry": [Point(destino_latlon[1], destino_latlon[0])]},
        crs="EPSG:4326",
    ).to_crs(crs_salida)

    puntos_entrada = []
    for r in rutas_info:
        coord = entradas_coord[r["direccion"]]
        puntos_entrada.append({
            "ruta": r["nombre"], "direccion": r["direccion"],
            "dist_km": round(r["dist_km"], 2),
            "tiempo_min": round(r["tiempo_min"], 1),
            "geometry": Point(coord[1], coord[0]),
        })
    gdf_entradas = gpd.GeoDataFrame(puntos_entrada, crs="EPSG:4326").to_crs(crs_salida)

    os.makedirs(os.path.dirname(salida) or ".", exist_ok=True)
    if os.path.exists(salida):
        os.remove(salida)  # evitar mezclar capas de una corrida anterior

    for r in rutas_info:
        r["gdf"].to_file(salida, layer=r["nombre"], driver="GPKG")
    gdf_destino.to_file(salida, layer="Destino", driver="GPKG")
    gdf_entradas.to_file(salida, layer="Puntos_Entrada", driver="GPKG")
    print(f"GeoPackage: {salida}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera rutas de acceso (OSMnx) hacia un destino.")
    parser.add_argument("--destino", nargs=2, type=float,
                        metavar=("LAT", "LON"), help="Destino en grados WGS84")
    parser.add_argument("--ciudad", required=True,
                        help='P. ej. "Nogales, Sonora, Mexico"')
    parser.add_argument("--salida",
                        help="Ruta del GPKG a escribir (no aplica con --solo-red)")
    parser.add_argument("--crs", default="EPSG:32612", help="CRS de salida (default EPSG:32612)")
    parser.add_argument("--direcciones", default="Norte,Sur,Este",
                        help="Puntos cardinales separados por coma")
    parser.add_argument("--cache-dir", default=None,
                        help="Carpeta para el caché .graphml (default: la del GPKG, o el cwd con --solo-red)")
    parser.add_argument("--velocidad-fallback", type=float, default=50,
                        help="km/h para calles sin dato (default 50)")
    parser.add_argument("--nombre-proyecto", default="Proyecto")
    parser.add_argument("--sin-instrucciones", action="store_true")
    parser.add_argument("--solo-red", action="store_true",
                        help="Solo descarga/cachea la red vial de la ciudad y termina "
                             "(precarga; no requiere --destino ni --salida).")
    args = parser.parse_args()

    if not args.solo_red and (not args.destino or not args.salida):
        print("ERROR: --destino y --salida son obligatorios sin --solo-red.")
        return 1

    import numpy as np
    import geopandas as gpd
    import networkx as nx
    import osmnx as ox
    from shapely.geometry import LineString, Point

    print(f"OSMnx {ox.__version__} | ciudad='{args.ciudad}'")

    if args.solo_red:
        cache_dir = args.cache_dir or os.getcwd()
        cargar_red(ox, args.ciudad, cache_dir, args.velocidad_fallback)
        print("Red vial cacheada. (--solo-red: no se calculan rutas)")
        return 0

    direcciones = [d.strip().capitalize() for d in args.direcciones.split(",") if d.strip()]
    validas = {"Norte", "Sur", "Este", "Oeste"}
    if not direcciones or not set(direcciones) <= validas:
        print(f"ERROR: direcciones inválidas {direcciones}; usa {sorted(validas)}")
        return 1
    cache_dir = args.cache_dir or (os.path.dirname(os.path.abspath(args.salida)))
    destino = tuple(args.destino)

    print(f"destino={destino} | crs={args.crs} | direcciones={direcciones}")

    G = cargar_red(ox, args.ciudad, cache_dir, args.velocidad_fallback)
    entradas_nodo, entradas_coord = detectar_entradas(ox, np, G, args.ciudad, args.crs)
    nodo_dest = encontrar_nodo_destino(
        ox, nx, gpd, Point, G, destino, entradas_nodo, direcciones, args.crs
    )
    rutas_info = calcular_rutas(
        ox, gpd, LineString, G, entradas_nodo, nodo_dest, direcciones, args.crs
    )
    if not rutas_info:
        print("ERROR: no se calculó ninguna ruta.")
        return 1

    if not args.sin_instrucciones:
        generar_instrucciones(G, rutas_info, args.salida)
    exportar_gpkg(gpd, Point, rutas_info, entradas_coord, destino,
                  args.nombre_proyecto, args.crs, args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
