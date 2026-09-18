# Generador Automático de Planos — SINERGIA

Plugin y script de QGIS que genera composiciones cartográficas completas
(planos y figuras de un trámite ambiental) y las exporta a PNG de forma
automática, a partir de capas PostGIS y plantillas QPT.

Cada corrida produce, además de los PNG, un **`index_planos.html`**: índice
con miniaturas de todos los planos, su estado (generado / fallido / omitido)
y liga al archivo. Ábrelo en el navegador para revisar la corrida completa de
un vistazo.

## Contenido

1. [Qué necesitas antes de empezar](#qué-necesitas-antes-de-empezar)
2. [Instalación (sin terminal)](#instalación-sin-terminal)
3. [Uso diario con el plugin](#uso-diario-con-el-plugin)
4. [Proyectos: crear, editar, clonar](#proyectos-crear-editar-clonar)
5. [Uso desde la consola Python](#uso-desde-la-consola-python-alternativa)
6. [Estructura del repositorio](#estructura-del-repositorio)
7. [Todas las capas viven en PostGIS](#todas-las-capas-viven-en-postgis)
8. [Configuración de un plano (referencia de campos)](#configuración-de-un-plano-referencia-de-campos)
9. [Tipos especiales de plano](#tipos-especiales-de-plano-tipo)
10. [Plantillas de layout y mapitas](#plantillas-de-layout-y-mapitas)
11. [Conexión y variables de entorno](#conexión-y-variables-de-entorno)
12. [Acceso a la base de datos (otras computadoras)](#acceso-a-la-base-de-datos-otras-computadoras)
13. [Fuentes de datos](#fuentes-de-datos)
14. [Pendientes conocidos](#pendientes-conocidos)

---

## Qué necesitas antes de empezar

- **QGIS** instalado (instalador normal; el plugin se prueba con 3.34+).
- **Acceso a la base de datos PostGIS** de la oficina — dirección, usuario y
  contraseña te los da quien administra el servidor (ver
  [Acceso a la base de datos](#acceso-a-la-base-de-datos-otras-computadoras)).
- Un **proyecto de QGIS con la capa del polígono del predio** (por convención
  `poligono_trabajo`). Es el único dato que aporta el usuario; todo lo demás
  sale de PostGIS.

## Instalación (sin terminal)

1. Instala QGIS y ábrelo una vez.
2. Descarga el proyecto: en la página de GitHub del repo, botón verde
   **"Code" → "Download ZIP"**, y descomprímelo donde quieras.
3. Dentro de esa carpeta:
   - **Windows:** doble clic en **`Instalar.bat`**.
   - **Linux:** clic derecho en **`instalar_plugin.sh`** → **"Ejecutar"**.
4. En QGIS: **Complementos → Administrar e instalar complementos →
   Instalados → activar "Planos Auto"** (marca "Mostrar también complementos
   experimentales" si no aparece). Queda un botón en la barra de herramientas.
5. La primera vez que abras el plugin te pedirá configurar la conexión al
   servidor: dirección, si eres administrador, contraseña y carpeta donde
   guardar los planos — todo con un formulario, sin editar archivos. Para
   cambiarlos después: botón **"Conexión…"** dentro del plugin.

**Actualizaciones:** el botón **"Buscar actualizaciones…"** dentro del plugin
descarga la versión más reciente de GitHub y la aplica solo, sin tocar tu
conexión, tus proyectos ni tus planos ya generados. Después hay que cerrar y
volver a abrir QGIS para que tome el código nuevo.

<details>
<summary>Instalación por terminal (equivalente)</summary>

```bash
git clone <url-del-repo> && cd planos_auto
./instalar_plugin.sh                                              # Linux/macOS
powershell -ExecutionPolicy Bypass -File .\instalar_plugin.ps1    # Windows
```

Ambos scripts solo **enlazan** (symlink) `planos_auto_plugin/` a la carpeta de
plugins del perfil de QGIS, sin copiar archivos: actualizar el repo actualiza
el plugin al instante (basta reabrir QGIS o usar "Plugin Reloader").
</details>

## Uso diario con el plugin

1. Abre tu proyecto de QGIS con la capa del polígono y **selecciónalo en el
   mapa** (el polígono seleccionado define el encuadre de todos los planos).
2. Clic en el botón **Planos Auto** → elige el proyecto, marca los planos a
   generar, ajusta el DPI y pulsa **Generar planos**.
3. El log aparece en vivo en el propio diálogo y se guarda en la carpeta de
   salida junto con los PNG y el `index_planos.html`.

### Botones del diálogo

| Botón | Qué hace |
|-------|----------|
| **Generar planos** | Corre la generación de los planos marcados |
| **Todas / Ninguna** | Marca o desmarca toda la lista de planos |
| **Guardar capas generadas…** | Exporta a un GeoPackage las capas temporales que quedaron en el panel de Capas (polígonos recortados, centroides, capas extra). Vive solo en la sesión de QGIS: sin esto se pierden al cerrar. Tras guardar, las capas del proyecto se reapuntan al GeoPackage y el plugin ofrece guardar también el `.qgz` |
| **Nuevo proyecto… / Editar datos… / Eliminar…** | Gestión de proyectos (ver abajo) |
| **Conexión…** | Formulario de servidor, usuario, contraseña y carpeta de salida (escribe el `.env`) |
| **Buscar actualizaciones…** | Descarga y aplica la última versión del repo |

### Panel de Capas en QGIS

Cada plano/figura genera su propio subgrupo dentro de **"Planos Generados"**,
nombrado igual que su `nombre_plano`. El fondo satelital y la estrella del
centroide del proyecto (compartidos por todos los planos) quedan al nivel
superior del grupo, fuera de los subgrupos.

## Proyectos: crear, editar, clonar

Un "proyecto" es un archivo `config/proyectos/<identificador>.json` que define
el nombre del trámite, la capa del polígono y la lista de planos a generar.

- **Nuevo proyecto…** — pide identificador de archivo, nombre del proyecto,
  tipo de trámite, capa polígono y los valores por defecto de cada plano
  (columna de geometría, tipo de geometría, columna llave, escala, opacidad,
  grid).

  Como los planos casi siempre son los mismos entre proyectos (solo cambia la
  escala según el tamaño del predio), también puedes elegir **"Copiar planos
  de:"** otro proyecto existente y un **factor de escala** (1.0 = igual,
  2.0 = el doble, 0.5 = la mitad). Se clona la lista completa multiplicando
  `escala` y `grid_intervalo` de cada plano; el proyecto origen no se modifica.
  Con "(ninguno)" el proyecto queda con `"capas": []` para editarlo a mano.
- **Editar datos…** — mismo formulario precargado; sobrescribe los datos
  generales sin tocar los planos existentes. Cambiar el identificador renombra
  el `.json`.
- **Eliminar…** — borra el `.json` previa confirmación (muestra cuántos planos
  define). Los PNG ya generados no se tocan.

Los campos avanzados por plano (tabla PostGIS, categoría, paleta, fuente,
overrides de ids/layout…) se editan directamente en el JSON — ver
[referencia de campos](#configuración-de-un-plano-referencia-de-campos).

### Plantillas incluidas

| Archivo | Para qué |
|---------|----------|
| `plantilla.json` | Base completa: todos los planos y figuras disponibles |
| `Plantilla_LAI.json` | Subconjunto curado para Licencia Ambiental Integral (18 planos) |
| `Plantilla_LAI_Municipal.json` | Subconjunto reducido para trámites municipales (9 planos) |

> **Los proyectos reales son personales de cada computadora** y no se comparten
> por Git (confidencialidad de clientes): `.gitignore` solo deja pasar las tres
> plantillas de arriba. Si necesitas pasarle un proyecto a un colega, mándale
> ese `.json` por fuera del repo.

## Uso desde la consola Python (alternativa)

1. Abre QGIS con tu proyecto y **selecciona** el polígono.
2. En la consola Python de QGIS:

```python
exec(open('/ruta/a/planos_auto/main.py').read())
```

Dentro de `main.py` se editan dos variables:

```python
PROYECTO_ACTIVO = "nombre_proyecto"   # debe existir en config/proyectos/
SOLO_CAPAS = ["Clima"]                # lista de 'nombre_capa'; vacía = todos
```

## Estructura del repositorio

```
planos_auto/
├── main.py                        ← Punto de entrada (consola de QGIS)
├── generar_planos.py              ← Orquestador principal
├── Instalar.bat / instalar_plugin.{sh,ps1}  ← Enlazan el plugin al perfil de QGIS
├── planos_auto_plugin/            ← Interfaz gráfica (plugin de QGIS)
│   ├── plugin.py                  ← Botón de barra + menú
│   ├── dialogo.py                 ← Diálogo: proyecto, planos, DPI, log, guardar capas
│   ├── editor_proyecto.py         ← Formulario de metadata/defaults del proyecto
│   ├── configurar_conexion.py     ← Formulario de conexión (escribe el .env)
│   └── actualizar.py              ← Descarga e instala la última versión del repo
├── core/
│   ├── utils.py                   ← Paletas, env, logger, sanitizar
│   ├── configuracion.py           ← Ensamblaje del CONFIG (global+proyecto+env) y validación
│   ├── capas.py                   ← Carga PostGIS, recorte/reproyección, máscaras, vértices
│   ├── mapitas.py                 ← Insertos de localización (nacional/estatal/municipal)
│   ├── simbologia.py              ← Renderers, patrones de relleno, etiquetas PAL, opacidad
│   ├── composicion.py             ← Layouts, leyenda, grid, logo, labels, barra de escala
│   ├── exportar.py                ← Exportación a PNG
│   └── reportes.py                ← Índice HTML
├── config/
│   ├── global.json                ← IDs de layout, DPI, CRS, config de mapitas
│   └── proyectos/                 ← Un .json por proyecto (nombre de archivo = identificador)
├── plantillas/                    ← Layouts QPT (ver "Plantillas de layout")
├── estilos/                       ← Archivos QML por capa
├── herramientas/rutas_cli.py      ← Generador de rutas de acceso (OSMnx), proceso aparte
├── docs/fuentes_datos.html        ← Versión navegable de fuentes_datos.md
├── fuentes_datos.md               ← De dónde sale cada capa
├── assets/logo_sinergia.jpg
├── .env                           ← Credenciales (en .gitignore)
└── .env.example                   ← Plantilla de credenciales
```

## Todas las capas viven en PostGIS

Ninguna capa de un plano o figura debe apuntar a un archivo local (shapefile,
GeoPackage suelto, etc.) — eso solo funciona en la máquina donde se creó. Para
agregar una capa nueva a partir de un archivo:

```bash
ogr2ogr -f "PostgreSQL" PG:"host=localhost port=5432 dbname=gis_empresa user=qgis_user password=$PGPASS" \
  "/ruta/al/archivo.shp" -nln nombre_tabla -lco SCHEMA=proyectos \
  -lco GEOMETRY_NAME=geom -lco FID=gid -nlt MULTIPOLYGON
```

Esto sigue la convención de las tablas existentes (`aica_nacional`,
`anp_estatales`, `uab_nacional`, …): PK `gid`, geometría en `geom`. Ojo:
`ogr2ogr` convierte los nombres de campo a minúsculas por default — usa esos
nombres (no los del archivo original) en `campo_categoria`/`campo_etiqueta`.
Luego el plano se agrega al JSON con `"tabla_postgis": "nombre_tabla"`.

**Esquemas:** `proyectos` para las capas temáticas de cada trámite;
`cartografia_base` para las capas de referencia compartidas (vías, ríos,
canales, estados, municipios) y para el ráster topográfico. El ráster se sube
con `raster2pgsql` y se referencia con `"tabla_postgis_raster"`:

```bash
raster2pgsql -s <SRID> -I -C -M -t 256x256 "/ruta/al/archivo.tif" \
  cartografia_base.nombre_tabla | psql -h <host> -p <puerto> -U qgis_user -d gis_empresa
```

La única excepción por diseño es el GeoPackage de
`FIGURA. VÍAS DE ACCESO AL SITIO` (`rutas_acceso`): se genera por proyecto con
`herramientas/rutas_cli.py`, no es un dato de referencia compartible.

## Configuración de un plano (referencia de campos)

En el JSON del proyecto, cada plano es un objeto del array `"capas"`. Lo que no
se especifique se hereda de `"defaults_capa"`.

```json
{
  "tabla_postgis":   "mi_nueva_tabla",
  "nombre_plano":    "PLANO. MI NUEVA CAPA",
  "nombre_capa":     "Mi_Capa",
  "titulo_capa":     "MI CAPA",
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

### Escala, grid y barra de escala

- `"escala"` acepta un número, `"auto"`, o puede omitirse. Con `"auto"` (o sin
  valor) se calcula la escala cartográfica redonda más cercana en la que el
  polígono cabe completo en el marco, con ~5 % de aire.
- Si la escala configurada **no alcanza** para el encuadre, se sube
  automáticamente a la mínima que sí cabe y se avisa en el log.
- `grid_intervalo` y `barra_escala_segmento` se asumen tuneados para la escala
  configurada: si la escala final difiere, se reescalan proporcionalmente
  (redondeados a valores cartográficos). `barra_escala_segmento` sin valor se
  deriva sola de la escala real del mapa.
- El filtro espacial contra PostGIS usa el **bbox de la vista final**, no el
  del polígono: con escala automática grande el mapa no queda con zonas vacías.

### Campos opcionales

| Campo | Valores | Efecto |
|-------|---------|--------|
| `titulo_capa` | texto | Nombre a mostrar en la leyenda (si no, se deriva de `nombre_capa`) |
| `paleta` | `default`, `suelos`, `geologia`, `clima`, `vegetacion`, `agua`, `conservacion` | Paleta temática del renderer categorizado |
| `campo_etiqueta_expresion` | expresión QGIS (p. ej. `concat("uga", ', ', "clave")`) | Etiqueta del mapa combinando varios campos en vez de uno solo |
| `campo_etiqueta: "auto"` | — | La capa no trae clave propia: numera las categorías 1..N, el mapa muestra el número y la leyenda "N, nombre" |
| `numerar_leyenda` | `true` | Numera la leyenda ("N, nombre") sin forzar el número en el mapa — combínalo con un `campo_etiqueta` explícito |
| `campo_legenda_extra` | nombre de campo | Muestra "valor, valor_extra" en cada categoría de la leyenda (asume relación 1:1 con `campo_categoria`) |
| `grupo_leyenda_categoria` | texto | Agrupa las categorías bajo un encabezado propio (p. ej. "SUBCUENCA") en vez de listarlas bajo el nombre técnico de la capa |
| `nombre_leyenda_categoria` | texto | Renombra la entrada de la capa dentro de la leyenda |
| `leyenda_solo_ubicacion` | `true` | En capas de zonificación regional, la leyenda solo nombra la categoría donde cae el centroide del proyecto (p. ej. UAB: el mapa muestra las regiones vecinas, la leyenda solo dice en cuál está el proyecto) |
| `leyenda_centrada` | `true` | Centra horizontalmente el bloque de leyenda en su marco |
| `estilo_qml` | archivo en `estilos/` | Aplica un QML en vez del renderer categorizado |
| `filtro_extra` | SQL (p. ej. `cve_ent = '26'`) | Condición extra en la consulta a PostGIS |
| `sin_bbox_filter` | `true` | Carga la tabla completa sin filtro espacial (capas de cobertura nacional dispersa, p. ej. AICA/RHP) |
| `centrar_en` | `{schema, tabla_postgis, filtro_extra}` | Encuadra el mapa en otra geometría (p. ej. el estado de Sonora) en vez del polígono del proyecto — para figuras de contexto regional |
| `recortar_a` | `{schema, tabla_postgis, filtro_extra}` | Recorta la capa a esa máscara (p. ej. limitar una capa nacional al estado) |
| `origen` | `"proyecto"` | Toma la capa ya cargada en el proyecto de QGIS (por `nombre_capa`) en lugar de PostGIS |
| `sin_basemap` | `true` | Oculta el fondo satelital (figuras de contexto en blanco) |
| `layout_nombre` | nombre de QPT en `plantillas/` | Usa una plantilla alternativa |
| `ids_override` | `{clave: id}` | Sustituye IDs de ítems del layout para esa composición |
| `marcador` | `"punto"` \| `"poligono"` | Estrella o contorno del polígono como referencia. Default: `"poligono"` en planos normales, `"punto"` en ráster/`capas_combinadas` |
| `opacidad` | `0.0`–`1.0` | Transparencia de la capa (también aplica al ráster de localización) |
| `grid_intervalo` | metros | Separación de la cuadrícula |
| `barra_escala_segmento` | metros | Unidades por segmento de la barra de escala |
| `fuente` | texto | Texto del label de fuente del plano |

La leyenda y los labels se **autoajustan a la plantilla**: el bloque de
simbología conserva siempre el tamaño reservado en el QPT y la letra se reduce
lo necesario para que quepa el contenido, en vez de desbordar el marco.

## Tipos especiales de plano (`"tipo"`)

Además del flujo normal (una tabla PostGIS categorizada), hay flujos dedicados:

| `tipo` | Uso | Claves relevantes |
|--------|-----|--------------------|
| `vertices` | Plano de vértices del polígono del proyecto | — |
| `raster` | Plano de localización sobre un ráster (carta topográfica) | `tabla_postgis_raster` (+ `schema_postgis_raster`, default `cartografia_base`) o `ruta_raster`; `capas_extra`, `barra_escala_segmento`. El ráster es opcional: sin él queda el basemap satelital + `capas_extra` |
| `rutas_acceso` | Figura de rutas hacia el sitio, extent ajustado al conjunto de rutas | `ruta_gpkg` (generado con `herramientas/rutas_cli.py`), `capas_rutas`, `capa_destino`, `capa_entrada` |
| `capas_combinadas` | Varias capas superpuestas en un mismo plano (p. ej. "Áreas Naturales Protegidas" = ANP federal/estatal + AICA + RTP + RHP) | `capas_postgis` y/o `capas_shapefile` |

Cada spec de `capas_postgis` / `capas_shapefile` acepta `tabla_postgis` (o
`ruta` para shapefile), `nombre`, `color`, `color_borde`, `patron`,
`estilo_borde`, `ancho_linea`, `ancho_borde`, `campo_etiqueta`, `filtro_extra`
y `grupo_leyenda`. Los `patron` disponibles son `solid`, `cross`, `horizontal`,
`vertical`, `f_diagonal`, `b_diagonal` — cada capa lleva relleno sólido **más**
un patrón de líneas superpuesto (no en vez del color), para que se distingan
entre sí sin verse deslavadas.

## Plantillas de layout y mapitas

| QPT | Uso |
|-----|-----|
| `Plantilla_Corporativa.qpt` | Planos (3 insertos: nacional / estatal / municipal) |
| `Plantilla_figuras.qpt` | Figuras (1 inserto de localización) |
| `Plantilla_Figurasv2.qpt` | Figuras de contexto regional (variante usada por las figuras de ANP/RTP/RHP/UAB) |

La plantilla por default se define en `config/global.json → layout_nombre`;
cada plano puede sobreescribirla con `"layout_nombre"`.

Los insertos de contexto se configuran en
`config/global.json → mapitas.mapitas_layout`, por plantilla:

```json
"mapitas_layout": {
  "Plantilla_Corporativa": {
    "Mapa 2": { "nivel": "nacional"  },
    "Mapa 3": { "nivel": "estatal"   },
    "Mapa 4": { "nivel": "municipal" }
  },
  "Plantilla_figuras": {
    "Mapa 2": { "nivel": "municipal" }
  }
}
```

Los niveles disponibles son `nacional`, `estatal` y `municipal`; el estado y el
municipio se detectan solos a partir del centroide del proyecto contra
`cartografia_base.mexico_estados` / `mexico_municipios`. Una plantilla sin
entrada en `mapitas_layout` simplemente no lleva insertos automáticos.

### Formatos de salida

En `config/global.json` (o por proyecto):

```json
"formatos": ["png"]
```

## Conexión y variables de entorno

Si usas el plugin, el botón **"Conexión…"** genera el `.env` por ti — esta
sección es solo para uso por consola o edición manual. Copia `.env.example` →
`.env` y llena tus valores:

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

La base (PostgreSQL/PostGIS) vive en un contenedor Docker en el **NAS Synology
de la oficina** (`scianas`, DS224+), no en una computadora de trabajo, así el
servidor está disponible sin depender de que alguien la deje encendida.

**Configuración actual (2026-08-05):**

- Servidor: contenedor `postgis/postgis` en el NAS, puerto **`55432`** (no el
  5432 estándar — ya estaba ocupado por otro servicio del NAS).
- Datos persistentes en una carpeta compartida del NAS (`postgis_data/data`),
  sobreviven reinicios y actualizaciones del contenedor; reinicio automático
  habilitado.
- **Tailscale activo en el NAS** (paquete oficial de Synology): el servidor es
  alcanzable dentro de la oficina y desde fuera, sin abrir puertos al internet
  público. IP de Tailscale del NAS: **`100.105.239.92`**; IP de LAN:
  **`192.168.100.132`**. Para conectarse desde fuera de la oficina hay que
  instalar Tailscale ([tailscale.com/download](https://tailscale.com/download))
  y autenticarse con la cuenta del equipo.
- **Usar la IP, no `scianas.local`:** QGIS (Flatpak en Linux) no resuelve
  nombres `.local`, aunque una terminal normal sí.
- Dos roles en la base:
  - `qgis_user` — lectura y escritura (administradores).
  - `planos_lector` — solo lectura (`GRANT SELECT`, con
    `ALTER DEFAULT PRIVILEGES` para que las tablas nuevas también queden
    visibles automáticamente).
- Todas las capas de referencia que antes eran archivos locales (vías, ríos,
  canales y el ráster topográfico) ya viven en PostGIS — cualquier computadora
  con la conexión configurada las ve, sin copiar archivos.

**Para dar acceso a un colega nuevo:**

1. Instala QGIS + el plugin siguiendo
   [Instalación](#instalación-sin-terminal). La primera vez el plugin pide:
   - **Dirección del servidor:** `192.168.100.132:55432` desde la oficina, o
     `100.105.239.92:55432` (Tailscale) desde fuera — dirección y puerto
     separados por `:`.
   - **¿Es administrador?** — solo si va a editar la base.
   - **Contraseña:** la del rol que le corresponda (`qgis_user` si es
     administrador, `planos_lector` si no).
   - **Carpeta de salida:** donde se guardarán sus PNG.
2. Si va a conectarse desde fuera de la oficina, además instala Tailscale y se
   autentica con la cuenta del equipo (paso aparte, no lo hace el plugin).

La contraseña se pasa por un canal aparte (WhatsApp, correo…), **nunca por
este repo**.

## Fuentes de datos

`fuentes_datos.md` documenta de qué dataset oficial sale cada capa (INEGI,
CONANP, CONABIO, CEDES, OpenStreetMap…), con su tabla en la base. Hay una
versión navegable en `docs/fuentes_datos.html`. El campo `"fuente"` de cada
plano en el JSON es lo que termina impreso en el pie del plano.

## Pendientes conocidos

- `FIGURA. VÍAS DE ACCESO AL SITIO` depende de un GeoPackage generado por
  proyecto con `herramientas/rutas_cli.py` (requiere OSMnx y corre como proceso
  aparte, fuera de QGIS). En una computadora sin ese archivo el plano no falla:
  se genera con el mapa base y el punto del proyecto, solo sin las rutas
  trazadas.
