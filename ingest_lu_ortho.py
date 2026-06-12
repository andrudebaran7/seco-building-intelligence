#!/usr/bin/env python3
"""Ingestión de prueba: ortofoto oficial 2025 de Luxemburgo — chips para CV.

Genera un dataset de visión por computador recortando la ortofoto oficial
(≤10 cm/píxel, CC0) alrededor de cada edificio ya ingerido por la cadena
luxemburguesa: un chip JPEG centrado en el centroide del edificio más un
manifiesto con los metadatos estructurados (altura 3D, parcela, dirección)
que sirven como etiquetas de entrenamiento.

Fuente: WMS abierto de geoportail.lu (capa ortho_2025, también ortho_2025_winter
y milésimas 1967-2023). Licencia CC0. Sin registro.

Uso:
    python3 ingest_lu_ortho.py                              # 24 chips de Bettendorf
    python3 ingest_lu_ortho.py --batiments data/lu_luxembourg_ville_batiments.jsonl \
        --zona luxembourg_ville --limit 50 --margen 30
"""

import argparse
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

WMS_URL = "https://wms.geoportail.lu/opendata/service"
SLEEP_BETWEEN_CALLS = 0.3
UA = "Mozilla/5.0 (compatible; ingest-test/0.1)"


def bbox_metros(lon: float, lat: float, half_m: float) -> str:
    """BBOX WMS 1.3.0 (lat,lon) de lado 2*half_m metros centrado en el punto."""
    dlat = half_m / 111320
    dlon = half_m / (111320 * math.cos(math.radians(lat)))
    return f"{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon}"


def fetch_chip(lon: float, lat: float, half_m: float, pixels: int, capa: str) -> bytes:
    params = urllib.parse.urlencode({
        "service": "WMS", "version": "1.3.0", "request": "GetMap",
        "layers": capa, "crs": "EPSG:4326",
        "bbox": bbox_metros(lon, lat, half_m),
        "width": pixels, "height": pixels,
        "format": "image/jpeg", "styles": "",
    })
    req = urllib.request.Request(f"{WMS_URL}?{params}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if not data.startswith(b"\xff\xd8"):  # firma JPEG
        raise ValueError(f"respuesta no JPEG ({len(data)} bytes): {data[:80]!r}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batiments", default="data/lu_bettendorf_batiments_3d.jsonl",
                        help="JSONL de la cadena LU (por defecto Bettendorf con alturas)")
    parser.add_argument("--zona", default="bettendorf", help="etiqueta para el directorio de salida")
    parser.add_argument("--limit", type=int, default=24, help="nº de chips (por defecto 24)")
    parser.add_argument("--margen", type=float, default=20,
                        help="semilado del chip en metros (por defecto 20 → chip de 40×40 m)")
    parser.add_argument("--pixels", type=int, default=400,
                        help="tamaño del chip en píxeles (400 con margen 20 ≈ 10 cm/px)")
    parser.add_argument("--capa", default="ortho_2025",
                        help="capa WMS (ortho_2025, ortho_2025_winter, ortho_2023...)")
    parser.add_argument("--out", default="data/ortho_chips", help="directorio base de salida")
    args = parser.parse_args()

    src = Path(args.batiments)
    if not src.exists():
        sys.exit(f"No existe {src}; ejecuta antes la cadena ingest_geoportail_lu/ingest_lu_3d")
    edificios = [json.loads(linea) for linea in src.open(encoding="utf-8")]
    # Priorizar edificios con altura 3D y dirección: mejores etiquetas para CV.
    edificios.sort(key=lambda b: (b.get("hauteur_m") is None, b.get("adresse_ejemplo") is None))
    seleccion = edificios[: args.limit]

    out_dir = Path(args.out) / args.zona
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    fallos = 0
    for i, b in enumerate(seleccion, 1):
        chip_id = (b.get("building_id") or f"b{i}").removeprefix("Building2D.")
        dest = out_dir / f"{chip_id}.jpg"
        if not dest.exists():
            try:
                dest.write_bytes(fetch_chip(b["lon"], b["lat"], args.margen,
                                            args.pixels, args.capa))
            except (urllib.error.URLError, ValueError) as e:
                print(f"\n  aviso: fallo en {chip_id}: {e}")
                fallos += 1
                continue
            time.sleep(SLEEP_BETWEEN_CALLS)
        manifest.append({
            "chip": dest.name,
            "building_id": b.get("building_id"),
            "lon": b["lon"], "lat": b["lat"],
            "lado_m": args.margen * 2,
            "pixels": args.pixels,
            "capa": args.capa,
            "hauteur_m": b.get("hauteur_m"),
            "parcel_ref": b.get("parcel_ref"),
            "adresse": b.get("adresse_ejemplo"),
        })
        print(f"  chips {i}/{len(seleccion)}", end="\r", flush=True)
    print()

    if not manifest:
        sys.exit("No se generó ningún chip.")
    man_path = out_dir / "manifest.csv"
    with man_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
        writer.writeheader()
        writer.writerows(manifest)
    with (out_dir / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    con_h = sum(1 for m in manifest if m["hauteur_m"] is not None)
    total_mb = sum((out_dir / m["chip"]).stat().st_size for m in manifest) / 1e6
    print(f"Guardados {len(manifest):,} chips ({total_mb:.1f} MB) en {out_dir}/ "
          f"+ manifest.csv/jsonl")
    print(f"  resolución ≈ {args.margen * 2 / args.pixels * 100:.0f} cm/píxel — "
          f"con etiqueta de altura: {con_h}/{len(manifest)} — fallos: {fallos}")


if __name__ == "__main__":
    main()
