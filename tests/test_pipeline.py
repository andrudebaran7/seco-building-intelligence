"""Tests de las funciones puras del pipeline (sin red ni modelos).

Cubren: troceado del corpus, parseo de informes (las 3 maquetaciones),
derivación de señales de riesgo, normalización del riesgo de arcillas,
bbox métrico de la ortofoto y geometría point-in-polygon.
"""

from extraer_informes import parsear_informe
from informe_edificio import derivar_senales
from ingest_be_geo import centroid, point_in_feature
from ingest_georisques import EXPOSITION_MAP, NOT_EXPOSED
from ingest_lu_ortho import bbox_metros
from rag_aqc import CHUNK_CHARS, OVERLAP_CHARS, chunk_text


# ------------------------------------------------------------- chunking

def test_chunk_text_respeta_tamano_y_solape():
    parrafos = [f"Párrafo {i} " + "palabra " * 60 for i in range(20)]
    chunks = chunk_text("\n\n".join(parrafos))
    assert len(chunks) > 1
    # ningún fragmento supera el objetivo + solape + un párrafo de margen
    assert all(len(c) <= CHUNK_CHARS + OVERLAP_CHARS + 600 for c in chunks)
    # el solape existe: el final de un chunk reaparece al inicio del siguiente
    cola = chunks[0][-50:]
    assert cola in chunks[1]


def test_chunk_text_no_pierde_contenido():
    texto = "\n\n".join(f"bloque{i}" for i in range(50))
    junto = " ".join(chunk_text(texto))
    assert all(f"bloque{i}" in junto for i in range(50))


# ------------------------------------------------- parseo de informes

PIE = "\nLe présent rapport est établi à des fins de démonstration."

PLANTILLA_1 = """RAPPORT D'INSPECTION TECHNIQUE
Référence : TIS-2026-1234
Date de visite : 2026-03-15
Inspecteur : M. Lambert
Adresse du bien : 4 Rue Saint-Jean 33800 Bordeaux
Type : immeuble - Construction : avant 1948

OBSERVATIONS
Observation 1 - Localisation : pignon nord - Gravité : majeure
Fissuration en escalier visible sur le pignon.
Observation 2 - Localisation : cave - Gravité : mineure
Traces d'humidité en partie basse des murs.
""" + PIE

PLANTILLA_2 = """COMPTE RENDU DE VISITE - CONTRÔLE TECHNIQUE
Dossier n° TIS-2026-2002 | Visite du 2026-01-20 | Établi par Mme Petit
Bien inspecté : 9 Rue Constant 33110 Le Bouscat (appartement, 2005)

DÉSORDRES CONSTATÉS
1. [MOYENNE] balcon du 2e étage
Éclats de béton laissant apparaître des aciers corrodés.
""" + PIE

PLANTILLA_3 = """FICHE D'INSPECTION
Réf. : TIS-2026-3003   Date : 2026-02-02
Adresse : 12 Avenue Foch 75016 Paris
Contrôleur : M. Da Silva
Typologie : appartement / 1960

POINTS RELEVÉS
Point 1 (salle de bains) - niveau de gravité : moyenne
Moisissures noires aux angles des plafonds.
""" + PIE


def test_parseo_plantilla_1():
    m = parsear_informe(PLANTILLA_1)
    assert m["ref"] == "TIS-2026-1234"
    assert m["fecha"] == "2026-03-15"
    assert m["inspecteur"] == "M. Lambert"
    assert m["adresse"] == "4 Rue Saint-Jean 33800 Bordeaux"
    assert len(m["defectos"]) == 2
    assert m["defectos"][0]["localisation"] == "pignon nord"
    assert m["defectos"][0]["gravite"] == "majeure"
    assert "escalier" in m["defectos"][0]["descripcion"]
    assert m["defectos"][1]["gravite"] == "mineure"


def test_parseo_plantilla_2():
    m = parsear_informe(PLANTILLA_2)
    assert m["ref"] == "TIS-2026-2002"
    assert m["inspecteur"] == "Mme Petit"
    assert m["adresse"] == "9 Rue Constant 33110 Le Bouscat"
    assert m["defectos"][0]["gravite"] == "moyenne"
    assert m["defectos"][0]["localisation"] == "balcon du 2e étage"


def test_parseo_plantilla_3():
    m = parsear_informe(PLANTILLA_3)
    assert m["ref"] == "TIS-2026-3003"
    assert m["inspecteur"] == "M. Da Silva"
    assert m["defectos"][0]["localisation"] == "salle de bains"
    assert "Moisissures" in m["defectos"][0]["descripcion"]


# ------------------------------------------------- señales de riesgo

def test_derivar_senales_edificio_de_riesgo():
    b = {"alea_argiles_final": "Fort", "alea_argiles_source": "BDNB",
         "etiquette_dpe": "F", "bdnb_mat_mur": "PIERRE",
         "bdnb_mat_toit": "TUILES", "periode_construction": "avant 1948"}
    senales = derivar_senales(b)
    assert len(senales) == 5
    assert all("query" in s and s["query"] for s in senales)


def test_derivar_senales_edificio_sin_riesgo():
    b = {"alea_argiles_final": "Non exposé", "etiquette_dpe": "B",
         "bdnb_mat_mur": "BETON", "bdnb_mat_toit": None,
         "periode_construction": "2001-2010"}
    assert derivar_senales(b) == []


# -------------------------------------------------- normalización RGA

def test_vocabulario_arcillas_normalizado():
    assert EXPOSITION_MAP["Exposition forte"] == "Fort"
    assert EXPOSITION_MAP["Exposition moyenne"] == "Moyen"
    assert EXPOSITION_MAP["Exposition faible"] == "Faible"
    assert NOT_EXPOSED == "Non exposé"


# ---------------------------------------------------- bbox ortofoto

def test_bbox_metros_orden_y_tamano():
    bbox = bbox_metros(6.13, 49.61, 20)
    lat_min, lon_min, lat_max, lon_max = map(float, bbox.split(","))
    assert lat_min < 49.61 < lat_max and lon_min < 6.13 < lon_max
    # 40 m de lado ≈ 0.00036° de latitud
    assert abs((lat_max - lat_min) * 111320 - 40) < 0.5


# ------------------------------------------------- point-in-polygon

CUADRADO = {"geometry": {"type": "Polygon", "coordinates": [
    [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}}


def test_point_in_feature():
    assert point_in_feature(5, 5, CUADRADO)
    assert not point_in_feature(15, 5, CUADRADO)
    assert not point_in_feature(-1, -1, CUADRADO)


def test_centroid_cuadrado():
    lon, lat = centroid(CUADRADO)
    assert abs(lon - 4) < 2.1 and abs(lat - 4) < 2.1  # media de vértices
