"""
core/reportes.py — Reportes de apoyo al estudio:
  - CSV de superficies por categoría dentro del polígono (ha y %)
  - Índice HTML con miniaturas de todos los planos generados
"""

import csv
import html
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# Superficies por categoría
# ---------------------------------------------------------------------------

def reporte_superficies(capa_tematica, feature_poligono, crs, campo: str,
                        nombre_capa: str, output_dir: str, log):
    """
    Cruza la capa temática con el polígono del proyecto y escribe un CSV
    con la superficie (ha) y el porcentaje que ocupa cada categoría.
    Devuelve la ruta del CSV o None si no se pudo calcular.
    """
    # Imports locales para que el resto del módulo funcione fuera de QGIS
    import processing
    from qgis.core import (
        QgsDistanceArea,
        QgsFeature,
        QgsProject,
        QgsUnitTypes,
        QgsVectorLayer,
    )

    if not campo or capa_tematica.fields().lookupField(campo) == -1:
        return None

    poly_mem = QgsVectorLayer(
        f"Polygon?crs={crs.authid()}", "poligono_superficies_tmp", "memory"
    )
    f_poly = QgsFeature()
    f_poly.setGeometry(feature_poligono.geometry())
    poly_mem.dataProvider().addFeatures([f_poly])

    try:
        res = processing.run("native:intersection", {
            "INPUT": capa_tematica, "OVERLAY": poly_mem, "OUTPUT": "memory:",
        })
    except Exception as exc:
        log.warning(f" → No se pudo calcular superficies para '{nombre_capa}': {exc}")
        return None

    da = QgsDistanceArea()
    da.setSourceCrs(res["OUTPUT"].crs(), QgsProject.instance().transformContext())
    da.setEllipsoid("WGS84")

    superficies: dict = {}
    for feat in res["OUTPUT"].getFeatures():
        geom = feat.geometry()
        if geom.isEmpty():
            continue
        ha = da.convertAreaMeasurement(
            da.measureArea(geom), QgsUnitTypes.AreaHectares
        )
        clave = str(feat[campo])
        superficies[clave] = superficies.get(clave, 0.0) + ha

    total = sum(superficies.values())
    if not superficies or total <= 0:
        log.warning(f" → Intersección vacía; sin reporte de superficies para '{nombre_capa}'.")
        return None

    ruta = os.path.join(output_dir, f"superficies_{nombre_capa}.csv")
    # utf-8-sig para que Excel abra las tildes correctamente
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow([campo, "superficie_ha", "porcentaje"])
        for clave, ha in sorted(superficies.items(), key=lambda kv: -kv[1]):
            writer.writerow([clave, f"{ha:.4f}", f"{100 * ha / total:.2f}"])
        writer.writerow(["TOTAL", f"{total:.4f}", "100.00"])

    log.info(
        f" ✓ Superficies: {len(superficies)} categoría(s), "
        f"{total:.2f} ha → {os.path.basename(ruta)}"
    )
    return ruta


# ---------------------------------------------------------------------------
# Índice HTML de planos generados
# ---------------------------------------------------------------------------

def generar_indice_html(resultados: list, output_dir: str,
                        nombre_proyecto: str, log) -> str:
    """
    Escribe index_planos.html en 'output_dir' con una miniatura por plano,
    su estado y ligas a PNG/PDF/CSV. 'resultados' es una lista de dicts:
      {nombre_plano, escala, png, pdf, csv, exito}
    """
    tarjetas = []
    for r in resultados:
        nombre = html.escape(r.get("nombre_plano", ""))
        escala = r.get("escala")
        exito  = r.get("exito", False)

        if exito and r.get("png"):
            img = os.path.basename(r["png"])
            cuerpo = (
                f'<a href="{img}" target="_blank">'
                f'<img src="{img}" alt="{nombre}" loading="lazy"></a>'
            )
        else:
            cuerpo = '<div class="sin-img">✗ No generado</div>'

        ligas = []
        for fmt in ("png", "pdf", "csv"):
            if r.get(fmt):
                ligas.append(
                    f'<a href="{os.path.basename(r[fmt])}" target="_blank">'
                    f'{fmt.upper()}</a>'
                )
        info = f"Escala 1:{escala:,}".replace(",", " ") if escala else ""

        tarjetas.append(f"""
      <div class="tarjeta {'ok' if exito else 'error'}">
        {cuerpo}
        <h3>{nombre}</h3>
        <p>{info}</p>
        <p class="ligas">{' · '.join(ligas)}</p>
      </div>""")

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_ok  = sum(1 for r in resultados if r.get("exito"))
    contenido = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Planos — {html.escape(nombre_proyecto)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f5f5f2; color: #222; }}
  h1 {{ font-size: 1.4rem; }} .meta {{ color: #666; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.2rem; }}
  .tarjeta {{ background: #fff; border-radius: 8px; padding: .8rem; box-shadow: 0 1px 4px rgba(0,0,0,.12); }}
  .tarjeta img {{ width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; }}
  .tarjeta h3 {{ font-size: .95rem; margin: .5rem 0 .2rem; }}
  .tarjeta p {{ margin: .15rem 0; font-size: .85rem; color: #555; }}
  .tarjeta.error {{ outline: 2px solid #d9534f; }}
  .sin-img {{ padding: 3rem 0; text-align: center; color: #d9534f; font-weight: bold; }}
  .ligas a {{ color: #2a6db0; }}
</style>
</head>
<body>
<h1>{html.escape(nombre_proyecto)}</h1>
<p class="meta">Generado: {fecha} — {n_ok}/{len(resultados)} planos exitosos</p>
<div class="grid">{''.join(tarjetas)}
</div>
</body>
</html>
"""
    ruta = os.path.join(output_dir, "index_planos.html")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(contenido)
    log.info(f" ✓ Índice HTML: {ruta}")
    return ruta
