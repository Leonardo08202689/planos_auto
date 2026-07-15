# Generador Automático de Planos — SINERGIA

Script QGIS para generar composiciones cartográficas y exportarlas a PNG/PDF
de forma automática, a partir de capas PostGIS y plantillas QPT.

Además de los planos, cada corrida produce:

- **`superficies_<capa>.csv`** — hectáreas y % del polígono por categoría
  (suelos, vegetación, etc.), listo para pegar en el estudio.
- **`index_planos.html`** — índice con miniaturas de todos los planos,
  su estado y ligas a PNG/PDF/CSV. Ábrelo en el navegador para revisar
  la corrida completa de un vistazo.

## Estructura del proyecto

```
Planos_auto/
├── main.py                        ← Punto de entrada (ejecutar en QGIS)
├── generar_planos.py              ← Orquestador principal
├── core/
│   ├── utils.py                   ← Paleta, env, logger, sanitizar
│   ├── capas.py                   ← Carga PostGIS, extracción de vértices
│   ├── simbologia.py              ← Renderers, etiquetas PAL, opacidad
│   ├── composicion.py             ← Layouts, leyenda, grid, logo, labels
│   ├── exportar.py                ← Exportación a PNG/PDF
│   └── reportes.py                ← CSV de superficies + índice HTML
├── config/
│   ├── global.json                ← IDs de layout, DPI, CRS
│   └── proyectos/
│       └── sonitronies_concise.json  ← Capas y metadata del proyecto
├── plantillas/
│   ├── Plantilla_Corporativa.qpt
│   └── Plantilla_figuras.qpt
├── estilos/                       ← Archivos QML por capa
├── assets/
│   └── logo_sinergia.jpg
├── salida/                        ← PNGs generados (en .gitignore)
├── .env                           ← Credenciales (en .gitignore)
└── .env.example                   ← Plantilla de credenciales
```

## Uso rápido

1. Abre QGIS y carga tu proyecto con la capa `poligono_trabajo`.
2. **Selecciona** el polígono del proyecto en el mapa.
3. Abre la consola Python de QGIS y ejecuta:

```python
exec(open('/home/leonardo/Codigos/Planos_auto/main.py').read())
```

### Regenerar solo algunos planos

Para no correr las 11 capas cuando solo ajustaste una, edita en `main.py`:

```python
SOLO_CAPAS = ["Clima"]   # lista de 'nombre_capa'; vacía = todos
```

## Cambiar de proyecto

Edita únicamente la variable `PROYECTO_ACTIVO` en `main.py`:

```python
PROYECTO_ACTIVO = "nombre_proyecto"   # debe existir en config/proyectos/
```

Luego crea `config/proyectos/nombre_proyecto.json` siguiendo la estructura
de `sonitronies_concise.json`.

## Variables de entorno (`.env`)

Copia `.env.example` → `.env` y llena tus valores:

```
PG_HOST=localhost
PG_PORT=5432
PG_DBNAME=gis_empresa
PG_SCHEMA=proyectos
PG_USER=qgis_user
PG_PASSWORD=tu_contraseña
OUTPUT_BASE=/ruta/a/planos_salida
LOGO_RUTA=/ruta/al/logo.jpg   # opcional, usa assets/logo_sinergia.jpg por defecto
```

## Agregar una nueva capa a un proyecto

En el JSON del proyecto añade un objeto al array `"capas"`:

```json
{
  "tabla_postgis":   "mi_nueva_tabla",
  "nombre_plano":    "Plano. Mi Nueva Capa",
  "nombre_capa":     "Mi_Capa",
  "escala":          10000,
  "geom_col":        "geom",
  "tipo_geom":       "MultiPolygon",
  "key":             "gid",
  "campo_categoria": "campo_color",
  "campo_etiqueta":  "campo_color",
  "paleta":          "vegetacion",
  "opacidad":        0.6,
  "grid_intervalo":  500,
  "fuente":          "Fuente del dato."
}
```

Campos opcionales adicionales:

| Campo | Valores | Efecto |
|-------|---------|--------|
| `paleta` | `default`, `suelos`, `geologia`, `clima`, `vegetacion`, `agua`, `conservacion` | Paleta de colores temática del renderer categorizado |
| `estilo_qml` | nombre de archivo en `estilos/` | Aplica un QML en vez del renderer categorizado |
| `reporte_superficies` | `true`/`false` (default `true`) | Genera o no el CSV de superficies |
| `sin_bbox_filter` | `true` | Carga la tabla completa sin filtro espacial |
| `layout_nombre` | nombre de QPT en `plantillas/` | Usa una plantilla alternativa |
| `marcador` | `"punto"` | Muestra la estrella del centroide en vez del polígono |

## Formatos de salida

En `config/global.json` (o por proyecto):

```json
"formatos": ["png", "pdf"]
```
