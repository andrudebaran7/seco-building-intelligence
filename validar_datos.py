#!/usr/bin/env python3
"""Validación de integridad de los datos que viajan en el repositorio.

Comprueba, SIN red y solo con la librería estándar, que los datos enviados
en el repo son coherentes con lo que la documentación afirma: columnas y
recuentos de los datasets, vocabularios controlados, bases SQLite legibles,
manifiestos de los corpora, índice RAG, ficheros de evaluación y muestras
de la demo. Corre en CI en cada push: si alguien commitea datos corruptos
o desincronizados con la documentación, el build falla.

Uso:
    python3 validar_datos.py          (exit 0 = todo OK, 1 = fallos)
"""

import json
import sqlite3
import sys
from pathlib import Path

FALLOS: list[str] = []


def check(condicion: bool, mensaje: str) -> None:
    estado = "✓" if condicion else "✗"
    print(f" {estado} {mensaje}")
    if not condicion:
        FALLOS.append(mensaje)


def jsonl(path: str) -> list[dict]:
    return [json.loads(linea) for linea in Path(path).open(encoding="utf-8")
            if linea.strip()]


def main() -> None:
    print("— Datasets franceses (cadena completa) —")
    esperados = {"data/dpe_rnb_bdnb_rga_dpto75.jsonl": 490,
                 "data/dpe_rnb_bdnb_rga_dpto33.jsonl": 423}
    columnas_fr = {"numero_dpe", "id_rnb", "adresse_ban", "rnb_match", "rnb_lon",
                   "rnb_lat", "bdnb_mat_mur", "alea_argiles_final",
                   "alea_argiles_source"}
    for path, n in esperados.items():
        rows = jsonl(path)
        check(len(rows) == n, f"{path}: {len(rows)} registros (esperados {n})")
        check(columnas_fr <= set(rows[0]), f"{path}: columnas requeridas presentes")
        check(all(r["rnb_match"] in ("id_rnb", "adresse_ban") for r in rows),
              f"{path}: rnb_match en vocabulario")
        check(all(r["alea_argiles_final"] in ("Faible", "Moyen", "Fort", "Non exposé")
                  for r in rows), f"{path}: alea_argiles_final en vocabulario")

    print("— Datasets belgas (3 regiones + contexto NIS) —")
    for region, zona, n_min in (("bruselas", "bruxelles_centre", 2000),
                                ("flandes", "antwerpen_centrum", 3000),
                                ("valonia", "liege_centre", 3500)):
        path = f"data/be_{region}_{zona}_batiments_ctx.jsonl"
        rows = jsonl(path)
        check(len(rows) >= n_min, f"{path}: {len(rows)} edificios (≥{n_min})")
        check({"parcel_capakey", "nis_pct_pre1946"} <= set(rows[0]),
              f"{path}: columnas CAPAKEY y contexto NIS presentes")

    print("— Luxemburgo —")
    rows = jsonl("data/lu_bettendorf_batiments_3d.jsonl")
    con_altura = sum(1 for r in rows if r.get("hauteur_m") is not None)
    check(len(rows) >= 2000, f"lu_bettendorf_batiments_3d: {len(rows)} edificios")
    check(con_altura >= 1400, f"lu_bettendorf: {con_altura} con altura 3D (≥1400)")
    chips = list(Path("data/ortho_chips/bettendorf").glob("*.jpg"))
    check(len(chips) == 24, f"ortho_chips: {len(chips)} chips (esperados 24)")

    print("— Corpora y RAG —")
    aqc = jsonl("corpus/aqc/manifest.jsonl")
    itm = jsonl("corpus/itm/manifest.jsonl")
    check(len(aqc) == 89, f"manifest AQC: {len(aqc)} fichas (esperadas 89)")
    check(len(itm) == 143, f"manifest ITM: {len(itm)} prescripciones (esperadas 143)")
    check(all(Path(d["txt"]).exists() for d in aqc + itm if d.get("txt")),
          "todos los .txt de los manifiestos existen")
    con = sqlite3.connect("corpus/rag_index.db")
    n_chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    n_docs = con.execute("SELECT COUNT(DISTINCT fichero) FROM chunks").fetchone()[0]
    fuentes = {r[0] for r in con.execute("SELECT DISTINCT fuente FROM chunks")}
    blob = con.execute("SELECT LENGTH(embedding) FROM chunks LIMIT 1").fetchone()[0]
    con.close()
    check(n_chunks == 7551, f"rag_index: {n_chunks} fragmentos (esperados 7551)")
    # 11 PDFs del ITM son escaneados sin capa de texto (pdftotext extrae 0
    # caracteres): se ingieren pero no pueden indexarse sin OCR (trabajo futuro).
    escaneados = sum(1 for d in itm if d.get("n_caracteres", 9999) < 100)
    check(n_docs == 221, f"rag_index: {n_docs} documentos indexados (esperados 221)")
    check(escaneados == 11, f"ITM: {escaneados} PDFs escaneados sin texto (esperados 11)")
    check(fuentes == {"AQC", "ITM"}, f"rag_index: fuentes {sorted(fuentes)}")
    check(blob == 384 * 4, f"rag_index: embeddings de 384 float32 ({blob} bytes)")
    queries = jsonl("corpus/eval_queries.jsonl")
    check(len(queries) == 22 and all(q.get("gold") for q in queries),
          f"eval_queries: {len(queries)} consultas gold")

    print("— Extracción e informes sintéticos —")
    gt = jsonl("informes_sinteticos/ground_truth.jsonl")
    check(len(gt) == 30, f"ground_truth: {len(gt)} informes (esperados 30)")
    n_def_gt = sum(len(g["defectos"]) for g in gt)
    con = sqlite3.connect("informes_sinteticos/defectos.db")
    n_inf = con.execute("SELECT COUNT(*) FROM informes").fetchone()[0]
    n_def = con.execute(
        "SELECT COUNT(*) FROM defectos WHERE COALESCE(origen,'texto')='texto'"
    ).fetchone()[0]
    con.close()
    check(n_inf == 30, f"defectos.db: {n_inf} informes")
    check(n_def == n_def_gt, f"defectos.db: {n_def} observaciones de texto "
                             f"(= {n_def_gt} del ground truth)")
    pdfs = list(Path("informes_sinteticos/pdf").glob("*.pdf"))
    check(len(pdfs) == 30, f"PDFs sintéticos: {len(pdfs)}")

    print("— Evaluaciones publicadas —")
    ev = json.loads(Path("docs/evaluacion.json").read_text(encoding="utf-8"))
    check(ev["clasificacion_aqc"]["top3_accuracy"] > 0.7,
          "evaluacion.json: top-3 > 70%")
    ev = json.loads(Path("docs/evaluacion_retrieval.json").read_text(encoding="utf-8"))
    check(ev["global"]["hit@5"] > 0.8, "evaluacion_retrieval.json: hit@5 > 80%")
    ev = json.loads(Path("docs/evaluacion_cv.json").read_text(encoding="utf-8"))
    check(ev["accuracy"] > 0.99, "evaluacion_cv.json: accuracy > 99%")

    print("— Módulo CV —")
    modelo = Path("models/cv_fisuras.joblib")
    check(modelo.exists() and modelo.stat().st_size > 1000,
          f"modelo CV presente ({modelo.stat().st_size if modelo.exists() else 0} bytes)")
    demo = sorted(p.name for p in Path("data/cv_demo").glob("*.jpg"))
    check(len(demo) == 10 and sum(n.startswith("NG") for n in demo) == 5,
          f"cv_demo: {len(demo)} fotos (5 NG + 5 OK)")

    print()
    if FALLOS:
        print(f"VALIDACIÓN FALLIDA: {len(FALLOS)} problema(s)")
        sys.exit(1)
    print("Validación OK: los datos del repo son coherentes con la documentación.")


if __name__ == "__main__":
    main()
