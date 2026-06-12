# Pipeline de ingestión de datos abiertos de edificios (FR / LU)

> Versión en español. La versión mantenida y más actual es [PIPELINE.md](PIPELINE.md) (inglés).

Prueba de concepto que demuestra, con datos reales, que las fuentes públicas
descritas en el reporte de fuentes (`docs/research/compass_fuentes.md`) son extraíbles de
forma automática, cruzables entre sí y consultables semánticamente. Todo
verificado en vivo el **11 de junio de 2026**, sin registro y sin claves de
API. Los scripts de ingestión usan solo Python 3 estándar; el índice RAG es
el único componente con dependencias (modelo de embeddings local en `.venv/`).

Documentación complementaria: **`METODOLOGIA.md`** (cómo se extrajo,
normalizó y cruzó cada dato, y el trabajo futuro) e **`INVENTARIO.md`**
(qué ficheros de datos existen y qué contienen).

## Resultado en una frase

Se construyeron las dos mitades del MVP "Building Intelligence" con 7 fuentes:
(1) una "carta de identidad" estructurada por edificio — en Francia,
diagnóstico energético + identidad/geometría + materiales/altura + riesgo
geotécnico (ADEME → RNB → BDNB → Géorisques); en Luxemburgo, huella +
dirección + parcela catastral + altura 3D (geoportail.lu → data.public.lu
CityGML) — y (2) un corpus RAG de patología constructiva (89 fichas AQC)
con búsqueda semántica multilingüe que explica los riesgos que la parte
estructurada cuantifica.

## Arquitectura

### Cadena Francia (encadenada por `id_rnb`)

```
ingest_dpe.py          ingest_rnb.py              ingest_bdnb.py             ingest_georisques.py
API DPE ADEME    →     API RNB                →   API BDNB (CSTB)        →   API Géorisques RGA
diagnósticos           geometría, estado,         materiales, altura,        riesgo arcillas para
energéticos            coordenadas                plantas, uso, arcillas     los huecos de BDNB
(filtro por dpto)      (por id_rnb)               (por id_rnb, en lotes)     (por lon/lat)

dpe_dptoNN.*     →     dpe_rnb_dptoNN.*       →   dpe_rnb_bdnb_dptoNN.*  →   dpe_rnb_bdnb_rga_dptoNN.*
```

Cada paso lee el JSONL del anterior y añade columnas. El registro final tiene
27 campos: DPE (etiquetas A–G, consumo, superficie, período) + RNB (estado,
lon/lat, INSEE) + BDNB (altura, huella, materiales muro/techo, nº plantas,
nº viviendas, uso) + riesgo de arcillas consolidado con trazabilidad de fuente.

### Cadena Luxemburgo (encadenada por ID de edificio ACT)

```
ingest_geoportail_lu.py                        ingest_lu_3d.py
WFS INSPIRE (wms.inspire.geoportail.lu)   →    CityGML por comuna (data.public.lu)
edificios + direcciones + parcelas             bldg:measuredHeight por edificio
cruce espacial point-in-polygon                join exacto por ID ACT_<uuid>

lu_<zona>_batiments.* (+3 .geojson)       →    lu_<zona>_batiments_3d.*
```

### Cadena corpus RAG (patología constructiva)

```
ingest_aqc.py                                  rag_aqc.py
API WordPress de qualiteconstruction.com  →    troceado (~1200 chars, solape 200)
89 PDFs + texto (pdftotext -layout)            + embeddings multilingual-e5-small
+ manifiesto con código/tema/título            + búsqueda coseno (FR/ES/EN)

corpus/aqc/{pdf,txt}/ + manifest.*        →    corpus/aqc/rag_index.db
```

### Conector: informe de riesgo por edificio

```
informe_edificio.py
dataset final FR (dpe_rnb_bdnb_rga_*.jsonl)  →  señales de riesgo  →  retrieval RAG  →  informe Markdown
  arcillas Fort/Moyen ───────────────────────→  "retrait-gonflement argiles"  →  [A.02] [A.05]
  etiqueta F/G ──────────────────────────────→  "condensations logements"     →  [E.09]
  muros PIERRE/MEULIERE ─────────────────────→  "remontées capillaires"       →  [B.01]
  cubierta TUILES/ARDOISES/ZINC ─────────────→  "infiltrations couverture"    →  [C.06]/[C.07]
  período avant 1948 ────────────────────────→  "structure plancher bois"     →  [B.11]
```

Cada atributo estructurado del edificio se convierte en una consulta de
patología; el índice RAG recupera las 2 mejores fichas por señal y el
informe final cita cada patología con su ficha AQC.

**Opciones de salida:**

- **Idiomas** — `--idiomas es,en,fr` (por defecto `es`) genera un informe por
  idioma: título, etiquetas de la ficha de identidad, cabeceras de señal y
  pie legal totalmente traducidos; los **extractos de las fichas AQC
  permanecen en francés** en todos los idiomas (son citas literales del
  corpus), y las consultas al RAG van siempre en francés (el idioma del
  corpus), así el retrieval no depende del idioma del informe.
- **Formatos** — Markdown siempre; `--pdf` exporta además cada informe a PDF
  (vía `markdown-pdf`), conservando ambos ficheros:
  `informe_<dpe>_<modo>_<lang>.md` + `.pdf`.
- **Redacción** — modo plantilla (sin LLM, por defecto) o
  `--llm anthropic|gemini|openrouter` (modelo configurable con `--modelo`;
  el idioma de salida se instruye en el prompt). Claves vía
  `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY`.

```bash
# un informe por idioma, cada uno con su PDF:
.venv/bin/python informe_edificio.py --max-riesgo --idiomas es,en,fr --pdf
# lo mismo vía make, con redacción LLM en francés:
make report LANGS=fr PDF=1 LLM=gemini
```

## Los scripts

| Script | Fuente | Entrada | Salida |
|---|---|---|---|
| `ingest_dpe.py` | API DPE ADEME | `--departement`, `--limit` | `data/dpe_dptoNN.{csv,jsonl}` |
| `ingest_rnb.py` | API RNB | `--dpe-file` | `data/dpe_rnb_dptoNN.{csv,jsonl,geojson}` |
| `ingest_bdnb.py` | API BDNB | `--in-file` | `data/dpe_rnb_bdnb_dptoNN.{csv,jsonl}` |
| `ingest_georisques.py` | API Géorisques RGA | `--in-file` | `data/dpe_rnb_bdnb_rga_dptoNN.{csv,jsonl}` |
| `ingest_geoportail_lu.py` | WFS INSPIRE LU | `--bbox`, `--zona` | `data/lu_<zona>_batiments.{csv,jsonl}` + 3 GeoJSON |
| `ingest_lu_3d.py` | Bâtiments 3D 2023 LU | `--commune` | `data/lu_<commune>_batiments_3d.{csv,jsonl}` + CSV de alturas |
| `ingest_aqc.py` | Fichas patología AQC | `--out`, `--skip-text` | `corpus/aqc/{pdf,txt}/` + `manifest.{csv,jsonl}` |
| `rag_aqc.py` | Corpus AQC local | `build` / `search "consulta"` | `corpus/aqc/rag_index.db` (SQLite con embeddings) |
| `informe_edificio.py` | Dataset final FR + índice RAG | `--max-riesgo` / `--numero-dpe`, `--llm <proveedor>`, `--idiomas es,en,fr`, `--pdf` | `informes/informe_<dpe>_<modo>_<lang>.{md,pdf}` |
| `ingest_be_geo.py` | UrbIS (BXL) / GRB (VL) vía WFS | `--region`, `--bbox`, `--zona` | `data/be_<region>_<zona>_batiments.{csv,jsonl}` + GeoJSON |
| `ingest_veka.py` | VEKA open data (Flandes) | `--dataset` | `data/veka_<dataset>.csv` |
| `ingest_lu_ortho.py` | Ortofoto 2025 LU (WMS) | `--batiments`, `--limit`, `--margen` | `data/ortho_chips/<zona>/` (JPEG + manifiesto) |

### Ejecución completa de ejemplo

```bash
# Francia — cualquier departamento (probado con 75 París y 33 Gironda)
python3 ingest_dpe.py --departement 33 --limit 500
python3 ingest_rnb.py --dpe-file data/dpe_dpto33.jsonl
python3 ingest_bdnb.py --in-file data/dpe_rnb_dpto33.jsonl
python3 ingest_georisques.py --in-file data/dpe_rnb_bdnb_dpto33.jsonl

# Luxemburgo — cualquier zona/comuna (probado con Luxembourg-Ville y Bettendorf)
python3 ingest_geoportail_lu.py --bbox 49.86,6.17,49.90,6.26 --zona bettendorf
python3 ingest_lu_3d.py --commune bettendorf
python3 ingest_lu_ortho.py                                 # chips CV de la ortofoto 2025

# Bélgica — Bruselas (UrbIS) y Flandes (GRB + VEKA)
python3 ingest_be_geo.py --region bruselas                 # Grand-Place por defecto
python3 ingest_be_geo.py --region flandes --bbox 51.05,3.71,51.06,3.74 --zona gent
python3 ingest_veka.py                                     # e-peil por comuna

# Corpus RAG — fichas de patología AQC (PDF + texto + manifiesto)
python3 ingest_aqc.py

# Índice RAG — troceado + embeddings + búsqueda semántica (requiere el venv)
.venv/bin/python rag_aqc.py build
.venv/bin/python rag_aqc.py search "fissures causées par les argiles" --top 5

# Informe de riesgo por edificio — conecta datos estructurados con el RAG
.venv/bin/python informe_edificio.py --max-riesgo            # edificio con más señales
.venv/bin/python informe_edificio.py --numero-dpe 2633E1530986O --llm  # con Claude
```

Nota: `rag_aqc.py` es el único script que necesita dependencias
(`sentence-transformers`, instalado en `.venv/`); los siete de ingestión son
Python estándar puro. El venv se creó con `python3 -m venv --without-pip .venv`
+ get-pip.py porque el sistema no trae `ensurepip` (ver Requisitos).

Convenciones comunes: salida doble CSV (análisis) + JSONL (pipelines),
pausas de cortesía entre peticiones, resumen de control al final de cada
corrida, y `--help` en todos.

## Resultados de las corridas de prueba

### Francia

| Métrica | Dpto 75 (París) | Dpto 33 (Gironda) |
|---|---|---|
| DPE disponibles en la API | 813.827 | 378.013 |
| DPE descargados (muestra) | 500 | 500 |
| Con `id_rnb` | 83 (17%) | 259 (52%) |
| Encontrados en RNB | 81/81 (100%) | 230/230 (100%) |
| Encontrados en BDNB | 81/81 (100%) | 213/230 (93%) |
| Riesgo arcillas consolidado | 100% (82 No expuesto, 1 Moyen) | 100% (102 Fort, 128 Moyen, 12 No expuesto) |

Los materiales reflejan la realidad regional (validación de plausibilidad):
piedra/ladrillo y cubierta de zinc en París; ladrillo/piedra y teja en Gironda.

### Luxemburgo

| Métrica | Luxembourg-Ville (centro) | Bettendorf |
|---|---|---|
| Edificios (WFS INSPIRE) | 788 | 2.037 |
| Con dirección (point-in-polygon) | 88% | 63% |
| Con parcela catastral | 100% | 99% |
| Con altura 3D (CityGML) | — | 1.411 (69%) |

### Ortofoto 2025 (Luxemburgo, módulo CV)

24 chips JPEG de 400×400 px (40×40 m, ≈10 cm/píxel) centrados en edificios
de Bettendorf, verificados visualmente (tejados centrados, coches
distinguibles), todos con etiqueta de altura 3D en el manifiesto. 0 fallos,
0,8 MB. La combinación chip + altura + parcela + dirección convierte el
pipeline en un generador de datasets de entrenamiento etiquetados.

### Bélgica

| Métrica | Bruselas centro (UrbIS) | Amberes centro (GRB) |
|---|---|---|
| Edificios (WFS) | 2.086 | 3.018 |
| Con parcela catastral (CAPAKEY) | 100% | 99% |
| Con dirección (point-in-polygon) | 86% | — (capa no disponible en GRB) |

VEKA: CSV de e-peil medio por comuna descargado (12.379 filas, 322 comunas,
serie temporal por año de permiso y tipo de uso). Es el equivalente flamenco
agregado del DPE francés — no hay certificado individual abierto.

### Corpus RAG (AQC)

| Métrica | Valor |
|---|---|
| Fichas descargadas (PDF) | 89 (temas A:10 B:13 C:13 D:14 E:16 F:10 G:13) |
| Texto extraído | 89/89, mediana ~14.500 caracteres/ficha |
| Fragmentos indexados | 1.011 × 384 dimensiones |
| Tamaño del índice | ~12 MB (SQLite) |

Consultas de validación (top-1 correcto en ambas):
- FR: *"fissures dans les murs causées par le retrait-gonflement des argiles"*
  → A.05 y A.02 (movimientos de fundaciones en suelos arcillosos), score ~0,89.
- ES (translingüe): *"humedad y condensación en ventanas por mala ventilación"*
  → E.09 "Condensations dans les logements" y E.08 "VMC", score ~0,85.

### Informes de riesgo (conector estructurado ↔ RAG)

Demostrado con dos perfiles distintos (modo plantilla):
- **Burdeos** (`informes/informe_2633E1530986O_plantilla.md`): inmueble
  anterior a 1948, piedra/teja, etiqueta F, arcillas Moyen → 5 señales,
  10 fichas citadas pertinentes (A.02/A.05 arcillas, E.09 condensación,
  B.01 remontées capillaires, C.06 cubierta de teja, B.11 estructura madera).
- **París** (`informes/informe_2675E1536668S_plantilla.md`): etiqueta G,
  piedra, cubierta de zinc, pre-1948 → 4 señales (sin arcillas, con C.07
  condensación bajo cubierta metálica), coherente con el perfil parisino.
- **Idiomas y PDF verificados**: el informe de Burdeos generado en es/en/fr
  (modo plantilla, textos traducidos, citas AQC en francés intactas) y en
  francés vía Gemini (`--llm gemini --idiomas fr`), cada uno con su PDF
  renderizando bien título, tabla de identidad y citas.

## Hallazgos y trampas descubiertas (no documentadas en el reporte original)

1. **La API open de la BDNB devuelve máximo 10 filas por respuesta** para
   usuarios anónimos e **ignora el parámetro `limit`** silenciosamente. Un
   filtro `in.(...)` con 50 IDs devolvía solo 10 resultados sin ningún error.
   Solución: paginar con `offset` dentro de cada lote (implementado en
   `ingest_bdnb.py`). Para volumen real, usar la descarga masiva por
   departamento de data.gouv.fr.

2. **Géorisques responde `200` con cuerpo vacío** cuando el punto consultado
   está fuera de toda zona de exposición RGA cartografiada. No es un error:
   significa "no expuesto". El script lo registra como `Non exposé` para
   distinguirlo de "no consultado".

3. **Validación cruzada BDNB ↔ Géorisques**: para un edificio de control de
   Gironda, la BDNB decía `Fort` y Géorisques devolvió `Exposition forte`
   para sus coordenadas. Las dos fuentes son coherentes.

4. **Existe "Base de données nationale des bâtiments 3D 2023"** en
   data.public.lu (el reporte solo recogía 2017 y 2020) y, a diferencia de la
   de 2020, **cubre la Ciudad de Luxemburgo**. LOD 2.2, CC0.

5. **Las huellas 2D "ligeras" del dataset 3D luxemburgués NO traen la altura**:
   tanto el GPKG nacional (63 MB) como el GeoJSON (46 MB) solo contienen la
   cota del suelo (`zmin`). La altura (`bldg:measuredHeight`) vive únicamente
   en los **CityGML por comuna** (150 MB–5,4 GB porque incluyen texturas jpg;
   el `.gml` interno es ~25% del zip).

6. **Los IDs de edificio luxemburgueses son consistentes entre fuentes**:
   el CityGML usa `ACT_<uuid>` y la capa WFS INSPIRE `Building2D.ACT_<uuid>`.
   El cruce es un join exacto por ID — no hace falta matching espacial ni
   reproyección desde LUREF (EPSG:2169).

7. **La cobertura de `id_rnb` en los DPE varía mucho por territorio**:
   52% en Gironda vs 17% en París (en los DPE más recientes). Para el resto
   habría que cruzar por dirección normalizada (`adresse_ban`).

8. **Desfase de millésimes**: 17 de 230 edificios de Gironda no estaban en la
   BDNB open (millésime 2025-07) pese a existir en el RNB actual. Confirma la
   advertencia del reporte: fijar versiones para reproducibilidad.

9. **El LOD1 2013 nacional (31 MB) es un callejón sin salida** para el cruce:
   tiene las alturas implícitas en los sólidos pero ningún ID ni atributo,
   y está en LUREF. Descartado en favor del CityGML 2023.

10. **El WFS INSPIRE de geoportail.lu sirve GeoJSON directamente**
    (`outputFormat=application/json`), lo que evita parsear GML. La capa de
    edificios trae geometría pero casi ningún atributo: la riqueza sale del
    cruce con direcciones y parcelas (y del CityGML para la altura).

11. **Las fichas AQC se listan por la API REST de WordPress** del propio
    sitio (`/wp-json/wp/v2/media?search=Fiche-Pathologie`), sin scraping de
    HTML. La edición vigente tiene **89 fichas** (el reporte contaba 75+11=86;
    han añadido nuevas, p.ej. G.13 de sept. 2025), en 7 temas A–G, todas con
    PDF de descarga directa y texto extraíble limpio con `pdftotext -layout`.

12. **El GeoServer "clásico" de UrbIS está casi vacío; el actual es otro**:
    `geoservices-urbis.irisnet.be` solo expone una capa residual. Las capas
    vigentes (Buildings, Addresses, CadastralParcels) están en
    `geoservices-vector.irisnet.be/geoserver/urbisvector/wfs` — encontrado
    vía el GeoNetwork del portal (`catalog.datastore.brussels/geonetwork`,
    GN 3.8). datastore.brussels en sí es una SPA sin API pública evidente.

13. **El WFS del GRB flamenco funciona sin cuenta**: el reporte advertía que
    la descarga masiva exige registro en download.vlaanderen.be, pero
    `geo.api.vlaanderen.be/GRB/wfs` sirve edificios (GBG) y parcelas (ADP)
    en GeoJSON sin autenticación. Solo exige la atribución de la licencia.

14. **VEKA: la raíz responde 403 pero los datos se descargan**:
    `open-data.energiesparen.be/` bloquea (WAF), pero los ficheros bajo
    `/Data/<NOMBRE>.csv` sirven sin problema. Las rutas exactas se obtienen
    del catálogo DCAT de `metadata.vlaanderen.be` (GeoNetwork 4, API
    Elasticsearch). La categoría residencial se llama `WONEN`.

15. **El CAPAKEY es la clave de cruce belga**: tanto UrbIS (Bruselas) como
    GRB (Flandes) exponen la clave catastral nacional (`CAPAKEY`) y el
    código de comuna NIS por parcela — el análogo belga del `id_rnb`
    francés para encadenar fuentes (catastro federal, Statbel por NIS).

16. **El WMS abierto de geoportail.lu sirve todas las milésimas de ortofoto
    sin registro** (`wms.geoportail.lu/opendata/service`): de 1967 a 2025,
    incluidas `ortho_2025` (verano) y `ortho_2025_winter`, en JPEG/PNG por
    GetMap. Pedir chips de 40×40 m a 400×400 px reproduce la resolución
    nativa de ~10 cm/píxel — no hace falta descargar los JP2 gigantes para
    generar datasets de visión por computador.

17. **Los embeddings se resolvieron 100% en local, sin claves de API**:
    la API de Anthropic no ofrece endpoint de embeddings (recomienda Voyage
    AI, de pago), así que el índice usa `intfloat/multilingual-e5-small`
    (~120 MB, licencia MIT) vía sentence-transformers. El corpus troceado son
    1.011 fragmentos × 384 dimensiones en un SQLite de consulta directa. La
    búsqueda es **translingüe verificada**: consultas en español recuperan
    fichas francesas correctas (p.ej. "humedad y condensación en ventanas por
    mala ventilación" → E.09 "Condensations dans les logements" y E.08 "VMC").

## Diccionario de datos del registro final francés

| Prefijo | Campos | Fuente |
|---|---|---|
| (sin prefijo) | `numero_dpe`, `date_etablissement_dpe`, `id_rnb`, `adresse_ban`, `code_postal_ban`, `nom_commune_ban`, `code_departement_ban`, `type_batiment`, `periode_construction`, `annee_construction`, `surface_habitable_logement`, `etiquette_dpe`, `etiquette_ges`, `conso_5_usages_par_m2_ep` | ADEME DPE |
| `rnb_` | `status`, `lon`, `lat`, `insee_code`, `n_addresses` | RNB |
| `bdnb_` | `batiment_groupe_id`, `hauteur`, `s_geom_cstr`, `altitude_sol`, `annee_construction`, `mat_mur`, `mat_toit`, `nb_niveau`, `nb_log`, `usage`, `alea_argiles` | BDNB |
| `alea_argiles_` | `final` (Faible/Moyen/Fort/Non exposé), `source` (BDNB/Géorisques) | consolidado |

Registro final luxemburgués: `building_id`, `lon`, `lat`, `n_addresses`,
`adresse_ejemplo`, `parcel_ref`, `parcel_label`, `parcel_area_m2`, `hauteur_m`.

## Endpoints verificados

| Fuente | Endpoint | Verificado |
|---|---|---|
| ADEME DPE | `https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines` | ✓ 2026-06-11 |
| RNB | `https://rnb-api.beta.gouv.fr/api/alpha/buildings/` | ✓ 2026-06-11 |
| BDNB | `https://api.bdnb.io/v1/bdnb/donnees/<tabla>` (PostgREST) | ✓ 2026-06-11 |
| Géorisques RGA | `https://www.georisques.gouv.fr/api/v1/rga?latlon=lon,lat` | ✓ 2026-06-11 |
| WFS INSPIRE LU | `https://wms.inspire.geoportail.lu/geoserver/wfs` | ✓ 2026-06-11 |
| data.public.lu | `https://data.public.lu/api/1/datasets/` (udata) | ✓ 2026-06-11 |
| AQC (WordPress) | `https://qualiteconstruction.com/wp-json/wp/v2/media` | ✓ 2026-06-11 |
| UrbIS WFS (BXL) | `https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs` | ✓ 2026-06-11 |
| GRB WFS (VL) | `https://geo.api.vlaanderen.be/GRB/wfs` | ✓ 2026-06-11 |
| VEKA (VL) | `https://open-data.energiesparen.be/Data/<NOMBRE>.csv` | ✓ 2026-06-11 |
| WMS ortofoto LU | `https://wms.geoportail.lu/opendata/service` | ✓ 2026-06-11 |

Límites conocidos: ADEME 600 req/60 s (anónimo); BDNB 10 filas/respuesta
(anónimo); RNB y Géorisques sin límite documentado (los scripts usan pausas
de 0,2–0,3 s).

## Requisitos

- **Python 3.10+** (probado con 3.13). Los 7 scripts de ingestión: solo stdlib.
- **`pdftotext`** (paquete `poppler-utils`) — únicamente para la extracción de
  texto de `ingest_aqc.py`; con `--skip-text` no hace falta.
- **`.venv/` con `sentence-transformers`** — únicamente para `rag_aqc.py`.
  Si no existe: `python3 -m venv --without-pip .venv`, instalar pip con
  get-pip.py y `.venv/bin/pip install sentence-transformers`. La primera
  corrida de `build` descarga el modelo (~120 MB) a `~/.cache/huggingface/`.

## Licencias de los datos descargados

| Fuente | Licencia |
|---|---|
| DPE ADEME, BDNB, RNB, Géorisques | Licence Ouverte (Etalab) — uso comercial OK con atribución |
| geoportail.lu / data.public.lu (ACT) | CC0 |
| UrbIS (Bruselas) | CC0 (parcelas catastrales: licencia SPF Finances) |
| GRB (Flandes) | Gratis Open Data Licentie Vlaanderen — atribución obligatoria |
| VEKA (Flandes) | Modellicentie Gratis Hergebruik — reuso libre |
| Fichas patología AQC | Descarga libre, sin licencia abierta explícita — uso como corpus interno citando AQC |

## Estructura del proyecto

```
├── compass_artifact_*.md        # reporte original de fuentes (entrada)
├── README.md                    # este documento
├── METODOLOGIA.md               # extracción, normalización, cruces y pendientes
├── INVENTARIO.md                # inventario detallado de los datos descargados
├── ingest_dpe.py                # paso 1 FR
├── ingest_rnb.py                # paso 2 FR
├── ingest_bdnb.py               # paso 3 FR
├── ingest_georisques.py         # paso 4 FR
├── ingest_geoportail_lu.py      # paso 1 LU
├── ingest_lu_3d.py              # paso 2 LU
├── ingest_aqc.py                # corpus RAG de patología (AQC)
├── rag_aqc.py                   # troceado + embeddings + búsqueda (usa .venv)
├── informe_edificio.py          # conector: datos estructurados → RAG → informe
├── ingest_be_geo.py             # Bélgica: UrbIS (Bruselas) / GRB (Flandes)
├── ingest_veka.py               # Bélgica: VEKA e-peil (Flandes)
├── ingest_lu_ortho.py           # Luxemburgo: chips CV de la ortofoto 2025
├── informes/                    # informes de riesgo generados (Markdown)
├── data/                        # todas las salidas (CSV/JSONL/GeoJSON)
├── corpus/aqc/                  # corpus RAG: pdf/, txt/, manifest.* y rag_index.db
├── .venv/                       # venv con sentence-transformers (solo rag_aqc.py)
└── downloads/                   # ficheros intermedios grandes — BORRABLE
```

`downloads/` (~1,2 GB: zips de CityGML, huellas nacionales, LOD1 descartado)
se puede borrar entero; `ingest_lu_3d.py` re-descarga lo que necesite.

## Trabajo futuro

La lista completa, priorizada por valor/esfuerzo y con el detalle de cada
punto, está en `METODOLOGIA.md` → §5. En resumen: cruce por dirección para
los DPE sin `id_rnb`; probar el modo `--llm` del generador de informes;
escalar a descargas masivas con millésimes fijados; cruces belgas de segundo
nivel (CAPAKEY/NIS → Statbel/VEKA); clasificador CV sobre los chips de
ortofoto; ampliar el corpus RAG (ITM, Legilux, JRC, TABULA); robustez de
ingeniería; y explorar Valonia (ODWB).
