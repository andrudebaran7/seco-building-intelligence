#!/usr/bin/env python3
"""Triage CV de fotos de inspección: ¿hay fisura en la foto?

Usa el modelo entrenado por entrenar_cv.py (MobileNetV3 congelado +
regresión logística, accuracy 99,9% en el test METU) para clasificar fotos
de superficie a corta distancia. Pensado como red de seguridad/triage de
las fotos de obra del inspector — el humano decide.

Integración opcional (--a-defectos REF): las detecciones positivas se
registran como observaciones en la base de defectos extraídos
(informes_sinteticos/defectos.db), clasificadas a la taxonomía AQC con el
mismo clasificador híbrido del pipeline de extracción — el concepto
"híbrido documento+visión" del análisis de producto.

Uso:
    .venv/bin/python clasificar_fotos.py foto1.jpg carpeta_fotos/
    .venv/bin/python clasificar_fotos.py fotos/ --a-defectos TIS-2026-1000
"""

import argparse
import json
import sqlite3
from pathlib import Path

from entrenar_cv import MODEL_PATH, get_backbone

DEFECTOS_DB = Path("informes_sinteticos/defectos.db")
EXTENSIONES = {".jpg", ".jpeg", ".png"}


def listar_fotos(rutas: list[str]) -> list[Path]:
    fotos = []
    for r in rutas:
        p = Path(r)
        if p.is_dir():
            fotos += sorted(q for q in p.iterdir() if q.suffix.lower() in EXTENSIONES)
        elif p.suffix.lower() in EXTENSIONES:
            fotos.append(p)
    return fotos


def clasificar(fotos: list[Path]) -> list[dict]:
    import joblib
    import torch
    from PIL import Image

    clf = joblib.load(MODEL_PATH)
    model, transform = get_backbone()
    out = []
    with torch.no_grad():
        for p in fotos:
            x = transform(Image.open(p).convert("RGB")).unsqueeze(0)
            prob = float(clf.predict_proba(model(x).numpy())[0, 1])
            out.append({"foto": str(p), "prob_fisura": round(prob, 4)})
    return out


def registrar_defectos(detecciones: list[dict], informe_ref: str) -> int:
    """Inserta las detecciones positivas como observaciones en defectos.db,
    clasificadas a la taxonomía AQC por el clasificador híbrido."""
    from extraer_informes import clasificar as clasificar_aqc

    positivas = [d for d in detecciones if d["es_fisura"]]
    if not positivas:
        return 0
    descripciones = [
        f"Fissuration visible détectée automatiquement (vision par ordinateur, "
        f"probabilité {d['prob_fisura']:.0%}) sur la photo {Path(d['foto']).name}."
        for d in positivas
    ]
    preds = clasificar_aqc(descripciones)

    con = sqlite3.connect(DEFECTOS_DB)
    cols = [r[1] for r in con.execute("PRAGMA table_info(defectos)")]
    if "origen" not in cols:
        con.execute("ALTER TABLE defectos ADD COLUMN origen TEXT DEFAULT 'texto'")
    base = con.execute("SELECT COALESCE(MAX(num),0) FROM defectos WHERE informe_ref=?",
                       (informe_ref,)).fetchone()[0]
    for i, (d, desc, pred) in enumerate(zip(positivas, descripciones, preds), 1):
        con.execute(
            "INSERT INTO defectos (informe_ref, num, localisation, gravite, "
            "descripcion, code_pred, score, top3, origen) VALUES (?,?,?,?,?,?,?,?,?)",
            (informe_ref, base + i, "photo", "à qualifier", desc,
             pred["code_pred"], pred["score"], json.dumps(pred["top3"]), "cv"))
    con.commit()
    con.close()
    return len(positivas)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rutas", nargs="+", help="fotos o carpetas de fotos")
    parser.add_argument("--umbral", type=float, default=0.5)
    parser.add_argument("--a-defectos", metavar="REF",
                        help="registrar positivos como observaciones del informe REF")
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        raise SystemExit(f"No existe {MODEL_PATH}; entrena antes: entrenar_cv.py")
    fotos = listar_fotos(args.rutas)
    if not fotos:
        raise SystemExit("Ninguna foto encontrada (jpg/png).")

    detecciones = clasificar(fotos)
    for d in detecciones:
        d["es_fisura"] = d["prob_fisura"] >= args.umbral
        marca = "FISURA" if d["es_fisura"] else "ok"
        print(f"  {marca:>6}  {d['prob_fisura']:.1%}  {d['foto']}")
    n_pos = sum(d["es_fisura"] for d in detecciones)
    print(f"{n_pos}/{len(detecciones)} fotos con fisura (umbral {args.umbral})")

    if args.a_defectos:
        n = registrar_defectos(detecciones, args.a_defectos)
        print(f"{n} observaciones CV registradas en {DEFECTOS_DB} "
              f"(informe {args.a_defectos}, origen='cv')")


if __name__ == "__main__":
    main()
