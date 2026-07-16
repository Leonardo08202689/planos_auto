# Generador Automático de Planos — SINERGIA

Script QGIS para generar composiciones cartográficas y exportarlas a PNG
de forma automática, a partir de capas PostGIS y plantillas QPT.

Además de los planos, cada corrida produce:

- **`index_planos.html`** — índice con miniaturas de todos los planos,
  su estado y liga al PNG. Ábrelo en el navegador para revisar
  la corrida completa de un vistazo.

## Estructura del proyecto

```
Planos_auto/
├── main.py                        ← Punto de entrada (consola de QGIS)
├── generar_planos.py              ← Orquestador principal
├── instalar_plugin.sh             ← Enlaza el plugin al perfil de QGIS
├── planos_auto_plugin/            ← Interfaz gráfica (plugin de QGIS)
│   ├── plugin.py                  ← Botón de barra + menú
│   └── dialogo.py                 ← Diálogo: proyecto, planos, DPI, log
├── core/
│   ├── utils.py                   ← Paleta, env, logger, sanitizar
│   ├── configuracion.py           ← Ensamblaje del CONFIG (global+proyecto+env)
│   ├── capas.py                   ← Carga PostGIS, extracción de vértices
│   ├── simbologia.py              ← Renderers, etiquetas PAL, opacidad
│   ├── composicion.py             ← Layouts, leyenda, grid, logo, labels
│   ├── exportar.py                ← Exportación a PNG
│   └── reportes.py                ← Índice HTML
├── config/
│   ├── global.json                ← IDs de layout, DPI, CRS
│   └── proyectos/
│       ├── plantilla.json         ← Proyecto plantilla (lista base de planos)
│       └── Magna.json             ← Proyecto real
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

## Uso con interfaz gráfica (plugin de QGIS)

Instalación (una sola vez):

```bash
./instalar_plugin.sh
```

Luego en QGIS: **Complementos → Administrar e instalar complementos →
Instalados → activar "Planos Auto"** (marca "Mostrar también complementos
experimentales" si no aparece). Queda un botón en la barra de herramientas.

Flujo:

1. Abre tu proyecto con la capa `poligono_trabajo` y **selecciona** el
   polígono en el mapa.
2. Clic en el botón **Planos Auto** → elige proyecto, marca los planos a
   generar, ajusta el DPI y pulsa **Generar planos**.
3. El log aparece en vivo en el propio diálogo (y también se guarda en la
   carpeta de salida, como siempre).

### Crear, editar o eliminar proyectos desde el plugin

Junto al combo de proyecto hay tres botones:

- **Nuevo proyecto…** — pide un identificador de archivo (el nombre del
  `.json`), nombre del proyecto, tipo de trámite, capa polígono y los
  valores por defecto de cada plano (columna de geometría, tipo de
  geometría, columna llave, escala, opacidad, grid).

  Como los planos casi siempre son los mismos entre proyectos (solo cambia
  la escala según el tamaño del predio), también puedes elegir
  **"Copiar planos de:"** otro proyecto existente y un **factor de
  escala** (1.0 = igual, 2.0 = el doble, 0.5 = la mitad). Se clona la
  lista completa de planos multiplicando `escala` y `grid_intervalo` de
  cada uno — el proyecto plantilla no se modifica. Si dejas
  "(ninguno)", el proyecto queda con `"capas": []` para editar el JSON
  a mano.
- **Editar datos…** — abre el mismo formulario precargado con los valores
  del proyecto seleccionado y los sobrescribe al guardar (sin tocar sus
  planos existentes ni la opción de plantilla, que solo aplica al crear).
  Cambiar el identificador de archivo renombra el `.json`.
- **Eliminar…** — borra el `.json` del proyecto seleccionado, previa
  confirmación (muestra cuántos planos define). Los PNG ya generados
  no se tocan.

Los campos avanzados por plano (tabla PostGIS, categoría, paleta, fuente,
overrides de ids/layout…) siguen editándose directamente en el JSON —
ver la estructura de `plantilla.json` más abajo.

Como el plugin se instala por symlink, los cambios en el repo se reflejan
al reabrir QGIS (o con el plugin "Plugin Reloader").

## Uso desde la consola Python (alternativa)

1. Abre QGIS y carga tu proyecto con la capa `poligono_trabajo`.
2. **Selecciona** el polígono del proyecto en el mapa.
3. Abre la consola Python de QGIS y ejecuta:

```python
exec(open('/home/leonardo/Codigos/Planos_auto/main.py').read())
```

### Regenerar solo algunos planos

En el plugin basta con marcar solo los planos deseados. Por consola,
edita en `main.py`:

```python
SOLO_CAPAS = ["Clima"]   # lista de 'nombre_capa'; vacía = todos
```

## Cambiar de proyecto

En el plugin se elige del combo "Proyecto". Por consola, edita la
variable `PROYECTO_ACTIVO` en `main.py`:

```python
PROYECTO_ACTIVO = "nombre_proyecto"   # debe existir en config/proyectos/
```

Luego crea `config/proyectos/nombre_proyecto.json` siguiendo la estructura
de `plantilla.json`.

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
| `sin_bbox_filter` | `true` | Carga la tabla completa sin filtro espacial |
| `layout_nombre` | nombre de QPT en `plantillas/` | Usa una plantilla alternativa |
| `marcador` | `"punto"` | Muestra la estrella del centroide en vez del polígono |

## Formatos de salida

En `config/global.json` (o por proyecto):

```json
"formatos": ["png"]
```
