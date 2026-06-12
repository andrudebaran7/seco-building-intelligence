#!/usr/bin/env python3
"""Cruce belga de segundo nivel: edificios → contexto comunal por código NIS.

Enriquece los edificios belgas (salida de ingest_be_geo.py) con el contexto
estadístico de su comuna, cruzando por el código NIS que aporta la parcela
catastral (CAPAKEY):

  - Statbel, parque catastral de edificios (CC BY 4.0): total de edificios,
    % construidos antes de 1946 y después de 1981 (la lógica
    "patología-por-época" del reporte original), % con calefacción
    central y nº de viviendas.
  - VEKA (solo Flandes): e-peil medio de las declaraciones EPB de vivienda,
    ponderado por nº de declaraciones.

El fichero de Statbel se descarga automáticamente si no está en downloads/.

Uso:
    python3 ingest_be_stats.py                   # todos los be_*_batiments.jsonl
    python3 ingest_be_stats.py --in-file data/be_valonia_liege_centre_batiments.jsonl
"""

import argparse
import csv
import json
import sys
import urllib.error
from collections import defaultdict
from pathlib import Path

from red import descargar

STATBEL_URL = ("https://statbel.fgov.be/sites/default/files/files/opendata/"
               "Buildstock/building_stock_open_data_2023.zip")
STATBEL_TXT = Path("downloads/building_stock_open_data_2023.txt")
VEKA_CSV = Path("data/veka_02_gemiddeld_e_peil_per_gemeente.csv")
UA = "Mozilla/5.0 (compatible; ingest-test/0.1)"

# Estadísticas Statbel usadas (se suman sobre los tipos de edificio R1-R6).
PRE_1946 = ("T3.1", "T3.2", "T3.3")
POST_1981 = ("T3.7",)


def asegurar_statbel() -> None:
    if STATBEL_TXT.exists():
        return
    import zipfile
    STATBEL_TXT.parent.mkdir(exist_ok=True)
    zip_path = STATBEL_TXT.parent / "statbel_building_stock.zip"
    print(f"Descargando Statbel ({STATBEL_URL}) ...")
    descargar(STATBEL_URL, zip_path, headers={"User-Agent": UA}, timeout=300)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(STATBEL_TXT.parent)


def cargar_statbel() -> dict[str, dict]:
    """Por NIS: agregados del parque de edificios (suma sobre tipos R1-R6)."""
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    with STATBEL_TXT.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="|")
        for r in reader:
            if r["CD_REFNIS_LVL"] != "5":   # nivel 5 = comuna
                continue
            acc[r["CD_REFNIS"]][r["CD_STAT_TYPE"]] += float(r["MS_VALUE"] or 0)
    ctx = {}
    for nis, s in acc.items():
        total = s.get("T1") or None
        ctx[nis] = {
            "nis_total_edificios": int(total) if total else None,
            "nis_pct_pre1946": round(100 * sum(s.get(k, 0) for k in PRE_1946) / total, 1)
                               if total else None,
            "nis_pct_post1981": round(100 * sum(s.get(k, 0) for k in POST_1981) / total, 1)
                                if total else None,
            "nis_pct_calefaccion": round(100 * s.get("T5", 0) / total, 1)
                                   if total else None,
            "nis_viviendas": int(s["T8"]) if s.get("T8") else None,
        }
    return ctx


def cargar_veka() -> dict[str, float]:
    """Por NIS flamenco: e-peil medio de vivienda ponderado por declaraciones."""
    if not VEKA_CSV.exists():
        return {}
    num, den = defaultdict(float), defaultdict(float)
    with VEKA_CSV.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["BESTEMMING"] != "WONEN" or not r["GEMIDDELD_E_PEIL"]:
                continue
            n = float(r["AANTAL_INGEDIENDE_AG"] or 0)
            num[r["NIS_CODE"]] += float(r["GEMIDDELD_E_PEIL"]) * n
            den[r["NIS_CODE"]] += n
    return {nis: round(num[nis] / den[nis], 1) for nis in num if den[nis]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-file", action="append", default=None,
                        help="JSONL de ingest_be_geo.py (repetible; por defecto "
                             "todos los data/be_*_batiments.jsonl)")
    args = parser.parse_args()

    ficheros = ([Path(f) for f in args.in_file] if args.in_file
                else sorted(Path("data").glob("be_*_batiments.jsonl")))
    ficheros = [f for f in ficheros if "_ctx" not in f.name]
    if not ficheros:
        sys.exit("No hay ficheros be_*_batiments.jsonl; ejecuta antes ingest_be_geo.py")

    try:
        asegurar_statbel()
    except urllib.error.URLError as e:
        sys.exit(f"Error de red contra Statbel: {e}")
    statbel = cargar_statbel()
    veka = cargar_veka()
    print(f"Statbel: contexto de {len(statbel):,} comunas | VEKA: {len(veka):,} comunas")

    for fp in ficheros:
        rows = [json.loads(linea) for linea in fp.open(encoding="utf-8")]
        con_ctx = 0
        for r in rows:
            nis = r.get("parcel_niscode")
            ctx = statbel.get(nis or "", {})
            r.update(ctx or {k: None for k in
                             ("nis_total_edificios", "nis_pct_pre1946",
                              "nis_pct_post1981", "nis_pct_calefaccion",
                              "nis_viviendas")})
            r["nis_epeil_medio"] = veka.get(nis or "")
            if ctx:
                con_ctx += 1
        stem = fp.with_name(fp.stem + "_ctx")
        with stem.with_suffix(".jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        ejemplo = next((r for r in rows if r.get("nis_total_edificios")), {})
        print(f"{fp.name}: {con_ctx:,}/{len(rows):,} edificios con contexto comunal "
              f"→ {stem.name}.csv|.jsonl")
        if ejemplo:
            print(f"   comuna NIS {ejemplo.get('parcel_niscode')}: "
                  f"{ejemplo.get('nis_total_edificios'):,} edificios, "
                  f"{ejemplo.get('nis_pct_pre1946')}% pre-1946, "
                  f"{ejemplo.get('nis_pct_calefaccion')}% con calefacción central"
                  + (f", e-peil medio {ejemplo['nis_epeil_medio']}"
                     if ejemplo.get("nis_epeil_medio") else ""))


if __name__ == "__main__":
    main()
