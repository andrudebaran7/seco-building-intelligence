#!/usr/bin/env python3
"""Ingestión de prueba: API BDNB (CSTB) + cruce con DPE↔RNB.

Lee la salida JSONL de ingest_rnb.py (DPE enriquecidos con RNB) y completa
la cadena consultando la BDNB open por id_rnb en lotes:

  1. batiment_construction      → batiment_groupe_id, altura, superficie huella
  2. batiment_groupe_ffo_bat    → materiales muro/techo, nº plantas, nº viviendas, año
  3. batiment_groupe_argiles    → exposición retrait-gonflement des argiles (RGA)

Fuente: https://api.bdnb.io (millésime open). Licence Ouverte v2.0, sin registro.

Uso:
    python3 ingest_bdnb.py                                      # usa data/dpe_rnb_dpto75.jsonl
    python3 ingest_bdnb.py --in-file data/dpe_rnb_dpto33.jsonl
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path

from red import http_json

API_BASE = "https://api.bdnb.io/v1/bdnb/donnees"
CHUNK = 50                 # ids por petición con el filtro in.()
PAGE = 10                  # la API open devuelve máx. 10 filas por respuesta (anónimo)
SLEEP_BETWEEN_CALLS = 0.3  # cortesía; la API open no documenta cuota anónima

# Columnas que la BDNB aporta al cruce final.
BDNB_FIELDS = [
    "bdnb_batiment_groupe_id",
    "bdnb_hauteur",            # altura del edificio (m)
    "bdnb_s_geom_cstr",        # superficie de la huella (m2)
    "bdnb_altitude_sol",       # altitud del suelo (m)
    "bdnb_annee_construction",
    "bdnb_mat_mur",            # material de muros (Fichiers Fonciers)
    "bdnb_mat_toit",           # material de cubierta
    "bdnb_nb_niveau",          # nº de plantas
    "bdnb_nb_log",             # nº de viviendas
    "bdnb_usage",
    "bdnb_alea_argiles",       # exposición RGA: Faible / Moyen / Fort
]


def fetch_table(table: str, key: str, values: list[str], select: str) -> list[dict]:
    """Consulta una tabla BDNB filtrando key=in.(values), troceado en CHUNK.

    La API open devuelve como máximo PAGE filas por respuesta aunque se pida
    más con limit, así que cada chunk se pagina con offset hasta agotarse.
    """
    rows: list[dict] = []
    for i in range(0, len(values), CHUNK):
        chunk = values[i:i + CHUNK]
        offset = 0
        while True:
            qs = urllib.parse.urlencode({
                key: f"in.({','.join(chunk)})",
                "select": select,
                "offset": str(offset),
            })
            page = http_json(f"{API_BASE}/{table}?{qs}", timeout=60)
            rows.extend(page)
            time.sleep(SLEEP_BETWEEN_CALLS)
            if len(page) < PAGE:
                break
            offset += PAGE
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-file", default="data/dpe_rnb_dpto75.jsonl",
                        help="JSONL generado por ingest_rnb.py (por defecto data/dpe_rnb_dpto75.jsonl)")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    args = parser.parse_args()

    in_file = Path(args.in_file)
    if not in_file.exists():
        sys.exit(f"No existe {in_file}; ejecuta antes ingest_dpe.py e ingest_rnb.py")

    with in_file.open(encoding="utf-8") as f:
        dpe_rnb = [json.loads(line) for line in f if line.strip()]
    rnb_ids = sorted({r["id_rnb"] for r in dpe_rnb if r.get("id_rnb")})
    print(f"Registros DPE↔RNB leídos: {len(dpe_rnb):,} — edificios únicos: {len(rnb_ids):,}")

    try:
        # Paso 1: rnb_id → batiment_groupe_id + geometría básica.
        constructions = fetch_table(
            "batiment_construction", "rnb_id", rnb_ids,
            "rnb_id,batiment_groupe_id,hauteur,s_geom_cstr,altitude_sol",
        )
        by_rnb = {c["rnb_id"]: c for c in constructions}
        groupe_ids = sorted({c["batiment_groupe_id"] for c in constructions})
        print(f"Encontrados en BDNB: {len(by_rnb):,}/{len(rnb_ids):,} rnb_ids "
              f"({len(groupe_ids):,} batiment_groupe)")

        # Paso 2: atributos por batiment_groupe.
        ffo = fetch_table(
            "batiment_groupe_ffo_bat", "batiment_groupe_id", groupe_ids,
            "batiment_groupe_id,annee_construction,mat_mur_txt,mat_toit_txt,"
            "nb_niveau,nb_log,usage_niveau_1_txt",
        )
        by_groupe_ffo = {r["batiment_groupe_id"]: r for r in ffo}

        argiles = fetch_table(
            "batiment_groupe_argiles", "batiment_groupe_id", groupe_ids,
            "batiment_groupe_id,alea",
        )
        by_groupe_argiles = {r["batiment_groupe_id"]: r for r in argiles}
    except urllib.error.URLError as e:
        sys.exit(f"Error de red contra la API de la BDNB: {e}")

    # Paso 3: cruce final fila a fila.
    joined = []
    for r in dpe_rnb:
        c = by_rnb.get(r.get("id_rnb"))
        if c is None:
            continue
        gid = c["batiment_groupe_id"]
        f = by_groupe_ffo.get(gid, {})
        a = by_groupe_argiles.get(gid, {})
        joined.append({
            **r,
            "bdnb_batiment_groupe_id": gid,
            "bdnb_hauteur": c.get("hauteur"),
            "bdnb_s_geom_cstr": c.get("s_geom_cstr"),
            "bdnb_altitude_sol": c.get("altitude_sol"),
            "bdnb_annee_construction": f.get("annee_construction"),
            "bdnb_mat_mur": f.get("mat_mur_txt"),
            "bdnb_mat_toit": f.get("mat_toit_txt"),
            "bdnb_nb_niveau": f.get("nb_niveau"),
            "bdnb_nb_log": f.get("nb_log"),
            "bdnb_usage": f.get("usage_niveau_1_txt"),
            "bdnb_alea_argiles": a.get("alea"),
        })

    if not joined:
        sys.exit("Ningún rnb_id del fichero de entrada existe en la BDNB open.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / in_file.stem.replace("dpe_rnb_", "dpe_rnb_bdnb_")

    fieldnames = list(joined[0].keys())
    csv_path = stem.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(joined)

    jsonl_path = stem.with_suffix(".jsonl")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in joined:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Guardado: {csv_path} y {jsonl_path}")

    # Resumen de control.
    def count(field: str) -> dict:
        acc: dict[str, int] = {}
        for r in joined:
            k = str(r.get(field) or "?")
            acc[k] = acc.get(k, 0) + 1
        return dict(sorted(acc.items(), key=lambda kv: -kv[1]))

    print(f"\nResumen de {len(joined):,} DPE con cadena completa DPE→RNB→BDNB:")
    print("  Material muros:", count("bdnb_mat_mur"))
    print("  Material techo:", count("bdnb_mat_toit"))
    print("  Riesgo arcillas (RGA):", count("bdnb_alea_argiles"))


if __name__ == "__main__":
    main()
