#!/usr/bin/env python3
"""Genera informes sintéticos de inspección técnica (PDF) con ground truth.

SECO no publica informes reales (confidenciales), así que el pipeline de
extracción se demuestra sobre informes sintéticos REALISTAS:

  - direcciones y características de edificios REALES (del dataset final
    francés ya ingerido),
  - observaciones de defectos redactadas en francés libre (varias
    formulaciones por tipo de defecto, escritas como las notas de un
    inspector — NO copiadas de las fichas AQC, para que la clasificación
    semántica posterior no sea trivial),
  - tres plantillas de maquetación distintas (los informes reales son
    heterogéneos),
  - y un ground truth JSONL con los valores correctos de cada campo,
    para evaluar la extracción con métricas.

Uso:
    .venv/bin/python sintetizar_informes.py            # 30 informes
    .venv/bin/python sintetizar_informes.py --n 50 --seed 7
"""

import argparse
import json
import random
from pathlib import Path

from fpdf import FPDF

OUT_DIR = Path("informes_sinteticos")

# ----------------------------------------------------------------------------
# Catálogo de defectos: código AQC verdadero + formulaciones libres de
# inspector (parafraseadas, no extraídas de las fichas) + localizaciones.
# ----------------------------------------------------------------------------
DEFECTOS = [
    {
        "code": "A.02",
        "tema": "fisuración por suelos arcillosos",
        "frases": [
            "Fissuration en escalier visible sur le pignon, ouverture variable selon la saison. Le terrain est argileux et le phénomène s'est aggravé après l'été sec.",
            "Lézardes traversantes au droit des angles du bâtiment, compatibles avec un tassement différentiel des fondations en sol sensible.",
            "Plusieurs fissures obliques de plus de 2 mm sur la façade arrière ; les fondations semblent affectées par les variations d'humidité du sol.",
        ],
        "localisations": ["pignon nord", "façade arrière", "angle sud-est"],
    },
    {
        "code": "A.05",
        "tema": "hundimiento de solera",
        "frases": [
            "Le carrelage du séjour est désolidarisé et le dallage présente un affaissement net au centre de la pièce.",
            "Affaissement du dallage du rez-de-chaussée avec contre-pente vers l'intérieur ; bourrage sous dallage vraisemblablement mal compacté.",
            "Dénivelé d'environ 3 cm du sol du garage, accompagné d'une fissuration périphérique du dallage.",
        ],
        "localisations": ["séjour", "garage", "rez-de-chaussée"],
    },
    {
        "code": "B.01",
        "tema": "humedades capilares",
        "frases": [
            "Traces d'humidité en partie basse des murs du rez-de-chaussée, avec salpêtre et décollement des plinthes. L'humidité remonte du sol, absence d'arase étanche.",
            "Auréoles persistantes jusqu'à environ 80 cm de hauteur sur les murs anciens en pierre ; l'enduit cloque et s'effrite.",
            "Le bas des murs du couloir reste humide toute l'année, peinture écaillée et odeur de moisi : remontées d'eau par capillarité probables.",
        ],
        "localisations": ["murs du rez-de-chaussée", "couloir", "cave"],
    },
    {
        "code": "B.05",
        "tema": "corrosión de armaduras",
        "frases": [
            "Éclats de béton en sous-face du balcon laissant apparaître des aciers corrodés, enrobage manifestement insuffisant.",
            "Les nez de dalle des balcons présentent des armatures apparentes et rouillées avec éclatement localisé du béton.",
            "Corrosion des aciers visible sur l'acrotère, le béton éclate par plaques.",
        ],
        "localisations": ["balcon du 2e étage", "nez de dalle", "acrotère"],
    },
    {
        "code": "B.11",
        "tema": "estructura de madera",
        "frases": [
            "Flèche anormale du plancher bois de l'étage ; plusieurs solives présentent des sections affaiblies.",
            "L'ossature bois du comble montre des assemblages desserrés et une déformation sensible sous charge.",
            "Plancher de l'étage souple à la marche, craquements importants, solivage sous-dimensionné à première vue.",
        ],
        "localisations": ["plancher de l'étage", "comble", "solivage du grenier"],
    },
    {
        "code": "C.06",
        "tema": "infiltraciones cubierta de teja",
        "frases": [
            "Traces d'infiltration au plafond du dernier niveau au droit de la noue ; plusieurs tuiles déplacées et solin dégradé autour de la souche de cheminée.",
            "Entrées d'eau ponctuelles par la couverture en tuiles, notamment au niveau du faîtage et de la fenêtre de toit.",
            "Auréoles récentes au plafond sous toiture : les points singuliers de la couverture (rives, arêtiers) sont défectueux.",
        ],
        "localisations": ["noue de toiture", "souche de cheminée", "faîtage"],
    },
    {
        "code": "C.07",
        "tema": "condensación bajo cubierta metálica",
        "frases": [
            "Gouttes d'eau en sous-face du bac acier par temps froid, sans fuite identifiable : condensation sous couverture métallique non ventilée.",
            "La sous-face de la couverture en zinc présente de la condensation matinale qui goutte sur l'isolant.",
        ],
        "localisations": ["sous-face de couverture", "versant nord"],
    },
    {
        "code": "D.01",
        "tema": "infiltraciones por carpinterías",
        "frases": [
            "Infiltrations d'eau autour des menuiseries de la façade exposée ; le calfeutrement entre dormant et gros oeuvre est dégradé.",
            "Entrées d'eau en pied de baie vitrée lors des pluies battantes, joint de liaison menuiserie/maçonnerie défaillant.",
            "L'appui de fenêtre de la chambre laisse passer l'eau, gonflement de la plaque de plâtre en allège.",
        ],
        "localisations": ["fenêtres façade ouest", "baie vitrée du salon", "chambre 2"],
    },
    {
        "code": "D.03",
        "tema": "desórdenes de revoco monocapa",
        "frases": [
            "L'enduit monocouche de façade présente un faïençage généralisé et des décollements par plaques au droit des points singuliers.",
            "Cloquage et chute localisée de l'enduit de façade, spectre des joints de maçonnerie apparent.",
        ],
        "localisations": ["façade sur rue", "façade sud"],
    },
    {
        "code": "E.09",
        "tema": "condensaciones interiores",
        "frases": [
            "Moisissures noires aux angles des plafonds des chambres et autour des fenêtres ; la ventilation du logement est insuffisante.",
            "Condensation récurrente sur les vitrages et taches de moisissure derrière les meubles des pièces humides.",
            "Les occupants signalent de la buée permanente et des taches noires au plafond de la salle de bains ; la VMC est hors service.",
        ],
        "localisations": ["chambres", "salle de bains", "cuisine"],
    },
]

GRAVITES = ["mineure", "moyenne", "majeure"]
INSPECTEURS = ["M. Lambert", "Mme Petit", "M. Da Silva", "Mme Hoffmann",
               "M. Diallo", "Mme Janssens"]


def cargar_edificios() -> list[dict]:
    edificios = []
    for f in ["data/dpe_rnb_bdnb_rga_dpto33.jsonl", "data/dpe_rnb_bdnb_rga_dpto75.jsonl"]:
        p = Path(f)
        if p.exists():
            edificios += [json.loads(linea) for linea in p.open(encoding="utf-8")]
    if not edificios:
        raise SystemExit("No hay dataset de edificios; ejecuta la cadena francesa antes.")
    return edificios


def construir_informe(i: int, rng: random.Random, edificios: list[dict]) -> dict:
    b = rng.choice(edificios)
    n_defectos = rng.randint(2, 5)
    tipos = rng.sample(DEFECTOS, n_defectos)
    defectos = []
    for t in tipos:
        defectos.append({
            "code_aqc": t["code"],
            "descripcion": rng.choice(t["frases"]),
            "localisation": rng.choice(t["localisations"]),
            "gravite": rng.choice(GRAVITES),
        })
    fecha = f"2026-{rng.randint(1, 5):02d}-{rng.randint(1, 28):02d}"
    return {
        "ref": f"TIS-2026-{1000 + i}",
        "fecha": fecha,
        "adresse": b.get("adresse_ban"),
        "inspecteur": rng.choice(INSPECTEURS),
        "type_batiment": b.get("type_batiment"),
        "annee_construction": b.get("annee_construction") or b.get("periode_construction"),
        "plantilla": rng.randint(1, 3),
        "defectos": defectos,
    }


def render_pdf(inf: dict, dest: Path) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    def titulo(txt, size=14):
        pdf.set_font("helvetica", "B", size)
        pdf.multi_cell(0, 8, txt)
        pdf.ln(1)

    def parrafo(txt, size=10, style=""):
        pdf.set_font("helvetica", style, size)
        pdf.multi_cell(0, 5.5, txt)
        pdf.ln(0.5)

    t = inf["plantilla"]
    if t == 1:
        titulo("RAPPORT D'INSPECTION TECHNIQUE")
        parrafo(f"Référence : {inf['ref']}")
        parrafo(f"Date de visite : {inf['fecha']}")
        parrafo(f"Inspecteur : {inf['inspecteur']}")
        parrafo(f"Adresse du bien : {inf['adresse']}")
        parrafo(f"Type : {inf['type_batiment']} - Construction : {inf['annee_construction']}")
        pdf.ln(3)
        titulo("OBSERVATIONS", 12)
        for k, d in enumerate(inf["defectos"], 1):
            parrafo(f"Observation {k} - Localisation : {d['localisation']} - "
                    f"Gravité : {d['gravite']}", style="B")
            parrafo(d["descripcion"])
    elif t == 2:
        titulo("COMPTE RENDU DE VISITE - CONTRÔLE TECHNIQUE")
        parrafo(f"Dossier n° {inf['ref']} | Visite du {inf['fecha']} | "
                f"Établi par {inf['inspecteur']}")
        parrafo(f"Bien inspecté : {inf['adresse']} ({inf['type_batiment']}, "
                f"{inf['annee_construction']})")
        pdf.ln(3)
        titulo("DÉSORDRES CONSTATÉS", 12)
        for k, d in enumerate(inf["defectos"], 1):
            parrafo(f"{k}. [{d['gravite'].upper()}] {d['localisation']}", style="B")
            parrafo(d["descripcion"])
    else:
        titulo("FICHE D'INSPECTION")
        parrafo(f"Réf. : {inf['ref']}   Date : {inf['fecha']}")
        parrafo(f"Adresse : {inf['adresse']}")
        parrafo(f"Contrôleur : {inf['inspecteur']}")
        parrafo(f"Typologie : {inf['type_batiment']} / {inf['annee_construction']}")
        pdf.ln(3)
        titulo("POINTS RELEVÉS", 12)
        for k, d in enumerate(inf["defectos"], 1):
            parrafo(f"Point {k} ({d['localisation']}) - niveau de gravité : "
                    f"{d['gravite']}", style="B")
            parrafo(d["descripcion"])

    pdf.ln(4)
    parrafo("Le présent rapport est établi à des fins de démonstration. "
            "Document synthétique généré automatiquement.", size=8, style="I")
    pdf.output(str(dest))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=30, help="nº de informes (por defecto 30)")
    parser.add_argument("--seed", type=int, default=42, help="semilla reproducible")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    edificios = cargar_edificios()
    pdf_dir = OUT_DIR / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    gt_path = OUT_DIR / "ground_truth.jsonl"
    with gt_path.open("w", encoding="utf-8") as gt:
        for i in range(args.n):
            inf = construir_informe(i, rng, edificios)
            render_pdf(inf, pdf_dir / f"{inf['ref']}.pdf")
            gt.write(json.dumps(inf, ensure_ascii=False) + "\n")

    n_def = sum(len(json.loads(linea)["defectos"]) for linea in gt_path.open(encoding="utf-8"))
    print(f"Generados {args.n} informes sintéticos ({n_def} defectos) en {pdf_dir}/")
    print(f"Ground truth: {gt_path}")


if __name__ == "__main__":
    main()
