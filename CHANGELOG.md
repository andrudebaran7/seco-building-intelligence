# Changelog

Chronological record of how the project was built. Each phase maps to one or
more thematic commits; details live in the linked docs.

## Phase 1 — Open-data pipeline, France (2026-06-11)

- Verified live that the public sources from the preliminary research are
  automatically extractable (no keys, no registration).
- Built the French chain joined on `id_rnb`: ADEME DPE (energy diagnoses) →
  RNB (building identity/geometry) → BDNB (materials, height, use, clay
  risk) → Géorisques RGA (clay-shrinkage gaps by coordinate), with source
  traceability on the consolidated clay-risk column.
- Found and worked around the BDNB API's silent 10-row cap (offset
  pagination) and interpreted Géorisques' empty-200 as "not exposed".
- Tested on two départements (Paris 75, Gironde 33), 500 DPE each.

## Phase 2 — Luxembourg and Belgium chains (2026-06-11)

- Luxembourg: INSPIRE WFS (buildings + addresses + parcels, point-in-polygon
  joins) + 3D heights from the per-commune CityGML (exact ACT-id join) +
  10 cm orthophoto chips via the open WMS (labeled CV dataset).
- Belgium: UrbIS (Brussels) and GRB (Flanders) via WFS with the national
  cadastral key (CAPAKEY), plus VEKA's aggregated energy CSV. Located the
  live UrbIS GeoServer through a hidden GeoNetwork; confirmed GRB's WFS
  needs no account; found VEKA's data path behind a WAF-blocked root.

## Phase 3 — Pathology corpus and RAG (2026-06-11)

- Downloaded the 89 AQC Fiches Pathologie via the site's WordPress REST API,
  extracted text with `pdftotext -layout`.
- Built a local RAG index (multilingual-e5-small embeddings, SQLite),
  verified cross-lingual search (Spanish queries → correct French sheets).
- Connector `informe_edificio.py`: building attributes → risk signals →
  cited AQC sheets → per-building risk report (the structured data says
  *how much* risk; the sheet explains *what* it is).

## Phase 4 — Product build for the SECO challenge (2026-06-11/12)

- Git repository with thematic commits; published to GitHub.
- Synthetic inspection reports (30 PDFs, 3 layouts, real addresses, ground
  truth) + extraction pipeline with a **measured** hybrid classifier
  (embeddings 0.7 + TF-IDF 0.3): metadata 100%, AQC top-1 55%, top-3 73%
  (the product metric, human-in-the-loop), macro F1 0.59. The method was
  chosen by experiment (naive retrieval scored 19.8%; a bigger model scored
  worse).
- Streamlit UI (portfolio + map, semantic search, extraction demo with
  metrics up front), tested with AppTest, deployed to Streamlit Community
  Cloud.
- Product README per the challenge brief; technical docs under `docs/`;
  pytest suite + GitHub Actions CI; pinned `requirements.txt`; MIT license;
  internal material purged from git history (`git filter-repo`).

## Phase 5 — Multi-provider LLM and trilingual reports (2026-06-12)

- `--llm anthropic|gemini|openrouter` on the report generator (stdlib HTTP
  for Gemini/OpenRouter; Gemini endpoint fallback for AI-Studio vs Vertex
  key formats). Verified end-to-end with Gemini's free tier.
- Trilingual reports (`--idiomas es,en,fr`): fixed strings, signal headings
  and identity labels translated; AQC excerpts stay French (literal
  citations); RAG queries always French (corpus language).
- `--pdf` export (markdown-pdf), keeping the Markdown alongside.

## Phase 6 — Usability wave (2026-06-12)

- Makefile with self-documented targets (`setup`, `ui`, `pipeline-fr`,
  `corpus`, `rag`, `extract`, `eval`, `report`, `test`).
- Mermaid architecture diagram and a full usage guide in the README.
- About tab in the UI; report-language selector (the signals previously
  rendered Spanish-only in an English UI).
- In-app LLM drafting (Gemini key via env or Streamlit secret, clean
  fallback) and `.md`/`.pdf` download buttons.
- English methodology (`docs/METHODOLOGY.md`); demo-video script (local).

## Phase 7 — Data coverage and corpus breadth (2026-06-12)

- **Address fallback for the RNB join**: the DPE's `identifiant_ban` doubles
  as the RNB API's `cle_interop_ban` when it is a full address key — no
  geocoder needed. French coverage rose from 17%/52% (Paris/Gironde) to
  **98%/90%**, with per-record provenance (`rnb_match`).
- **ITM regulatory corpus**: 143 Luxembourg ITM-SST prescriptions
  (building/fire series, 140 FR + 3 DE) ingested from the conditions-types
  page; the RAG index became multi-corpus (232 docs, 7,551 chunks, source +
  language per chunk). The search UI spans pathology + regulations with a
  source filter; risk reports keep citing AQC only. JRC Eurocodes reports
  (the original second source) are WAF-blocked for non-browser clients —
  documented in the methodology.

## Phase 8 — Retrieval benchmark and full Belgian map (2026-06-12)

- **Retrieval evaluation**: 22-query gold benchmark in FR/ES/EN/DE over the
  multi-corpus index — hit@3 73%, hit@5 86%, MRR 0.62, with per-corpus and
  per-language breakdowns and miss analysis (cross-lingual queries
  underperform French; ITM-SST 1106 turned out to be German content without
  a `-de` suffix).
- **Wallonia**: PICC building footprints (SPW, ArcGIS REST with GeoJSON
  output — a different protocol from the WFS regions) + the **federal**
  INSPIRE/CP cadastre (SPF Finances) for parcels with the national CAPAKEY.
  All three Belgian regions covered.
- **Second-level NIS joins** (`ingest_be_stats.py`): every Belgian building
  enriched with its commune's Statbel building-stock profile (% pre-1946,
  % post-1981, central heating, dwellings) and VEKA's mean e-peil in
  Flanders. Documented caveat: Wallonia's NIS is derived from the CAPAKEY
  prefix (cadastral division ≈ pre-merger communes), so only ~44% match
  directly there.

## Reference

| Document | Content |
|---|---|
| `README.md` | Product README: problem, demo, sources, AI evaluation, trade-offs, usage guide |
| `docs/PIPELINE.md` / `.es.md` | Technical documentation: architecture, results, 17+ findings |
| `docs/METHODOLOGY.md` / `METODOLOGIA.md` | Extraction, normalization, joins, validations, future work |
| `docs/INVENTARIO.md` | Data inventory (what files, from which source) |
| `docs/evaluacion.md` | Extraction-pipeline metrics detail |
