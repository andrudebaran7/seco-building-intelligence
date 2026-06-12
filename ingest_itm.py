#!/usr/bin/env python3
"""Ingestión de prueba: prescripciones ITM (Luxemburgo) — corpus normativo.

Descarga las "conditions types" ITM-SST de la Inspection du Travail et des
Mines de Luxemburgo: prescripciones de seguridad de cumplimiento obligatorio
para établissements classés. Por defecto se ingiere la serie de edificación
e incendio (carpeta itm-cl-1100-2000: bâtiments bas/élevés, parkings,
désenfumage, ascensores…), en francés y alemán cuando hay versión.

Los PDFs se listan parseando la página de conditions-types (HTML estable,
sin API) y se descargan directamente. Texto extraído con pdftotext -layout.
Manifiesto con el mismo esquema que el corpus AQC + campos fuente/idioma.

Fuente: https://itm.public.lu (Estado luxemburgués). Consulta/descarga libre
según los términos del portal estatal; citar ITM como fuente.

Uso:
    python3 ingest_itm.py                      # serie edificación (1100-2000)
    python3 ingest_itm.py --series itm-cl-1100-2000 itm-cl-2001-3000
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

from red import http_get as red_http_get

LISTADO = ("https://itm.public.lu/fr/securite-sante-travail/"
           "etablissements-classes/conditions-types.html")
UA = "Mozilla/5.0 (compatible; ingest-test/0.1)"
SLEEP_BETWEEN_CALLS = 0.3
SERIES_DEFECTO = ["itm-cl-1100-2000"]  # edificación e incendio

RE_PDF = re.compile(r'href="(https://itm\.public\.lu/[^"]+/conditions-types/+'
                    r'(itm-cl-[\d-]+)/([^"/]+\.pdf))"', re.IGNORECASE)


def http_get(url: str) -> bytes:
    return red_http_get(url, headers={"User-Agent": UA}, timeout=120)


def listar_pdfs(series: list[str]) -> list[dict]:
    html = http_get(LISTADO).decode("utf-8", errors="replace")
    vistos, docs = set(), []
    for m in RE_PDF.finditer(html):
        url, serie, fichero = m.group(1), m.group(2), m.group(3)
        if serie not in series or url in vistos:
            continue
        vistos.add(url)
        # ITM-SST-1501-1.pdf -> code "ITM-SST 1501.1"; sufijo -de = alemán
        base = fichero[:-4]
        lang = "fr"
        for suf, idioma in (("-de", "de"), ("-en", "en")):
            if base.lower().endswith(suf):
                base, lang = base[: -len(suf)], idioma
        mm = re.match(r"(?i)itm-(sst|cl)-(\d+)-(\d+)$", base)
        code = (f"ITM-{mm.group(1).upper()} {mm.group(2)}.{mm.group(3)}"
                if mm else base.upper())
        docs.append({"code": code, "lang": lang, "serie": serie,
                     "fichero": fichero, "url": url})
    return docs


RUIDO_TITULO = re.compile(
    r"(?i)(grand-duch|strassen|le présent (texte|document)|inspection du travail"
    r"|service incendie|page|sommaire|itm-(sst|cl)|^\d+\s*$|comporte \d+ pages"
    r"|großherzogtum|das vorliegende)")


def titulo_desde_texto(txt_path: Path, code: str) -> str:
    """Título = líneas de asunto de la cabecera, saltando el membrete."""
    lineas = [linea.strip() for linea in
              txt_path.read_text(encoding="utf-8", errors="replace").splitlines()]
    utiles = [linea for linea in lineas[:25]
              if len(linea) > 8 and not RUIDO_TITULO.search(linea)]
    return " — ".join(dict.fromkeys(utiles[:3]))[:160] or code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", nargs="+", default=SERIES_DEFECTO,
                        help=f"carpetas de la web ITM (por defecto {SERIES_DEFECTO})")
    parser.add_argument("--out", default="corpus/itm", help="directorio del corpus")
    parser.add_argument("--skip-text", action="store_true")
    args = parser.parse_args()

    pdf_dir = Path(args.out) / "pdf"
    txt_dir = Path(args.out) / "txt"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    try:
        docs = listar_pdfs(args.series)
    except urllib.error.URLError as e:
        sys.exit(f"Error de red contra itm.public.lu: {e}")
    print(f"Prescripciones encontradas en {args.series}: {len(docs)}")

    extraer = not args.skip_text
    fallos = 0
    for i, d in enumerate(docs, 1):
        pdf_path = pdf_dir / d["fichero"]
        if not pdf_path.exists():
            try:
                pdf_path.write_bytes(http_get(d["url"]))
            except Exception as e:
                print(f"\n  aviso: fallo descargando {d['fichero']}: {e}")
                fallos += 1
                continue
            time.sleep(SLEEP_BETWEEN_CALLS)
        d["pdf"] = str(pdf_path)
        if extraer:
            txt_path = txt_dir / (pdf_path.stem + ".txt")
            if not txt_path.exists():
                subprocess.run(["pdftotext", "-layout", str(pdf_path), str(txt_path)],
                               capture_output=True)
            if txt_path.exists():
                d["txt"] = str(txt_path)
                d["titulo"] = f"{d['code']} — {titulo_desde_texto(txt_path, d['code'])}"
                d["n_caracteres"] = len(txt_path.read_text(encoding="utf-8",
                                                           errors="replace"))
        d.setdefault("titulo", d["code"])
        print(f"  procesadas {i}/{len(docs)}", end="\r", flush=True)
    print()

    docs = [d for d in docs if d.get("pdf")]
    with (Path(args.out) / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with (Path(args.out) / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(docs[0].keys()))
        writer.writeheader()
        writer.writerows(docs)

    por_lang = {}
    for d in docs:
        por_lang[d["lang"]] = por_lang.get(d["lang"], 0) + 1
    print(f"Corpus ITM: {len(docs)} documentos ({por_lang}) — fallos: {fallos}")
    print(f"Manifiesto: {args.out}/manifest.csv|.jsonl")


if __name__ == "__main__":
    main()
