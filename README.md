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

Las capas de referencia (vías, ríos, canales) que usa `capas_extra` viven en
el esquema `cartografia_base` (no `proyectos`, que es para las capas
temáticas de cada trámite), siguiendo el mismo patrón: se agregan con
`"tabla_postgis"` dentro de cada entrada de `capas_extra.capas`. El ráster
del plano de Localización también vive en PostGIS (esquema
`cartografia_base`, subido con `raster2pgsql`), referenciado con
`"tabla_postgis_raster"` en vez de `"ruta_raster"`:

```bash
raster2pgsql -s <SRID> -I -C -M -t 256x256 "/ruta/al/archivo.tif" \
  cartografia_base.nombre_tabla | psql -h <host> -p <puerto> -U qgis_user -d gis_empresa
```

La única excepción real que sigue siendo un archivo por diseño es el
GeoPackage de `FIGURA. VÍAS DE ACCESO AL SITIO` (`rutas_acceso`): se genera
por proyecto con `herramientas/rutas_cli.py`, no es un dato de referencia
fijo compartible entre proyectos.

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
   "Acceso a la base de datos" más abajo). Si necesitas cambiarlos
   después, hay un botón **"Conexión…"** dentro del plugin.

Cuando haya una actualización del programa, no hace falta repetir todo
esto: el botón **"Buscar actualizaciones…"** dentro del plugin descarga
la versión más reciente de GitHub y la aplica solo (sin tocar tu conexión,
tus proyectos ni tus planos ya generados) — solo hay que cerrar y volver a
abrir QGIS después para que tome el código nuevo.

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

## Acceso a la base de datos (otras computadoras)

La base de datos (PostgreSQL/PostGIS) vive en un contenedor Docker en el
**NAS Synology de la oficina** (`scianas`, DS224+), no en la máquina de
Leonardo — así el servidor está disponible sin depender de que una compu de
trabajo se quede encendida.

**Configuración actual (2026-08-05):**

- Servidor: contenedor `postgis/postgis` en el NAS, puerto **`55432`**
  (no el 5432 estándar — ya estaba ocupado por otro servicio del NAS).
- Datos persistentes en una carpeta compartida del NAS (`postgis_data/data`),
  sobreviven reinicios/actualizaciones del contenedor. Reinicio automático
  del contenedor habilitado.
- **Tailscale activo en el NAS** (paquete oficial de Synology): el servidor
  es alcanzable tanto dentro de la red de oficina como desde cualquier
  otro lugar (ej. desde casa), sin abrir puertos al internet público.
  IP de Tailscale del NAS: **`100.105.239.92`**. Cada colega que necesite
  conectarse desde fuera de la oficina instala Tailscale en su compu
  ([tailscale.com/download](https://tailscale.com/download)) y se
  autentica con la cuenta del equipo — sin eso, solo funciona la IP de
  LAN (`192.168.100.132`), útil estando en la oficina.
- **Usar la IP, no el nombre `scianas.local`:** aunque el NAS resuelve por
  mDNS y una terminal normal sí encuentra `scianas.local`, **QGIS (Flatpak
  en Linux) no puede resolver nombres `.local`** — hay que usar siempre
  una IP (de LAN o de Tailscale, según el caso).
- Dos roles en la base (mismos permisos que la base anterior, migrados tal
  cual):
  - `qgis_user` — lectura y escritura (para administradores).
  - `planos_lector` — solo lectura (`GRANT SELECT`, sin permisos de escritura;
    incluye `ALTER DEFAULT PRIVILEGES` para que las tablas nuevas que se suban
    después también queden visibles automáticamente).
- Todas las capas de referencia que antes eran archivos locales (vías,
  ríos, canales, y el ráster topográfico de Localización) ya viven en
  PostGIS (esquema `cartografia_base`, el ráster como PostGIS raster) —
  cualquier compu configurada con la conexión correcta ya las ve, sin
  copiar ningún archivo aparte.

**Para dar acceso a un colega nuevo:**

1. El colega instala QGIS + el plugin siguiendo "Instalación para un colega"
   más arriba (descarga ZIP, doble clic en `Instalar.bat`/`instalar_plugin.sh`
   — sin terminal). La primera vez que abra el plugin le va a pedir estos
   datos en un formulario (botón **"Conexión…"**):
   - **Dirección del servidor:** `192.168.100.132:55432` si va a trabajar
     desde la oficina, o `100.105.239.92:55432` (IP de Tailscale) si
     necesita conectarse desde otro lado — puerto y dirección van juntos
     separados por `:`.
   - **¿Es administrador?**: solo si va a poder editar la base de datos.
   - **Contraseña:** la del rol que le corresponda (`qgis_user` si es
     administrador, `planos_lector` si no).
   - **Carpeta de salida:** donde se guardarán sus PNG, la elige con el
     explorador de archivos.
2. Si va a conectarse desde fuera de la oficina, también instala Tailscale
   en su compu y se autentica con la cuenta del equipo (paso aparte, no lo
   hace el plugin).

Esos datos (sobre todo la contraseña) se le pasan por un canal aparte —
WhatsApp, correo, etc. — nunca por este repo.

⚠️ **Pendiente:** `FIGURA. VÍAS DE ACCESO AL SITIO` sigue dependiendo de un
GeoPackage generado por proyecto con `herramientas/rutas_cli.py` (no es un
dato de referencia fijo, así que no se migra a PostGIS). En una compu sin
ese archivo, el plano ya no falla — se genera igual con el mapa base y el
punto del proyecto, solo sin las rutas trazadas.

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
