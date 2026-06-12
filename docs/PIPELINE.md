# Open building data ingestion pipeline (FR / LU / BE)

> Spanish version: [PIPELINE.es.md](PIPELINE.es.md)

Proof of concept demonstrating, with real data, that the public sources
described in the preliminary source research can be
extracted automatically, cross-referenced with each other and queried
semantically. Everything was verified live on **June 11, 2026**, with no
registration and no API keys. The ingestion scripts use only the Python 3
standard library; the RAG index and the extraction pipeline are the only
components with dependencies (local embeddings model in `.venv/`).

Companion documentation: **`docs/METODOLOGIA.md`** (how each piece of data was
extracted, normalized and joined, plus future work), **`docs/INVENTARIO.md`**
(which data files exist and what they contain) and **`evaluacion.md`**
(metrics of the extraction pipeline).

## Result in one sentence

The two halves of the "Building Intelligence" MVP were built on 7+ sources:
(1) a structured "identity card" per building — in France, energy diagnosis +
identity/geometry + materials/height + geotechnical risk (ADEME → RNB → BDNB →
Géorisques); in Luxembourg, footprint + address + cadastral parcel + 3D height
(geoportail.lu → data.public.lu CityGML); in Belgium, footprint + national
cadastral key (UrbIS/GRB) — and (2) a construction-pathology RAG corpus
(89 AQC sheets) with multilingual semantic search that explains the risks the
structured half quantifies. On top of both: an **inspection-report extraction
pipeline with measured accuracy** and a per-building risk report generator.

## Architecture

### France chain (joined on `id_rnb`)

```
ingest_dpe.py          ingest_rnb.py              ingest_bdnb.py             ingest_georisques.py
ADEME DPE API    →     RNB API                →   BDNB API (CSTB)        →   Géorisques RGA API
energy                 geometry, status,          materials, height,         clay-shrinkage risk
diagnoses              coordinates                floors, use, clay risk     for BDNB gaps
(by département)       (by id_rnb)                (by id_rnb, batched)       (by lon/lat)

dpe_dptoNN.*     →     dpe_rnb_dptoNN.*       →   dpe_rnb_bdnb_dptoNN.*  →   dpe_rnb_bdnb_rga_dptoNN.*
```

Each step reads the previous step's JSONL and adds columns. The final record
has 27 fields: DPE (A–G labels, consumption, area, period) + RNB (status,
lon/lat, INSEE) + BDNB (height, footprint, wall/roof materials, floors,
dwellings, use) + consolidated clay risk with source traceability.

### Luxembourg chain (joined on the ACT building ID)

```
ingest_geoportail_lu.py                        ingest_lu_3d.py
INSPIRE WFS (wms.inspire.geoportail.lu)   →    CityGML per commune (data.public.lu)
buildings + addresses + parcels                bldg:measuredHeight per building
point-in-polygon spatial join                  exact join on ACT_<uuid> ID

lu_<zone>_batiments.* (+3 .geojson)       →    lu_<zone>_batiments_3d.*
```

### RAG corpus chain (pathology + regulations)

```
ingest_aqc.py: AQC pathology sheets (FR)       rag_aqc.py
  WordPress API → 89 PDFs + text          →    chunking (~1,200 chars, 200 overlap)
ingest_itm.py: ITM prescriptions (LU)          + multilingual-e5-small embeddings
  conditions-types page → 143 PDFs             + cosine search, source + lang columns
  (building/fire series, FR + DE)
corpus/{aqc,itm}/ + manifests             →    corpus/rag_index.db (232 docs, 7,551 chunks)
```

Risk reports cite **AQC only** (pathology); the search UI spans both corpora
with a source filter.

### Connector: per-building risk report

```
informe_edificio.py
final FR dataset (dpe_rnb_bdnb_rga_*.jsonl)  →  risk signals  →  RAG retrieval  →  Markdown report
  clay risk Fort/Moyen ──────────────────────→  "retrait-gonflement argiles"  →  [A.02] [A.05]
  energy label F/G ──────────────────────────→  "condensations logements"     →  [E.09]
  PIERRE/MEULIERE walls ─────────────────────→  "remontées capillaires"       →  [B.01]
  TUILES/ARDOISES/ZINC roof ─────────────────→  "infiltrations couverture"    →  [C.06]/[C.07]
  built before 1948 ─────────────────────────→  "structure plancher bois"     →  [B.11]
```

Each structured attribute of the building becomes a pathology query; the RAG
index retrieves the 2 best sheets per signal and the final report cites each
pathology with its AQC sheet.

**Output options:**

- **Languages** — `--idiomas es,en,fr` (default `es`) generates one report
  per language: title, identity-card labels, risk-signal headings and the
  legal footer are fully translated; the **AQC sheet excerpts stay in
  French** in every language (they are literal corpus citations), and the
  RAG queries are always French (the corpus language), so retrieval quality
  does not depend on the report language.
- **Formats** — Markdown always; `--pdf` additionally exports each report
  to PDF (via `markdown-pdf`), keeping both files side by side:
  `informe_<dpe>_<mode>_<lang>.md` + `.pdf`.
- **Drafting** — template mode (no LLM, default) or
  `--llm anthropic|gemini|openrouter` (model overridable with `--modelo`;
  the output language is instructed in the prompt). Keys via
  `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY`.

```bash
# one report per language, each with its PDF:
.venv/bin/python informe_edificio.py --max-riesgo --idiomas es,en,fr --pdf
# same via make, with LLM drafting in French:
make report LANGS=fr PDF=1 LLM=gemini
```

### Report extraction pipeline (evaluated AI core)

```
sintetizar_informes.py        extraer_informes.py             evaluar_extraccion.py
30 synthetic inspection   →   PDF → text → metadata parse →   metrics vs ground truth:
reports (PDF, 3 layouts,      hybrid classification of        metadata 100%, top-1 55%,
real addresses, 101           each observation to the         top-3 73% (product metric,
defects in free French)       89-sheet AQC taxonomy           human-in-the-loop),
+ ground truth JSONL          (embeddings 0.7 + TF-IDF 0.3)   macro F1 0.59
                              → SQLite defectos.db            → docs/evaluacion.md
```

SECO does not publish real reports (confidential), so the pipeline is
demonstrated on realistic synthetic ones: real building addresses from our
datasets, defect observations written in free inspector French (not copied
from the AQC sheets, so the classification is a genuine semantic task) and
three different layouts. Remaining top-1 errors are dominated by sibling
sheets of the taxonomy (A.01/A.02 are two parts of the same phenomenon),
which is why the product metric is top-3 with inspector validation.

## The scripts

| Script | Source | Input | Output |
|---|---|---|---|
| `ingest_dpe.py` | ADEME DPE API | `--departement`, `--limit` | `data/dpe_dptoNN.{csv,jsonl}` |
| `ingest_rnb.py` | RNB API | `--dpe-file` | `data/dpe_rnb_dptoNN.{csv,jsonl,geojson}` |
| `ingest_bdnb.py` | BDNB API | `--in-file` | `data/dpe_rnb_bdnb_dptoNN.{csv,jsonl}` |
| `ingest_georisques.py` | Géorisques RGA API | `--in-file` | `data/dpe_rnb_bdnb_rga_dptoNN.{csv,jsonl}` |
| `ingest_geoportail_lu.py` | LU INSPIRE WFS | `--bbox`, `--zona` | `data/lu_<zone>_batiments.{csv,jsonl}` + 3 GeoJSON |
| `ingest_lu_3d.py` | LU 3D Buildings 2023 | `--commune` | `data/lu_<commune>_batiments_3d.{csv,jsonl}` + heights CSV |
| `ingest_aqc.py` | AQC pathology sheets | `--out`, `--skip-text` | `corpus/aqc/{pdf,txt}/` + `manifest.{csv,jsonl}` |
| `ingest_itm.py` | ITM prescriptions (LU) | `--series` | `corpus/itm/{pdf,txt}/` + `manifest.{csv,jsonl}` |
| `rag_aqc.py` | AQC + ITM corpora | `build` / `search "query"` | `corpus/rag_index.db` (SQLite with embeddings) |
| `informe_edificio.py` | Final FR dataset + RAG index | `--max-riesgo` / `--numero-dpe`, `--llm <provider>`, `--idiomas es,en,fr`, `--pdf` | `informes/informe_<dpe>_<mode>_<lang>.{md,pdf}` |
| `ingest_be_geo.py` | UrbIS (BXL) / GRB (VL) via WFS; PICC+CadGIS (Wallonia) via ArcGIS REST | `--region`, `--bbox`, `--zona` | `data/be_<region>_<zone>_batiments.{csv,jsonl}` + GeoJSON |
| `ingest_veka.py` | VEKA open data (Flanders) | `--dataset` | `data/veka_<dataset>.csv` |
| `ingest_be_stats.py` | Statbel + VEKA by NIS | `--in-file` | `data/be_*_batiments_ctx.{csv,jsonl}` |
| `ingest_lu_ortho.py` | LU 2025 orthophoto (WMS) | `--batiments`, `--limit`, `--margen` | `data/ortho_chips/<zone>/` (JPEG + manifest) |
| `sintetizar_informes.py` | Own FR dataset + defect catalog | `--n`, `--seed` | `informes_sinteticos/pdf/` + `ground_truth.jsonl` |
| `extraer_informes.py` | Synthetic PDFs + AQC taxonomy | `--pdf-dir` | `informes_sinteticos/defectos.db` (SQLite) |
| `evaluar_extraccion.py` | Extraction DB + ground truth | — | `evaluacion.{md,json}` |

### Full example run

```bash
# France — any département (tested with 75 Paris and 33 Gironde)
python3 ingest_dpe.py --departement 33 --limit 500
python3 ingest_rnb.py --dpe-file data/dpe_dpto33.jsonl
python3 ingest_bdnb.py --in-file data/dpe_rnb_dpto33.jsonl
python3 ingest_georisques.py --in-file data/dpe_rnb_bdnb_dpto33.jsonl

# Luxembourg — any zone/commune (tested with Luxembourg City and Bettendorf)
python3 ingest_geoportail_lu.py --bbox 49.86,6.17,49.90,6.26 --zona bettendorf
python3 ingest_lu_3d.py --commune bettendorf
python3 ingest_lu_ortho.py                                 # CV chips from the 2025 orthophoto

# Belgium — Brussels (UrbIS) and Flanders (GRB + VEKA)
python3 ingest_be_geo.py --region bruselas                 # Grand-Place by default
python3 ingest_be_geo.py --region flandes --bbox 51.05,3.71,51.06,3.74 --zona gent
python3 ingest_veka.py                                     # e-peil per municipality

# RAG corpus — AQC pathology sheets (PDF + text + manifest)
python3 ingest_aqc.py

# RAG index — chunking + embeddings + semantic search (requires the venv)
.venv/bin/python rag_aqc.py build
.venv/bin/python rag_aqc.py search "fissures causées par les argiles" --top 5

# Per-building risk report — connects structured data with the RAG
.venv/bin/python informe_edificio.py --max-riesgo                      # building with most signals
.venv/bin/python informe_edificio.py --max-riesgo --idiomas es,en,fr --pdf  # trilingual + PDF
.venv/bin/python informe_edificio.py --numero-dpe 2633E1530986O --llm gemini --idiomas fr

# Report extraction pipeline with evaluation
.venv/bin/python sintetizar_informes.py
.venv/bin/python extraer_informes.py
.venv/bin/python evaluar_extraccion.py
```

Note: the ingestion scripts are pure standard-library Python; `rag_aqc.py`,
the extraction pipeline and the report generator use the venv
(`sentence-transformers`, `scikit-learn`, `fpdf2`, `anthropic`). The venv was
created with `python3 -m venv --without-pip .venv` + get-pip.py because the
system lacks `ensurepip` (see Requirements).

Shared conventions: dual CSV (analysis) + JSONL (pipelines) output, courtesy
pauses between requests, a control summary at the end of every run, and
`--help` on every script.

## Results of the test runs

### France

| Metric | Dept 75 (Paris) | Dept 33 (Gironde) |
|---|---|---|
| DPE available in the API | 813,827 | 378,013 |
| DPE downloaded (sample) | 500 | 500 |
| With `id_rnb` | 83 (17%) | 259 (52%) |
| Matched via BAN address (fallback) | +408 | +189 |
| **RNB coverage (id + address)** | **491 (98%)** | **448 (90%)** |
| Found in BDNB | 442/443 buildings (99.8%) | — (90%+ of matched) |
| Final dataset (full chain) | 490 DPE | 423 DPE |
| Consolidated clay risk | 100% (489 not exposed, 1 Moyen) | 100% (159 Fort, 239 Moyen, 25 not exposed) |

Materials reflect regional reality (plausibility check): stone/brick and zinc
roofing in Paris; brick/stone and tiles in Gironde.

### Luxembourg

| Metric | Luxembourg City (center) | Bettendorf |
|---|---|---|
| Buildings (INSPIRE WFS) | 788 | 2,037 |
| With address (point-in-polygon) | 88% | 63% |
| With cadastral parcel | 100% | 99% |
| With 3D height (CityGML) | — | 1,411 (69%) |

### 2025 orthophoto (Luxembourg, CV module)

24 JPEG chips of 400×400 px (40×40 m, ≈10 cm/pixel) centered on Bettendorf
buildings, visually verified (roofs centered, cars distinguishable), all with
a 3D-height label in the manifest. 0 failures, 0.8 MB. Chip + height + parcel
+ address turns the pipeline into a labeled-training-dataset generator.

### Belgium

| Metric | Brussels (UrbIS) | Antwerp (GRB) | Liège (PICC) |
|---|---|---|---|
| Buildings | 2,086 (WFS) | 3,018 (WFS) | 3,515 (ArcGIS REST) |
| With cadastral parcel (CAPAKEY) | 100% | 99% | 97% (federal INSPIRE/CP) |
| With address (point-in-polygon) | 86% | — | — |
| With NIS commune context (Statbel) | 99.8% | 99.4% | 44%* |

\* In Wallonia the NIS is derived from the CAPAKEY prefix, which is the
*cadastral division* (pre-merger commune codes) — it only approximates the
current NIS. Brussels/Flanders parcels carry the true NISCODE directly.

**Second-level NIS join** (`ingest_be_stats.py` → `be_*_batiments_ctx.*`):
each building gets its commune's Statbel building-stock profile (total
buildings, % pre-1946, % post-1981, % central heating, dwellings — the
"pathology-by-epoch" context) and, in Flanders, the VEKA mean e-peil.
Sample: Brussels NIS 21004 = 69% pre-1946; Antwerp NIS 11002 = 48.7%
pre-1946, mean e-peil 52.3; Liège NIS 62063 = 63.3% pre-1946.

VEKA: average e-peil per municipality CSV downloaded (12,379 rows, 322
municipalities, time series by permit year and use type). It is the Flemish
aggregated equivalent of the French DPE — no open individual certificate.

### RAG corpus (AQC pathology + ITM regulations)

| Metric | Value |
|---|---|
| AQC sheets (FR) | 89 (themes A:10 B:13 C:13 D:14 E:16 F:10 G:13) |
| ITM prescriptions (LU, building/fire series) | 143 (140 FR + 3 DE), median ~29,000 chars |
| Indexed chunks | 7,551 × 384 dimensions (232 documents) |
| Index size | ~30 MB (SQLite), `fuente` and `lang` per chunk |

Validation queries (top-1 correct in both):
- FR: *"fissures dans les murs causées par le retrait-gonflement des argiles"*
  → A.05 and A.02 (foundation movements in clay soils), score ~0.89.
- ES (cross-lingual): *"humedad y condensación en ventanas por mala ventilación"*
  → E.09 "Condensations dans les logements" and E.08 "VMC", score ~0.85.
- ITM (FR): *"désenfumage des bâtiments élevés sécurité incendie"* →
  ITM-SST 1500/1503 fire-prevention prescriptions, score ~0.91.
- ITM (DE): *"Sicherheitsvorschriften für Aufzüge"* → German-language ITM
  documents. Pathology queries remain AQC-dominated (no cross-corpus noise).

**Retrieval benchmark** (22 gold queries in FR/ES/EN/DE,
`evaluar_retrieval.py` → `evaluacion_retrieval.md`):

| Segment | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| Global (n=22) | 45% | 73% | 86% | 0.62 |
| AQC pathology (n=16) | 50% | 75% | — | — |
| ITM regulations (n=6) | 33% | 67% | — | — |

Miss analysis: most misses are rank-2 with a *related* document first
(B.02 vs B.01, both humidity) — taxonomy granularity, same pattern as the
classifier. Cross-lingual queries (ES/EN) score below French ones. One
discovered data quirk: ITM-SST 1106 ("Blitzschutz") is written in German
despite carrying no `-de` suffix, so French queries about lightning
protection miss it while German ones hit it.

### Risk reports (structured ↔ RAG connector)

Demonstrated on two distinct profiles (template mode):
- **Bordeaux** (`informes/informe_2633E1530986O_plantilla.md`): pre-1948
  building, stone/tiles, label F, clay risk Moyen → 5 signals, 10 relevant
  cited sheets (A.02/A.05 clay, E.09 condensation, B.01 rising damp,
  C.06 tile roofing, B.11 timber structure).
- **Paris** (`informes/informe_2675E1536668S_plantilla.md`): label G, stone,
  zinc roof, pre-1948 → 4 signals (no clay, with C.07 condensation under
  metal roofing), consistent with the Parisian profile.
- **Languages and PDF verified**: the Bordeaux report generated in es/en/fr
  (template mode, all strings translated, French AQC citations intact) and
  in French via Gemini (`--llm gemini --idiomas fr`), each with its PDF
  export rendering title, identity table and citations correctly.

### CV module: crack triage for inspection photos

CPU-friendly transfer learning: frozen MobileNetV3-Small (ImageNet) +
logistic head, trained on the METU concrete-crack dataset (CC BY 4.0,
auto-downloaded; the free Debian 7z lacks the RAR codec — extraction uses
libarchive). Measured on a held-out 1,000-image test set:

| Metric | Value |
|---|---|
| Accuracy | **99.9%** |
| Precision / Recall (crack) | 99.8% / 100% |
| F1 | 0.999 |

**Domain**: close-up surface photos (what an inspector shoots on site) —
not aerial/orthophoto imagery, and METU is a clean benchmark (real-world
photos will be harder). Integration: `clasificar_fotos.py --a-defectos REF`
registers positive detections as observations in the same defects DB,
classified to the AQC taxonomy by the existing hybrid classifier
(`origen='cv'`) — the "document+vision hybrid" from the product research.
The UI gains a Photo-triage tab with live upload. Full reference
(dataset, model, expected input sizes, limits): [`CV.md`](CV.md).

### Extraction pipeline (measured)

| Metric | Value |
|---|---|
| Metadata (ref, date, address, inspector) | 100% exact match |
| Observation coverage / severity / location | 100% |
| AQC code classification, top-1 (89 classes) | 55.4% |
| AQC code classification, top-3 (product metric) | 73.3% |
| Macro F1 (top-1) | 0.59 |

Full breakdown, per-code F1 and confusion analysis in `evaluacion.md`.
Reaching this required 4 method iterations (naive chunk retrieval scored
19.8%; the bigger e5-base model scored *worse* than e5-small; the winner is
a hybrid of embeddings over cleaned per-sheet profiles + TF-IDF).

## Findings and traps discovered (not documented in the original report)

1. **The open BDNB API returns at most 10 rows per response** for anonymous
   users and **silently ignores the `limit` parameter**. An `in.(...)` filter
   with 50 IDs returned only 10 results with no error. Fix: paginate with
   `offset` inside each batch (implemented in `ingest_bdnb.py`). For real
   volume, use the bulk per-département download from data.gouv.fr.

2. **Géorisques replies `200` with an empty body** when the queried point is
   outside any mapped RGA exposure zone. It is not an error: it means "not
   exposed". The script records it as `Non exposé` to distinguish it from
   "not queried".

3. **BDNB ↔ Géorisques cross-validation**: for a control building in Gironde,
   BDNB said `Fort` and Géorisques returned "Exposition forte" for its
   coordinates. The two sources are consistent.

4. **A "Base de données nationale des bâtiments 3D 2023" exists** on
   data.public.lu (the report only listed 2017 and 2020) and, unlike the 2020
   edition, **it covers Luxembourg City**. LOD 2.2, CC0.

5. **The "light" 2D footprints of the Luxembourg 3D dataset do NOT carry the
   height**: both the national GPKG (63 MB) and the GeoJSON (46 MB) only
   contain the ground elevation (`zmin`). The height (`bldg:measuredHeight`)
   lives only in the **per-commune CityGML files** (150 MB–5.4 GB because they
   include jpg textures; the inner `.gml` is ~25% of the zip).

6. **Luxembourg building IDs are consistent across sources**: the CityGML uses
   `ACT_<uuid>` and the INSPIRE WFS layer `Building2D.ACT_<uuid>`. The join is
   an exact ID match — no spatial matching or reprojection from LUREF
   (EPSG:2169) needed.

7. **`id_rnb` coverage in DPE records varies a lot by territory**: 52% in
   Gironde vs 17% in Paris (in recent DPEs). **Mitigated**: the DPE's
   `identifiant_ban` works as the RNB API's `cle_interop_ban` when it is a
   full address key (commune_street_number), which lifts coverage to 90-98%
   with `rnb_match` recording the join path per record. Street-only BAN keys
   (no house number) remain unmatchable by design.

8. **Vintage mismatch**: 17 of 230 Gironde buildings were missing from the
   open BDNB (2025-07 vintage) despite existing in the current RNB. Confirms
   the report's warning: pin versions for reproducibility.

9. **The national LOD1 2013 file (31 MB) is a dead end** for the join: it has
   heights implicit in the solids but no IDs or attributes, and it is in
   LUREF. Discarded in favor of the 2023 CityGML.

10. **The geoportail.lu INSPIRE WFS serves GeoJSON directly**
    (`outputFormat=application/json`), avoiding GML parsing. The buildings
    layer has geometry but almost no attributes: the richness comes from the
    join with addresses and parcels (and from the CityGML for the height).

11. **The AQC sheets are listed via the site's WordPress REST API**
    (`/wp-json/wp/v2/media?search=Fiche-Pathologie`) — no HTML scraping. The
    current edition has **89 sheets** (the report counted 75+11=86; new ones
    have been added, e.g. G.13 from Sept 2025), in 7 themes A–G, all with
    direct-download PDFs and clean text extraction via `pdftotext -layout`.

12. **The "classic" UrbIS GeoServer is nearly empty; the current one is
    elsewhere**: `geoservices-urbis.irisnet.be` exposes one residual layer.
    The live layers (Buildings, Addresses, CadastralParcels) are at
    `geoservices-vector.irisnet.be/geoserver/urbisvector/wfs` — found via the
    portal's GeoNetwork (`catalog.datastore.brussels/geonetwork`, GN 3.8).
    datastore.brussels itself is a SPA with no obvious public API.

13. **The Flemish GRB WFS works without an account**: the report warned that
    the bulk download requires registration at download.vlaanderen.be, but
    `geo.api.vlaanderen.be/GRB/wfs` serves buildings (GBG) and parcels (ADP)
    as GeoJSON with no authentication. Only the license attribution is
    required.

14. **VEKA: the root answers 403 but the data downloads fine**:
    `open-data.energiesparen.be/` blocks (WAF), but files under
    `/Data/<NAME>.csv` are served without issue. The exact paths come from the
    DCAT catalog of `metadata.vlaanderen.be` (GeoNetwork 4, Elasticsearch
    API). The residential category is called `WONEN`.

15. **CAPAKEY is the Belgian join key**: both UrbIS (Brussels) and GRB
    (Flanders) expose the national cadastral key (`CAPAKEY`) and the NIS
    municipality code per parcel — the Belgian analogue of the French
    `id_rnb` for chaining sources (federal cadastre, Statbel by NIS).

16. **The open geoportail.lu WMS serves every orthophoto vintage without
    registration** (`wms.geoportail.lu/opendata/service`): from 1967 to 2025,
    including `ortho_2025` (summer) and `ortho_2025_winter`, as JPEG/PNG via
    GetMap. Requesting 40×40 m chips at 400×400 px reproduces the native
    ~10 cm/pixel resolution — no need to download the giant JP2 files to
    build computer-vision datasets.

17. **Embeddings were solved 100% locally, with no API keys**: the Anthropic
    API has no embeddings endpoint (it recommends Voyage AI, paid), so the
    index uses `intfloat/multilingual-e5-small` (~120 MB, MIT license) via
    sentence-transformers. The chunked corpus is 7,551 fragments × 384
    dimensions in a directly queryable SQLite file. The search is
    **verified cross-lingual**: Spanish queries retrieve the correct French
    sheets (e.g. "humedad y condensación en ventanas por mala ventilación" →
    E.09 "Condensations dans les logements" and E.08 "VMC").

## Data dictionary of the final French record

| Prefix | Fields | Source |
|---|---|---|
| (no prefix) | `numero_dpe`, `date_etablissement_dpe`, `id_rnb`, `identifiant_ban`, `adresse_ban`, `code_postal_ban`, `nom_commune_ban`, `code_departement_ban`, `type_batiment`, `periode_construction`, `annee_construction`, `surface_habitable_logement`, `etiquette_dpe`, `etiquette_ges`, `conso_5_usages_par_m2_ep` | ADEME DPE |
| `rnb_` | `status`, `lon`, `lat`, `insee_code`, `n_addresses`, `match` (id_rnb \| adresse_ban) | RNB |
| `bdnb_` | `batiment_groupe_id`, `hauteur`, `s_geom_cstr`, `altitude_sol`, `annee_construction`, `mat_mur`, `mat_toit`, `nb_niveau`, `nb_log`, `usage`, `alea_argiles` | BDNB |
| `alea_argiles_` | `final` (Faible/Moyen/Fort/Non exposé), `source` (BDNB/Géorisques) | consolidated |

Final Luxembourg record: `building_id`, `lon`, `lat`, `n_addresses`,
`adresse_ejemplo`, `parcel_ref`, `parcel_label`, `parcel_area_m2`, `hauteur_m`.

## Verified endpoints

| Source | Endpoint | Verified |
|---|---|---|
| ADEME DPE | `https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines` | ✓ 2026-06-11 |
| RNB | `https://rnb-api.beta.gouv.fr/api/alpha/buildings/` | ✓ 2026-06-11 |
| BDNB | `https://api.bdnb.io/v1/bdnb/donnees/<table>` (PostgREST) | ✓ 2026-06-11 |
| Géorisques RGA | `https://www.georisques.gouv.fr/api/v1/rga?latlon=lon,lat` | ✓ 2026-06-11 |
| LU INSPIRE WFS | `https://wms.inspire.geoportail.lu/geoserver/wfs` | ✓ 2026-06-11 |
| data.public.lu | `https://data.public.lu/api/1/datasets/` (udata) | ✓ 2026-06-11 |
| AQC (WordPress) | `https://qualiteconstruction.com/wp-json/wp/v2/media` | ✓ 2026-06-11 |
| UrbIS WFS (BXL) | `https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs` | ✓ 2026-06-11 |
| GRB WFS (VL) | `https://geo.api.vlaanderen.be/GRB/wfs` | ✓ 2026-06-11 |
| VEKA (VL) | `https://open-data.energiesparen.be/Data/<NAME>.csv` | ✓ 2026-06-11 |
| LU orthophoto WMS | `https://wms.geoportail.lu/opendata/service` | ✓ 2026-06-11 |

Known limits: ADEME 600 req/60 s (anonymous); BDNB 10 rows/response
(anonymous); RNB and Géorisques without documented limits (the scripts use
0.2–0.3 s pauses).

## Requirements

- **Python 3.10+** (tested with 3.13). The ingestion scripts: stdlib only.
- **`pdftotext`** (`poppler-utils` package) — only for the text extraction in
  `ingest_aqc.py` and `extraer_informes.py`.
- **`.venv/` with `sentence-transformers`** (plus `scikit-learn`, `fpdf2`,
  `anthropic`) — for the RAG index, the extraction pipeline and the report
  generator. If it does not exist: `python3 -m venv --without-pip .venv`,
  install pip with get-pip.py and `.venv/bin/pip install sentence-transformers
  fpdf2 anthropic`. The first `build` run downloads the model (~120 MB) into
  `~/.cache/huggingface/`.

## Licenses of the downloaded data

| Source | License |
|---|---|
| ADEME DPE, BDNB, RNB, Géorisques | Licence Ouverte (Etalab) — commercial use OK with attribution |
| geoportail.lu / data.public.lu (ACT) | CC0 |
| UrbIS (Brussels) | CC0 (cadastral parcels: SPF Finances license) |
| GRB (Flanders) | Gratis Open Data Licentie Vlaanderen — attribution required |
| VEKA (Flanders) | Modellicentie Gratis Hergebruik — free reuse |
| AQC pathology sheets | Free download, no explicit open license — internal corpus use citing AQC |

## Project structure

```
├── README.md                    # this document (English)
├── README.es.md                 # Spanish version
├── METODOLOGIA.md               # extraction, normalization, joins, future work
├── INVENTARIO.md                # detailed inventory of the downloaded data
├── docs/evaluacion.{md,json}    # extraction-pipeline metrics
├── ingest_dpe.py                # FR step 1
├── ingest_rnb.py                # FR step 2
├── ingest_bdnb.py               # FR step 3
├── ingest_georisques.py         # FR step 4
├── ingest_geoportail_lu.py      # LU step 1
├── ingest_lu_3d.py              # LU step 2
├── ingest_aqc.py                # pathology RAG corpus (AQC)
├── rag_aqc.py                   # chunking + embeddings + search (uses .venv)
├── informe_edificio.py          # connector: structured data → RAG → report
├── ingest_be_geo.py             # Belgium: UrbIS (Brussels) / GRB (Flanders)
├── ingest_veka.py               # Belgium: VEKA e-peil (Flanders)
├── ingest_lu_ortho.py           # Luxembourg: CV chips from the 2025 orthophoto
├── sintetizar_informes.py       # synthetic inspection reports + ground truth
├── extraer_informes.py          # PDF → structured defects DB (hybrid classifier)
├── evaluar_extraccion.py        # F1 metrics vs ground truth
├── informes/                    # generated risk reports (Markdown)
├── informes_sinteticos/         # synthetic PDFs, ground truth, defectos.db
├── data/                        # all outputs (CSV/JSONL/GeoJSON)
├── corpus/aqc/                  # RAG corpus: txt/, manifest.* and rag_index.db
├── .venv/                       # venv with dependencies (not in git)
└── downloads/                   # large intermediate files — DELETABLE (not in git)
```

`downloads/` (~1.5 GB: CityGML zips, national footprints, discarded LOD1) can
be deleted entirely; `ingest_lu_3d.py` re-downloads what it needs.

## Future work

The full list, prioritized by value/effort and with details for each item, is
in `docs/METODOLOGIA.md` → §5. In short: scale to bulk downloads
with pinned vintages; second-level Belgian joins (CAPAKEY/NIS →
Statbel/VEKA); a CV classifier on the orthophoto chips; expanding the RAG
corpus (ITM, Legilux, JRC, TABULA); engineering hardening; and exploring
Wallonia (ODWB).
