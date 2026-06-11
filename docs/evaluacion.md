# Evaluación del pipeline de extracción

30 informes sintéticos, 101 defectos, contra ground truth.

## Metadatos (exact match)

| Campo | Exactitud |
|---|---|
| Referencia detectada | 100.0% |
| fecha | 100.0% |
| adresse | 100.0% |
| inspecteur | 100.0% |
| Cobertura de observaciones (todas segmentadas) | 100.0% |
| Gravedad | 100.0% |
| Localización | 100.0% |

## Clasificación semántica a código AQC (componente IA)

- **Top-1 accuracy: 55.4%** (código exacto entre 89 fichas)
- **Top-3 accuracy: 73.3%** — la métrica de producto: la UI propone 3 candidatos y el inspector valida (human-in-the-loop)
- Tema correcto (letra A–G): 68.3%
- Macro F1 (top-1): 0.590

Parte del error top-1 es ambigüedad de la taxonomía (fichas hermanas: A.01/A.02 son dos partes del mismo fenómeno; B.11/C.01 madera de forjado vs de cubierta; D.03/D.12 dos fichas de revocos) — ver confusiones abajo.

| Código | Precision | Recall | F1 | Soporte |
|---|---|---|---|---|
| A.02 | 0.00 | 0.00 | 0.00 | 9 |
| A.05 | 1.00 | 0.55 | 0.71 | 11 |
| B.01 | 1.00 | 0.62 | 0.76 | 13 |
| B.05 | 1.00 | 0.80 | 0.89 | 15 |
| B.11 | 0.00 | 0.00 | 0.00 | 8 |
| C.06 | 1.00 | 1.00 | 1.00 | 9 |
| C.07 | 1.00 | 1.00 | 1.00 | 9 |
| D.01 | 0.23 | 0.43 | 0.30 | 7 |
| D.03 | 1.00 | 0.45 | 0.62 | 11 |
| E.09 | 1.00 | 0.44 | 0.62 | 9 |

## Confusiones (verdadero → predicho)

- B.11 → C.01: 7
- D.03 → D.12: 6
- A.05 → D.02: 5
- B.01 → D.05: 5
- E.09 → D.01: 5
- A.02 → D.01: 5
- A.02 → A.01: 4
- D.01 → G.08: 4
- B.05 → B.07: 3
- B.11 → F.05: 1
