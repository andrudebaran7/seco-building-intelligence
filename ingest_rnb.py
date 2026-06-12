#!/usr/bin/env python3
"""Ingestión de prueba: API RNB (Référentiel National des Bâtiments) + cruce con DPE.

Lee la salida JSONL de ingest_dpe.py y cruza cada DPE con su edificio RNB
por dos vías, en orden de preferencia:

  1. id_rnb directo (presente en el 17-52% de los DPE según territorio).
  2. Fallback por dirección: el identifiant_ban del DPE, cuando es una clave
     completa (comuna_calle_número, p.ej. 33249_0271_00001), funciona como
     cle_interop_ban en la API del RNB. Las claves sin número de portal
     (solo calle) no pueden resolver a un edificio y se descartan.

La columna rnb_match registra la vía de cada cruce (id_rnb | adresse_ban).
Si la clave BAN devuelve varios edificios se prefiere el de estado
"constructed" (y el primero en caso de empate).

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
import urllib.parse
from pathlib import Path

from red import http_json

API_BASE = "https://rnb-api.beta.gouv.fr/api/alpha/buildings"
SLEEP_BETWEEN_CALLS = 0.25  # cortesía con una API beta sin límite documentado

# Columnas que el RNB aporta al cruce, aplanadas para CSV.
RNB_FIELDS = [
    "rnb_status",        # constructed / demolished / ...
    "rnb_lon",
    "rnb_lat",
    "rnb_insee_code",    # código de comuna INSEE
    "rnb_n_addresses",   # nº de direcciones asociadas al edificio
    "rnb_match",         # vía del cruce: id_rnb | adresse_ban
]


def fetch_building(rnb_id: str) -> dict | None:
    try:
        return http_json(f"{API_BASE}/{rnb_id}/", timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # id_rnb del DPE ya no existe en el RNB actual
        raise


def cle_ban_completa(identifiant_ban: str | None) -> bool:
    """Una clave BAN resuelve a edificio solo si incluye número de portal
    (comuna_calle_número = 3+ segmentos); las de solo calle tienen 2."""
    return bool(identifiant_ban) and len(identifiant_ban.split("_")) >= 3


def fetch_by_cle_ban(cle: str) -> dict | None:
    """Busca edificios por clave BAN; prefiere estado 'constructed'."""
    qs = urllib.parse.urlencode({"cle_interop_ban": cle})
    results = http_json(f"{API_BASE}/?{qs}", timeout=30).get("results", [])
    if not results:
        return None
    construidos = [b for b in results if b.get("status") == "constructed"]
    return (construidos or results)[0]


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
    por_ban = [r for r in dpe_rows
               if not r.get("id_rnb") and cle_ban_completa(r.get("identifiant_ban"))]
    ids = sorted({r["id_rnb"] for r in with_id})
    cles = sorted({r["identifiant_ban"] for r in por_ban})
    print(f"DPE leídos: {len(dpe_rows):,} — con id_rnb: {len(with_id):,} "
          f"({len(ids):,} edificios) — candidatos por dirección BAN: "
          f"{len(por_ban):,} ({len(cles):,} claves)")

    # Vía 1: id_rnb directo. Un edificio puede tener varios DPE (pisos):
    # consultar cada id una sola vez.
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
        print(f"  por id: {i:,}/{len(ids):,}", end="\r", flush=True)
        time.sleep(SLEEP_BETWEEN_CALLS)
    print()
    if not_found:
        print(f"  ids no encontrados en el RNB actual: {not_found}")

    # Vía 2: fallback por clave BAN para los DPE sin id_rnb.
    por_cle: dict[str, dict | None] = {}
    for i, cle in enumerate(cles, 1):
        try:
            por_cle[cle] = fetch_by_cle_ban(cle)
        except urllib.error.URLError as e:
            sys.exit(f"Error de red contra la API del RNB en clave BAN {cle}: {e}")
        print(f"  por dirección: {i:,}/{len(cles):,}", end="\r", flush=True)
        time.sleep(SLEEP_BETWEEN_CALLS)
    print()
    matched_ban = sum(1 for b in por_cle.values() if b)
    print(f"  claves BAN resueltas a edificio: {matched_ban:,}/{len(cles):,}")

    # Cruce: primero por id, después por dirección (rellenando id_rnb).
    joined = []
    for r in with_id:
        b = buildings.get(r["id_rnb"])
        if b is None:
            continue
        joined.append({**r, **flatten(b), "rnb_match": "id_rnb"})
    for r in por_ban:
        b = por_cle.get(r["identifiant_ban"])
        if b is None:
            continue
        buildings[b["rnb_id"]] = b  # para el GeoJSON
        joined.append({**r, "id_rnb": b["rnb_id"], **flatten(b),
                       "rnb_match": "adresse_ban"})

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
        dpe_del_edificio = [r for r in joined if r["id_rnb"] == rnb_id]
        if not dpe_del_edificio:
            continue
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
    via_id = sum(1 for r in joined if r["rnb_match"] == "id_rnb")
    via_ban = len(joined) - via_id
    print(f"\nResumen del cruce: {len(joined):,} DPE enriquecidos "
          f"({via_id:,} por id_rnb + {via_ban:,} por dirección BAN) "
          f"sobre {len(features):,} edificios RNB — cobertura "
          f"{100 * len(joined) / len(dpe_rows):.0f}% de los {len(dpe_rows):,} DPE")


if __name__ == "__main__":
    main()
