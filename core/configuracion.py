"""
core/configuracion.py — Ensamblaje del dict de configuración final
(global.json + proyecto.json + .env). Compartido por main.py y el plugin.
"""

import json
import os

from .utils import leer_env


def listar_proyectos(base: str) -> list:
    """Nombres (sin extensión) de los JSON en config/proyectos/."""
    carpeta = os.path.join(base, "config", "proyectos")
    if not os.path.isdir(carpeta):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(carpeta)
        if f.endswith(".json")
    )


def leer_proyecto(base: str, proyecto: str) -> dict:
    """Carga el JSON de un proyecto tal cual, sin fusionar con global."""
    ruta = os.path.join(base, "config", "proyectos", f"{proyecto}.json")
    with open(ruta, encoding="utf-8") as fh:
        return json.load(fh)


def _validar_capas(cfg_proyecto: dict, proyecto: str) -> None:
    """
    Valida lo mínimo indispensable de cada plano; lanza ValueError con
    el nombre del plano mal definido para no fallar a media corrida.
    """
    for i, capa in enumerate(cfg_proyecto.get("capas", []), start=1):
        if not capa.get("nombre_plano"):
            continue  # entradas de comentario (_grupo)
        nombre = capa["nombre_plano"]
        if not capa.get("nombre_capa"):
            raise ValueError(
                f"[{proyecto}] El plano '{nombre}' (entrada #{i}) "
                f"no define 'nombre_capa'."
            )
        es_vertices = capa.get("tipo") == "vertices"
        de_proyecto = capa.get("origen") == "proyecto"
        if not es_vertices and not de_proyecto and not capa.get("tabla_postgis"):
            raise ValueError(
                f"[{proyecto}] El plano '{nombre}' (entrada #{i}) no define "
                f"'tabla_postgis' (ni es tipo='vertices' u origen='proyecto')."
            )


def cargar_config(base: str, proyecto: str,
                  solo_capas: list = None, dpi: int = None) -> dict:
    """
    Construye el CONFIG final que consume generar_composiciones():
    fusión de global.json + proyecto.json + variables de .env.
    'dpi' (si se da) tiene prioridad sobre proyecto y global.
    Lanza ValueError si algún plano está mal definido.
    """
    env = {}
    for ruta in (
        os.path.join(base, ".env"),
        os.path.join(os.path.expanduser("~"), ".env_planos"),
    ):
        env = leer_env(ruta)
        if env:
            break

    with open(os.path.join(base, "config", "global.json"), encoding="utf-8") as fh:
        cfg_global = json.load(fh)
    cfg_proyecto = leer_proyecto(base, proyecto)
    _validar_capas(cfg_proyecto, proyecto)

    return {
        # ── Datos del proyecto ────────────────────────────────────────────────
        **cfg_proyecto,
        "defaults_capa": cfg_proyecto.get("defaults_capa", {}),

        # ── Parámetros globales (el proyecto tiene prioridad si los define) ───
        "ids":           {**cfg_global["ids"], **cfg_proyecto.get("ids", {})},
        "dpi":           dpi or cfg_proyecto.get("dpi", cfg_global.get("dpi", 200)),
        "layout_nombre": cfg_proyecto.get(
            "layout_nombre", cfg_global.get("layout_nombre", "Plantilla_Corporativa")
        ),
        "coordenadas":   cfg_proyecto.get(
            "coordenadas", cfg_global.get("coordenadas", "COORDENADAS UTM WGS84, R12")
        ),
        "fecha_plano":   cfg_proyecto.get("fecha_plano", cfg_global.get("fecha_plano", "")),
        "mapitas":       cfg_proyecto.get("mapitas", cfg_global.get("mapitas", {})),
        "formatos":      cfg_proyecto.get("formatos", cfg_global.get("formatos", ["png"])),
        "solo_capas":    solo_capas or [],

        # ── Rutas resueltas desde .env ────────────────────────────────────────
        "output_base":    env.get(
            "OUTPUT_BASE",
            os.path.join(os.path.expanduser("~"), "planos_salida", "prueba"),
        ),
        "logo_ruta":      env.get(
            "LOGO_RUTA",
            os.path.join(base, "assets", "logo_sinergia.jpg"),
        ),
        "plantillas_dir": os.path.join(base, "plantillas"),
        "estilos_dir":    os.path.join(base, "estilos"),

        # ── Conexión PostGIS ──────────────────────────────────────────────────
        "pg": {
            "host":     env.get("PG_HOST",     "localhost"),
            "port":     env.get("PG_PORT",     "5432"),
            "dbname":   env.get("PG_DBNAME",   "gis_empresa"),
            "schema":   env.get("PG_SCHEMA",   "proyectos"),
            "user":     env.get("PG_USER",     "postgres"),
            "password": env.get("PG_PASSWORD", ""),
        },
    }
