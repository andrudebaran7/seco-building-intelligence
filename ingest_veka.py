#!/usr/bin/env python3
"""Ingestión de prueba: open data de VEKA — rendimiento energético en Flandes.

Descarga los CSV abiertos del Vlaams Energie- en Klimaatagentschap (VEKA)
con resultados agregados de las declaraciones EPB (el equivalente flamenco,
agregado por comuna, del DPE francés).

Particularidad descubierta: la raíz de open-data.energiesparen.be responde
403, pero los ficheros bajo /Data/<NOMBRE>.csv se descargan sin problema.
Las rutas exactas salen del catálogo DCAT de metadata.vlaanderen.be.

Licencia: Modellicentie Gratis Hergebruik (Vlaanderen) — reuso libre.

Uso:
    python3 ingest_veka.py                          # e-peil medio por comuna
    python3 ingest_veka.py --dataset 05_AG_OVERZICHT_RESULTATEN_DETAIL  # 62 MB
"""

import argparse
import csv
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://open-data.energiesparen.be/Data"
UA = "Mozilla/5.0 (compatible; ingest-test/0.1)"
DATASET_DEFECTO = "02_GEMIDDELD_E_PEIL_PER_GEMEENTE"


def download(dataset: str, out_dir: Path) -> Path:
    url = f"{BASE}/{dataset}.csv"
    dest = out_dir / f"veka_{dataset.lower()}.csv"
    print(f"Descargando {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)
    print(f"  guardado: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest


def resumen_e_peil(path: Path) -> None:
    """Resumen de control para el dataset por defecto (e-peil por comuna)."""
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    print(f"\nFilas: {len(rows):,} — columnas: {list(rows[0].keys())}")

    # E-peil medio regional (NIS 02000 = Vlaanderen) para vivienda (WONEN):
    # cuanto más bajo el e-peil, mejor el rendimiento energético.
    serie = sorted(
        (r["AANVRAAG_JAAR_VERGUNNING"], r["GEMIDDELD_E_PEIL"], r["AANTAL_INGEDIENDE_AG"])
        for r in rows
        if r["NIS_CODE"] == "02000" and r["BESTEMMING"] == "WONEN"
    )
    if serie:
        print("E-peil medio en Flandes, vivienda (año permiso → e-peil, nº declaraciones):")
        for anyo, e_peil, n in serie:
            print(f"  {anyo}: {e_peil}  ({n} declaraciones)")
    comunas = {r["HOOFD_GEMEENTE"] for r in rows if r["PROVINCIE"]}
    print(f"Comunas distintas con datos: {len(comunas):,}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", default=DATASET_DEFECTO,
                        help=f"nombre del dataset VEKA (por defecto {DATASET_DEFECTO})")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        dest = download(args.dataset, out_dir)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} para {args.dataset} — ¿nombre de dataset correcto? "
                 f"(los nombres salen de las fichas en /HTML/ del portal VEKA)")
    except urllib.error.URLError as e:
        sys.exit(f"Error de red contra open-data.energiesparen.be: {e}")

    if args.dataset == DATASET_DEFECTO:
        resumen_e_peil(dest)


if __name__ == "__main__":
    main()
