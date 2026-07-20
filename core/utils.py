"""
core/utils.py — Utilidades puras: paleta de colores, env, nombres, logger.
Sin dependencias de QGIS para facilitar pruebas unitarias.
"""

import hashlib
import logging
import os
import re
import unicodedata
from datetime import datetime

# ---------------------------------------------------------------------------
# Paletas cartográficas temáticas
# ---------------------------------------------------------------------------
# Cada capa/plano puede elegir su paleta con el campo "paleta" en el JSON.
# Así los suelos salen en tonos tierra, la vegetación en verdes, etc.

_PALETAS = {
    # Pastel genérica (la original del proyecto)
    "default": [
        "#e6b89c", "#9ed8db", "#b5d8b7", "#f5c48a", "#aec6e8",
        "#d4a5c9", "#f7e59a", "#b2d3a8", "#f4a261", "#84c5f4",
        "#cdb4db", "#caffbf", "#ffd6a5", "#a8dadc", "#f1c0e8",
        "#b9fbc0", "#ffcfd2", "#8ecae6", "#e9c46a", "#f4a0b5",
    ],
    # Tonos tierra — suelos / edafología
    "suelos": [
        "#d9b38c", "#c19a6b", "#e8d0a9", "#a9846b", "#d4b483", "#8c6d4f",
        "#e3c99f", "#b5916b", "#caa472", "#9c7a5b", "#e6ce9c", "#b08d57",
    ],
    # Grises, malvas y rosas — geología / litología
    "geologia": [
        "#b8b8c0", "#c4b7d9", "#d9a6a6", "#a8bfc9", "#d6c6b8", "#9e94b8",
        "#cfc0d3", "#b8a6a6", "#8f9fb3", "#d3bfcd", "#a9a9bd", "#c2b280",
    ],
    # Gradiente cálido → frío — unidades climáticas
    "clima": [
        "#f4a261", "#e9c46a", "#f6e8a6", "#d8e2a8", "#a8d5ba", "#7fcdbb",
        "#66b2c2", "#5a9bd4", "#8fb8de", "#c0d6ea", "#e76f51", "#f2cc8f",
    ],
    # Verdes — vegetación / uso de suelo
    "vegetacion": [
        "#a1d99b", "#74c476", "#c7e9c0", "#4c9f70", "#b2df8a", "#8fbc8f",
        "#addd8e", "#66c2a5", "#d9f0a3", "#78c679", "#94c9a9", "#5aa87a",
    ],
    # Azules y turquesas — hidrología / cuencas
    "agua": [
        "#9ecae1", "#6baed6", "#c6dbef", "#4292c6", "#a6cee3", "#81c3d7",
        "#74a9cf", "#bdd7e7", "#56a0c8", "#8ed1cc", "#b3e0dc", "#5f9ea0",
    ],
    # Verdes-azulados — figuras de conservación (ANP, AICA, RTP…)
    "conservacion": [
        "#80cdc1", "#a6dba0", "#c7eae5", "#5ab4ac", "#b8d4a8", "#94c9a9",
        "#66b2a2", "#a8ddb5", "#7fbf9b", "#cdeccd", "#69a58f", "#9bd4c0",
    ],
}


def paletas_disponibles() -> list:
    """Nombres de paletas válidos para el campo 'paleta' del JSON."""
    return list(_PALETAS)


def color_para_categoria(indice: int, valor: str, paleta: str = "default") -> str:
    """Devuelve un color hex '#rrggbb' de la paleta; si se agota, genera uno por hash."""
    colores = _PALETAS.get(paleta) or _PALETAS["default"]
    if indice < len(colores):
        return colores[indice]
    digest = int(hashlib.md5(str(valor).encode()).hexdigest(), 16)
    r = (digest >> 16) % 160 + 60
    g = (digest >>  8) % 160 + 60
    b = (digest      ) % 160 + 60
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Variables de entorno
# ---------------------------------------------------------------------------

def leer_env(ruta: str) -> dict:
    """Lee un archivo .env simple (KEY=VALUE) y devuelve un dict."""
    env = {}
    if not os.path.exists(ruta):
        return env
    with open(ruta, encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                env[clave.strip()] = valor.strip().strip("\"'")
    return env


# ---------------------------------------------------------------------------
# Formato de escala
# ---------------------------------------------------------------------------

def formato_escala(escala) -> str:
    """'Escala 1:5 000' con espacio como separador de miles."""
    return f"Escala 1:{escala:,}".replace(",", " ")


# ---------------------------------------------------------------------------
# Nombres de archivo
# ---------------------------------------------------------------------------

def sanitizar_nombre(texto: str) -> str:
    """Convierte texto con tildes/espacios en nombre de archivo seguro."""
    nfkd       = unicodedata.normalize("NFKD", texto)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("ASCII")
    limpio     = re.sub(r"[^\w\-]", "_", ascii_text)
    return re.sub(r"_+", "_", limpio).strip("_")


# ---------------------------------------------------------------------------
# Título legible para leyenda/simbología
# ---------------------------------------------------------------------------

def titulo_capa(cfg_capa: dict) -> str:
    """
    Nombre a mostrar como encabezado de capa en la leyenda del plano.

    `nombre_capa` es un identificador técnico (se usa para buscar la capa en
    el proyecto/PostGIS) y suele llevar guiones bajos, p. ej. "Tipo_de_Suelo".
    Si la config trae "titulo_capa" se usa tal cual; si no, se deriva
    reemplazando "_" por espacios (p. ej. "Tipo de Suelo").
    """
    titulo = cfg_capa.get("titulo_capa")
    if titulo:
        return titulo
    return cfg_capa.get("nombre_capa", "").replace("_", " ").strip()


# ---------------------------------------------------------------------------
# Validación de identificadores SQL
# ---------------------------------------------------------------------------

_ID_SEGURO = re.compile(r"^\w+$")


def valida_id(nombre: str, ctx: str) -> None:
    """Lanza ValueError si el nombre no es un identificador alfanumérico."""
    if not _ID_SEGURO.match(nombre):
        raise ValueError(f"Identificador inseguro en {ctx}: '{nombre}'")


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

# Handlers adicionales (p. ej. el panel de log del plugin) que crear_logger
# conserva cada vez que reconstruye el logger.
EXTRA_HANDLERS: list = []


def crear_logger(output_dir: str) -> logging.Logger:
    """Crea y devuelve un logger con handlers de archivo y consola."""
    os.makedirs(output_dir, exist_ok=True)
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = logging.getLogger("Composiciones")
    logger.setLevel(logging.INFO)
    for h in list(logger.handlers):
        h.close()
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
    fh  = logging.FileHandler(
        os.path.join(output_dir, f"log_{ts}.txt"), encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    for extra in EXTRA_HANDLERS:
        logger.addHandler(extra)
    return logger
