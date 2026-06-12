#!/usr/bin/env python3
"""Ingestión de prueba: WFS INSPIRE de geoportail.lu (Luxemburgo).

Luxemburgo no publica equivalentes abiertos al DPE/RNB/BDNB franceses, así
que aquí la cadena es geoespacial pura: se descargan edificios, direcciones
y parcelas catastrales por bounding box y se cruzan espacialmente
(dirección dentro de edificio, centroide de edificio dentro de parcela)
para componer una "carta de identidad" básica por edificio.

Fuente: https://wms.inspire.geoportail.lu/geoserver/wfs (ACT). Licencia CC0.

Capas: bu:BU.Building (2D, base nacional 2023), ad:AD_Address (puntos),
cp:CP.CadastralParcel (polígonos con superficie y referencia catastral).

Uso:
    python3 ingest_geoportail_lu.py                     # centro de Luxembourg-Ville
    python3 ingest_geoportail_lu.py --bbox 49.86,6.08,49.88,6.11   # Diekirch
"""

import argparse
import csv
import json
import sys
import time
import urllib.parse
from pathlib import Path

from red import http_json

WFS_URL = "https://wms.inspire.geoportail.lu/geoserver/wfs"
PAGE = 1000
SLEEP_BETWEEN_CALLS = 0.3

LAYERS = {
    "buildings": "bu:BU.Building",
    "addresses": "ad:AD_Address",
    "parcels": "cp:CP.CadastralParcel",
}

# Centro de Luxembourg-Ville (lat_min, lon_min, lat_max, lon_max).
DEFAULT_BBOX = "49.608,6.122,49.615,6.135"


def fetch_layer(type_name: str, bbox: str) -> list[dict]:
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
        page = http_json(f"{WFS_URL}?{params}", timeout=120)
        feats = page.get("features", [])
        features.extend(feats)
        time.sleep(SLEEP_BETWEEN_CALLS)
        if len(feats) < PAGE:
            break
        start += PAGE
    return features


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray casting sobre el anillo exterior de un polígono."""
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
    """Anillos exteriores de un Polygon o MultiPolygon."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def point_in_feature(lon: float, lat: float, feature: dict) -> bool:
    return any(point_in_ring(lon, lat, r) for r in outer_rings(feature["geometry"]))


def centroid(feature: dict) -> tuple[float, float]:
    """Centroide simple (media de vértices del primer anillo exterior)."""
    ring = outer_rings(feature["geometry"])[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return sum(lons) / len(lons), sum(lats) / len(lats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bbox", default=DEFAULT_BBOX,
                        help=f"lat_min,lon_min,lat_max,lon_max (por defecto {DEFAULT_BBOX})")
    parser.add_argument("--out", default="data", help="directorio de salida (por defecto ./data)")
    parser.add_argument("--zona", default="luxembourg_ville",
                        help="etiqueta para los nombres de fichero (por defecto luxembourg_ville)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    layers: dict[str, list[dict]] = {}
    for name, type_name in LAYERS.items():
        try:
            layers[name] = fetch_layer(type_name, args.bbox)
        except urllib.error.URLError as e:
            sys.exit(f"Error de red contra el WFS de geoportail.lu ({name}): {e}")
        print(f"Descargados {len(layers[name]):,} {name}")
        geojson_path = out_dir / f"lu_{args.zona}_{name}.geojson"
        with geojson_path.open("w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": layers[name]}, f,
                      ensure_ascii=False)
        print(f"  guardado: {geojson_path}")

    # Cruce espacial 1: direcciones (puntos) dentro de cada edificio.
    print("Cruzando direcciones con edificios (point-in-polygon)...")
    addr_by_building: dict[int, list[dict]] = {}
    for addr in layers["addresses"]:
        lon, lat = addr["geometry"]["coordinates"][:2]
        for i, b in enumerate(layers["buildings"]):
            if point_in_feature(lon, lat, b):
                addr_by_building.setdefault(i, []).append(addr)
                break

    # Cruce espacial 2: centroide del edificio dentro de una parcela.
    print("Cruzando edificios con parcelas...")
    rows = []
    for i, b in enumerate(layers["buildings"]):
        lon, lat = centroid(b)
        parcel = next((p for p in layers["parcels"] if point_in_feature(lon, lat, p)), None)
        addrs = addr_by_building.get(i, [])
        rows.append({
            "building_id": b["properties"].get("inspireid_identifier_localid"),
            "lon": round(lon, 7),
            "lat": round(lat, 7),
            "n_addresses": len(addrs),
            "adresse_ejemplo": (addrs[0]["properties"].get("gml_description") if addrs else None),
            "parcel_ref": (parcel["properties"].get("national_cadastral_reference") if parcel else None),
            "parcel_label": (parcel["properties"].get("label") if parcel else None),
            "parcel_area_m2": (parcel["properties"].get("area") if parcel else None),
        })

    csv_path = out_dir / f"lu_{args.zona}_batiments.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    jsonl_path = out_dir / f"lu_{args.zona}_batiments.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Guardado: {csv_path} y {jsonl_path}")

    con_dir = sum(1 for r in rows if r["n_addresses"])
    con_par = sum(1 for r in rows if r["parcel_ref"])
    print(f"\nResumen de {len(rows):,} edificios en bbox {args.bbox}:")
    print(f"  con dirección asociada: {con_dir:,} ({100 * con_dir / len(rows):.0f}%)")
    print(f"  con parcela catastral:  {con_par:,} ({100 * con_par / len(rows):.0f}%)")


if __name__ == "__main__":
    main()
