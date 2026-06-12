#!/usr/bin/env python3
"""Módulo CV: entrena y evalúa un clasificador de fisuras en fotos.

Transfer learning apto para CPU: un backbone MobileNetV3-Small congelado
(pesos ImageNet, torchvision) extrae descriptores de 576 dimensiones y una
regresión logística (scikit-learn) clasifica fisura / no fisura.

Dataset: METU "Concrete Crack Images for Classification" (Özgenel, Mendeley
Data, doi:10.17632/5y9wdsg2zt.2, CC BY 4.0) — 40.000 fotos 227×227 de
superficies de hormigón a corta distancia. **Dominio**: fotos de inspección
de cerca, NO imágenes aéreas; el modelo es para el triage de las fotos que
un inspector hace en obra.

Salidas: models/cv_fisuras.joblib (cabeza entrenada) y métricas medidas
sobre un test set separado en docs/evaluacion_cv.{md,json}.

Uso:
    .venv/bin/python entrenar_cv.py                # 2000+2000 train, 500+500 test
    .venv/bin/python entrenar_cv.py --n-train 4000 --n-test 1000
"""

import argparse
import json
import random
from pathlib import Path

DATA_DIR = Path("downloads/metu")
MODEL_PATH = Path("models/cv_fisuras.joblib")
OUT_MD = Path("docs/evaluacion_cv.md")
OUT_JSON = Path("docs/evaluacion_cv.json")


MENDELEY_API = ("https://data.mendeley.com/public-api/datasets/"
                "5y9wdsg2zt/files?folder_id=root&version=2")


def descargar_metu() -> None:
    """Descarga (241 MB, RAR) y extrae el dataset METU vía la API de Mendeley.

    Nota: el 7z "libre" de Debian no trae el códec RAR ("Unsupported
    Method"); libarchive sí lo decodifica, de ahí la dependencia.
    """
    import libarchive

    from red import descargar, http_json
    rar = DATA_DIR.parent / "metu_crack.rar"
    DATA_DIR.parent.mkdir(exist_ok=True)
    if not rar.exists():
        url = http_json(MENDELEY_API, timeout=60)[0]["content_details"]["download_url"]
        print("Descargando dataset METU (241 MB) ...")
        descargar(url, rar, timeout=900)
    print("Extrayendo 40.000 imágenes (libarchive) ...")
    with libarchive.file_reader(str(rar)) as a:
        for entry in a:
            dest = DATA_DIR / entry.pathname
            if entry.isdir:
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                for block in entry.get_blocks():
                    f.write(block)


def get_backbone():
    """MobileNetV3-Small congelado, sin la capa clasificadora."""
    import torch
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
    weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1
    model = mobilenet_v3_small(weights=weights)
    model.classifier = torch.nn.Identity()   # salida: 576-d
    model.eval()
    return model, weights.transforms()


def extraer_features(rutas: list[Path], model, transform, batch: int = 64):
    import numpy as np
    import torch
    from PIL import Image
    feats = []
    with torch.no_grad():
        for i in range(0, len(rutas), batch):
            imgs = [transform(Image.open(p).convert("RGB"))
                    for p in rutas[i:i + batch]]
            feats.append(model(torch.stack(imgs)).numpy())
            print(f"  features {min(i + batch, len(rutas))}/{len(rutas)}",
                  end="\r", flush=True)
    print()
    return np.concatenate(feats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n-train", type=int, default=2000,
                        help="imágenes de entrenamiento POR CLASE (defecto 2000)")
    parser.add_argument("--n-test", type=int, default=500,
                        help="imágenes de test POR CLASE (defecto 500)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not DATA_DIR.exists():
        descargar_metu()

    rng = random.Random(args.seed)
    rutas, labels = [], []
    for label, carpeta in ((1, "Positive"), (0, "Negative")):
        files = sorted((DATA_DIR / carpeta).glob("*.jpg"))
        rng.shuffle(files)
        sel = files[: args.n_train + args.n_test]
        rutas += sel
        labels += [label] * len(sel)
    print(f"Dataset: {len(rutas):,} imágenes ({args.n_train}+{args.n_test} por clase)")

    print("Cargando backbone MobileNetV3-Small (ImageNet)…")
    model, transform = get_backbone()
    X = extraer_features(rutas, model, transform)

    # Split reproducible: los primeros n_train de cada clase a train.
    import numpy as np
    labels = np.array(labels)
    idx_train, idx_test = [], []
    for label in (1, 0):
        idx = np.where(labels == label)[0]
        idx_train += list(idx[: args.n_train])
        idx_test += list(idx[args.n_train:])
    Xtr, ytr = X[idx_train], labels[idx_train]
    Xte, yte = X[idx_test], labels[idx_test]

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
    clf = LogisticRegression(max_iter=2000, C=1.0)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    clf.predict_proba(Xte)[:, 1]

    acc = accuracy_score(yte, pred)
    prec, rec, f1, _ = precision_recall_fscore_support(
        yte, pred, average="binary", pos_label=1)
    tn, fp, fn, tp = confusion_matrix(yte, pred).ravel()

    import joblib
    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(clf, MODEL_PATH)

    resultados = {
        "dataset": "METU Concrete Crack (CC BY 4.0)",
        "backbone": "mobilenet_v3_small (ImageNet, congelado)",
        "n_train_por_clase": args.n_train, "n_test_por_clase": args.n_test,
        "accuracy": acc, "precision": prec, "recall": rec, "f1": f1,
        "confusion": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)},
    }
    OUT_JSON.write_text(json.dumps(resultados, indent=2), encoding="utf-8")
    def pct(x):
        return f"{100 * x:.1f}%"
    OUT_MD.write_text(f"""# Evaluación del clasificador CV de fisuras

Transfer learning CPU: MobileNetV3-Small congelado (ImageNet) + regresión
logística, sobre el dataset METU (CC BY 4.0). Test set separado de
{2 * args.n_test} imágenes ({args.n_test} por clase), nunca vistas en
entrenamiento.

| Métrica | Valor |
|---|---|
| Accuracy | **{pct(acc)}** |
| Precision (fisura) | {pct(prec)} |
| Recall (fisura) | {pct(rec)} |
| F1 (fisura) | {f1:.3f} |
| Confusión (tp/fp/fn/tn) | {tp}/{fp}/{fn}/{tn} |

**Dominio**: fotos de superficie a corta distancia (las que hace un
inspector en obra) — no imágenes aéreas ni ortofotos. Hormigón
principalmente; la transferencia a otros materiales debe validarse.
""", encoding="utf-8")

    print(f"Accuracy {pct(acc)} | Precision {pct(prec)} | Recall {pct(rec)} "
          f"| F1 {f1:.3f}")
    print(f"Modelo: {MODEL_PATH} — métricas: {OUT_MD}")


if __name__ == "__main__":
    main()
