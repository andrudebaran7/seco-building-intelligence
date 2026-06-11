#!/usr/bin/env python3
"""Índice RAG del corpus AQC: troceado + embeddings + búsqueda semántica.

Trocea los textos extraídos por ingest_aqc.py en fragmentos con solape,
los vectoriza con un modelo de embeddings multilingüe local (sin APIs de
pago ni claves) y guarda el índice en SQLite. La búsqueda embebe la
consulta y rankea por similitud coseno.

Modelo: intfloat/multilingual-e5-small (~120 MB, MIT). Multilingüe:
el corpus está en francés pero se puede consultar en español o inglés.
Convención e5: los documentos se embeben con prefijo "passage: " y las
consultas con "query: ".

Requiere el venv del proyecto:  .venv/bin/python rag_aqc.py ...

Uso:
    .venv/bin/python rag_aqc.py build
    .venv/bin/python rag_aqc.py search "fissures dues aux argiles" --top 5
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

MODEL_NAME = "intfloat/multilingual-e5-small"
CHUNK_CHARS = 1200   # tamaño objetivo del fragmento
OVERLAP_CHARS = 200  # solape entre fragmentos consecutivos
DB_PATH = Path("corpus/aqc/rag_index.db")
MANIFEST = Path("corpus/aqc/manifest.jsonl")


def load_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def chunk_text(text: str) -> list[str]:
    """Trocea por párrafos acumulando hasta CHUNK_CHARS, con solape."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        if len(current) + len(p) > CHUNK_CHARS and current:
            chunks.append(current.strip())
            current = current[-OVERLAP_CHARS:]  # solape con el final del anterior
        current += "\n\n" + p
    if current.strip():
        chunks.append(current.strip())
    return chunks


def build(args) -> None:
    import numpy as np

    if not MANIFEST.exists():
        sys.exit(f"No existe {MANIFEST}; ejecuta antes ingest_aqc.py")
    fiches = [json.loads(l) for l in MANIFEST.open(encoding="utf-8")]
    fiches = [f for f in fiches if f.get("txt")]

    rows = []  # (code, titulo, fichero, chunk_idx, texto)
    for f in fiches:
        text = Path(f["txt"]).read_text(encoding="utf-8")
        for i, chunk in enumerate(chunk_text(text)):
            rows.append((f["code"], f["titulo"], f["txt"], i, chunk))
    print(f"Fichas: {len(fiches):,} — fragmentos: {len(rows):,}")

    print(f"Cargando modelo {MODEL_NAME} (se descarga la primera vez)...")
    model = load_model()
    embeddings = model.encode(
        [f"passage: {r[4]}" for r in rows],
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=32,
    ).astype(np.float32)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS meta;
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            code TEXT, titulo TEXT, fichero TEXT, chunk_idx INTEGER,
            texto TEXT, embedding BLOB
        );
        CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);
    """)
    con.executemany(
        "INSERT INTO chunks (code, titulo, fichero, chunk_idx, texto, embedding) VALUES (?,?,?,?,?,?)",
        [(c, t, fp, i, txt, emb.tobytes()) for (c, t, fp, i, txt), emb in zip(rows, embeddings)],
    )
    con.execute("INSERT INTO meta VALUES ('modelo', ?)", (MODEL_NAME,))
    con.execute("INSERT INTO meta VALUES ('dimension', ?)", (str(embeddings.shape[1]),))
    con.commit()
    con.close()
    print(f"Índice guardado en {DB_PATH} "
          f"({len(rows):,} fragmentos × {embeddings.shape[1]} dimensiones)")


def search(args) -> None:
    import numpy as np

    if not DB_PATH.exists():
        sys.exit(f"No existe {DB_PATH}; ejecuta antes: rag_aqc.py build")
    con = sqlite3.connect(DB_PATH)
    modelo_indexado = con.execute("SELECT valor FROM meta WHERE clave='modelo'").fetchone()[0]
    if modelo_indexado != MODEL_NAME:
        sys.exit(f"El índice fue creado con {modelo_indexado}; reconstruye con: rag_aqc.py build")

    data = con.execute("SELECT code, titulo, chunk_idx, texto, embedding FROM chunks").fetchall()
    con.close()
    matrix = np.frombuffer(b"".join(r[4] for r in data), dtype=np.float32).reshape(len(data), -1)

    model = load_model()
    q = model.encode([f"query: {args.consulta}"], normalize_embeddings=True)[0].astype(np.float32)
    scores = matrix @ q  # embeddings normalizados → producto punto = coseno

    top = np.argsort(-scores)[: args.top]
    print(f'Consulta: "{args.consulta}"\n')
    for rank, idx in enumerate(top, 1):
        code, titulo, chunk_idx, texto, _ = data[idx]
        snippet = " ".join(texto.split())[:300]
        print(f"{rank}. [{code}] (score {scores[idx]:.3f}) {titulo[:90]}")
        print(f"   …{snippet}…\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="trocear y vectorizar el corpus")
    p_search = sub.add_parser("search", help="búsqueda semántica en el índice")
    p_search.add_argument("consulta")
    p_search.add_argument("--top", type=int, default=5, help="resultados a mostrar (por defecto 5)")
    args = parser.parse_args()
    build(args) if args.cmd == "build" else search(args)


if __name__ == "__main__":
    main()
