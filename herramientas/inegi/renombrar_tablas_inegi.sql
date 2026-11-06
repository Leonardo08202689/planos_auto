-- Renombra las tablas mg_* del esquema inegi a nombres descriptivos
-- (también renombra sus índices y llaves). Se puede correr más de una vez.
-- Uso:  psql -h 100.67.21.105 -U leonardo -d gis_empresa -f renombrar_tablas_inegi.sql
BEGIN;

DO $$
DECLARE
  r record;
  i record;
  nombres text[][] := ARRAY[
    ['mg_ent', 'estado'],
    ['mg_mun', 'municipios'],
    ['mg_l',   'localidades'],
    ['mg_lpr', 'localidades_rurales_puntos'],
    ['mg_a',   'ageb_urbanas'],
    ['mg_ar',  'ageb_rurales'],
    ['mg_m',   'manzanas'],
    ['mg_fm',  'frentes_manzana'],
    ['mg_e',   'vialidades'],
    ['mg_cd',  'caserio_disperso'],
    ['mg_pe',  'poligono_externo_localidad'],
    ['mg_pem', 'poligono_externo_manzana'],
    ['mg_ti',  'territorio_insular'],
    ['mg_sia', 'servicios_area'],
    ['mg_sil', 'servicios_linea'],
    ['mg_sip', 'servicios_puntos']
  ];
  viejo text; nuevo text;
BEGIN
  FOR k IN 1 .. array_length(nombres, 1) LOOP
    viejo := nombres[k][1]; nuevo := nombres[k][2];
    IF to_regclass('inegi.' || viejo) IS NULL THEN CONTINUE; END IF;
    IF to_regclass('inegi.' || nuevo) IS NOT NULL THEN
      EXECUTE format('DROP TABLE inegi.%I CASCADE', nuevo);
    END IF;
    EXECUTE format('ALTER TABLE inegi.%I RENAME TO %I', viejo, nuevo);
    -- índices y PK: mg_m_pkey -> manzanas_pkey, mg_m_geom_geom_idx -> manzanas_geom_idx, ...
    FOR i IN SELECT indexname FROM pg_indexes
             WHERE schemaname = 'inegi' AND tablename = nuevo AND indexname LIKE viejo || '\_%'
    LOOP
      EXECUTE format('ALTER INDEX inegi.%I RENAME TO %I', i.indexname,
        replace(nuevo || substr(i.indexname, length(viejo) + 1), '_geom_geom_idx', '_geom_idx'));
    END LOOP;
    -- secuencia del gid
    IF to_regclass('inegi.' || viejo || '_gid_seq') IS NOT NULL THEN
      EXECUTE format('ALTER SEQUENCE inegi.%I RENAME TO %I', viejo || '_gid_seq', nuevo || '_gid_seq');
    END IF;
  END LOOP;

  -- índices de colonias y denue con el mismo estilo
  FOR i IN SELECT indexname FROM pg_indexes
           WHERE schemaname = 'inegi' AND indexname LIKE '%\_geom\_geom\_idx'
  LOOP
    EXECUTE format('ALTER INDEX inegi.%I RENAME TO %I', i.indexname, replace(i.indexname, '_geom_geom_idx', '_geom_idx'));
  END LOOP;
END $$;

COMMENT ON TABLE inegi.estado                     IS 'INEGI Marco Geoestadístico 2025 (corte jul-2025): área geoestadística estatal';
COMMENT ON TABLE inegi.municipios                 IS 'INEGI Marco Geoestadístico 2025: áreas geoestadísticas municipales';
COMMENT ON TABLE inegi.localidades                IS 'INEGI Marco Geoestadístico 2025: polígonos de localidades urbanas y rurales amanzanadas';
COMMENT ON TABLE inegi.localidades_rurales_puntos IS 'INEGI Marco Geoestadístico 2025: localidades rurales puntuales';
COMMENT ON TABLE inegi.ageb_urbanas               IS 'INEGI Marco Geoestadístico 2025: AGEB urbanas';
COMMENT ON TABLE inegi.ageb_rurales               IS 'INEGI Marco Geoestadístico 2025: AGEB rurales';
COMMENT ON TABLE inegi.manzanas                   IS 'INEGI Marco Geoestadístico 2025: manzanas';
COMMENT ON TABLE inegi.frentes_manzana            IS 'INEGI Marco Geoestadístico 2025: frentes de manzana';
COMMENT ON TABLE inegi.vialidades                 IS 'INEGI Marco Geoestadístico 2025: ejes de vialidad';
COMMENT ON TABLE inegi.caserio_disperso           IS 'INEGI Marco Geoestadístico 2025: caserío disperso';
COMMENT ON TABLE inegi.poligono_externo_localidad IS 'INEGI Marco Geoestadístico 2025: polígono externo de localidad rural con caserío disperso';
COMMENT ON TABLE inegi.poligono_externo_manzana   IS 'INEGI Marco Geoestadístico 2025: polígono externo de manzana (caserío disperso en periferia urbana)';
COMMENT ON TABLE inegi.territorio_insular         IS 'INEGI Marco Geoestadístico 2025: territorio insular';
COMMENT ON TABLE inegi.servicios_area             IS 'INEGI Marco Geoestadístico 2025: servicios de área (camellones, parques, deportivos)';
COMMENT ON TABLE inegi.servicios_linea            IS 'INEGI Marco Geoestadístico 2025: servicios de línea (ríos, ferrocarril, corrientes)';
COMMENT ON TABLE inegi.servicios_puntos           IS 'INEGI Marco Geoestadístico 2025: servicios puntuales (escuelas, templos, salud, etc.)';

COMMIT;

SELECT f_table_name AS tabla, type AS geom, obj_description(format('inegi.%I', f_table_name)::regclass) AS descripcion
FROM geometry_columns WHERE f_table_schema = 'inegi' ORDER BY 1;
