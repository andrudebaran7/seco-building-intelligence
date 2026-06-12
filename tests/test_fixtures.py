"""Tests sobre formas reales de respuesta de las APIs (fixtures grabadas).

Sin red: las respuestas están grabadas (tests/fixtures/) o reproducidas con
la forma exacta observada en cada fuente. Cubren los parsers/normalizadores
de cada cadena y la política de reintentos del helper HTTP.
"""

import json
import urllib.error
from pathlib import Path

import pytest

import red
from evaluar_retrieval import es_acierto
from informe_edificio import T_SENAL, T
from ingest_be_geo import building_id, parcel_info
from ingest_be_stats import cargar_statbel, cargar_veka
from ingest_itm import RE_PDF, titulo_desde_texto
from ingest_rnb import cle_ban_completa, flatten

FIXTURES = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------ RNB

def test_flatten_edificio_rnb_real():
    b = json.loads((FIXTURES / "rnb_building.json").read_text(encoding="utf-8"))
    f = flatten(b)
    assert f["rnb_status"] == "constructed"
    assert 2.29 < f["rnb_lon"] < 2.30 and 48.84 < f["rnb_lat"] < 48.85
    assert f["rnb_insee_code"] == "75115"
    assert f["rnb_n_addresses"] == 2


def test_flatten_tolera_edificio_sin_direcciones():
    f = flatten({"status": "demolished", "point": None, "addresses": None})
    assert f["rnb_status"] == "demolished"
    assert f["rnb_lon"] is None and f["rnb_insee_code"] is None


def test_cle_ban_completa():
    assert cle_ban_completa("33249_0271_00001")        # comuna_calle_número
    assert not cle_ban_completa("33281_6kzvfu")        # solo calle
    assert not cle_ban_completa("")
    assert not cle_ban_completa(None)


# ------------------------------------------------------------ Bélgica

URBIS_PARCEL = {"CAPAKEY": "21802B1102/00A003", "TYPE": "PR",
                "MUNNISCODE": "https://databrussels.be/id/municipality/21004"}
GRB_PARCEL = {"CAPAKEY": "11804D0567/00B000", "NISCODE": "11002"}
FEDERAL_PARCEL = {"label": "980C", "nationalCadastralRef": "62063A0980/00C000"}


def test_parcel_info_urbis_niscode_desde_url():
    p = parcel_info(URBIS_PARCEL)
    assert p["parcel_capakey"] == "21802B1102/00A003"
    assert p["parcel_niscode"] == "21004"   # extraído del final de la URL


def test_parcel_info_grb_directo():
    assert parcel_info(GRB_PARCEL) == {"parcel_capakey": "11804D0567/00B000",
                                       "parcel_niscode": "11002"}


def test_parcel_info_federal_nis_desde_capakey():
    p = parcel_info(FEDERAL_PARCEL)
    assert p["parcel_capakey"] == "62063A0980/00C000"
    assert p["parcel_niscode"] == "62063"   # prefijo del CAPAKEY (división)


def test_building_id_por_region():
    assert building_id("bruselas",
                       {"INSPIRE_ID": "https://databrussels.be/id/building/1638842"}) == "1638842"
    assert building_id("flandes", {"OIDN": 4034312}) == "4034312"
    assert building_id("valonia",
                       {"GEOREF_ID": "BE.WL.GEOREF.11C1BB6D"}) == "11C1BB6D"


STATBEL_MUESTRA = """﻿CD_YEAR|CD_REFNIS|CD_REFNIS_NL|CD_REFNIS_FR|CD_REFNIS_LVL|CD_STAT_TYPE|CD_STAT_TYPE_NL|CD_STAT_TYPE_FR|CD_BUILDING_TYPE|CD_BUILDING_TYPE_NL|CD_BUILDING_TYPE_FR|MS_VALUE
2023|11002|ANTWERPEN|ANVERS|5|T1|x|x|R1|x|x|600
2023|11002|ANTWERPEN|ANVERS|5|T1|x|x|R4|x|x|400
2023|11002|ANTWERPEN|ANVERS|5|T3.1|x|x|R1|x|x|250
2023|11002|ANTWERPEN|ANVERS|5|T3.7|x|x|R1|x|x|100
2023|11002|ANTWERPEN|ANVERS|5|T5|x|x|R1|x|x|500
2023|11002|ANTWERPEN|ANVERS|5|T8|x|x|R1|x|x|1500
2023|01000|BELGIE|BELGIQUE|1|T1|x|x|R1|x|x|99999
"""

VEKA_MUESTRA = """﻿TIMESTAMP_EXTRACT,NIS_CODE,PROVINCIE,HOOFD_GEMEENTE,AANVRAAG_JAAR_VERGUNNING,BESTEMMING,GEMIDDELD_E_PEIL,AANTAL_INGEDIENDE_AG
2026-05-31,11002,Antwerpen,Antwerpen,2020,WONEN,60,10
2026-05-31,11002,Antwerpen,Antwerpen,2023,WONEN,30,30
2026-05-31,11002,Antwerpen,Antwerpen,2023,KANTOOR,99,5
"""


def test_statbel_agrega_por_nis_nivel_comuna(tmp_path, monkeypatch):
    f = tmp_path / "statbel.txt"
    f.write_text(STATBEL_MUESTRA, encoding="utf-8")
    monkeypatch.setattr("ingest_be_stats.STATBEL_TXT", f)
    ctx = cargar_statbel()
    assert set(ctx) == {"11002"}                     # el nivel 1 (país) se excluye
    c = ctx["11002"]
    assert c["nis_total_edificios"] == 1000          # suma R1+R4
    assert c["nis_pct_pre1946"] == 25.0              # 250/1000
    assert c["nis_pct_post1981"] == 10.0
    assert c["nis_pct_calefaccion"] == 50.0
    assert c["nis_viviendas"] == 1500


def test_veka_media_ponderada_solo_wonen(tmp_path, monkeypatch):
    f = tmp_path / "veka.csv"
    f.write_text(VEKA_MUESTRA, encoding="utf-8")
    monkeypatch.setattr("ingest_be_stats.VEKA_CSV", f)
    epeil = cargar_veka()
    # (60*10 + 30*30) / 40 = 37.5 — KANTOOR no cuenta
    assert epeil == {"11002": 37.5}


# ------------------------------------------------------------ ITM

ITM_HTML = '''<a href="https://itm.public.lu/dam-assets/fr/securite-sante/conditions-types/itm-cl-1100-2000/ITM-SST-1501-1.pdf">x</a>
<a href="https://itm.public.lu/dam-assets/fr/securite-sante/conditions-types/itm-cl-1100-2000/ITM-SST-1106-2-de.pdf">x</a>
<a href="https://itm.public.lu/dam-assets/fr/securite-sante/conditions-types/itm-cl-1-100/ITM-CL-005-1.pdf">x</a>'''


def test_regex_pdfs_itm_extrae_serie_y_fichero():
    hits = [(m.group(2), m.group(3)) for m in RE_PDF.finditer(ITM_HTML)]
    assert ("itm-cl-1100-2000", "ITM-SST-1501-1.pdf") in hits
    assert ("itm-cl-1100-2000", "ITM-SST-1106-2-de.pdf") in hits
    assert ("itm-cl-1-100", "ITM-CL-005-1.pdf") in hits


def test_titulo_itm_salta_membrete(tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("""GRAND-DUCHE DE LUXEMBOURG
   Strassen, février 2009
   ITM-SST 1501.1
   Prescriptions de sécurité incendie
   Bâtiments bas
   Le présent document comporte 53 pages
""", encoding="utf-8")
    titulo = titulo_desde_texto(txt, "ITM-SST 1501.1")
    assert "Prescriptions de sécurité incendie" in titulo
    assert "GRAND-DUCHE" not in titulo and "Strassen" not in titulo


# ------------------------------------------------------------ retrieval / informes

def test_es_acierto_exacto_y_por_familia():
    assert es_acierto("A.02", ["A.01", "A.02"])
    assert not es_acierto("A.03", ["A.01", "A.02"])
    assert es_acierto("ITM-SST 1501.4", ["ITM-SST 1501"])   # familia
    assert not es_acierto("ITM-SST 1502.1", ["ITM-SST 1501"])


def test_traducciones_completas_en_los_tres_idiomas():
    idiomas = {"es", "en", "fr"}
    assert set(T) == idiomas and set(T_SENAL) == idiomas
    claves = {k for v in T.values() for k in v}
    assert all(set(v) == claves for v in T.values())
    claves_s = {k for v in T_SENAL.values() for k in v}
    assert all(set(v) == claves_s for v in T_SENAL.values())


# ------------------------------------------------------------ red.py (reintentos)

class _Resp:
    def __init__(self, body: bytes):
        self.body = body
    def read(self, *a):
        b, self.body = self.body, b""
        return b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_red_reintenta_5xx_y_acaba_bien(monkeypatch):
    intentos = []
    def fake_urlopen(req, timeout=None):
        intentos.append(1)
        if len(intentos) < 3:
            raise urllib.error.HTTPError(req.full_url, 503, "boom", None, None)
        return _Resp(b'{"ok": true}')
    monkeypatch.setattr(red.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(red.time, "sleep", lambda s: None)
    assert red.http_json("http://x/api") == {"ok": True}
    assert len(intentos) == 3


def test_red_no_reintenta_404(monkeypatch):
    intentos = []
    def fake_urlopen(req, timeout=None):
        intentos.append(1)
        raise urllib.error.HTTPError(req.full_url, 404, "no", None, None)
    monkeypatch.setattr(red.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        red.http_get("http://x/api")
    assert len(intentos) == 1   # sin reintentos para 4xx


def test_red_agota_reintentos_y_relanza(monkeypatch):
    intentos = []
    def fake_urlopen(req, timeout=None):
        intentos.append(1)
        raise urllib.error.URLError("caída")
    monkeypatch.setattr(red.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(red.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.URLError):
        red.http_get("http://x/api", reintentos=3)
    assert len(intentos) == 3
