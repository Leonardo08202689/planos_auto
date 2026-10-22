# Fuentes de Datos de las Capas

Este documento es la referencia de dónde viene la información geográfica que usa **Planos_auto**. Sirve para tener certeza, ante cualquier duda (propia, de un colega o de una autoridad), de qué dataset oficial respalda cada plano generado.

Cada capa vive en la base de datos PostGIS (esquema `proyectos` u otros) y se referencia en los archivos `config/proyectos/*.json` mediante el campo `"fuente"`. Esta tabla junta esa información en un solo lugar.

## Planos corporativos (base de todo proyecto)

| Capa | Tabla en la BD | Fuente |
|------|-----------------|--------|
| Tipo de Suelo | `suelos_edafologia_serie3` | [Conjunto nacional de información edafológica. Escala 1:250 000 **Serie III**](https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=794551118313). INEGI, 2024. |
| Tipos de Roca | `Geologia` | Servicio Geológico Mexicano (SGM), Continuo Nacional de Geología de la República Mexicana, escala 1:250,000. [Consultar recurso en datos.gob.mx](https://www.datos.gob.mx/dataset/cartografia_geologica_republica_mexicana_escala_1-250-000/resource/2038cfc3-6e11-41c3-b6ee-27a013122409) |
| Tipo de Clima | `Clima` | [Conjunto de datos vectoriales escala 1:1 000 000. Unidades climáticas](https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=702825267568). INEGI, 2008. |
| Tipos de Vegetación | `Vegetacion` | [Conjunto de datos vectoriales de uso del suelo y vegetación. Escala 1:250 000. **Serie VII**. Conjunto Nacional](https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=889463842781). INEGI, 2018. |
| Hidrología Superficial | `hidrologia_superficial` | [Red hidrográfica, subcuencas hidrográficas de México](http://geoportal.conabio.gob.mx/metadatos/doc/html/redsub84gw.html). Escala 1:50 000, edición 2. INEGI, 2010 (distribuido por CONABIO). Ríos, canales y cuerpos de agua: [Conjunto Nacional de Información Topográfica escala 1:50 000 (CNIT50k)](https://www.inegi.org.mx/programas/topografia/50000/cnit50k/). INEGI. |
| Vértices del Proyecto | *(generado)* | Vértices del polígono del proyecto (no es un dataset externo, se calcula de la geometría cargada por el usuario). |
| Localización | raster (`raster_26030` Hermosillo, `raster_26029` Guaymas) + `cnit50k.gpkg` | [Mapa Topográfico municipal, Hermosillo, Sonora](https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=794551129623). Escala 1:245 000, elaborado con información topográfica 1:50 000 serie III. INEGI, 2024. [Mapa Topográfico municipal, Guaymas, Sonora](https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=794551129616). Escala 1:150 000, elaborado con información topográfica 1:50 000 serie III. INEGI, 2024. Vialidades: [Conjunto Nacional de Información Topográfica escala 1:50 000 (CNIT50k)](https://www.inegi.org.mx/programas/topografia/50000/cnit50k/). INEGI. |
| Rutas de Acceso | `Rutas_Acceso` | Rutas de acceso generadas a partir de la red vial de OpenStreetMap. |

## Figuras (planos de contexto regional)

| Capa | Tabla en la BD | Fuente |
|------|-----------------|--------|
| POET Sonora | `poet_sonora` | Programa de Ordenamiento Ecológico Territorial del Estado de Sonora. |
| Áreas Naturales Protegidas | `ANP_Conjunto` | ANP Federal: CONANP. ANP Estatal: CEDES Sonora. AICA/RTP/RHP: CONABIO. |
| AICA (Áreas de Importancia para la Conservación de Aves) | `aica_nacional` | Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO). |
| ANP Estatales | `anp_estatales` | Comisión de Ecología y Desarrollo Sustentable del Estado de Sonora (CEDES). |
| Regiones Hidrológicas Prioritarias | `regiones_hidrologicas_prioritarias` | Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO). |
| Regiones Terrestres Prioritarias | `regiones_terrestres_prioritarias` | Comisión Nacional para el Conocimiento y Uso de la Biodiversidad (CONABIO). |
| UAB Nacional | `uab_nacional` | Modelo de Ordenamiento Ecológico General del Territorio (MOEGT), SEMARNAT. |

## Notas

- El campo **`"fuente"`** de cada capa en los archivos `config/proyectos/*.json` es la fuente oficial de esta tabla — si se actualiza un dataset (ej. INEGI publica una nueva serie), hay que actualizar el JSON del proyecto **y** esta tabla juntos, para que no queden desincronizados.
- Escalas y series indican la resolución/año del levantamiento oficial: a mayor escala numérica (ej. 1:1 000 000), menor detalle; a menor escala numérica (ej. 1:50 000), mayor detalle.
- Ante cualquier duda sobre si un dato está actualizado o corresponde a la fuente vigente, verificar directamente con el sitio de INEGI/CONABIO/CONANP/SEMARNAT según corresponda.

## Referencias documentales

- Diccionario de Datos Edafológicos. INEGI. Escala 1:250 000 (Versión 3). Edición 2021 (Serie III, WRB 2014). https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=889463842644
- Diccionario de datos del continuo nacional geológico. INEGI-SGM. Escala 1:250 000. Edición 2021 (cobertura temporal 2012). https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=889463842651
