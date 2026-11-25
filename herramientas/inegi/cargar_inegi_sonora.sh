#!/usr/bin/env bash
# Carga capas INEGI de Sonora completo a PostGIS (gis_empresa, esquema inegi)
#   - Marco Geoestadístico 2025, corte jul-2025 (26_sonora.zip) -> inegi.manzanas, municipios, ...
#   - Colonias / asentamientos DCAH nov-2025 (26_sonora (1).zip) -> inegi.colonias
#   - DENUE may-2026 (denue_26_shp.zip)                    -> inegi.denue
# Todo queda en EPSG:6372, geometrías reparadas, índice espacial e índice por cve_mun.
#
# Fuentes: ver fuentes_datos.md (sección "Capas base INEGI")
#
# Uso:  SIG_DIR=~/SIG bash herramientas/inegi/cargar_inegi_sonora.sh
# Variables opcionales: PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD SIG_DIR SCHEMA
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SIG_DIR="${SIG_DIR:-$HOME/SIG}"            # carpeta con los zips descargados de INEGI
export PGHOST="${PGHOST:-100.67.21.105}"      # servidorsin (Tailscale); en la LAN: 192.168.100.24
export PGPORT="${PGPORT:-5432}"
export PGDATABASE="${PGDATABASE:-gis_empresa}"
export PGUSER="${PGUSER:-leonardo}"
SCHEMA="${SCHEMA:-inegi}"
READER_ROLE="qgis_user"

MG_ZIP="$SIG_DIR/26_sonora.zip"
AS_ZIP="$SIG_DIR/26_sonora (1).zip"
DENUE_ZIP="$SIG_DIR/denue_26_shp.zip"

for c in ogr2ogr psql; do
  command -v "$c" >/dev/null || { echo "Falta '$c' (sudo apt install gdal-bin postgresql-client)"; exit 1; }
done
for z in "$MG_ZIP" "$AS_ZIP" "$DENUE_ZIP"; do
  [[ -f "$z" ]] || { echo "No encuentro: $z"; exit 1; }
done

if [[ -z "${PGPASSWORD:-}" ]] && ! grep -qs "$PGHOST" ~/.pgpass; then
  read -rsp "Contraseña de $PGUSER@$PGHOST: " PGPASSWORD; echo
  export PGPASSWORD
fi

PG="PG:host=$PGHOST port=$PGPORT dbname=$PGDATABASE user=$PGUSER"
PSQL=(psql -v ON_ERROR_STOP=1 -q)

"${PSQL[@]}" -c "SELECT 1" >/dev/null || { echo "No conecta a $PGHOST:$PGPORT/$PGDATABASE"; exit 1; }
"${PSQL[@]}" -c "CREATE SCHEMA IF NOT EXISTS $SCHEMA;"

export SHAPE_ENCODING="ISO-8859-1"   # los .dbf de INEGI vienen en Latin-1
export PG_USE_COPY=YES

# load <ruta_vsizip> <tabla> <tipo_geom> [opciones extra de ogr2ogr...]
load() {
  local src="$1" tabla="$2" nlt="$3"; shift 3
  echo ">> $SCHEMA.$tabla"
  ogr2ogr -f PostgreSQL "$PG" "$src" \
    -overwrite -progress \
    -nln "$SCHEMA.$tabla" -nlt "$nlt" \
    -makevalid \
    -lco GEOMETRY_NAME=geom -lco FID=gid -lco SPATIAL_INDEX=GIST -lco LAUNDER=YES \
    "$@"
}

# ---- Marco Geoestadístico (proyección LCC ITRF2008 = EPSG:6372, se asigna explícita)
MG="/vsizip/$MG_ZIP/conjunto_de_datos"
declare -A MG_CAPAS=(
  [ent]="MULTIPOLYGON"    [mun]="MULTIPOLYGON"   [l]="MULTIPOLYGON"
  [a]="MULTIPOLYGON"      [ar]="MULTIPOLYGON"    [m]="MULTIPOLYGON"
  [pe]="MULTIPOLYGON"     [pem]="MULTIPOLYGON"   [ti]="MULTIPOLYGON"
  [sia]="MULTIPOLYGON"    [e]="MULTILINESTRING"  [fm]="MULTILINESTRING"
  [sil]="MULTILINESTRING" [sip]="POINT"          [lpr]="POINT"
  [cd]="MULTIPOINT"
)
declare -A MG_TABLA=(
  [ent]=estado [mun]=municipios [l]=localidades [lpr]=localidades_rurales_puntos
  [a]=ageb_urbanas [ar]=ageb_rurales [m]=manzanas [fm]=frentes_manzana [e]=vialidades
  [cd]=caserio_disperso [pe]=poligono_externo_localidad [pem]=poligono_externo_manzana
  [ti]=territorio_insular [sia]=servicios_area [sil]=servicios_linea [sip]=servicios_puntos
)
for k in ent mun l a ar m pe pem ti sia e fm sil sip lpr cd; do
  load "$MG/26$k.shp" "${MG_TABLA[$k]}" "${MG_CAPAS[$k]}" -a_srs EPSG:6372
done

# ---- Colonias / asentamientos humanos (ya trae EPSG:6372)
load "/vsizip/$AS_ZIP/conjunto_de_datos/26as.shp" "colonias" MULTIPOLYGON -t_srs EPSG:6372

# ---- DENUE: WGS84 -> 6372; se descartan los pocos puntos con coordenadas fuera de Sonora
load "/vsizip/$DENUE_ZIP/conjunto_de_datos/denue_inegi_26_.shp" "denue" POINT \
  -s_srs EPSG:4326 -t_srs EPSG:6372 -lco PRECISION=NO \
  -where "latitud BETWEEN 26 AND 33 AND longitud BETWEEN -115.5 AND -108.3"

# ---- Nombres de índices y comentarios por tabla
"${PSQL[@]}" -f "$SCRIPT_DIR/renombrar_tablas_inegi.sql" >/dev/null

# ---- Índices por municipio, permisos, comentarios
echo ">> índices, permisos y comentarios"
"${PSQL[@]}" <<SQL
DO \$\$
DECLARE t record;
BEGIN
  FOR t IN SELECT table_name FROM information_schema.columns
           WHERE table_schema = '$SCHEMA' AND column_name = 'cve_mun'
  LOOP
    EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON $SCHEMA.%I (cve_mun)', t.table_name || '_cve_mun_idx', t.table_name);
    EXECUTE format('ANALYZE $SCHEMA.%I', t.table_name);
  END LOOP;
END \$\$;

DO \$\$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$READER_ROLE') THEN
    GRANT USAGE ON SCHEMA $SCHEMA TO $READER_ROLE;
    GRANT SELECT ON ALL TABLES IN SCHEMA $SCHEMA TO $READER_ROLE;
    ALTER DEFAULT PRIVILEGES IN SCHEMA $SCHEMA GRANT SELECT ON TABLES TO $READER_ROLE;
  END IF;
END \$\$;

COMMENT ON SCHEMA $SCHEMA IS 'Capas base INEGI, Sonora completo, EPSG:6372';
COMMENT ON TABLE $SCHEMA.colonias IS 'INEGI DCAH - Delimitación de Colonias y otros Asentamientos Humanos, Sonora (nov-2025)';
COMMENT ON TABLE $SCHEMA.denue    IS 'INEGI DENUE Sonora (may-2026), reproyectado WGS84 -> 6372';
SQL


echo
echo "== Resumen ($SCHEMA en $PGHOST/$PGDATABASE)"
"${PSQL[@]}" -c "
SELECT f_table_name AS tabla, type AS geom, srid,
       (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', f_table_schema, f_table_name), false, true, '')))[1]::text::int AS registros
FROM geometry_columns WHERE f_table_schema = '$SCHEMA' ORDER BY 1;"
