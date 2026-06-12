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

## Prueba adicional: 20 imágenes nunca vistas

Verificación independiente del benchmark: 10 imágenes con fisura (NG) y 10
sin fisura (OK) tomadas **de fuera** de las 2.500 por clase usadas en
train+test (misma semilla del entrenador replicada para garantizarlo).

| Grupo | Aciertos | Confianza del modelo |
|---|---|---|
| 10 NG (fisura) | 10/10 | 97,3–100% |
| 10 OK (sin fisura) | 9/10 | correctas: 0–1,9% |
| **Total** | **19/20 (95%)** | |

El único "fallo" es instructivo: una imagen etiquetada *Negative* en METU
que muestra líneas oscuras ramificadas visualmente indistinguibles de una
fisura capilar (el modelo dio 99%). Es ruido de etiquetado del dataset o un
caso genuinamente ambiguo — y refuerza dos cosas: (1) el 99,9% del
benchmark incluye algo de ruido de etiquetas, y (2) el framing correcto es
triage con validación del inspector, no decisión automática.

Las probabilidades están bien calibradas en los extremos: fisuras claras
~100%, superficies sanas ~0%, sin zona gris.

**Set de demo**: `data/cv_demo/` contiene 5 NG + 5 OK de este grupo nunca
visto (excluida la ambigua), para probar la pestaña Photo triage de la UI.
Nota: este fichero lo regenera `entrenar_cv.py`; esta sección documenta la
prueba del 2026-06-12.
