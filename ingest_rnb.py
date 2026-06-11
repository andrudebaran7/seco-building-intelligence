#!/usr/bin/env python3
"""Ingestión de prueba: API RNB (Référentiel National des Bâtiments) + cruce con DPE.

Lee la salida JSONL de ingest_dpe.py, toma los registros que traen id_rnb,
consulta la API del RNB edificio por edificio y produce un dataset cruzado:
diagnóstico energético (ADEME) + geometría y estado del edificio (RNB).

Fuente: https://rnb.beta.gouv.fr — API abierta, sin registro.

Uso:
    python3 ingest_rnb.py                                  # usa data/dpe_dpto75.jsonl
    python3 ingest_rnb.py --dpe-file data/dpe_dpto33.jsonl
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://rnb-api.beta.gouv.fr/api/alpha/buildings"
SLEEP_BETWEEN_CALLS = 0.25  # cortesía con una API beta sin límite documentado

# Columnas que el RNB aporta al cruce, aplanadas para CSV.
RNB_FIELDS = [
    "rnb_status",        # constructed / demolished / ...
    "rnb_lon",
    "rnb_lat",
    "rnb_insee_code",    # código de comuna INSEE
    "rnb_n_addresses",   # nº de direcciones asociadas al edificio
]


def fetch_building(rnb_id: str) -> dict | None:
    url = f"{API_BASE}/{rnb_id}/"
    req = urllib.request.Request(url, headers={"User-Agent": "ingest-test/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # id_rnb del DPE ya no existe en el RNB actual
        raise


def flatten(building: dict) -> dict:
    point = building.get("point") or {}
    coords = point.get("coordinates") or [None, None]
    addresses = building.get("addresses") or []
    insee = addresses[0].get("city_insee_code") if addresses else None
    return {
        "rnb_status": building.get("status"),
        "rnb_lon": coords[0],
        "rnb_lat": coords[1],
        "rnb_insee_code": insee,
        "rnb_n_addresses": len(addresses),
    }


def load_dpe(dpe_file: Path) -> list[dict]:
    with dpe_file.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dpe-file", default="data/dpe_dpto75.jsonl",
                        help="JSONL generado por ingest_dpe.py (por defecto data/dpe_dpto75.jsonl)")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    args = parser.parse_args()

    dpe_file = Path(args.dpe_file)
    if not dpe_file.exists():
        sys.exit(f"No existe {dpe_file}; ejecuta antes ingest_dpe.py")

    dpe_rows = load_dpe(dpe_file)
    with_id = [r for r in dpe_rows if r.get("id_rnb")]
    ids = sorted({r["id_rnb"] for r in with_id})
    print(f"DPE leídos: {len(dpe_rows):,} — con id_rnb: {len(with_id):,} ({len(ids):,} edificios únicos)")

    # Un edificio puede tener varios DPE (varios pisos): consultar cada id una sola vez.
    buildings: dict[str, dict | None] = {}
    not_found = 0
    for i, rnb_id in enumerate(ids, 1):
        try:
            b = fetch_building(rnb_id)
        except urllib.error.URLError as e:
            sys.exit(f"Error de red contra la API del RNB en {rnb_id}: {e}")
        if b is None:
            not_found += 1
        buildings[rnb_id] = b
        print(f"  consultados {i:,}/{len(ids):,}", end="\r", flush=True)
        time.sleep(SLEEP_BETWEEN_CALLS)
    print()
    if not_found:
        print(f"  ids no encontrados en el RNB actual: {not_found}")

    # Cruce: cada fila DPE con id_rnb se enriquece con las columnas del RNB.
    joined = []
    for r in with_id:
        b = buildings.get(r["id_rnb"])
        if b is None:
            continue
        joined.append({**r, **flatten(b)})

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / (dpe_file.stem.replace("dpe_", "dpe_rnb_") or "dpe_rnb")

    fieldnames = list(joined[0].keys()) if joined else []
    csv_path = stem.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(joined)

    jsonl_path = stem.with_suffix(".jsonl")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in joined:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # GeoJSON con la geometría completa del edificio, para visualizar en QGIS/kepler.gl.
    features = []
    for rnb_id, b in buildings.items():
        if b is None:
            continue
        dpe_del_edificio = [r for r in with_id if r["id_rnb"] == rnb_id]
        features.append({
            "type": "Feature",
            "geometry": b.get("shape") or b.get("point"),
            "properties": {
                "rnb_id": rnb_id,
                "status": b.get("status"),
                "n_dpe": len(dpe_del_edificio),
                "etiquettes_dpe": [r.get("etiquette_dpe") for r in dpe_del_edificio],
            },
        })
    geojson_path = stem.with_suffix(".geojson")
    with geojson_path.open("w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False)

    print(f"Guardado: {csv_path}, {jsonl_path} y {geojson_path}")
    print(f"\nResumen del cruce: {len(joined):,} DPE enriquecidos sobre {len(features):,} edificios RNB")


if __name__ == "__main__":
    main()
