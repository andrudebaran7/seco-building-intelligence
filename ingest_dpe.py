#!/usr/bin/env python3
"""Ingestión de prueba: API DPE de ADEME (dpe03existant).

Descarga diagnósticos de rendimiento energético (DPE) de viviendas
existentes en Francia y los guarda de forma estructurada en CSV y JSONL.

Fuente: https://data.ademe.fr/datasets/dpe03existant
Licencia de los datos: Licence Ouverte (Etalab). Sin registro.
Límite de la API para usuarios anónimos: 600 peticiones / 60 s.

Uso:
    python3 ingest_dpe.py                          # 500 registros de París (dpto 75)
    python3 ingest_dpe.py --departement 33 --limit 2000
"""

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
PAGE_SIZE = 250          # registros por petición (la API admite hasta 10000)
SLEEP_BETWEEN_CALLS = 0.2  # margen amplio frente al límite de 600 req/min

# Subconjunto de los 230 campos del dataset, elegidos para el caso de uso
# "Building Intelligence": identificación, cruce con RNB/BDNB, características
# constructivas y resultado energético.
FIELDS = [
    "numero_dpe",
    "date_etablissement_dpe",
    "id_rnb",                    # clave de cruce con BDNB / RNB
    "adresse_ban",
    "code_postal_ban",
    "nom_commune_ban",
    "code_departement_ban",
    "type_batiment",
    "periode_construction",
    "annee_construction",
    "surface_habitable_logement",
    "etiquette_dpe",             # etiqueta energía A-G
    "etiquette_ges",             # etiqueta emisiones A-G
    "conso_5_usages_par_m2_ep",  # kWh energía primaria / m2 / año
]


def fetch_page(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ingest-test/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def build_first_url(departement: str) -> str:
    params = {
        "size": PAGE_SIZE,
        "select": ",".join(FIELDS),
        "qs": f'code_departement_ban:"{departement}"',
        "sort": "-date_etablissement_dpe",  # los más recientes primero
    }
    return f"{API_BASE}?{urllib.parse.urlencode(params)}"


def ingest(departement: str, limit: int, out_dir: Path) -> list[dict]:
    rows: list[dict] = []
    url = build_first_url(departement)
    total = None
    while url and len(rows) < limit:
        page = fetch_page(url)
        if total is None:
            total = page.get("total")
            print(f"Total disponible en la API para el dpto {departement}: {total:,} DPE")
        for r in page.get("results", []):
            rows.append({f: r.get(f) for f in FIELDS})
            if len(rows) >= limit:
                break
        print(f"  descargados {len(rows):,}/{limit:,}", end="\r", flush=True)
        url = page.get("next")
        time.sleep(SLEEP_BETWEEN_CALLS)
    print()
    return rows


def save(rows: list[dict], out_dir: Path, departement: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"dpe_dpto{departement}"

    csv_path = stem.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    jsonl_path = stem.with_suffix(".jsonl")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Guardado: {csv_path} y {jsonl_path}")


def summary(rows: list[dict]) -> None:
    labels: dict[str, int] = {}
    with_rnb = 0
    for r in rows:
        labels[r.get("etiquette_dpe") or "?"] = labels.get(r.get("etiquette_dpe") or "?", 0) + 1
        if r.get("id_rnb"):
            with_rnb += 1
    print(f"\nResumen de {len(rows):,} registros:")
    print("  Etiquetas energía:", "  ".join(f"{k}:{v}" for k, v in sorted(labels.items())))
    print(f"  Con id_rnb (cruzables con BDNB): {with_rnb:,} ({100 * with_rnb / len(rows):.0f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--departement", default="75", help="código de departamento francés (por defecto 75, París)")
    parser.add_argument("--limit", type=int, default=500, help="máximo de registros a descargar (por defecto 500)")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    args = parser.parse_args()

    try:
        rows = ingest(args.departement, args.limit, Path(args.out))
    except urllib.error.URLError as e:
        sys.exit(f"Error de red contra la API de ADEME: {e}")

    if not rows:
        sys.exit("La API no devolvió registros; revisa el código de departamento.")

    save(rows, Path(args.out), args.departement)
    summary(rows)


if __name__ == "__main__":
    main()
