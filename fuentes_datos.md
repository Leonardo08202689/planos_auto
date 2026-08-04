# Fuentes de Datos de las Capas

Este documento es la referencia de dónde viene la información geográfica que usa **Planos_auto**. Sirve para tener certeza, ante cualquier duda (propia, de un colega o de una autoridad), de qué dataset oficial respalda cada plano generado.

Cada capa vive en la base de datos PostGIS (esquema `proyectos` u otros) y se referencia en los archivos `config/proyectos/*.json` mediante el campo `"fuente"`. Esta tabla junta esa información en un solo lugar.

## Planos corporativos (base de todo proyecto)

| Capa | Tabla en la BD | Fuente |
|------|-----------------|--------|
| Tipo de Suelo | `suelos_edafologia_serie2` | Conjunto de Datos Vectorial Edafológico. Escala 1:250 000 Serie II. INEGI. |
| Tipos de Roca | `Geologia` | Continuo Nacional de Geología de la República Mexicana, escala 1:250 000. |
| Tipo de Clima | `Clima` | Conjunto de Datos Nacionales de Unidades Climáticas, escala 1:1 000 000. INEGI. |
| Tipos de Vegetación | `Vegetacion` | Conjunto de datos vectoriales de uso del suelo y vegetación. Escala 1:250 000. **Serie VII**. INEGI. |
| Hidrología Superficial | `hidrologia_superficial` | Red hidrográfica, Subcuencas hidrográficas de México, escala 1:50 000. Ríos, canales y cuerpos de agua: Carta Topográfica INEGI 1:50 000 (cnit50k). |
| Vértices del Proyecto | *(generado)* | Vértices del polígono del proyecto (no es un dataset externo, se calcula de la geometría cargada por el usuario). |
| Localización | raster + `cnit50k.gpkg` | Mapa Topográfico municipal, Hermosillo, Sonora, escala 1:50 000, serie III. Vialidades: Carta Topográfica INEGI 1:50 000 (cnit50k). |
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
