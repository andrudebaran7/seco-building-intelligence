#!/usr/bin/env python3
"""Ingestión de prueba: API Géorisques RGA — completa el riesgo de arcillas.

Lee la salida JSONL de ingest_bdnb.py y, para los edificios sin dato de
arcillas en la BDNB, consulta la exposición retrait-gonflement des argiles
(RGA) en Géorisques usando las coordenadas lon/lat que aportó el RNB.

La API devuelve 200 con cuerpo vacío cuando el punto está fuera de toda
zona de exposición cartografiada; se registra como "Non exposé".

Fuente: https://www.georisques.gouv.fr/api/v1/rga (BRGM). Licence Ouverte.

Uso:
    python3 ingest_georisques.py                                       # usa data/dpe_rnb_bdnb_dpto75.jsonl
    python3 ingest_georisques.py --in-file data/dpe_rnb_bdnb_dpto33.jsonl
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
from pathlib import Path

from red import http_get

API_URL = "https://www.georisques.gouv.fr/api/v1/rga"
SLEEP_BETWEEN_CALLS = 0.2  # la API pública admite ~10 req/s; margen amplio

# Normalización al vocabulario de la BDNB (Faible/Moyen/Fort) para que la
# columna final sea homogénea venga de donde venga.
EXPOSITION_MAP = {
    "Exposition faible": "Faible",
    "Exposition moyenne": "Moyen",
    "Exposition forte": "Fort",
}
NOT_EXPOSED = "Non exposé"


def fetch_rga(lon: float, lat: float) -> str | None:
    """Devuelve la exposición RGA normalizada para un punto, o None si falla."""
    body = http_get(f"{API_URL}?latlon={lon},{lat}",
                    timeout=30).decode("utf-8").strip()
    if not body:
        return NOT_EXPOSED
    data = json.loads(body)
    return EXPOSITION_MAP.get(data.get("exposition"), data.get("exposition"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-file", default="data/dpe_rnb_bdnb_dpto75.jsonl",
                        help="JSONL generado por ingest_bdnb.py (por defecto data/dpe_rnb_bdnb_dpto75.jsonl)")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    args = parser.parse_args()

    in_file = Path(args.in_file)
    if not in_file.exists():
        sys.exit(f"No existe {in_file}; ejecuta antes la cadena ingest_dpe → ingest_rnb → ingest_bdnb")

    with in_file.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    # Edificios únicos sin dato BDNB de arcillas y con coordenadas del RNB.
    pending: dict[str, tuple[float, float]] = {}
    for r in rows:
        if not r.get("bdnb_alea_argiles") and r.get("rnb_lon") is not None:
            pending.setdefault(r["id_rnb"], (r["rnb_lon"], r["rnb_lat"]))
    print(f"Registros leídos: {len(rows):,} — edificios sin dato de arcillas: {len(pending):,}")

    rga_by_id: dict[str, str | None] = {}
    for i, (rnb_id, (lon, lat)) in enumerate(sorted(pending.items()), 1):
        try:
            rga_by_id[rnb_id] = fetch_rga(lon, lat)
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            print(f"\n  aviso: fallo en {rnb_id}: {e}")
            rga_by_id[rnb_id] = None
        print(f"  consultados {i:,}/{len(pending):,}", end="\r", flush=True)
        time.sleep(SLEEP_BETWEEN_CALLS)
    print()

    # Columna final homogénea + trazabilidad de la fuente.
    for r in rows:
        if r.get("bdnb_alea_argiles"):
            r["alea_argiles_final"] = r["bdnb_alea_argiles"]
            r["alea_argiles_source"] = "BDNB"
        else:
            rga = rga_by_id.get(r.get("id_rnb"))
            r["alea_argiles_final"] = rga
            r["alea_argiles_source"] = "Géorisques" if rga else None

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / in_file.stem.replace("dpe_rnb_bdnb_", "dpe_rnb_bdnb_rga_")

    fieldnames = list(rows[0].keys())
    csv_path = stem.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    jsonl_path = stem.with_suffix(".jsonl")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Guardado: {csv_path} y {jsonl_path}")

    final: dict[str, int] = {}
    for r in rows:
        k = f"{r['alea_argiles_final'] or '?'} ({r['alea_argiles_source'] or 'sin fuente'})"
        final[k] = final.get(k, 0) + 1
    print(f"\nResumen de {len(rows):,} registros — riesgo arcillas consolidado:")
    for k, v in sorted(final.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
