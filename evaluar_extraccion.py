#!/usr/bin/env python3
"""Evaluación del pipeline de extracción contra el ground truth.

Compara la base de datos extraída (defectos.db) con el ground truth de los
informes sintéticos y calcula:

  - exactitud por campo de metadatos (ref, fecha, dirección, inspector),
  - cobertura de observaciones (¿se segmentaron todas?),
  - exactitud de gravedad y localización,
  - clasificación de defectos a código AQC: accuracy top-1 y top-3,
    y precision/recall/F1 por código (+ macro F1),
  - matriz de confusión de los códigos.

Escribe los resultados en docs/evaluacion.md y docs/evaluacion.json.

Uso:
    .venv/bin/python evaluar_extraccion.py
"""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

GT_PATH = Path("informes_sinteticos/ground_truth.jsonl")
DB_PATH = Path("informes_sinteticos/defectos.db")
OUT_MD = Path("docs/evaluacion.md")
OUT_JSON = Path("docs/evaluacion.json")


def main() -> None:
    gt = {json.loads(linea)["ref"]: json.loads(linea) for linea in GT_PATH.open(encoding="utf-8")}
    con = sqlite3.connect(DB_PATH)
    informes = {r[0]: {"fecha": r[1], "adresse": r[2], "inspecteur": r[3]}
                for r in con.execute("SELECT ref, fecha, adresse, inspecteur FROM informes")}
    defectos = defaultdict(list)
    for r in con.execute("SELECT informe_ref, num, localisation, gravite, code_pred, top3 "
                         "FROM defectos ORDER BY informe_ref, num"):
        defectos[r[0]].append({"localisation": r[2], "gravite": r[3],
                               "code_pred": r[4], "top3": json.loads(r[5])})
    con.close()

    # --- metadatos ---
    campos = ["fecha", "adresse", "inspecteur"]
    meta_ok = {c: 0 for c in campos}
    refs_ok = sum(1 for ref in gt if ref in informes)
    for ref, g in gt.items():
        e = informes.get(ref, {})
        for c in campos:
            if (e.get(c) or "").strip() == (g.get(c) or "").strip():
                meta_ok[c] += 1
    n = len(gt)

    # --- defectos: alineación por orden dentro del informe ---
    tp = defaultdict(int)   # por código: predicho == verdadero
    fp = defaultdict(int)   # predicho ese código y no era
    fn = defaultdict(int)   # era ese código y no se predijo
    confusion = defaultdict(int)
    grav_ok = loc_ok = top1_ok = top3_ok = tema_ok = total = 0
    cobertura_ok = 0
    for ref, g in gt.items():
        ed = defectos.get(ref, [])
        if len(ed) == len(g["defectos"]):
            cobertura_ok += 1
        for gd, edf in zip(g["defectos"], ed, strict=False):
            total += 1
            true_c, pred_c = gd["code_aqc"], edf["code_pred"]
            confusion[(true_c, pred_c)] += 1
            if pred_c == true_c:
                tp[true_c] += 1
                top1_ok += 1
            else:
                fp[pred_c] += 1
                fn[true_c] += 1
            if true_c in edf["top3"]:
                top3_ok += 1
            if pred_c[:1] == true_c[:1]:  # tema = letra A-G de la taxonomía
                tema_ok += 1
            if edf["gravite"] == gd["gravite"]:
                grav_ok += 1
            if edf["localisation"].strip().lower() == gd["localisation"].strip().lower():
                loc_ok += 1

    codigos = sorted({c for c, _ in confusion} | {c for _, c in confusion})
    por_codigo = {}
    f1s = []
    for c in codigos:
        p = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0
        r = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        soporte = tp[c] + fn[c]
        if soporte:
            f1s.append(f1)
        por_codigo[c] = {"precision": p, "recall": r, "f1": f1, "soporte": soporte}
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0

    resultados = {
        "n_informes": n,
        "n_defectos": total,
        "metadatos": {"ref_detectada": refs_ok / n,
                      **{c: meta_ok[c] / n for c in campos}},
        "cobertura_observaciones": cobertura_ok / n,
        "gravedad_accuracy": grav_ok / total,
        "localisation_accuracy": loc_ok / total,
        "clasificacion_aqc": {"top1_accuracy": top1_ok / total,
                              "top3_accuracy": top3_ok / total,
                              "tema_accuracy": tema_ok / total,
                              "macro_f1": macro_f1,
                              "por_codigo": por_codigo},
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(resultados, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # --- informe Markdown ---
    def pct(x):
        return f"{100 * x:.1f}%"
    lineas = [
        "# Evaluación del pipeline de extracción",
        "",
        f"{n} informes sintéticos, {total} defectos, contra ground truth.",
        "",
        "## Metadatos (exact match)",
        "",
        "| Campo | Exactitud |",
        "|---|---|",
        f"| Referencia detectada | {pct(refs_ok / n)} |",
        *(f"| {c} | {pct(meta_ok[c] / n)} |" for c in campos),
        f"| Cobertura de observaciones (todas segmentadas) | {pct(cobertura_ok / n)} |",
        f"| Gravedad | {pct(grav_ok / total)} |",
        f"| Localización | {pct(loc_ok / total)} |",
        "",
        "## Clasificación semántica a código AQC (componente IA)",
        "",
        f"- **Top-1 accuracy: {pct(top1_ok / total)}** (código exacto entre 89 fichas)",
        f"- **Top-3 accuracy: {pct(top3_ok / total)}** — la métrica de producto: la UI "
        "propone 3 candidatos y el inspector valida (human-in-the-loop)",
        f"- Tema correcto (letra A–G): {pct(tema_ok / total)}",
        f"- Macro F1 (top-1): {macro_f1:.3f}",
        "",
        "Parte del error top-1 es ambigüedad de la taxonomía (fichas hermanas: "
        "A.01/A.02 son dos partes del mismo fenómeno; B.11/C.01 madera de forjado "
        "vs de cubierta; D.03/D.12 dos fichas de revocos) — ver confusiones abajo.",
        "",
        "| Código | Precision | Recall | F1 | Soporte |",
        "|---|---|---|---|---|",
    ]
    for c, m in sorted(por_codigo.items()):
        if m["soporte"] or m["precision"]:
            lineas.append(f"| {c} | {m['precision']:.2f} | {m['recall']:.2f} | "
                          f"{m['f1']:.2f} | {m['soporte']} |")
    errores = [(t, p, k) for (t, p), k in confusion.items() if t != p]
    if errores:
        lineas += ["", "## Confusiones (verdadero → predicho)", ""]
        for t, p, k in sorted(errores, key=lambda x: -x[2]):
            lineas.append(f"- {t} → {p}: {k}")
    OUT_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    print(f"Top-1 accuracy: {pct(top1_ok / total)} | Top-3: {pct(top3_ok / total)} "
          f"| Macro F1: {macro_f1:.3f}")
    print("Metadatos: " + "  ".join(f"{c}:{pct(meta_ok[c] / n)}" for c in campos))
    print(f"Gravedad: {pct(grav_ok / total)} | Localización: {pct(loc_ok / total)}")
    print(f"Resultados completos en {OUT_MD} y {OUT_JSON}")


if __name__ == "__main__":
    main()
