#!/usr/bin/env python3
"""Evaluación del retrieval del buscador semántico (RAG).

Mide la calidad de la búsqueda contra un set de consultas con respuesta
correcta conocida (corpus/eval_queries.jsonl): 22 consultas en FR/ES/EN/DE
que cubren patología AQC y normativa ITM. El gold de cada consulta es una
lista de códigos aceptables (las fichas hermanas de la taxonomía, p. ej.
A.01/A.02, cuentan ambas como acierto; los códigos ITM se aceptan a nivel
de familia, p. ej. cualquier ITM-SST 1501.x).

Métricas: hit@1 / hit@3 / hit@5 (¿algún gold entre los k primeros
documentos distintos?) y MRR (mean reciprocal rank), con desglose por
idioma y por corpus. Resultados en docs/evaluacion_retrieval.{md,json}.

Uso:
    .venv/bin/python evaluar_retrieval.py
"""

import json
import sqlite3
from pathlib import Path

QUERIES = Path("corpus/eval_queries.jsonl")
DB_PATH = Path("corpus/rag_index.db")
MODEL_NAME = "intfloat/multilingual-e5-small"
OUT_MD = Path("docs/evaluacion_retrieval.md")
OUT_JSON = Path("docs/evaluacion_retrieval.json")
K_MAX = 5


def cargar_indice():
    import numpy as np
    con = sqlite3.connect(DB_PATH)
    data = con.execute("SELECT fuente, code, embedding FROM chunks").fetchall()
    con.close()
    matrix = np.frombuffer(b"".join(r[2] for r in data), dtype=np.float32) \
               .reshape(len(data), -1)
    return data, matrix


def top_codigos(scores, data, k: int) -> list[str]:
    """Los k primeros documentos distintos (deduplicados por código)."""
    import numpy as np
    codes, vistos = [], set()
    for idx in np.argsort(-scores):
        code = data[int(idx)][1]
        if code in vistos:
            continue
        vistos.add(code)
        codes.append(code)
        if len(codes) >= k:
            break
    return codes


def es_acierto(code: str, gold: list[str]) -> bool:
    """Acierto exacto (AQC: 'A.02') o por familia (ITM: 'ITM-SST 1501')."""
    return any(code == g or code.startswith(g + ".") or code.startswith(g + " ")
               for g in gold)


def main() -> None:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    queries = [json.loads(linea) for linea in QUERIES.open(encoding="utf-8") if linea.strip()]
    data, matrix = cargar_indice()
    model = SentenceTransformer(MODEL_NAME)

    resultados = []
    for q in queries:
        emb = model.encode([f"query: {q['query']}"],
                           normalize_embeddings=True)[0].astype(np.float32)
        codes = top_codigos(matrix @ emb, data, K_MAX)
        rank = next((i + 1 for i, c in enumerate(codes)
                     if es_acierto(c, q["gold"])), None)
        corpus = "ITM" if q["gold"][0].startswith("ITM") else "AQC"
        resultados.append({**q, "corpus": corpus, "rank": rank, "top5": codes})

    def agregar(subset):
        n = len(subset)
        return {
            "n": n,
            "hit@1": sum(1 for r in subset if r["rank"] == 1) / n,
            "hit@3": sum(1 for r in subset if r["rank"] and r["rank"] <= 3) / n,
            "hit@5": sum(1 for r in subset if r["rank"] and r["rank"] <= 5) / n,
            "mrr": sum(1 / r["rank"] for r in subset if r["rank"]) / n,
        }

    global_m = agregar(resultados)
    por_corpus = {c: agregar([r for r in resultados if r["corpus"] == c])
                  for c in ("AQC", "ITM")}
    por_lang = {idioma: agregar([r for r in resultados if r["lang"] == idioma])
                for idioma in sorted({r["lang"] for r in resultados})}

    salida = {"global": global_m, "por_corpus": por_corpus, "por_idioma": por_lang,
              "consultas": resultados}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(salida, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def pct(x):
        return f"{100 * x:.0f}%"
    def fila(n, m):
        return (f"| {n} | {m['n']} | {pct(m['hit@1'])} | {pct(m['hit@3'])} "
                             f"| {pct(m['hit@5'])} | {m['mrr']:.2f} |")
    lineas = [
        "# Evaluación del retrieval (buscador semántico)",
        "",
        f"{len(resultados)} consultas con gold conocido sobre el índice "
        "multi-corpus (232 documentos). hit@k = algún código correcto entre "
        "los k primeros documentos distintos; MRR = mean reciprocal rank.",
        "",
        "| Segmento | N | hit@1 | hit@3 | hit@5 | MRR |",
        "|---|---|---|---|---|---|",
        fila("**Global**", global_m),
        *(fila(f"Corpus {c}", m) for c, m in por_corpus.items()),
        *(fila(f"Idioma {linea}", m) for linea, m in por_lang.items()),
    ]
    fallos = [r for r in resultados if r["rank"] is None or r["rank"] > 1]
    if fallos:
        lineas += ["", "## Consultas sin acierto en top-1", ""]
        for r in fallos:
            lineas.append(f"- ({r['lang']}) *\"{r['query']}\"* — esperado "
                          f"{r['gold']}, rank={r['rank']}, top-3: {r['top5'][:3]}")
    OUT_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    print(f"Global: hit@1 {pct(global_m['hit@1'])} | hit@3 {pct(global_m['hit@3'])} "
          f"| hit@5 {pct(global_m['hit@5'])} | MRR {global_m['mrr']:.2f}")
    for c, m in por_corpus.items():
        print(f"  {c}: hit@1 {pct(m['hit@1'])} hit@3 {pct(m['hit@3'])} (n={m['n']})")
    print(f"Resultados completos en {OUT_MD} y {OUT_JSON}")


if __name__ == "__main__":
    main()
