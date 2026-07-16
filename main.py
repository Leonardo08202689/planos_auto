"""
main.py — Punto de entrada del Generador Automático de Planos.

Uso en la consola Python de QGIS:
    exec(open('/home/leonardo/Codigos/Planos_auto/main.py').read())

Para cambiar de proyecto basta con editar la variable PROYECTO_ACTIVO.
También existe interfaz gráfica: ver planos_auto_plugin/ (plugin de QGIS).
"""

import importlib
import os
import sys

# ── Ajustar sys.path para que los imports de core/ funcionen en QGIS ──────────
try:
    _BASE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _BASE = os.path.join(os.path.expanduser("~"), "Codigos", "Planos_auto")

if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

# =============================================================================
# ① SELECCIÓN DE PROYECTO — edita solo esta variable para cambiar de proyecto
# =============================================================================
PROYECTO_ACTIVO = "sonitronies_concise"

# Para regenerar solo algunos planos, lista aquí sus 'nombre_capa'.
# Vacío = generar todos.  Ej.: SOLO_CAPAS = ["Clima", "Vegetacion"]
SOLO_CAPAS: list = []

# =============================================================================
# ② RECARGA DE MÓDULOS (evita caché en QGIS) Y EJECUCIÓN
# =============================================================================
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith("core.") or mod_name == "generar_planos":
        importlib.reload(sys.modules[mod_name])

from core.configuracion import cargar_config  # noqa: E402
from generar_planos import generar_composiciones  # noqa: E402

CONFIG = cargar_config(_BASE, PROYECTO_ACTIVO, solo_capas=SOLO_CAPAS)
generar_composiciones(CONFIG)
