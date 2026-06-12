#!/usr/bin/env python3
"""Chequeo de salud de todas las fuentes de datos del proyecto.

Hace una petición mínima a cada endpoint y valida la FORMA de la respuesta
(no solo el código HTTP): que el JSON tenga los campos esperados, que el
WFS devuelva features, que el WMS devuelva un JPEG, que el CSV tenga la
cabecera correcta… Convierte el "verificado en vivo el 2026-06-11" de la
documentación en algo re-ejecutable: `make health`.

Las APIs públicas cambian sin avisar (este proyecto ya encontró un
GeoServer migrado y un portal tras WAF); este script detecta esas roturas
en minutos en lugar de a mitad de una ingesta.

Uso:
    python3 verificar_fuentes.py        (exit 0 = todo sano, 1 = hay caídas)
"""

import sys
import time
import urllib.request

from red import UA_DEFECTO, http_get, http_json

UA_NAV = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
                        "Gecko/20100101 Firefox/128.0"}


def peek(url: str, n: int = 200, headers: dict | None = None) -> bytes:
    """Lee solo los primeros bytes (para ficheros grandes)."""
    h = {"User-Agent": UA_DEFECTO}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(n)


def chk_ademe():
    d = http_json("https://data.ademe.fr/data-fair/api/v1/datasets/"
                  "dpe03existant/lines?size=1&select=numero_dpe")
    assert d["total"] > 1_000_000 and d["results"][0].get("numero_dpe")
    return f"{d['total']:,} DPE disponibles"


def chk_rnb():
    d = http_json("https://rnb-api.beta.gouv.fr/api/alpha/buildings/MJ8ZTZ38EJSZ/")
    assert d["rnb_id"] == "MJ8ZTZ38EJSZ" and d["point"]["coordinates"]
    return f"edificio de control OK ({d['status']})"


def chk_bdnb():
    d = http_json("https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe?limit=1")
    assert d and d[0].get("batiment_groupe_id")
    return "tabla batiment_groupe responde"


def chk_georisques():
    d = http_json("https://www.georisques.gouv.fr/api/v1/rga"
                  "?latlon=-0.504388,44.902904")
    assert "exposition" in d
    return f"punto de control: {d['exposition']}"


def chk_geoportail_lu():
    d = http_json("https://wms.inspire.geoportail.lu/geoserver/wfs?service=WFS"
                  "&version=2.0.0&request=GetFeature&typeNames=bu:BU.Building"
                  "&bbox=49.610,6.125,49.611,6.127,urn:ogc:def:crs:EPSG::4326"
                  "&outputFormat=application/json&count=1")
    assert d["features"]
    return "WFS INSPIRE sirve edificios"


def chk_data_public_lu():
    d = http_json("https://data.public.lu/api/1/datasets/"
                  "base-de-donnees-nationale-des-batiments-3d-2023/")
    assert len(d.get("resources", [])) > 50
    return f"{len(d['resources'])} recursos en el dataset 3D"


def chk_wms_ortho():
    img = http_get("https://wms.geoportail.lu/opendata/service?service=WMS"
                   "&version=1.3.0&request=GetMap&layers=ortho_2025"
                   "&crs=EPSG:4326&bbox=49.61,6.12,49.6105,6.1205"
                   "&width=50&height=50&format=image/jpeg&styles=")
    assert img.startswith(b"\xff\xd8")
    return f"GetMap devuelve JPEG ({len(img)} bytes)"


def chk_aqc():
    d = http_json("https://qualiteconstruction.com/wp-json/wp/v2/media"
                  "?search=Fiche-Pathologie&per_page=1", headers=UA_NAV)
    assert d and d[0].get("source_url")
    return "API WordPress lista fichas"


def chk_itm():
    html = http_get("https://itm.public.lu/fr/securite-sante-travail/"
                    "etablissements-classes/conditions-types.html",
                    headers=UA_NAV).decode("utf-8", errors="replace")
    n = html.count("conditions-types/")
    assert n > 100
    return f"{n} enlaces a prescripciones"


def chk_urbis():
    d = http_json("https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs"
                  "?service=WFS&version=2.0.0&request=GetFeature"
                  "&typeNames=urbisvector:Buildings"
                  "&bbox=50.845,4.348,50.846,4.350,urn:ogc:def:crs:EPSG::4326"
                  "&outputFormat=application/json&count=1", headers=UA_NAV)
    assert d["features"]
    return "UrbIS sirve edificios"


def chk_grb():
    d = http_json("https://geo.api.vlaanderen.be/GRB/wfs?service=WFS"
                  "&version=2.0.0&request=GetFeature&typeNames=GRB:GBG"
                  "&bbox=51.217,4.398,51.218,4.400,urn:ogc:def:crs:EPSG::4326"
                  "&outputFormat=application/json&count=1")
    assert d["features"]
    return "GRB sirve edificios"


def chk_picc():
    d = http_json("https://geoservices.wallonie.be/arcgis/rest/services/"
                  "TOPOGRAPHIE/PICC_VDIFF/MapServer/11/query"
                  "?geometry=5.570,50.640,5.572,50.642"
                  "&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326"
                  "&where=1%3D1&outFields=GEOREF_ID&f=geojson&resultRecordCount=1")
    assert d["features"]
    return "PICC sirve edificios"


def chk_cadastre_federal():
    d = http_json("https://ccff02.minfin.fgov.be/geoservices/arcgis/rest/services/"
                  "INSPIRE/CP/MapServer/1/query?geometry=5.570,50.640,5.572,50.642"
                  "&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326"
                  "&where=1%3D1&outFields=nationalCadastralRef&f=geojson"
                  "&resultRecordCount=1")
    assert d["features"][0]["properties"].get("nationalCadastralRef")
    return "catastro federal sirve CAPAKEY"


def chk_veka():
    head = peek("https://open-data.energiesparen.be/Data/"
                "02_GEMIDDELD_E_PEIL_PER_GEMEENTE.csv", headers=UA_NAV)
    assert b"NIS_CODE" in head
    return "CSV con cabecera esperada"


def chk_statbel():
    head = peek("https://statbel.fgov.be/sites/default/files/files/opendata/"
                "Buildstock/building_stock_open_data_2023.zip",
                headers=UA_NAV, n=4)
    assert head[:2] == b"PK"  # firma zip
    return "zip del parque catastral accesible"


def chk_mendeley():
    d = http_json("https://data.mendeley.com/public-api/datasets/"
                  "5y9wdsg2zt/files?folder_id=root&version=2", headers=UA_NAV)
    assert d[0]["content_details"]["download_url"]
    return "dataset METU descargable"


CHECKS = [
    ("ADEME DPE (FR)", chk_ademe),
    ("RNB (FR)", chk_rnb),
    ("BDNB (FR)", chk_bdnb),
    ("Géorisques RGA (FR)", chk_georisques),
    ("geoportail.lu WFS (LU)", chk_geoportail_lu),
    ("data.public.lu (LU)", chk_data_public_lu),
    ("WMS ortofoto (LU)", chk_wms_ortho),
    ("AQC WordPress (corpus)", chk_aqc),
    ("ITM conditions-types (LU)", chk_itm),
    ("UrbIS WFS (BE)", chk_urbis),
    ("GRB WFS (BE)", chk_grb),
    ("PICC ArcGIS (BE)", chk_picc),
    ("Catastro federal (BE)", chk_cadastre_federal),
    ("VEKA (BE)", chk_veka),
    ("Statbel (BE)", chk_statbel),
    ("Mendeley/METU (CV)", chk_mendeley),
]


def main() -> None:
    caidas = 0
    for nombre, fn in CHECKS:
        t0 = time.monotonic()
        try:
            detalle = fn()
            ms = (time.monotonic() - t0) * 1000
            print(f" ✓ {nombre:<28} {ms:6.0f} ms — {detalle}")
        except Exception as e:  # noqa: BLE001 — reportar cualquier rotura
            ms = (time.monotonic() - t0) * 1000
            print(f" ✗ {nombre:<28} {ms:6.0f} ms — {type(e).__name__}: {e}")
            caidas += 1
    print()
    if caidas:
        print(f"{caidas}/{len(CHECKS)} fuentes con problemas")
        sys.exit(1)
    print(f"Las {len(CHECKS)} fuentes responden con la forma esperada.")


if __name__ == "__main__":
    main()
