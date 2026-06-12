# Evaluación del retrieval (buscador semántico)

22 consultas con gold conocido sobre el índice multi-corpus (232 documentos). hit@k = algún código correcto entre los k primeros documentos distintos; MRR = mean reciprocal rank.

| Segmento | N | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|---|
| **Global** | 22 | 45% | 73% | 86% | 0.62 |
| Corpus AQC | 16 | 50% | 75% | 88% | 0.65 |
| Corpus ITM | 6 | 33% | 67% | 83% | 0.53 |
| Idioma de | 1 | 0% | 100% | 100% | 0.50 |
| Idioma en | 3 | 33% | 33% | 67% | 0.40 |
| Idioma es | 3 | 33% | 67% | 67% | 0.50 |
| Idioma fr | 15 | 53% | 80% | 93% | 0.70 |

## Consultas sin acierto en top-1

- (fr) *"corrosion des armatures du balcon, béton éclaté"* — esperado ['B.05'], rank=2, top-3: ['G.04', 'B.05', 'B.07']
- (fr) *"infiltration d'eau autour des fenêtres"* — esperado ['D.01'], rank=4, top-3: ['D.02', 'D.13', 'C.06']
- (fr) *"affaissement du dallage du rez-de-chaussée"* — esperado ['A.05'], rank=2, top-3: ['B.09', 'A.05', 'C.12']
- (fr) *"ventilation mécanique contrôlée défaillante"* — esperado ['E.08'], rank=2, top-3: ['G.06', 'E.08', 'E.09']
- (es) *"humedad que sube por los muros desde el suelo"* — esperado ['B.01'], rank=2, top-3: ['B.02', 'B.01', 'C.05']
- (es) *"grietas en la fachada por suelos arcillosos"* — esperado ['A.01', 'A.02', 'A.05'], rank=None, top-3: ['B.04', 'C.06', 'B.05']
- (en) *"cracks in masonry walls on clay soil"* — esperado ['A.01', 'A.02', 'A.05'], rank=5, top-3: ['G.04', 'F.03', 'D.02']
- (en) *"water leaks through the roof tiles"* — esperado ['C.06', 'C.09'], rank=None, top-3: ['D.03', 'D.13', 'G.04']
- (fr) *"prescriptions de sécurité incendie pour les bâtiments bas"* — esperado ['ITM-SST 1501'], rank=2, top-3: ['ITM-SST 1503.2', 'ITM-SST 1501.4', 'ITM-SST 1501.5']
- (fr) *"prescriptions de prévention incendie pour bâtiments moyens"* — esperado ['ITM-SST 1502'], rank=5, top-3: ['ITM-SST 1503.2', 'ITM-SST 1501.1', 'ITM-SST 1514.3']
- (fr) *"protection contre la foudre, paratonnerre"* — esperado ['ITM-SST 1106'], rank=None, top-3: ['ITM-SST 1503.2', 'ITM-SST 1501.6', 'ITM-SST 1503.5']
- (de) *"Blitzschutz Sicherheitsvorschriften"* — esperado ['ITM-SST 1106'], rank=2, top-3: ['ITM-SST 1710.1', 'ITM-SST 1106.1', 'ITM-SST 1710.2']
