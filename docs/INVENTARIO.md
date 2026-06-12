# Inventario de datos descargados

Inventario detallado de toda la información descargada por el pipeline,
su fuente y los datos que contiene. Corridas del **11 de junio de 2026**.
Visión general del proyecto y scripts: ver `README.md`. Cómo se extrajo,
normalizó y cruzó cada dato: ver `METODOLOGIA.md`.

## Francia — cadena estructurada (en `data/`)

| Fichero(s) | Fuente | Registros | Datos contenidos |
|---|---|---|---|
| `dpe_dpto75.{csv,jsonl}` | API DPE ADEME | 500 DPE (París) | Diagnósticos energéticos: nº DPE, fecha, dirección, tipo de edificio, período/año construcción, superficie, etiquetas energía y CO₂ (A–G), consumo kWh/m², `id_rnb` |
| `dpe_dpto33.{csv,jsonl}` | API DPE ADEME | 500 DPE (Gironda) | Ídem, departamento 33 |
| `dpe_rnb_dpto75.{csv,jsonl}` | + API RNB | 83 DPE / 81 edificios | Lo anterior + estado del edificio, coordenadas lon/lat, código INSEE, nº direcciones |
| `dpe_rnb_dpto75.geojson` | API RNB | 81 edificios | Huellas poligonales reales con etiquetas DPE como propiedades (para QGIS/kepler.gl) |
| `dpe_rnb_dpto33.{csv,jsonl,geojson}` | + API RNB | 259 DPE / 230 edificios | Ídem, Gironda |
| `dpe_rnb_bdnb_dpto75.{csv,jsonl}` | + API BDNB (CSTB) | 83 DPE | Lo anterior + altura, superficie de huella, altitud, año construcción catastral, **materiales muro/techo**, nº plantas, nº viviendas, uso |
| `dpe_rnb_bdnb_dpto33.{csv,jsonl}` | + API BDNB | 242 DPE | Ídem, Gironda |
| `dpe_rnb_bdnb_rga_dpto75.{csv,jsonl}` | + API Géorisques (BRGM) | 83 DPE — **registro final** | Lo anterior + **riesgo de arcillas consolidado** (`Fort/Moyen/Faible/Non exposé`) con fuente trazada. 27 campos por registro |
| `dpe_rnb_bdnb_rga_dpto33.{csv,jsonl}` | + API Géorisques | 242 DPE — **registro final** | Ídem: 102 Fort, 128 Moyen, 12 Non exposé |

## Luxemburgo — cadena geoespacial (en `data/`)

| Fichero(s) | Fuente | Registros | Datos contenidos |
|---|---|---|---|
| `lu_luxembourg_ville_{buildings,addresses,parcels}.geojson` | WFS INSPIRE geoportail.lu (ACT) | 788 / 1.025 / 972 | Huellas de edificios 2D (base nacional 2023), puntos de dirección completos, parcelas con superficie y referencia catastral |
| `lu_luxembourg_ville_batiments.{csv,jsonl}` | Cruce espacial de las 3 capas | 788 edificios | Por edificio: ID, centroide, direcciones contenidas (88%), parcela catastral (100%), superficie de parcela |
| `lu_bettendorf_{buildings,addresses,parcels}.geojson` | WFS INSPIRE | 2.037 edificios + capas | Ídem, comuna de Bettendorf |
| `lu_bettendorf_batiments.{csv,jsonl}` | Cruce espacial | 2.037 edificios | Ídem (63% con dirección, 99% con parcela) |
| `lu_3d_bettendorf_hauteurs.csv` | CityGML 3D 2023 data.public.lu | 1.501 edificios | `building_id` → altura en metros (`bldg:measuredHeight`) |
| `lu_bettendorf_batiments_3d.{csv,jsonl}` | Cruce por ID ACT | 2.037 (1.411 con altura) | La carta de identidad completa: dirección + parcela + **altura 3D** |
| `ortho_chips/bettendorf/` (24 JPEG + manifiesto) | WMS ortofoto 2025 (wms.geoportail.lu) | 24 chips | Recortes 400×400 px (40×40 m, ≈10 cm/píxel) centrados en edificios, con altura/parcela/dirección como etiquetas |

## Bélgica — cadena geoespacial y energética (en `data/`)

| Fichero(s) | Fuente | Registros | Datos contenidos |
|---|---|---|---|
| `be_bruselas_bruxelles_centre_{buildings,addresses,parcels}.geojson` | WFS UrbIS (geoservices-vector.irisnet.be) | 2.086 edificios + capas | Huellas 2D, direcciones bilingües FR/NL, parcelas con CAPAKEY |
| `be_bruselas_bruxelles_centre_batiments.{csv,jsonl}` | Cruce espacial | 2.086 edificios | Por edificio: ID INSPIRE, centroide, superficie, dirección (86%), CAPAKEY (100%), código NIS |
| `be_flandes_antwerpen_centrum_{buildings,parcels}.geojson` | WFS GRB (geo.api.vlaanderen.be) | 3.018 edificios + parcelas | Huellas con tipo (hoofdgebouw/bijgebouw) y fechas, parcelas con CAPAKEY y NIS |
| `be_flandes_antwerpen_centrum_batiments.{csv,jsonl}` | Cruce espacial | 3.018 edificios | Por edificio: OIDN, centroide, tipo, CAPAKEY (99%), código NIS |
| `veka_02_gemiddeld_e_peil_per_gemeente.csv` | VEKA open data | 12.379 filas / 322 comunas | E-peil medio (rendimiento energético EPB) por comuna, año de permiso y tipo de uso |

## Corpus RAG (en `corpus/aqc/`)

| Fichero(s) | Fuente | Registros | Datos contenidos |
|---|---|---|---|
| `pdf/` | qualiteconstruction.com (AQC, vía API WordPress) | 89 PDFs | Fichas de patología constructiva, temas A–G (fundaciones, envolvente, ventilación, mantenimiento…) |
| `txt/` | Extracción con pdftotext | 89 textos | Texto plano de cada ficha (~14.500 caracteres de mediana) |
| `manifest.{csv,jsonl}` | Generado | 89 entradas | Código de ficha (A.01–G.13), tema, título, URL origen, fecha publicación, rutas locales |
| `rag_index.db` (30 MB, en `corpus/`) | Generado (embeddings locales e5-small) | 7.551 fragmentos / 232 docs | AQC + ITM troceados, vector de 384 dims + fuente + idioma por fragmento, consultable en FR/ES/EN/DE |
| `itm/pdf/` + `itm/txt/` + `manifest.*` | itm.public.lu (conditions-types) | 143 prescripciones (140 FR, 3 DE) | Serie edificación/incendio ITM-SST 1100-2000: prescripciones de seguridad obligatorias de Luxemburgo |

## Intermedios (en `downloads/`, ~1,5 GB — **borrable entero**)

| Fichero | Fuente | Para qué sirvió |
|---|---|---|
| `act2023v2-bati3d-bettendorf.zip` + su `.gml` | data.public.lu | Extraer las alturas 3D (se conserva como caché del script) |
| `ACT2023v2_Buildings3d_Footprints.gpkg` | data.public.lu | Explorado: huellas nacionales, descartado por no traer altura |
| `ACT2023_Buildings3d_footprints.json` | data.public.lu | Ídem (versión GeoJSON) |
| `lod1.zip` + `Luxembourg.gml` | data.public.lu | LOD1 2013 explorado y descartado (sin IDs ni atributos) |

## Generados a partir de lo anterior (en `informes/`)

| Fichero | Generado por | Contenido |
|---|---|---|
| `informe_2633E1530986O_plantilla.md` | `informe_edificio.py` | Informe de riesgo de un inmueble de Burdeos: 5 señales, 10 fichas AQC citadas |
| `informe_2633E1530986O_plantilla_{es,en,fr}.{md,pdf}` | `informe_edificio.py --idiomas es,en,fr --pdf` | El mismo informe en los tres idiomas, cada uno con su PDF |
| `informe_2633E1530986O_llm-gemini.md` / `_llm-gemini_fr.{md,pdf}` | `informe_edificio.py --llm gemini` | Informes redactados por LLM (gemini-2.5-flash) en español y francés, con citas AQC |
| `informe_2675E1536668S_plantilla.md` | `informe_edificio.py` | Informe de riesgo de un inmueble de París: 4 señales |

## Totales

- **~8.850 edificios cruzados en 3 países**: 913 Francia (cadena completa de
  4 fuentes, cobertura 90-98% tras el fallback por dirección BAN),
  2.825 Luxemburgo (dirección/parcela, 1.411 con altura 3D),
  5.104 Bélgica (CAPAKEY catastral; 1.786 con dirección en Bruselas).
- **232 documentos** (89 fichas de patología AQC + 143 prescripciones ITM)
  indexados en 7.551 fragmentos vectorizados con fuente e idioma.
- **1 dataset energético agregado** (VEKA, 322 comunas flamencas).
- **24 chips de ortofoto a 10 cm/píxel** con etiquetas estructuradas (módulo CV).
- Licencias: Licence Ouverte (Etalab), CC0, Gratis Open Data Licentie
  Vlaanderen y Modellicentie Gratis Hergebruik; fichas AQC de descarga libre
  citando la fuente. Detalle por fuente en `README.md` → Licencias.
