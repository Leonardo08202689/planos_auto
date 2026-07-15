"""
main.py — Punto de entrada del Generador Automático de Planos.

Uso en la consola Python de QGIS:
    exec(open('/home/leonardo/Codigos/Planos_auto/main.py').read())

Para cambiar de proyecto basta con editar la variable PROYECTO_ACTIVO.
"""

import json
import os
import sys

# ── Ajustar sys.path para que los imports de core/ funcionen en QGIS ──────────
try:
    _BASE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _BASE = os.path.join(os.path.expanduser("~"), "Codigos", "Planos_auto")

if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from core.utils import leer_env  # noqa: E402  (import tras sys.path)

# =============================================================================
# ① SELECCIÓN DE PROYECTO — edita solo esta variable para cambiar de proyecto
# =============================================================================
PROYECTO_ACTIVO = "sonitronies_concise"

# Para regenerar solo algunos planos, lista aquí sus 'nombre_capa'.
# Vacío = generar todos.  Ej.: SOLO_CAPAS = ["Clima", "Vegetacion"]
SOLO_CAPAS: list = []

# =============================================================================
# ② VARIABLES DE ENTORNO (credenciales PostGIS, rutas de salida, etc.)
# =============================================================================
_ENV_PATHS = [
    os.path.join(_BASE, ".env"),
    os.path.join(os.path.expanduser("~"), ".env_planos"),
]
_ENV = {}
for _p in _ENV_PATHS:
    _ENV = leer_env(_p)
    if _ENV:
        break

# =============================================================================
# ③ CARGA DE CONFIGURACIONES
# =============================================================================
with open(os.path.join(_BASE, "config", "global.json"), encoding="utf-8") as _f:
    _cfg_global = json.load(_f)

_proyecto_path = os.path.join(
    _BASE, "config", "proyectos", f"{PROYECTO_ACTIVO}.json"
)
with open(_proyecto_path, encoding="utf-8") as _f:
    _cfg_proyecto = json.load(_f)

# =============================================================================
# ④ ENSAMBLAJE DEL CONFIG FINAL
# =============================================================================
CONFIG = {
    # ── Datos del proyecto ────────────────────────────────────────────────────
    **_cfg_proyecto,
    "defaults_capa": _cfg_proyecto.get("defaults_capa", {}),

    # ── Parámetros globales (el proyecto tiene prioridad si los define) ───────
    "ids":           {**_cfg_global["ids"], **_cfg_proyecto.get("ids", {})},
    "dpi":           _cfg_proyecto.get("dpi", _cfg_global.get("dpi", 200)),
    "layout_nombre": _cfg_proyecto.get(
        "layout_nombre", _cfg_global.get("layout_nombre", "Plantilla_Corporativa")
    ),
    "coordenadas":   _cfg_proyecto.get(
        "coordenadas", _cfg_global.get("coordenadas", "COORDENADAS UTM WGS84, R12")
    ),
    "fecha_plano":   _cfg_proyecto.get("fecha_plano", _cfg_global.get("fecha_plano", "")),
    "mapitas":       _cfg_proyecto.get("mapitas", _cfg_global.get("mapitas", {})),
    "formatos":      _cfg_proyecto.get("formatos", _cfg_global.get("formatos", ["png"])),
    "solo_capas":    SOLO_CAPAS,

    # ── Rutas resueltas desde .env ────────────────────────────────────────────
    "output_base":    _ENV.get(
        "OUTPUT_BASE",
        os.path.join(os.path.expanduser("~"), "planos_salida", "prueba"),
    ),
    "logo_ruta":      _ENV.get(
        "LOGO_RUTA",
        os.path.join(_BASE, "assets", "logo_sinergia.jpg"),
    ),
    "plantillas_dir": os.path.join(_BASE, "plantillas"),
    "estilos_dir":    os.path.join(_BASE, "estilos"),

    # ── Conexión PostGIS ──────────────────────────────────────────────────────
    "pg": {
        "host":     _ENV.get("PG_HOST",     "localhost"),
        "port":     _ENV.get("PG_PORT",     "5432"),
        "dbname":   _ENV.get("PG_DBNAME",   "gis_empresa"),
        "schema":   _ENV.get("PG_SCHEMA",   "proyectos"),
        "user":     _ENV.get("PG_USER",     "postgres"),
        "password": _ENV.get("PG_PASSWORD", ""),
    },
}

# =============================================================================
# ⑤ EJECUTAR
# =============================================================================
import importlib

# Recargar todos los módulos del proyecto para evitar caché en QGIS
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith("core.") or mod_name == "generar_planos":
        importlib.reload(sys.modules[mod_name])

import generar_planos  # noqa: E402
from generar_planos import generar_composiciones  # noqa: E402

generar_composiciones(CONFIG)
