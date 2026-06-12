#!/usr/bin/env python3
"""Ingestión de prueba: Bâtiments 3D 2023 de data.public.lu — altura por edificio.

Las huellas 2D abiertas (GPKG/GeoJSON) solo traen la cota del suelo; la
altura vive en los CityGML por comuna (bldg:measuredHeight). Este script:

  1. resuelve la URL del zip de la comuna vía la API de data.public.lu,
  2. lo descarga y extrae solo el .gml (ignora las texturas jpg),
  3. parsea gml:id → measuredHeight de cada edificio,
  4. cruza por ID con la salida de ingest_geoportail_lu.py
     (Building2D.ACT_<uuid> ↔ ACT_<uuid>).

Fuente: dataset "Base de données nationale des bâtiments 3D 2023" (ACT), CC0.

Uso:
    python3 ingest_lu_3d.py --commune bettendorf
    python3 ingest_lu_3d.py --commune bettendorf --batiments data/lu_bettendorf_batiments.jsonl
"""

import argparse
import csv
import json
import re
import sys
import urllib.error
import zipfile
from pathlib import Path

from red import descargar, http_json

DATASET_API = ("https://data.public.lu/api/1/datasets/"
               "base-de-donnees-nationale-des-batiments-3d-2023/")


def resolve_url(commune: str) -> str:
    dataset = http_json(DATASET_API, timeout=30)
    wanted = f"act2023v2-bati3d-{commune.lower()}.zip"
    for r in dataset["resources"]:
        if r["title"].lower() == wanted:
            return r["url"]
    sys.exit(f"No existe el recurso {wanted} en el dataset (¿nombre de comuna?)")


def download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"Ya descargado: {dest}")
        return
    print(f"Descargando {url} ...")
    descargar(url, dest, timeout=600)
    print(f"  guardado: {dest} ({dest.stat().st_size / 1e6:.0f} MB)")


def extract_gml(zip_path: Path, out_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path) as z:
        gml_names = [n for n in z.namelist() if n.endswith(".gml")]
        if not gml_names:
            sys.exit(f"El zip {zip_path} no contiene ningún .gml")
        z.extract(gml_names[0], out_dir)
    return out_dir / gml_names[0]


# Cada edificio aparece como <bldg:Building gml:id="ACT_..."> y contiene un
# <bldg:measuredHeight uom="#m">N</bldg:measuredHeight>.
BUILDING_RE = re.compile(
    r'<bldg:Building gml:id="(?P<id>[^"]+)".*?'
    r'<bldg:measuredHeight[^>]*>(?P<h>[\d.]+)</bldg:measuredHeight>',
    re.DOTALL,
)


def parse_heights(gml_path: Path) -> dict[str, float]:
    text = gml_path.read_text(encoding="utf-8", errors="replace")
    heights = {m.group("id"): float(m.group("h")) for m in BUILDING_RE.finditer(text)}
    return heights


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commune", required=True,
                        help="nombre de la comuna tal como aparece en el dataset (p.ej. bettendorf)")
    parser.add_argument("--batiments", default=None,
                        help="JSONL de ingest_geoportail_lu.py a enriquecer "
                             "(por defecto data/lu_<commune>_batiments.jsonl)")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    parser.add_argument("--downloads", default="downloads",
                        help="directorio para los zips (por defecto ./downloads)")
    args = parser.parse_args()

    commune = args.commune.lower()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dl_dir = Path(args.downloads)
    dl_dir.mkdir(parents=True, exist_ok=True)

    try:
        url = resolve_url(commune)
        zip_path = dl_dir / f"act2023v2-bati3d-{commune}.zip"
        download(url, zip_path)
    except urllib.error.URLError as e:
        sys.exit(f"Error de red contra data.public.lu: {e}")

    gml_path = extract_gml(zip_path, dl_dir)
    heights = parse_heights(gml_path)
    print(f"Alturas extraídas del CityGML: {len(heights):,} edificios")

    heights_csv = out_dir / f"lu_3d_{commune}_hauteurs.csv"
    with heights_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["building_id", "hauteur_m"])
        for bid, h in sorted(heights.items()):
            writer.writerow([bid, h])
    print(f"Guardado: {heights_csv}")

    # Cruce con la salida del paso WFS, si existe.
    batiments_path = Path(args.batiments or out_dir / f"lu_{commune}_batiments.jsonl")
    if not batiments_path.exists():
        print(f"\nNota: no existe {batiments_path}; ejecuta ingest_geoportail_lu.py "
              f"con --zona {commune} para poder cruzar. Solo se generó el CSV de alturas.")
        return

    with batiments_path.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]

    matched = 0
    for r in rows:
        # Building2D.ACT_<uuid> (INSPIRE) ↔ ACT_<uuid> (CityGML)
        short_id = (r.get("building_id") or "").removeprefix("Building2D.")
        h = heights.get(short_id)
        r["hauteur_m"] = h
        if h is not None:
            matched += 1

    stem = out_dir / f"lu_{commune}_batiments_3d"
    csv_path = stem.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    jsonl_path = stem.with_suffix(".jsonl")
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Guardado: {csv_path} y {jsonl_path}")

    con_h = [r["hauteur_m"] for r in rows if r.get("hauteur_m") is not None]
    print(f"\nResumen: {matched:,}/{len(rows):,} edificios con altura "
          f"({100 * matched / len(rows):.0f}%)")
    if con_h:
        con_h.sort()
        print(f"  altura mín/mediana/máx: {con_h[0]:.1f} / "
              f"{con_h[len(con_h) // 2]:.1f} / {con_h[-1]:.1f} m")


if __name__ == "__main__":
    main()
