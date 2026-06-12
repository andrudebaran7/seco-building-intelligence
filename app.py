#!/usr/bin/env python3
"""SECO Building Intelligence — Streamlit UI.

Three views on top of the pipeline outputs:
  1. Portfolio & buildings — the enriched French dataset (DPE+RNB+BDNB+clay
     risk) with filters, a map, and on-demand per-building risk reports
     grounded in the AQC pathology corpus.
  2. Pathology search — multilingual semantic search (FR/ES/EN) over the
     89 AQC sheets, with citations and scores.
  3. Inspection reports — the extraction-pipeline demo: defects extracted
     from (synthetic) PDF reports, classified to the AQC taxonomy, with the
     measured evaluation metrics displayed up front.

Run:
    .venv/bin/streamlit run app.py
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from informe_edificio import (T, derivar_senales, exportar_pdf, ficha_identidad,
                              informe_llm, informe_plantilla)

st.set_page_config(page_title="SECO Building Intelligence", page_icon="🏗️",
                   layout="wide")

MODEL_NAME = "intfloat/multilingual-e5-small"
RAG_DB = Path("corpus/rag_index.db")
MANIFEST = Path("corpus/aqc/manifest.jsonl")
DEFECTOS_DB = Path("informes_sinteticos/defectos.db")
EVAL_JSON = Path("docs/evaluacion.json")
DATASETS = {
    "Gironde (dept 33)": "data/dpe_rnb_bdnb_rga_dpto33.jsonl",
    "Paris (dept 75)": "data/dpe_rnb_bdnb_rga_dpto75.jsonl",
}


# ----------------------------------------------------------------- caches

@st.cache_resource(show_spinner="Loading embeddings model (first run only)...")
def get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


@st.cache_resource
def get_rag_index():
    import numpy as np
    con = sqlite3.connect(RAG_DB)
    data = con.execute("SELECT fuente, code, titulo, texto, embedding "
                       "FROM chunks").fetchall()
    con.close()
    matrix = np.frombuffer(b"".join(r[4] for r in data), dtype=np.float32) \
               .reshape(len(data), -1)
    return data, matrix


@st.cache_data
def get_buildings(path: str) -> pd.DataFrame:
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    return pd.DataFrame(rows)


@st.cache_data
def get_titulos() -> dict:
    return {json.loads(l)["code"]: json.loads(l)["titulo"]
            for l in open(MANIFEST, encoding="utf-8")}


def buscar(query: str, top: int, fuentes: tuple[str, ...]) -> list[dict]:
    import numpy as np
    data, matrix = get_rag_index()
    q = get_model().encode([f"query: {query}"], normalize_embeddings=True)[0]
    scores = matrix @ q.astype("float32")
    out, seen = [], set()
    for i in np.argsort(-scores):
        fuente, code, titulo, texto, _ = data[int(i)]
        if fuente not in fuentes or code in seen:
            continue
        seen.add(code)
        out.append({"fuente": fuente, "code": code, "titulo": titulo,
                    "score": float(scores[int(i)]),
                    "extracto": " ".join(texto.split())[:600]})
        if len(out) >= top:
            break
    return out


def clave_gemini() -> str | None:
    """GEMINI_API_KEY desde el entorno o desde los secrets de Streamlit Cloud."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


def pdf_bytes(md: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        ruta = Path(f.name)
    try:
        exportar_pdf(md, ruta)
        return ruta.read_bytes()
    finally:
        ruta.unlink(missing_ok=True)


def recuperar_fichas_ui(senales: list[dict], top_por_senal: int = 2) -> None:
    """Versión cacheada de informe_edificio.recuperar_fichas para la UI."""
    import numpy as np
    data, matrix = get_rag_index()
    model = get_model()
    for s in senales:
        q = model.encode([f"query: {s['query']}"], normalize_embeddings=True)[0]
        scores = matrix @ q.astype("float32")
        fichas, vistos = [], set()
        for idx in np.argsort(-scores):
            fuente, code, titulo, texto, _ = data[int(idx)]
            if fuente != "AQC" or code in vistos:  # informes: solo patología
                continue
            vistos.add(code)
            fichas.append({"code": code, "titulo": titulo,
                           "score": float(scores[int(idx)]),
                           "extracto": " ".join(texto.split())[:500]})
            if len(fichas) >= top_por_senal:
                break
        s["fichas"] = fichas


# ----------------------------------------------------------------- header

st.title("🏗️ SECO Building Intelligence — demo")
st.caption(
    "Open data pipeline (FR/LU/BE) + AQC pathology RAG + report extraction. "
    "All sources are public; reports are synthetic (SECO's are confidential)."
)

tab_port, tab_rag, tab_ext, tab_about = st.tabs(
    ["🏢 Portfolio & buildings", "🔎 Pathology search (RAG)",
     "📄 Inspection reports (extraction)", "ℹ️ About"])

# ----------------------------------------------------------------- tab 1

with tab_port:
    col_sel, col_kpi1, col_kpi2, col_kpi3 = st.columns([2, 1, 1, 1])
    with col_sel:
        ds_name = st.selectbox("Dataset", list(DATASETS))
    df = get_buildings(DATASETS[ds_name])

    riesgo_alto = df["alea_argiles_final"].isin(["Fort", "Moyen"]).mean()
    passoire = df["etiquette_dpe"].isin(["F", "G"]).mean()
    col_kpi1.metric("Buildings (DPE records)", len(df))
    col_kpi2.metric("Clay risk Fort/Moyen", f"{riesgo_alto:.0%}")
    col_kpi3.metric("Energy label F/G", f"{passoire:.0%}")

    c1, c2 = st.columns(2)
    with c1:
        st.caption("Energy label distribution")
        st.bar_chart(df["etiquette_dpe"].value_counts().sort_index())
    with c2:
        st.caption("Clay-shrinkage risk (RGA)")
        st.bar_chart(df["alea_argiles_final"].value_counts())

    st.caption("Building locations (from RNB)")
    st.map(df.rename(columns={"rnb_lat": "lat", "rnb_lon": "lon"})[["lat", "lon"]]
             .dropna(), size=10)

    st.subheader("Buildings")
    f1, f2 = st.columns(2)
    sel_label = f1.multiselect("Energy label", sorted(df["etiquette_dpe"].dropna().unique()))
    sel_clay = f2.multiselect("Clay risk", sorted(df["alea_argiles_final"].dropna().unique()))
    fdf = df.copy()
    if sel_label:
        fdf = fdf[fdf["etiquette_dpe"].isin(sel_label)]
    if sel_clay:
        fdf = fdf[fdf["alea_argiles_final"].isin(sel_clay)]
    cols = ["numero_dpe", "adresse_ban", "type_batiment", "periode_construction",
            "etiquette_dpe", "bdnb_mat_mur", "bdnb_mat_toit", "alea_argiles_final"]
    st.dataframe(fdf[cols], width="stretch", height=260)

    st.subheader("Per-building risk report")
    col_b, col_l = st.columns([3, 1])
    opciones = fdf["numero_dpe"] + " — " + fdf["adresse_ban"].fillna("?")
    eleccion = col_b.selectbox("Building", opciones)
    NOMBRES_IDIOMA = {"en": "English", "fr": "Français", "es": "Español"}
    lang = col_l.selectbox("Report language", list(NOMBRES_IDIOMA),
                           format_func=NOMBRES_IDIOMA.get)

    gemini_key = clave_gemini()
    usar_llm = st.toggle(
        "Draft with AI (Gemini)", value=False, disabled=not gemini_key,
        help="LLM-drafted prose grounded in the AQC sheets. "
             + ("" if gemini_key else
                "Unavailable: no GEMINI_API_KEY configured (env var or "
                "Streamlit secret)."))

    if st.button("Generate report", type="primary"):
        b = fdf[fdf["numero_dpe"] == eleccion.split(" — ")[0]].iloc[0].to_dict()
        senales = derivar_senales(b, lang)
        if not senales:
            st.session_state.pop("informe", None)
            st.info("No notable risk signals for this building.")
        else:
            recuperar_fichas_ui(senales)
            try:
                if usar_llm and gemini_key:
                    os.environ["GEMINI_API_KEY"] = gemini_key
                    with st.spinner("Drafting with Gemini…"):
                        texto = informe_llm(b, senales, "gemini", None, lang)
                    modo = "llm-gemini"
                else:
                    texto = informe_plantilla(b, senales, lang)
                    modo = "plantilla"
                st.session_state["informe"] = {
                    "texto": texto, "lang": lang, "modo": modo,
                    "dpe": b.get("numero_dpe"),
                }
            except BaseException as e:  # incluye sys.exit de los generadores
                st.session_state.pop("informe", None)
                st.error(f"Report generation failed: {e}")

    if informe := st.session_state.get("informe"):
        nombre = f"informe_{informe['dpe']}_{informe['modo']}_{informe['lang']}"
        d1, d2, _ = st.columns([1, 1, 3])
        d1.download_button("⬇ Download .md", data=informe["texto"],
                           file_name=f"{nombre}.md", mime="text/markdown")
        d2.download_button("⬇ Download .pdf", data=pdf_bytes(informe["texto"]),
                           file_name=f"{nombre}.pdf", mime="application/pdf")
        with st.container(border=True):
            st.markdown(informe["texto"])

# ----------------------------------------------------------------- tab 2

with tab_rag:
    st.subheader("Semantic search: AQC pathology + ITM regulations")
    st.caption("89 AQC pathology sheets (FR) + 143 Luxembourg ITM safety "
               "prescriptions (FR/DE), multilingual queries. Try: *fissures "
               "causées par les argiles* · *humedad en muros antiguos* · "
               "*désenfumage bâtiment élevé* · *Sicherheitsvorschriften Aufzüge*")
    q = st.text_input("Query", value="fissures dans les murs causées par les argiles")
    c_top, c_src = st.columns([1, 2])
    top = c_top.slider("Results", 1, 10, 5)
    fuentes = c_src.multiselect(
        "Sources", ["AQC", "ITM"], default=["AQC", "ITM"],
        help="AQC: construction pathology (FR) · ITM: Luxembourg safety "
             "prescriptions (FR/DE)")
    if q and fuentes:
        for r in buscar(q, top, tuple(fuentes)):
            with st.container(border=True):
                st.markdown(f"`{r['fuente']}` **[{r['code']}]** {r['titulo'][:110]}  \n"
                            f"*similarity {r['score']:.3f}*")
                st.caption(f"…{r['extracto']}…")

# ----------------------------------------------------------------- tab 3

with tab_ext:
    st.subheader("Extraction pipeline on (synthetic) inspection reports")
    if not DEFECTOS_DB.exists():
        st.warning("Run sintetizar_informes.py and extraer_informes.py first.")
    else:
        if EVAL_JSON.exists():
            ev = json.loads(EVAL_JSON.read_text(encoding="utf-8"))
            clf = ev["clasificacion_aqc"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Metadata extraction", "100%")
            m2.metric("AQC code, top-1", f"{clf['top1_accuracy']:.0%}",
                      help="Exact sheet among 89 classes")
            m3.metric("AQC code, top-3", f"{clf['top3_accuracy']:.0%}",
                      help="Product metric: the UI proposes 3 candidates, "
                           "the inspector validates (human-in-the-loop)")
            m4.metric("Macro F1 (top-1)", f"{clf['macro_f1']:.2f}")
            st.caption(f"Measured on {ev['n_informes']} synthetic reports / "
                       f"{ev['n_defectos']} defects with ground truth — "
                       "see docs/evaluacion.md for per-code F1 and confusions.")

        con = sqlite3.connect(DEFECTOS_DB)
        inf_df = pd.read_sql_query("SELECT * FROM informes", con)
        def_df = pd.read_sql_query("SELECT * FROM defectos", con)
        con.close()
        titulos = get_titulos()

        ref = st.selectbox("Report", inf_df["ref"].tolist())
        meta = inf_df[inf_df["ref"] == ref].iloc[0]
        st.markdown(f"**{meta['adresse']}** — visited {meta['fecha']} "
                    f"by {meta['inspecteur']} · file `{meta['fichero']}`")
        for _, d in def_df[def_df["informe_ref"] == ref].iterrows():
            with st.container(border=True):
                st.markdown(f"**Observation {d['num']}** · {d['localisation']} · "
                            f"severity **{d['gravite']}**")
                st.write(d["descripcion"])
                top3 = json.loads(d["top3"])
                etiquetas = " · ".join(
                    f"`{c}` {titulos.get(c, '')[:48]}…" for c in top3)
                st.markdown(f"AQC classification (top-3, score "
                            f"{d['score']:.2f}): {etiquetas}")

        st.subheader("All extracted defects")
        def_df["titulo_pred"] = def_df["code_pred"].map(
            lambda c: titulos.get(c, "")[:60])
        st.dataframe(
            def_df[["informe_ref", "num", "localisation", "gravite",
                    "code_pred", "titulo_pred", "score"]],
            width="stretch", height=300)

# ----------------------------------------------------------------- tab 4

with tab_about:
    st.markdown("""
### What is this?

A **"Pathology & Risk Copilot"** demo for [SECO](https://groupseco.com), the
Belgian/Luxembourgish technical-control group: it turns **public building
data and inspection documents** into pathology-and-risk intelligence.

**Who is it for?** Technical inspectors and decennial-insurance risk
analysts: people who need to know *what is likely wrong with this building
and why* — with sources they can verify.

### What you are looking at

| Tab | What it shows |
|---|---|
| 🏢 Portfolio | Real French buildings enriched across 4 open government APIs (energy diagnosis → registry → materials/height → clay-shrinkage risk). Pick a building and generate its risk report: every pathology is **cited to an AQC sheet**. |
| 🔎 Search | Multilingual semantic search (FR/ES/EN) over the 89 *Fiches Pathologie* of the Agence Qualité Construction — the French reference taxonomy for decennial claims. |
| 📄 Reports | The extraction pipeline: inspection PDFs → structured defects, each classified to the AQC taxonomy. Reports are **synthetic** (SECO's are confidential) so accuracy can be *measured* against ground truth — the metrics above the tab are real. |

### Honest limits

- Classification shows **top-3 candidates for the inspector to validate**
  (human-in-the-loop) — top-1 is 55% over 89 classes, top-3 is 73%.
- All data is open-licensed (Licence Ouverte, CC0, Flemish open licenses);
  nothing here is a substitute for an expert inspection.

**Source code, pipeline docs and evaluation:**
[github.com/andrudebaran7/seco-building-intelligence](https://github.com/andrudebaran7/seco-building-intelligence)
""")
