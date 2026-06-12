# Evaluación del clasificador CV de fisuras

Transfer learning CPU: MobileNetV3-Small congelado (ImageNet) + regresión
logística, sobre el dataset METU (CC BY 4.0). Test set separado de
1000 imágenes (500 por clase), nunca vistas en
entrenamiento.

| Métrica | Valor |
|---|---|
| Accuracy | **99.9%** |
| Precision (fisura) | 99.8% |
| Recall (fisura) | 100.0% |
| F1 (fisura) | 0.999 |
| Confusión (tp/fp/fn/tn) | 500/1/0/499 |

**Dominio**: fotos de superficie a corta distancia (las que hace un
inspector en obra) — no imágenes aéreas ni ortofotos. Hormigón
principalmente; la transferencia a otros materiales debe validarse.
