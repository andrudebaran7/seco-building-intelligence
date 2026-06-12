# Methodology: data extraction, normalization and joins

> Spanish version: [METODOLOGIA.md](METODOLOGIA.md)

This document explains **how** the pipeline was built: where and with which
technique each piece of data was extracted, how it was normalized, and which
keys join the sources together. It complements `PIPELINE.md` (overview and
results) and `INVENTARIO.md` (which data files exist and what they contain).

Everything was verified live on June 11, 2026.

---

## 1. Extraction: technique per source

Each source exposes its data differently. This table summarizes the access
method that actually worked (not always the documented one):

| Source | Extraction technique | Discovered quirk |
|---|---|---|
| ADEME DPE (FR) | data-fair REST API, cursor (`next`) pagination | Supports column `select=` and `qs=` department filter; 600 req/min anonymous limit |
| RNB (FR) | REST API, one request per `rnb_id` | The bbox requires a specific order (lat_max first); cursor pagination |
| BDNB (FR) | PostgREST API, batched `field=in.(v1,v2,…)` filter | **Silent 10-row cap per response** (ignores `limit`); paginate with `offset` inside each batch |
| Géorisques RGA (FR) | REST API by coordinate `?latlon=lon,lat` | `200` with an **empty body** = point outside any mapped zone (not an error) |
| geoportail.lu (LU) | WFS 2.0 (GeoServer), `outputFormat=application/json` | Serves GeoJSON directly — no GML parsing; `startIndex` pagination |
| 3D Buildings 2023 (LU) | Per-commune zip via the data.public.lu udata API + inner `.gml` extraction | The height only exists in the CityGML (`bldg:measuredHeight`); the "light" 2D footprints only carry ground elevation |
| 2025 orthophoto (LU) | WMS GetMap, 40×40 m chips at 400×400 px | The open WMS serves every vintage 1967–2025 without registration; avoids the giant JP2s |
| UrbIS (BE-Brussels) | WFS 2.0 GeoServer | The "historical" GeoServer is empty; the live one (`geoservices-vector.irisnet.be`) was located via the portal's GeoNetwork |
| GRB (BE-Flanders) | WFS 2.0 | Works **without** the account the bulk download requires |
| VEKA (BE-Flanders) | Direct CSV download under `/Data/` | The portal root answers 403 (WAF) but the files are served; paths found in the DCAT catalog of metadata.vlaanderen.be |
| AQC sheets (corpus) | WordPress REST API (`/wp-json/wp/v2/media`) + PDF downloads | No HTML scraping; text extracted with `pdftotext -layout` |

Shared extraction conventions across all scripts:

- **No keys, no registration**: every source is queried anonymously.
- **Courtesy pauses** (0.2–0.5 s) between requests, below any documented limit.
- **Identifiable User-Agent** (`ingest-test/0.1`); some portals (AQC, UrbIS,
  VEKA) require a browser-like UA.
- **Cache for large downloads**: zips (CityGML, orthophotos) are not
  re-downloaded if already present in `downloads/`.

---

## 2. Normalization

### 2.1 Output formats

Every tabular output is written **twice**:

- **CSV** — for human analysis (Excel, pandas).
- **JSONL** (one JSON object per line) — for chaining scripts: each pipeline
  step reads the previous step's JSONL. It is the project's canonical format.

Geometries are stored separately as **GeoJSON** (WGS84), directly usable in
QGIS/kepler.gl. Indexes (RAG) live in **SQLite**.

### 2.2 Coordinate reference systems

Every source is requested in or converted to **EPSG:4326 (WGS84, lon/lat)**:

- The French APIs already serve WGS84.
- The WFS services (LU, BE) are requested with `srsName=EPSG:4326`, avoiding
  client-side reprojection from LUREF (EPSG:2169) or Belgian Lambert
  (EPSG:31370).
- The only source left in its native CRS is the explored-and-discarded
  Luxembourg GPKG (not used in any join).

### 2.3 Field selection and renaming

- **DPE**: 14 relevant fields are selected from the dataset's 230 (identity,
  normalized BAN address, characteristics, labels, consumption). Selection
  happens in the API itself (`select=`), not client-side.
- **Per-source prefixes**: when joining, each source contributes its columns
  with a prefix (`rnb_*`, `bdnb_*`) so the origin of every value is obvious
  and there are no collisions (e.g. the DPE's `annee_construction` vs the
  cadastral `bdnb_annee_construction`, which can disagree and are both kept
  deliberately).
- **Flattened geometries**: for the CSV, polygons are reduced to centroid
  (`lon`, `lat`) and scalar attributes; the full geometry lives in GeoJSON.

### 2.4 Vocabularies and special values

- **Clay risk**: Géorisques answers "Exposition faible/moyenne/forte" and
  BDNB "Faible/Moyen/Fort". Everything is normalized **to the BDNB
  vocabulary** (`Faible | Moyen | Fort`), and Géorisques' empty body is
  encoded as **`Non exposé`** — distinct from null, which means "not queried".
- **Traceability**: the consolidated column travels with its source
  (`alea_argiles_source = BDNB | Géorisques`). General project rule: when a
  value can come from two places, record where it came from.
- **IDs as text**, never as numbers (Belgian CAPAKEYs and NIS codes have
  leading zeros; RNB ids are alphanumeric).
- **Encoding**: UTF-8 everywhere; VEKA CSVs arrive with a BOM (`utf-8-sig`)
  and GML/XML files are read with `errors="replace"` due to occasional
  invalid bytes.

### 2.5 Corpus normalization (RAG)

- **Text**: `pdftotext -layout` preserves the visual structure of the sheets.
- **Chunking**: by paragraph, accumulating up to ~1,200 characters with a
  **200-character overlap** so no concept is cut between fragments.
- **Embeddings**: `intfloat/multilingual-e5-small` (384 dims), following the
  model's convention: documents prefixed `passage:` and queries `query:`.
  Vectors are **normalized** → dot product equals cosine similarity.
- **Per-fragment metadata**: sheet code (A.01–G.13), theme (letter), title
  and source file — what is needed to cite the source in any answer.

---

## 3. Joins: the keys that connect the sources

### 3.1 France — exact identifier join

```
DPE ──(id_rnb)──> RNB ──(id_rnb)──> BDNB[batiment_construction]
                                        │ (batiment_groupe_id)
                                        ├──> BDNB[ffo_bat]      materials, floors
                                        └──> BDNB[argiles]      clay risk
DPE+RNB+BDNB ──(rnb_lon, rnb_lat)──> Géorisques RGA   (only where BDNB had no value)
```

- **`id_rnb`** is the national pivot identifier (recommended by the source
  report itself). Present in 17–52% of recent DPEs depending on territory.
- Inside BDNB the join takes two hops: `rnb_id → batiment_groupe_id` (table
  `batiment_construction`) and from there to the attribute tables. Queries go
  in **batches of 50 IDs** (`in.(...)`) paginated with `offset`.
- **Deduplication first**: several DPEs (apartments) share one building; each
  `rnb_id` is queried once and the result is fanned out to all its DPE rows.
- The Géorisques join is **by coordinate**, only for the gaps, and is the
  only spatial join in the French chain.
- **Cardinality**: the final dataset is 1 row = 1 DPE (not 1 building);
  a building with 3 DPEs appears 3 times with the same building attributes.

### 3.2 Luxembourg — spatial join + ID join

```
WFS buildings (polygons)
   ▲ point-in-polygon              ▲ point-in-polygon
addresses (points)           building centroid → parcels (polygons)

INSPIRE building "Building2D.ACT_<uuid>"  ──(strip prefix)──>  CityGML "ACT_<uuid>" → height
building (lon, lat) ──(GetMap bbox)──> orthophoto chip
```

- **Hand-rolled point-in-polygon** (ray casting in pure Python, no
  dependencies): each address point is assigned to the building containing
  it; each building centroid to its parcel. Only the outer ring of polygons
  is evaluated (sufficient in practice for this use).
- **The finding that avoided spatial matching with the 3D data**: the UUIDs
  of the WFS layer (`Building2D.ACT_x`) and the CityGML (`ACT_x`) are the
  same ID with different prefixes → the height join is an exact match after
  `removeprefix("Building2D.")`.
- **Orthophoto chips** are generated by a metric bbox around the centroid
  (40×40 m → 400×400 px ≈ the native 10 cm/pixel resolution), and the
  manifest carries the structured labels (height, parcel, address).

### 3.3 Belgium — same spatial pattern, national cadastral key

- Same point-in-polygon as Luxembourg (Brussels: addresses + parcels;
  Flanders: parcels only, GRB exposes no address layer).
- The output key is the **CAPAKEY** (Belgian national cadastral key, present
  in UrbIS and GRB) and the municipal **NIS code** — the hooks for future
  joins with Statbel and with VEKA's per-municipality e-peil.

### 3.4 Semantic join — structured data ↔ corpus

The connector (`informe_edificio.py`) links the two halves without any shared
key, by **meaning**:

```
structured attribute             pathology query (FR)                      retrieved sheets
alea_argiles ∈ {Fort, Moyen} →  "retrait-gonflement des argiles…"      →  [A.02] [A.05]
etiquette_dpe ∈ {F, G}       →  "condensations moisissures logements…" →  [E.09]
mat_mur ~ PIERRE/MEULIERE    →  "remontées capillaires murs pierre"    →  [B.01]
mat_toit ~ TUILES/ZINC/ARD.  →  "infiltrations couverture…"            →  [C.06]/[C.07]
periode = avant 1948         →  "structure plancher bois ancien"       →  [B.11]
```

Each rule is a pair (condition on the record, query in French). The queries
were **tuned empirically**: the first version of two of them retrieved
poorly-matching sheets; variants were tested against the index and replaced.
Lesson: in RAG, query wording matters as much as the embeddings model.

The resulting report cites every pathology with its `[code]` sheet and
similarity score — the structured data says *how much* risk there is and the
sheet explains *what* it is and *how* it manifests.

---

## 4. Validations applied

1. **Join coverage measured and reported** (every script prints a summary):
   100% RNB, 93–100% BDNB, 99–100% parcels, 63–88% addresses, 69% heights
   (explainable: bbox larger than the commune + the CityGML's 20 m² floor).
2. **Cross-validation between independent sources**: a control building with
   `Fort` in BDNB returned "Exposition forte" in Géorisques.
3. **Regional plausibility**: coherent dominant materials (zinc in Paris,
   tiles in Gironde); heights with a 9.4 m median in a village.
4. **Visual verification**: GeoJSONs inspectable in QGIS; orthophoto chips
   reviewed by eye (roof centered, sharpness).
5. **Cross-lingual search verified**: a Spanish query retrieves the correct
   French sheet.
6. **Extraction pipeline measured against ground truth** (see
   `evaluacion.md`): metadata 100%, AQC classification top-1 55.4% /
   top-3 73.3%, macro F1 0.59, with confusion analysis.

---

## 5. Future work (pending)

Ordered by estimated value/effort:

1. **Address join for DPEs without `id_rnb`** (48–83% of DPEs). The BAN
   address is already normalized; the RNB API supports address search. Would
   push the French chain's coverage toward ~100%.
2. ~~Test the report generator's `--llm` mode~~ — **done**: verified
   end-to-end with Gemini (free tier) and multi-provider support added
   (anthropic / gemini / openrouter).
3. **Scale to volume**: replace APIs with bulk downloads (BDNB GPKG per
   département, RNB dump) and join locally; pin vintages of every source for
   reproducibility (an RNB-current vs BDNB-2025-07 mismatch was observed).
4. **Second-level Belgian joins**: CAPAKEY → federal cadastre; NIS → Statbel
   (stock, permits) and VEKA e-peil per municipality, replicating the French
   enrichment scheme.
5. **CV module**: train/evaluate a classifier on the orthophoto chips (roof
   condition) with transfer from SDNET2018/METU (both CC-BY, commercially
   usable per the source report). Chips already come labeled with
   height/parcel/address.
6. **Expand the RAG corpus**: ITM prescriptions (LU), Legilux XML, JRC
   Eurocodes reports, TABULA/EPISCOPE — all free per the source report; the
   fragment+metadata+embedding scheme is already in place.
7. **Engineering hardening** (conscious prototype debt): retries with
   backoff, point-in-polygon with a spatial index (R-tree) for large zones,
   polygon inner rings, more automated tests, and an orchestrator chaining
   the steps without manual invocation (partially addressed by the Makefile).
8. **Wallonia**: the only uncovered region; the source report flagged its
   open data as incomplete (ODWB portal to explore).

---

## 6. Project document map

| Document | Content |
|---|---|
| `README.md` (root) | Product README per the challenge brief |
| `docs/PIPELINE.md` | Full technical documentation: results, 17 findings |
| `docs/METHODOLOGY.md` | This document (Spanish: `METODOLOGIA.md`) |
| `docs/INVENTARIO.md` | Which data files exist, from which source (ES) |
| `docs/evaluacion.md` | AI evaluation detail (metrics, confusions) |
| `docs/research/` | Challenge brief + product research reports |
| Each script's docstring | Usage, source, license and quirks (`--help`) |
