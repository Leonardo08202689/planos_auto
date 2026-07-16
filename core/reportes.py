"""
core/reportes.py — Reportes de apoyo al estudio:
  - Índice HTML con miniaturas de todos los planos generados
"""

import html
import os
from datetime import datetime


# ---------------------------------------------------------------------------
# Índice HTML de planos generados
# ---------------------------------------------------------------------------

def generar_indice_html(resultados: list, output_dir: str,
                        nombre_proyecto: str, log) -> str:
    """
    Escribe index_planos.html en 'output_dir' con una miniatura por plano,
    su estado y liga al PNG. 'resultados' es una lista de dicts:
      {nombre_plano, escala, png, exito}
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
        for fmt in ("png",):
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
