"""
actualizar.py — Descarga la última versión del repo desde GitHub y la
aplica sobre la instalación local, sin necesitar git ni terminal.
"""

import os
import shutil
import tempfile
import urllib.request
import zipfile

_ZIP_URL = "https://github.com/Leonardo08202689/planos_auto/archive/refs/heads/main.zip"


def buscar_actualizacion(base: str) -> None:
    """
    Descarga el ZIP más reciente de GitHub, lo extrae, y copia su contenido
    sobre 'base' (la carpeta del proyecto). No toca archivos que no vienen
    en el repo (.env, config/proyectos/*.json reales, salida/, cache/,
    etc. — todos en .gitignore, así que ni siquiera están en el ZIP).

    Lanza RuntimeError con un mensaje entendible si algo falla (red,
    ZIP corrupto), para que quien llame lo muestre en un QMessageBox.
    """
    with tempfile.TemporaryDirectory() as tmp:
        ruta_zip = os.path.join(tmp, "planos_auto.zip")
        try:
            urllib.request.urlretrieve(_ZIP_URL, ruta_zip)
        except Exception as e:
            raise RuntimeError(
                "No se pudo descargar la actualización. Revisa tu conexión "
                f"a internet.\n\nDetalle: {e}"
            )

        try:
            with zipfile.ZipFile(ruta_zip) as zf:
                zf.extractall(tmp)
        except zipfile.BadZipFile:
            raise RuntimeError(
                "El archivo descargado no es un ZIP válido; inténtalo de nuevo."
            )

        # GitHub empaqueta el contenido dentro de una subcarpeta tipo
        # 'planos_auto-main'; se busca esa carpeta dentro de lo descomprimido.
        candidatos = [
            d for d in os.listdir(tmp)
            if os.path.isdir(os.path.join(tmp, d)) and d.lower().startswith("planos_auto")
        ]
        if not candidatos:
            raise RuntimeError(
                "No se encontró la carpeta del proyecto dentro del ZIP descargado."
            )
        origen = os.path.join(tmp, candidatos[0])

        shutil.copytree(origen, base, dirs_exist_ok=True)
