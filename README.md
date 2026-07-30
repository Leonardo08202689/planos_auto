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
│   ├── dialogo.py                 ← Diálogo: proyecto, planos, DPI, log
│   └── editor_proyecto.py         ← Formulario de metadata/defaults del proyecto
├── core/
│   ├── utils.py                   ← Paletas, env, logger, sanitizar
│   ├── configuracion.py           ← Ensamblaje del CONFIG (global+proyecto+env) y validación
│   ├── capas.py                   ← Carga PostGIS, recorte/reproyección, extracción de vértices
│   ├── mapitas.py                 ← Insertos de localización (nacional/estatal/municipal)
│   ├── simbologia.py              ← Renderers, patrones de relleno, etiquetas PAL, opacidad
│   ├── composicion.py             ← Layouts, leyenda, grid, logo, labels, barra de escala
│   ├── exportar.py                ← Exportación a PNG
│   └── reportes.py                ← Índice HTML
├── config/
│   ├── global.json                ← IDs de layout, DPI, CRS, config de mapitas
│   └── proyectos/                 ← Un .json por proyecto (nombre de archivo = identificador)
│       ├── plantilla.json         ← Plantilla base (todos los planos/figuras disponibles)
│       ├── Plantilla_LAI.json     ← Plantilla curada para trámites de Licencia Ambiental Integral
│       └── *.json                 ← Proyectos reales, uno por trámite (NO se suben a Git, ver abajo)
├── plantillas/
│   ├── Plantilla_Corporativa.qpt  ← Layout de "Plano" (3 insertos: nacional/estatal/municipal)
│   └── Plantilla_figuras.qpt      ← Layout de "Figura" (1 inserto de localización)
├── estilos/                       ← Archivos QML por capa
├── assets/
│   └── logo_sinergia.jpg
├── salida/                        ← PNGs generados (en .gitignore)
├── .env                           ← Credenciales (en .gitignore)
└── .env.example                   ← Plantilla de credenciales
```

## Todas las capas viven en PostGIS

Ninguna capa de un plano o figura debe apuntar a un archivo local (shapefile,
GeoPackage suelto, etc.) — eso solo funciona en la máquina donde se creó. Si
necesitas agregar una capa nueva a partir de un archivo:

```bash
ogr2ogr -f "PostgreSQL" PG:"host=localhost port=5432 dbname=gis_empresa user=qgis_user password=$PGPASS" \
  "/ruta/al/archivo.shp" -nln nombre_tabla -lco SCHEMA=proyectos \
  -lco GEOMETRY_NAME=geom -lco FID=gid -nlt MULTIPOLYGON
```

Esto sigue la misma convención que las tablas existentes (`aica_nacional`,
`anp_estatales`, `uab_nacional`, …): PK `gid`, geometría en `geom`. Ojo:
`ogr2ogr` convierte los nombres de campo a minúsculas por default — usa esos
nombres (no los del archivo original) en `campo_categoria`/`campo_etiqueta`.
Luego el plano se agrega al JSON con `"tabla_postgis": "nombre_tabla"` como
cualquier otro.

Las únicas excepciones (por diseño, no por atajo) son el ráster del plano de
localización (`ruta_raster`) y los GeoPackage de referencia/topografía usados
como `capas_extra` o en `rutas_acceso` — esos sí son intrínsecamente archivos.

## Uso con interfaz gráfica (plugin de QGIS)

### Instalación para un colega (sin usar terminal)

1. Instala QGIS (instalador normal, como cualquier programa) y ábrelo una
   vez.
2. Descarga el proyecto: en la página de GitHub del repo, botón verde
   **"Code" → "Download ZIP"**, y descomprímelo donde quieras.
3. Adentro de esa carpeta:
   - **Windows:** doble clic en **`Instalar.bat`**.
   - **Linux:** clic derecho en **`instalar_plugin.sh`** → **"Ejecutar"**
     (o doble clic, según el gestor de archivos).
4. En QGIS: **Complementos → Administrar e instalar complementos →
   Instalados → activar "Planos Auto"** (marca "Mostrar también complementos
   experimentales" si no aparece). Queda un botón en la barra de
   herramientas.
5. La primera vez que abras el plugin te va a pedir configurar la conexión
   al servidor: dirección, si eres administrador, contraseña y carpeta
   donde guardar los planos — todo con un formulario, sin editar ningún
   archivo. Esos datos te los da quien administra el servidor (ver
   "Acceso remoto a la base de datos" más abajo). Si necesitas cambiarlos
   después, hay un botón **"Conexión…"** dentro del plugin.

(Instalación técnica equivalente por terminal, para quien prefiera `git
clone` + `./instalar_plugin.sh` / `powershell -ExecutionPolicy Bypass -File
.\instalar_plugin.ps1`: funciona igual, ambos scripts solo enlazan
`planos_auto_plugin/` a la carpeta de plugins del perfil de QGIS sin copiar
archivos, así que actualizar el repo actualiza el plugin al instante.)

Flujo de uso:

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

**Los proyectos reales son personales de cada computadora**, no se comparten
por Git (por confidencialidad de clientes) — solo `plantilla.json` y
`Plantilla_LAI.json` vienen con el repo. Cada quien crea sus propios proyectos
localmente (desde el plugin, botón **"Nuevo proyecto…"**, o copiando una
plantilla a mano). Si necesitas pasarle un proyecto específico a un colega,
comparte ese `.json` por fuera del repo (correo, carpeta compartida, etc.), no
lo subas a Git.

## Variables de entorno (`.env`)

Si usas el plugin, el botón **"Conexión…"** genera este archivo por ti (ver
"Instalación para un colega" arriba) — no hace falta tocarlo a mano. Esta
sección es para uso por consola o edición manual:

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

## Acceso remoto a la base de datos (otras computadoras)

La base de datos (PostgreSQL/PostGIS) vive en la máquina de Leonardo. Para que otra
computadora (en otra oficina, no en la misma red) se conecte, se usa
[Tailscale](https://tailscale.com) (VPN gratuita, cifrada, no requiere abrir puertos
al internet público) en vez de exponer el puerto 5432 directamente.

**Configuración del lado del servidor** (ya hecha, documentado para referencia):

- Tailscale instalado en la máquina con la base de datos; su IP de Tailscale se
  obtiene con `tailscale ip -4`.
- `postgresql.conf` → `listen_addresses` incluye esa IP de Tailscale (además de
  `localhost`), no `'*'`.
- `pg_hba.conf` → una regla `host gis_empresa <rol> 100.64.0.0/10 scram-sha-256`
  por cada rol autorizado (100.64.0.0/10 es el rango interno de Tailscale).
- Dos roles en la base:
  - `qgis_user` — lectura y escritura (para administradores).
  - `planos_lector` — solo lectura (`GRANT SELECT`, sin permisos de escritura;
    incluye `ALTER DEFAULT PRIVILEGES` para que las tablas nuevas que se suban
    después también queden visibles automáticamente).

**Para dar acceso a un colega nuevo:**

1. Compartir la máquina servidor desde el panel de Tailscale
   (https://login.tailscale.com/admin/machines → menú de la máquina → **Share**)
   con el correo del colega. Él necesita su propia cuenta de Tailscale (gratis).
2. El colega instala Tailscale (instalador normal) en su computadora y acepta
   la invitación.
3. El colega instala QGIS + el plugin siguiendo "Instalación para un colega"
   más arriba (descarga ZIP, doble clic en `Instalar.bat`/`instalar_plugin.sh`
   — sin terminal). La primera vez que abra el plugin le va a pedir estos
   datos en un formulario (botón **"Conexión…"**):
   - **Dirección del servidor:** la IP de Tailscale, ej. `100.77.90.48`.
   - **¿Es administrador?**: solo si va a poder editar la base de datos.
   - **Contraseña:** la del rol que le corresponda (`qgis_user` si es
     administrador, `planos_lector` si no).
   - **Carpeta de salida:** donde se guardarán sus PNG, la elige con el
     explorador de archivos.

Esos datos (sobre todo la contraseña) se le pasan por un canal aparte —
WhatsApp, correo, etc. — nunca por este repo.

⚠️ **Pendiente:** dos planos siguen dependiendo de archivos locales que solo
existen en la máquina de Leonardo, y por diseño (ver sección "Todas las capas
viven en PostGIS") no se migran a PostGIS porque no son datos temáticos fijos:

- `PLANO. LOCALIZACIÓN` — el ráster topográfico (`ruta_raster`).
- `PLANO. HIDROLOGÍA SUPERFICIAL` / `PLANO. LOCALIZACIÓN` — el GeoPackage
  `cnit50k.gpkg` de vías/ríos/canales usado como `capas_extra`.
- `FIGURA. RUTAS DE ACCESO` — su GeoPackage se genera por proyecto con
  `herramientas/rutas_cli.py`, no es un dato de referencia fijo.

Esos planos no van a funcionar todavía en otra computadora sin copiar esos
archivos ahí. (El shapefile de ANP Federal ya se migró a PostGIS —
`proyectos.anp_federales` — y funciona igual que sus tablas hermanas.)

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
| `titulo_capa` | texto | Nombre a mostrar en la leyenda (si no, se deriva de `nombre_capa`) |
| `paleta` | `default`, `suelos`, `geologia`, `clima`, `vegetacion`, `agua`, `conservacion` | Paleta de colores temática del renderer categorizado |
| `campo_etiqueta_expresion` | expresión QGIS (p. ej. `concat("uga", ', ', "clave")`) | Etiqueta sobre el mapa combinando varios campos, en vez de uno solo (`campo_etiqueta`) |
| `campo_legenda_extra` | nombre de campo | Muestra "valor, valor_extra" en cada categoría de la leyenda (asume relación 1:1 con `campo_categoria`) |
| `leyenda_solo_ubicacion` | `true` | En capas de zonificación regional (`campo_categoria`), la leyenda solo nombra la categoría donde cae el centroide del proyecto, no todas las visibles en el extent (p. ej. UAB: el mapa muestra las regiones vecinas de contexto, pero la leyenda solo dice en cuál está el proyecto) |
| `estilo_qml` | nombre de archivo en `estilos/` | Aplica un QML en vez del renderer categorizado |
| `sin_bbox_filter` | `true` | Carga la tabla completa sin filtro espacial (necesario para capas de cobertura nacional dispersa, p. ej. AICA/RHP) |
| `layout_nombre` | nombre de QPT en `plantillas/` | Usa una plantilla alternativa (`Plantilla_Corporativa` = plano, `Plantilla_figuras` = figura) |
| `marcador` | `"punto"` \| `"poligono"` | Punto (estrella) o contorno del polígono como referencia. Default: `"poligono"` en planos normales, `"punto"` en ráster/`capas_combinadas` |
| `opacidad` | `0.0`–`1.0` | Transparencia de la capa (funciona también para el ráster de localización) |
| `grid_intervalo` | metros | Separación de la cuadrícula del mapa |
| `barra_escala_segmento` | metros | Unidades por segmento de la barra de escala (solo planos `raster`) |

### Tipos especiales de plano (`"tipo"`)

Además del flujo normal (una tabla PostGIS categorizada), hay flujos dedicados:

| `tipo` | Uso | Claves relevantes |
|--------|-----|--------------------|
| `vertices` | Plano de vértices del polígono del proyecto | — |
| `raster` | Plano de localización sobre un ráster (mapa topográfico) | `ruta_raster`, `capas_extra` (vías de referencia desde un GeoPackage), `barra_escala_segmento` |
| `rutas_acceso` | Figura de rutas hacia el sitio, extent ajustado al conjunto de rutas | `ruta_gpkg` (generado aparte con `herramientas/rutas_cli.py`), `capas_rutas`, `capa_destino`, `capa_entrada` |
| `capas_combinadas` | Varias tablas PostGIS superpuestas en un mismo plano (p. ej. "Áreas Naturales Protegidas" = ANP federal/estatal + AICA + RTP + RHP) | `capas_postgis` (lista de specs con `tabla_postgis`, `color`, `color_borde`, `patron`, `estilo_borde`, `campo_etiqueta`) |

Los `patron` disponibles para `capas_combinadas` son `solid`, `cross`,
`horizontal`, `vertical`, `f_diagonal`, `b_diagonal` — cada capa lleva un
relleno sólido más un patrón de líneas superpuesto (no en vez del color), para
que se distingan entre sí sin verse deslavadas.

## Insertos de localización (mapitas)

Cada composición trae hasta 3 mapas pequeños de contexto (nacional/estatal/
municipal), configurados en `config/global.json → mapitas.mapitas_layout`,
por plantilla:

```json
"mapitas_layout": {
  "Plantilla_Corporativa": {
    "Mapa 2": { "nivel": "nacional"  },
    "Mapa 3": { "nivel": "estatal"   },
    "Mapa 4": { "nivel": "municipal" }
  },
  "Plantilla_figuras": {
    "Mapa 2": { "nivel": "estatal" }
  }
}
```

`Plantilla_figuras` solo tiene un inserto ("Mapa 2"), configurado en
`"estatal"` (estado con el municipio del proyecto resaltado).

## Panel de Capas en QGIS

Cada plano/figura genera su propio subgrupo dentro de "Planos Generados" en
el panel de Capas, nombrado igual que su `nombre_plano`. El fondo satelital y
la estrella del centroide del proyecto (compartidos por todos los planos)
quedan al nivel superior del grupo, fuera de los subgrupos.

## Formatos de salida

En `config/global.json` (o por proyecto):

```json
"formatos": ["png"]
```
