#!/usr/bin/env python3
"""Pipeline de extracción: informes PDF → base de datos estructurada de defectos.

Para cada informe de inspección en PDF:
  1. extrae el texto (pdftotext -layout; los sintéticos son PDFs nativos —
     para escaneos se sustituiría este paso por OCR, p.ej. docTR),
  2. parsea los metadatos con expresiones tolerantes a las distintas
     maquetaciones (referencia, fecha, dirección, inspector),
  3. segmenta las observaciones de defectos (3 formatos de encabezado),
  4. clasifica CADA observación contra la taxonomía AQC (89 fichas) con un
     clasificador HÍBRIDO: similitud de embeddings multilingües contra un
     perfil limpio por ficha (título + inicio del texto sin boilerplate)
     combinada con similitud léxica TF-IDF (los términos técnicos son señal
     fuerte). Pesos 0,7 semántico / 0,3 léxico, elegidos por evaluación
     (ver evaluar_extraccion.py). Devuelve top-3 con scores: el producto
     propone, el inspector valida (human-in-the-loop).
  5. persiste todo en SQLite (informes_sinteticos/defectos.db).

La clasificación es el componente de IA evaluable: ver evaluar_extraccion.py.

Uso:
    .venv/bin/python extraer_informes.py
"""

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

PDF_DIR = Path("informes_sinteticos/pdf")
DB_PATH = Path("informes_sinteticos/defectos.db")
RAG_DB = Path("corpus/rag_index.db")
MODEL_NAME = "intfloat/multilingual-e5-small"

# --- parseo de metadatos (tolerante a las 3 plantillas) ----------------------

RE_REF = re.compile(r"\b(TIS-\d{4}-\d+)\b")
RE_FECHA = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
RE_INSPECTOR = re.compile(
    r"(?:Inspecteur|Établi par|Contrôleur)\s*:?\s*((?:M\.|Mme)\s+[A-Za-zÀ-ÿ'\- ]+?)\s*(?:$|\|)",
    re.MULTILINE)
RE_ADRESSE = re.compile(
    r"(?:Adresse du bien|Bien inspecté|Adresse)\s*:\s*(.+?)\s*(?:\(|$)", re.MULTILINE)

# Encabezados de observación de las 3 plantillas.
RE_OBS = [
    # "Observation 1 - Localisation : X - Gravité : g"
    re.compile(r"Observation\s+\d+\s*-\s*Localisation\s*:\s*(?P<loc>.+?)\s*-\s*"
               r"Gravité\s*:\s*(?P<grav>\w+)", re.IGNORECASE),
    # "1. [MAJEURE] localisation"
    re.compile(r"^\s*\d+\.\s*\[(?P<grav>\w+)\]\s*(?P<loc>.+)$", re.MULTILINE),
    # "Point 1 (localisation) - niveau de gravité : g"
    re.compile(r"Point\s+\d+\s*\((?P<loc>.+?)\)\s*-\s*niveau de gravité\s*:\s*"
               r"(?P<grav>\w+)", re.IGNORECASE),
]


def pdf_a_texto(pdf: Path) -> str:
    r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pdftotext falló en {pdf}: {r.stderr[:200]}")
    return r.stdout


def parsear_informe(texto: str) -> dict:
    meta = {
        "ref": (RE_REF.search(texto) or [None, None])[1] if RE_REF.search(texto) else None,
        "fecha": (m.group(1) if (m := RE_FECHA.search(texto)) else None),
        "inspecteur": (m.group(1).strip() if (m := RE_INSPECTOR.search(texto)) else None),
        "adresse": (m.group(1).strip() if (m := RE_ADRESSE.search(texto)) else None),
    }
    # Observaciones: encontrar todos los encabezados (de cualquier plantilla)
    # y tomar como descripción el texto hasta el siguiente encabezado.
    hits = []
    for rx in RE_OBS:
        for m in rx.finditer(texto):
            hits.append((m.start(), m.end(), m.group("loc").strip(),
                         m.group("grav").lower().strip()))
    hits.sort()
    pie = texto.find("Le présent rapport")
    observaciones = []
    for i, (ini, fin, loc, grav) in enumerate(hits):
        fin_desc = hits[i + 1][0] if i + 1 < len(hits) else (pie if pie > 0 else len(texto))
        desc = " ".join(texto[fin:fin_desc].split())
        observaciones.append({"localisation": loc, "gravite": grav, "descripcion": desc})
    meta["defectos"] = observaciones
    return meta


# --- clasificación híbrida contra la taxonomía AQC ---------------------------

MANIFEST = Path("corpus/aqc/manifest.jsonl")
ALPHA = 0.7        # peso semántico (0,3 léxico) — elegido por evaluación
PERFIL_CHARS = 1200  # título + inicio del texto (sección "LE CONSTAT")
BOILER = re.compile(
    r"(Retrouvez l.ensemble.*?AppliQC|www\.\S+|©.*?$|Photo\s*:?\s*©.*?$)", re.M)


def cargar_perfiles() -> tuple[list[str], list[str]]:
    """Perfil limpio por ficha: título + inicio del texto sin boilerplate."""
    fichas = [json.loads(l) for l in MANIFEST.open(encoding="utf-8")]
    codes, perfiles = [], []
    for f in fichas:
        if not f.get("txt"):
            continue
        t = " ".join(BOILER.sub(" ", Path(f["txt"]).read_text(encoding="utf-8")).split())
        codes.append(f["code"])
        perfiles.append(f"{f['titulo']}. {t[:PERFIL_CHARS]}")
    return codes, perfiles


def clasificar(descripciones: list[str]) -> list[dict]:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    codes, perfiles = cargar_perfiles()
    model = SentenceTransformer(MODEL_NAME)
    # Similitud simétrica passage↔passage (las observaciones son párrafos,
    # no consultas cortas; medido mejor que el prefijo "query:").
    q = model.encode([f"passage: {d}" for d in descripciones],
                     normalize_embeddings=True).astype(np.float32)
    pm = model.encode([f"passage: {p}" for p in perfiles],
                      normalize_embeddings=True).astype(np.float32)
    s_emb = q @ pm.T

    tfidf = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)
    P = tfidf.fit_transform(perfiles)
    Q = tfidf.transform(descripciones)
    s_lex = np.asarray((normalize(Q) @ normalize(P).T).todense())

    scores = ALPHA * s_emb + (1 - ALPHA) * s_lex
    resultados = []
    for fila in scores:
        orden = np.argsort(-fila)[:3]
        resultados.append({
            "code_pred": codes[int(orden[0])],
            "score": float(fila[orden[0]]),
            "top3": [codes[int(i)] for i in orden],
        })
    return resultados


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf-dir", default=str(PDF_DIR))
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    pdfs = sorted(Path(args.pdf_dir).glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No hay PDFs en {args.pdf_dir}; ejecuta antes sintetizar_informes.py")
    if not RAG_DB.exists():
        sys.exit(f"No existe {RAG_DB}; ejecuta antes rag_aqc.py build")

    informes = []
    for pdf in pdfs:
        meta = parsear_informe(pdf_a_texto(pdf))
        meta["fichero"] = pdf.name
        informes.append(meta)
    n_def = sum(len(i["defectos"]) for i in informes)
    print(f"Parseados {len(informes)} informes con {n_def} observaciones")

    print("Clasificando observaciones contra la taxonomía AQC (híbrido)...")
    todas = [d["descripcion"] for i in informes for d in i["defectos"]]
    preds = clasificar(todas)
    k = 0
    for inf in informes:
        for d in inf["defectos"]:
            d.update(preds[k])
            k += 1

    db = Path(args.db)
    con = sqlite3.connect(db)
    con.executescript("""
        DROP TABLE IF EXISTS informes;
        DROP TABLE IF EXISTS defectos;
        CREATE TABLE informes (
            ref TEXT PRIMARY KEY, fecha TEXT, adresse TEXT,
            inspecteur TEXT, fichero TEXT
        );
        CREATE TABLE defectos (
            id INTEGER PRIMARY KEY, informe_ref TEXT, num INTEGER,
            localisation TEXT, gravite TEXT, descripcion TEXT,
            code_pred TEXT, score REAL, top3 TEXT,
            FOREIGN KEY (informe_ref) REFERENCES informes(ref)
        );
    """)
    for inf in informes:
        con.execute("INSERT INTO informes VALUES (?,?,?,?,?)",
                    (inf["ref"], inf["fecha"], inf["adresse"],
                     inf["inspecteur"], inf["fichero"]))
        for n, d in enumerate(inf["defectos"], 1):
            con.execute(
                "INSERT INTO defectos (informe_ref, num, localisation, gravite, "
                "descripcion, code_pred, score, top3) VALUES (?,?,?,?,?,?,?,?)",
                (inf["ref"], n, d["localisation"], d["gravite"], d["descripcion"],
                 d["code_pred"], d["score"], json.dumps(d["top3"])))
    con.commit()
    con.close()
    print(f"Base de datos estructurada guardada en {db}")


if __name__ == "__main__":
    main()
