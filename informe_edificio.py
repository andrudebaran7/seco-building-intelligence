#!/usr/bin/env python3
"""Informe de riesgo por edificio: conecta los datos estructurados con el RAG.

Toma un edificio del dataset final francés (salida de ingest_georisques.py),
deriva sus señales de riesgo a partir de los atributos estructurados
(exposición a arcillas, etiqueta energética, materiales, época), recupera
las fichas de patología AQC pertinentes del índice RAG y genera un informe
en Markdown con citas a las fichas.

Dos modos de redacción:
  - plantilla (por defecto): informe estructurado sin LLM, siempre funciona.
  - --llm: redacción con Claude (SDK oficial de Anthropic, modelo
    claude-opus-4-8). Requiere ANTHROPIC_API_KEY en el entorno.

Requiere el venv del proyecto y el índice RAG ya construido:
    .venv/bin/python informe_edificio.py --max-riesgo
    .venv/bin/python informe_edificio.py --numero-dpe 2333E0421762G --llm
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("corpus/aqc/rag_index.db")
MODEL_NAME = "intfloat/multilingual-e5-small"
OUT_DIR = Path("informes")


# ---------------------------------------------------------------- señales

def derivar_senales(b: dict) -> list[dict]:
    """Mapea atributos estructurados del edificio a consultas de patología."""
    senales = []

    alea = b.get("alea_argiles_final")
    if alea in ("Fort", "Moyen"):
        senales.append({
            "senal": f"Exposición {alea} al retrait-gonflement des argiles "
                     f"(fuente: {b.get('alea_argiles_source')})",
            "query": "fissures dans les murs et fondations causées par le "
                     "retrait-gonflement des argiles en sols sensibles",
        })

    if b.get("etiquette_dpe") in ("F", "G"):
        senales.append({
            "senal": f"Etiqueta energética {b['etiquette_dpe']} (passoire thermique)",
            "query": "condensations moisissures dans les logements ventilation "
                     "insuffisante humidité intérieure",
        })

    mur = (b.get("bdnb_mat_mur") or "").upper()
    if "PIERRE" in mur or "MEULIERE" in mur:
        senales.append({
            "senal": f"Muros de fábrica antigua ({b['bdnb_mat_mur']})",
            "query": "humidité remontées capillaires dans murs anciens en pierre",
        })

    toit = (b.get("bdnb_mat_toit") or "").upper()
    if "TUILES" in toit:
        senales.append({
            "senal": f"Cubierta de teja ({b['bdnb_mat_toit']})",
            "query": "défauts d'étanchéité de couverture en tuiles infiltrations",
        })
    elif "ARDOISES" in toit:
        senales.append({
            "senal": f"Cubierta de pizarra ({b['bdnb_mat_toit']})",
            "query": "défauts de couverture en ardoises infiltrations",
        })
    elif "ZINC" in toit:
        senales.append({
            "senal": f"Cubierta de zinc ({b['bdnb_mat_toit']})",
            "query": "défauts d'étanchéité couverture zinc toiture métallique",
        })

    if b.get("periode_construction") == "avant 1948":
        senales.append({
            "senal": "Edificio anterior a 1948 (sin normativa térmica ni DTU modernos)",
            "query": "désordres structure plancher bois bâtiment ancien",
        })

    return senales


# ---------------------------------------------------------------- retrieval

def recuperar_fichas(senales: list[dict], top_por_senal: int = 2) -> None:
    """Añade a cada señal las fichas AQC más relevantes del índice RAG."""
    import numpy as np
    from sentence_transformers import SentenceTransformer

    con = sqlite3.connect(DB_PATH)
    data = con.execute("SELECT code, titulo, texto, embedding FROM chunks").fetchall()
    con.close()
    matrix = np.frombuffer(b"".join(r[3] for r in data), dtype=np.float32).reshape(len(data), -1)

    model = SentenceTransformer(MODEL_NAME)
    for s in senales:
        q = model.encode([f"query: {s['query']}"], normalize_embeddings=True)[0].astype(np.float32)
        scores = matrix @ q
        fichas, vistos = [], set()
        for idx in np.argsort(-scores):
            code, titulo, texto, _ = data[idx]
            if code in vistos:
                continue
            vistos.add(code)
            fichas.append({
                "code": code,
                "titulo": titulo,
                "score": float(scores[idx]),
                "extracto": " ".join(texto.split())[:500],
            })
            if len(fichas) >= top_por_senal:
                break
        s["fichas"] = fichas


# ---------------------------------------------------------------- informes

def ficha_identidad(b: dict) -> str:
    filas = [
        ("Dirección", b.get("adresse_ban")),
        ("Tipo", b.get("type_batiment")),
        ("Período de construcción", b.get("periode_construction")),
        ("Superficie habitable (vivienda)", f"{b.get('surface_habitable_logement')} m²"),
        ("Etiqueta energía / CO₂", f"{b.get('etiquette_dpe')} / {b.get('etiquette_ges')}"),
        ("Consumo energía primaria", f"{b.get('conso_5_usages_par_m2_ep')} kWh/m²/año"),
        ("Altura / plantas / viviendas",
         f"{b.get('bdnb_hauteur')} m / {b.get('bdnb_nb_niveau')} / {b.get('bdnb_nb_log')}"),
        ("Materiales muro / techo", f"{b.get('bdnb_mat_mur')} / {b.get('bdnb_mat_toit')}"),
        ("Riesgo arcillas (RGA)",
         f"{b.get('alea_argiles_final')} (fuente: {b.get('alea_argiles_source')})"),
        ("IDs", f"DPE {b.get('numero_dpe')} · RNB {b.get('id_rnb')} · "
                f"BDNB {b.get('bdnb_batiment_groupe_id')}"),
    ]
    cuerpo = "\n".join(f"| {k} | {v} |" for k, v in filas)
    return f"| Atributo | Valor |\n|---|---|\n{cuerpo}"


def informe_plantilla(b: dict, senales: list[dict]) -> str:
    partes = [
        f"# Informe de riesgo — {b.get('adresse_ban')}",
        "",
        "## Identidad del edificio",
        "",
        ficha_identidad(b),
        "",
        "## Señales de riesgo y patologías asociadas",
        "",
    ]
    if not senales:
        partes.append("Sin señales de riesgo destacables según los datos disponibles.")
    for i, s in enumerate(senales, 1):
        partes.append(f"### {i}. {s['senal']}")
        partes.append("")
        for f in s["fichas"]:
            partes.append(f"**[{f['code']}]** {f['titulo']} *(similitud {f['score']:.2f})*")
            partes.append("")
            partes.append(f"> {f['extracto']}…")
            partes.append("")
    partes += [
        "---",
        "",
        "*Generado automáticamente a partir de datos abiertos (ADEME, RNB, BDNB, "
        "Géorisques — Licence Ouverte) y de las Fiches Pathologie de l'AQC "
        "(qualiteconstruction.com). Documento de demostración, sin valor pericial.*",
    ]
    return "\n".join(partes)


def informe_llm(b: dict, senales: list[dict]) -> str:
    import anthropic

    contexto = []
    for s in senales:
        contexto.append(f"SEÑAL: {s['senal']}")
        for f in s["fichas"]:
            contexto.append(f"  FICHA [{f['code']}] {f['titulo']}\n  EXTRACTO: {f['extracto']}")
    prompt = (
        "Eres un ingeniero de control técnico de la construcción. Redacta en "
        "español un informe de riesgo breve (400-600 palabras) para el "
        "siguiente edificio, dirigido a un perito no especialista.\n\n"
        f"DATOS ESTRUCTURADOS DEL EDIFICIO (fuentes abiertas FR):\n"
        f"{json.dumps(b, ensure_ascii=False, indent=2)}\n\n"
        f"SEÑALES DE RIESGO Y FICHAS AQC RECUPERADAS:\n" + "\n".join(contexto) + "\n\n"
        "Reglas: fundamenta cada afirmación de patología citando la ficha AQC "
        "entre corchetes, p.ej. [A.02]. No inventes patologías sin ficha de "
        "respaldo. Cierra con recomendaciones de inspección priorizadas y una "
        "nota de que el documento no tiene valor pericial."
    )
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    texto = next(blk.text for blk in response.content if blk.type == "text")
    return (f"# Informe de riesgo — {b.get('adresse_ban')}\n\n"
            f"## Identidad del edificio\n\n{ficha_identidad(b)}\n\n{texto}\n")


# ---------------------------------------------------------------- main

def puntuar_riesgo(b: dict) -> int:
    """Heurística simple para --max-riesgo: más señales = más interesante."""
    return len(derivar_senales(b))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-file", default="data/dpe_rnb_bdnb_rga_dpto33.jsonl",
                        help="dataset final de ingest_georisques.py")
    sel = parser.add_mutually_exclusive_group()
    sel.add_argument("--numero-dpe", help="seleccionar el edificio por nº de DPE")
    sel.add_argument("--max-riesgo", action="store_true",
                     help="seleccionar el edificio con más señales de riesgo")
    parser.add_argument("--llm", action="store_true",
                        help="redactar con Claude (requiere ANTHROPIC_API_KEY)")
    parser.add_argument("--out", default=str(OUT_DIR), help="directorio de salida")
    args = parser.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"No existe {DB_PATH}; ejecuta antes: rag_aqc.py build")
    in_file = Path(args.in_file)
    if not in_file.exists():
        sys.exit(f"No existe {in_file}; ejecuta antes la cadena de ingestión francesa")

    registros = [json.loads(l) for l in in_file.open(encoding="utf-8")]
    if args.numero_dpe:
        candidatos = [r for r in registros if r.get("numero_dpe") == args.numero_dpe]
        if not candidatos:
            sys.exit(f"No hay ningún DPE {args.numero_dpe} en {in_file}")
        edificio = candidatos[0]
    else:
        edificio = max(registros, key=puntuar_riesgo)

    senales = derivar_senales(edificio)
    print(f"Edificio: {edificio.get('adresse_ban')} (DPE {edificio.get('numero_dpe')})")
    print(f"Señales de riesgo detectadas: {len(senales)}")
    for s in senales:
        print(f"  - {s['senal']}")

    recuperar_fichas(senales)

    if args.llm:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("--llm requiere ANTHROPIC_API_KEY en el entorno; "
                     "sin ella usa el modo plantilla (por defecto).")
        texto = informe_llm(edificio, senales)
        sufijo = "llm"
    else:
        texto = informe_plantilla(edificio, senales)
        sufijo = "plantilla"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"informe_{edificio.get('numero_dpe')}_{sufijo}.md"
    out_path.write_text(texto, encoding="utf-8")
    print(f"\nInforme guardado en {out_path}")


if __name__ == "__main__":
    main()
