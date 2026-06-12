# SECO Building Intelligence — common tasks.
# Run `make help` (or just `make`) to see what's available.

PY    := .venv/bin/python
DEPT  ?= 33
LIMIT ?= 500

.PHONY: help setup ui pipeline-fr corpus rag search extract eval report test clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target> [DEPT=33] [LIMIT=500]\n\n"} \
	      /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create .venv and install dependencies (handles missing ensurepip)
	@python3 -m venv .venv 2>/dev/null || python3 -m venv --without-pip .venv
	@test -x .venv/bin/pip || (curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py \
	    && $(PY) /tmp/get-pip.py --quiet)
	.venv/bin/pip install --quiet -r requirements.txt
	@echo "Done. Try: make ui"

ui: ## Launch the Streamlit app (all demo data ships in the repo)
	.venv/bin/streamlit run app.py

pipeline-fr: ## Run the full French chain: DPE -> RNB -> BDNB -> clay risk (DEPT, LIMIT)
	python3 ingest_dpe.py --departement $(DEPT) --limit $(LIMIT)
	python3 ingest_rnb.py --dpe-file data/dpe_dpto$(DEPT).jsonl
	python3 ingest_bdnb.py --in-file data/dpe_rnb_dpto$(DEPT).jsonl
	python3 ingest_georisques.py --in-file data/dpe_rnb_bdnb_dpto$(DEPT).jsonl

corpus: ## Download the AQC pathology corpus (89 PDFs + text + manifest)
	python3 ingest_aqc.py

rag: ## Build the RAG index (chunking + embeddings) over the corpus
	$(PY) rag_aqc.py build

search: ## Semantic search, e.g.: make search Q="fissures argiles"
	$(PY) rag_aqc.py search "$(Q)" --top 5

extract: ## Generate synthetic inspection reports and extract them to SQLite
	$(PY) sintetizar_informes.py
	$(PY) extraer_informes.py

eval: ## Evaluate the extraction pipeline against ground truth (F1 metrics)
	$(PY) evaluar_extraccion.py

report: ## Per-building risk report (LLM=gemini|openrouter|anthropic, LANGS=es,en,fr, PDF=1)
	$(PY) informe_edificio.py --max-riesgo $(if $(LLM),--llm $(LLM),) \
	    $(if $(LANGS),--idiomas $(LANGS),) $(if $(PDF),--pdf,)

test: ## Run the test suite
	$(PY) -m pytest -q

clean: ## Remove re-downloadable intermediates (downloads/, caches)
	rm -rf downloads/ __pycache__ .pytest_cache
