#!/usr/bin/env python3
"""Ingestión de prueba: capas geoespaciales belgas — UrbIS (Bruselas) y GRB (Flandes).

Misma técnica que en Luxemburgo: descarga edificios y parcelas (y direcciones
en Bruselas) por bounding box vía WFS en GeoJSON, y los cruza espacialmente
(point-in-polygon) para componer una tabla por edificio con su parcela
catastral (CAPAKEY, la clave catastral nacional belga).

Fuentes:
  - Bruselas: UrbIS, https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs
    (Paradigm). Licencia CC0 (parcelas: SPF Finances). Sin registro.
  - Flandes: GRB, https://geo.api.vlaanderen.be/GRB/wfs (Digitaal Vlaanderen).
    "Gratis Open Data Licentie Vlaanderen" — el WFS funciona SIN la cuenta
    que sí exige la descarga masiva. Atribución requerida.

Uso:
    python3 ingest_be_geo.py --region bruselas                    # Grand-Place
    python3 ingest_be_geo.py --region flandes --bbox 51.05,3.71,51.06,3.74 --zona gent
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PAGE = 1000
SLEEP_BETWEEN_CALLS = 0.3
UA = "Mozilla/5.0 (compatible; ingest-test/0.1)"

REGIONS = {
    "bruselas": {
        "wfs": "https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs",
        "capas": {
            "buildings": "urbisvector:Buildings",
            "addresses": "urbisvector:Addresses",
            "parcels": "urbisvector:CadastralParcels",
        },
        "bbox_defecto": "50.843,4.345,50.850,4.360",   # Grand-Place y alrededores
        "zona_defecto": "bruxelles_centre",
        "atribucion": "UrbIS (c) Paradigm / CC0",
    },
    "flandes": {
        "wfs": "https://geo.api.vlaanderen.be/GRB/wfs",
        "capas": {
            "buildings": "GRB:GBG",
            "parcels": "GRB:ADP",
        },
        "bbox_defecto": "51.215,4.395,51.222,4.410",   # centro de Amberes
        "zona_defecto": "antwerpen_centrum",
        "atribucion": "Bron: Grootschalig Referentie Bestand Vlaanderen, Informatie Vlaanderen",
    },
}


def fetch_layer(wfs: str, type_name: str, bbox: str) -> list[dict]:
    """Descarga una capa completa por bbox, paginando con startIndex."""
    features: list[dict] = []
    start = 0
    while True:
        params = urllib.parse.urlencode({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": type_name,
            "bbox": f"{bbox},urn:ogc:def:crs:EPSG::4326",
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
            "count": str(PAGE),
            "startIndex": str(start),
        })
        req = urllib.request.Request(f"{wfs}?{params}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            page = json.load(resp)
        feats = page.get("features", [])
        features.extend(feats)
        time.sleep(SLEEP_BETWEEN_CALLS)
        if len(feats) < PAGE:
            break
        start += PAGE
    return features


# --- geometría (idéntico criterio que ingest_geoportail_lu.py) ---------------

def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def outer_rings(geometry: dict) -> list[list]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def point_in_feature(lon: float, lat: float, feature: dict) -> bool:
    return any(point_in_ring(lon, lat, r) for r in outer_rings(feature["geometry"]))


def centroid(feature: dict) -> tuple[float, float]:
    ring = outer_rings(feature["geometry"])[0]
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def first_point(geometry: dict) -> tuple[float, float]:
    c = geometry["coordinates"]
    return tuple(c[0][:2]) if geometry["type"] == "MultiPoint" else tuple(c[:2])


# --- extracción de atributos por región --------------------------------------

def building_id(region: str, props: dict) -> str:
    if region == "bruselas":
        return (props.get("INSPIRE_ID") or "").rsplit("/", 1)[-1]
    return str(props.get("OIDN"))


def parcel_info(props: dict) -> dict:
    return {
        "parcel_capakey": props.get("CAPAKEY"),
        "parcel_niscode": str(props.get("MUNNISCODE") or props.get("NISCODE") or "")
                          .rsplit("/", 1)[-1] or None,
    }


def address_text(props: dict) -> str:
    calle = props.get("STRNAMEFRE") or props.get("STRNAMEDUT") or ""
    return f"{calle} {props.get('POLICENUM') or ''}, {props.get('ZIPCODE') or ''} " \
           f"{props.get('MUNNAMEFRE') or ''}".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--region", choices=REGIONS, required=True)
    parser.add_argument("--bbox", help="lat_min,lon_min,lat_max,lon_max")
    parser.add_argument("--zona", help="etiqueta para los nombres de fichero")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    args = parser.parse_args()

    cfg = REGIONS[args.region]
    bbox = args.bbox or cfg["bbox_defecto"]
    zona = args.zona or cfg["zona_defecto"]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    layers: dict[str, list[dict]] = {}
    for name, type_name in cfg["capas"].items():
        try:
            layers[name] = fetch_layer(cfg["wfs"], type_name, bbox)
        except urllib.error.URLError as e:
            sys.exit(f"Error de red contra el WFS de {args.region} ({name}): {e}")
        print(f"Descargados {len(layers[name]):,} {name}")
        path = out_dir / f"be_{args.region}_{zona}_{name}.geojson"
        with path.open("w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": layers[name]}, f,
                      ensure_ascii=False)
        print(f"  guardado: {path}")

    # Cruce 1 (solo Bruselas): direcciones dentro de cada edificio.
    addr_by_building: dict[int, list[dict]] = {}
    if "addresses" in layers:
        print("Cruzando direcciones con edificios (point-in-polygon)...")
        for addr in layers["addresses"]:
            lon, lat = first_point(addr["geometry"])
            for i, b in enumerate(layers["buildings"]):
                if point_in_feature(lon, lat, b):
                    addr_by_building.setdefault(i, []).append(addr)
                    break

    # Cruce 2: centroide del edificio dentro de una parcela.
    print("Cruzando edificios con parcelas...")
    rows = []
    for i, b in enumerate(layers["buildings"]):
        lon, lat = centroid(b)
        parcel = next((p for p in layers["parcels"] if point_in_feature(lon, lat, p)), None)
        addrs = addr_by_building.get(i, [])
        row = {
            "building_id": building_id(args.region, b["properties"]),
            "lon": round(lon, 7),
            "lat": round(lat, 7),
            "area_m2": b["properties"].get("AREA"),
            "tipo": b["properties"].get("LBLTYPE"),
        }
        if "addresses" in layers:
            row["n_addresses"] = len(addrs)
            row["adresse_ejemplo"] = address_text(addrs[0]["properties"]) if addrs else None
        row.update(parcel_info(parcel["properties"]) if parcel else
                   {"parcel_capakey": None, "parcel_niscode": None})
        rows.append(row)

    stem = out_dir / f"be_{args.region}_{zona}_batiments"
    with stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with stem.with_suffix(".jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Guardado: {stem}.csv y {stem}.jsonl")

    con_par = sum(1 for r in rows if r["parcel_capakey"])
    print(f"\nResumen de {len(rows):,} edificios en bbox {bbox} ({args.region}):")
    print(f"  con parcela catastral (CAPAKEY): {con_par:,} ({100 * con_par / len(rows):.0f}%)")
    if "addresses" in layers:
        con_dir = sum(1 for r in rows if r["n_addresses"])
        print(f"  con dirección asociada: {con_dir:,} ({100 * con_dir / len(rows):.0f}%)")
    print(f"  atribución requerida: {cfg['atribucion']}")


if __name__ == "__main__":
    main()
