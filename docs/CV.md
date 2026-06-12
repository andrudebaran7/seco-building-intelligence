# CV module: crack triage for inspection photos

Reference documentation for the computer-vision component: dataset, model,
expected inputs, metrics, integration and limits. The regenerable metrics
file is [`evaluacion_cv.md`](evaluacion_cv.md); this document is stable.

## Purpose and domain

Binary triage of **close-up surface photos** — the kind an inspector takes
on site: *does this photo show a crack?* It is an assistance/triage tool
(the inspector validates), not an automatic decision system, and it does
**not** localize the crack or grade its severity — it classifies the photo.

Out of domain: aerial/orthophoto imagery (the 10 cm/pixel chips produced by
the Luxembourg chain are visual context, not classifier input), wide shots
of whole façades, and non-concrete materials (untested).

## Dataset

| | |
|---|---|
| Name | METU — *Concrete Crack Images for Classification* |
| Author / source | Çağlar Fırat Özgenel, Mendeley Data, **doi:10.17632/5y9wdsg2zt.2** |
| License | **CC BY 4.0** (commercial use OK with attribution) |
| Contents | **40,000 RGB images of 227×227 px** — 20,000 `Positive` (crack) + 20,000 `Negative` (sound) |
| Origin | Cropped from 458 high-resolution photos (4032×3024 px) of concrete surfaces in METU campus buildings |
| Size | 241 MB (RAR) |

**Auto-download**: `entrenar_cv.py` fetches it via the Mendeley public API
(which returns the signed S3 URL) into `downloads/metu/`. Extraction uses
**libarchive** (`libarchive-c`): Debian's free `7z` lacks the RAR codec and
*silently* produces 40,000 empty files ("Unsupported Method") — a
documented trap.

**Known label noise**: the never-seen spot-check found one `Negative` image
showing what visually is a branching hairline crack. The 99.9% benchmark
accuracy therefore contains some label noise; treat it as an upper bound.

## Model

Two-stage design chosen for CPU-only training (minutes, not hours):

| Stage | Component | Details |
|---|---|---|
| Feature extractor | **MobileNetV3-Small**, ImageNet weights, **frozen** | torchvision `MobileNet_V3_Small_Weights.IMAGENET1K_V1`; classifier head removed → **576-d descriptor** per image |
| Classifier | **Logistic regression** (scikit-learn) | `max_iter=2000, C=1.0`; saved to `models/cv_fisuras.joblib` (~3 KB) |

Training config (reproducible, `--seed 42`): 2,000 images/class train,
500/class held-out test, deterministic shuffle of the sorted file list.
Backbone weights (~10 MB) download automatically from torchvision on first
use and are cached in `~/.cache/torch/`.

## Expected input images (important for testing)

The preprocessing is fixed by the backbone's ImageNet transform:

```
resize shorter side → 256 px  →  center-crop 224×224  →  ImageNet normalization
```

Practical consequences:

- **Any input size is accepted** — images are resized automatically. There
  is no minimum/maximum enforced.
- **Only the central square is analyzed** (center-crop). A crack in the
  corner of a non-square photo can fall outside the crop.
- **Scale matters more than size**: the training images are close-up crops
  where the surface fills the frame and the crack is clearly visible at
  227×227. A 4000×3000 photo of a whole wall gets squeezed to 224×224 —
  hairline cracks effectively vanish.

**Recommendation for testing**: crop the area of interest to a roughly
square patch where the suspected crack is visible at arm's-length scale
(like the samples in `data/cv_demo/`). For large photos, classify several
crops rather than the whole frame. Formats: JPG/PNG (the UI uploader and
`clasificar_fotos.py` accept `.jpg/.jpeg/.png`; anything PIL opens works
via the CLI).

## Measured performance

Held-out test (1,000 images, never used in training):

| Metric | Value |
|---|---|
| Accuracy | 99.9% |
| Precision (crack) | 99.8% |
| Recall (crack) | 100% |
| F1 | 0.999 |

Independent spot-check on 20 images provably outside train+test: **19/20**,
with well-calibrated extremes (cracks 97–100%, sound surfaces 0–2%) and the
single miss being the mislabeled image described above. Details:
[`evaluacion_cv.md`](evaluacion_cv.md).

> METU is a clean benchmark — uniform concrete, good lighting, centered
> cracks. Expect lower accuracy on real-world inspection photos (varied
> materials, shadows, dirt, paint); validating on SECO's own photo archive
> is the intended next step.

## How to use it

```bash
make cv                                   # train + evaluate (auto-downloads dataset)
.venv/bin/python clasificar_fotos.py fotos/              # CLI triage
.venv/bin/python clasificar_fotos.py fotos/ --umbral 0.7 # stricter threshold
.venv/bin/python clasificar_fotos.py fotos/ --a-defectos TIS-2026-1000
```

- `--a-defectos REF` registers positive detections as **observations in the
  extraction defects DB** (`informes_sinteticos/defectos.db`), classified to
  the AQC taxonomy by the same hybrid classifier as the text pipeline, with
  `origen='cv'` — the "document + vision hybrid".
- **UI**: the *📷 Photo triage* tab shows the measured metrics, a gallery of
  4 preselectable never-seen samples (2 NG + 2 OK, one-click classify) and a
  live uploader. Ten samples ship in `data/cv_demo/`.

## Files

| Path | What |
|---|---|
| `entrenar_cv.py` | Download + train + evaluate |
| `clasificar_fotos.py` | Inference CLI + defects-DB integration |
| `models/cv_fisuras.joblib` | Trained head (3 KB; backbone re-instantiated at runtime) |
| `docs/evaluacion_cv.{md,json}` | Metrics (regenerated on retrain) + spot-check |
| `data/cv_demo/` | 10 never-seen sample photos (5 NG + 5 OK) |
| `downloads/metu/` | Dataset (not in git; auto-downloaded) |

## Limits and future work

- Classification only — no localization (bounding boxes), no crack-width
  measurement, no severity grading.
- Concrete domain; transfer to brick/render/stone must be validated.
- Next steps: validate on real SECO photos, fine-tune the backbone (GPU),
  multi-defect classes (spalling, efflorescence, corrosion — CODEBRIM-style,
  minding its non-commercial license), and roof-condition models on the
  labeled orthophoto chips.
