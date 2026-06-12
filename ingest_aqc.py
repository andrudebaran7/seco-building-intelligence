#!/usr/bin/env python3
"""Ingestión de prueba: fichas de patología AQC — corpus para RAG.

Descarga las "Fiches Pathologie bâtiment" de la Agence Qualité Construction
usando la API REST de WordPress del propio sitio (sin scraping de HTML),
extrae el texto de cada PDF con pdftotext y genera un manifiesto estructurado
listo para indexar en un RAG.

Fuente: https://qualiteconstruction.com (AQC). Descarga libre; sin licencia
abierta explícita — uso como corpus interno, citar AQC como fuente.

Requiere: pdftotext (poppler-utils) para la extracción de texto.

Uso:
    python3 ingest_aqc.py                  # descarga todo el corpus
    python3 ingest_aqc.py --skip-text     # solo PDFs y manifiesto, sin texto
"""

import argparse
import csv
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

from red import http_get as red_http_get

WP_API = "https://qualiteconstruction.com/wp-json/wp/v2/media"
SEARCH = "Fiche-Pathologie"
PER_PAGE = 100
SLEEP_BETWEEN_CALLS = 0.5
UA = "Mozilla/5.0 (compatible; ingest-test/0.1)"

# Código de ficha en el nombre de fichero: ...-A02-..., ...-G13-...
CODE_RE = re.compile(r"-([A-G])(\d{1,2})-")


def http_get(url: str) -> bytes:
    return red_http_get(url, headers={"User-Agent": UA}, timeout=120)


def list_fiches() -> list[dict]:
    """Lista todos los PDFs de fichas vía la API WP, paginando."""
    fiches = []
    page = 1
    while True:
        url = f"{WP_API}?search={SEARCH}&per_page={PER_PAGE}&page={page}"
        try:
            items = json.loads(http_get(url))
        except urllib.error.HTTPError as e:
            if e.code == 400:  # página más allá del total
                break
            raise
        if not items:
            break
        for m in items:
            src = m.get("source_url", "")
            if not src.lower().endswith(".pdf"):
                continue  # la API devuelve también las miniaturas png
            title = html.unescape(re.sub(r"<[^>]+>", "", m.get("title", {}).get("rendered", "")))
            code_m = CODE_RE.search(src)
            fiches.append({
                "code": f"{code_m.group(1)}.{int(code_m.group(2)):02d}" if code_m else None,
                "tema": code_m.group(1) if code_m else None,
                "titulo": title.replace(" ", " ").strip(),
                "url": src,
                "fecha_publicacion": m.get("date", "")[:10],
            })
        page += 1
        time.sleep(SLEEP_BETWEEN_CALLS)
    # Deduplicar por URL conservando el orden.
    seen = set()
    return [f for f in fiches if not (f["url"] in seen or seen.add(f["url"]))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="corpus/aqc", help="directorio del corpus (por defecto corpus/aqc)")
    parser.add_argument("--skip-text", action="store_true", help="no extraer texto con pdftotext")
    args = parser.parse_args()

    pdf_dir = Path(args.out) / "pdf"
    txt_dir = Path(args.out) / "txt"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    try:
        fiches = list_fiches()
    except urllib.error.URLError as e:
        sys.exit(f"Error de red contra la API de qualiteconstruction.com: {e}")
    print(f"Fichas PDF encontradas vía API WordPress: {len(fiches):,}")

    extract = not args.skip_text
    if extract and subprocess.run(["which", "pdftotext"], capture_output=True).returncode != 0:
        print("Aviso: pdftotext no está instalado; se omite la extracción de texto.")
        extract = False

    for i, f in enumerate(fiches, 1):
        pdf_path = pdf_dir / Path(f["url"]).name
        if not pdf_path.exists():
            try:
                pdf_path.write_bytes(http_get(f["url"]))
            except urllib.error.URLError as e:
                print(f"\n  aviso: fallo descargando {f['url']}: {e}")
                f["pdf"], f["txt"], f["n_caracteres"] = None, None, None
                continue
            time.sleep(SLEEP_BETWEEN_CALLS)
        f["pdf"] = str(pdf_path)

        if extract:
            txt_path = txt_dir / (pdf_path.stem + ".txt")
            if not txt_path.exists():
                subprocess.run(["pdftotext", "-layout", str(pdf_path), str(txt_path)],
                               capture_output=True)
            text = txt_path.read_text(encoding="utf-8", errors="replace") if txt_path.exists() else ""
            f["txt"] = str(txt_path) if text else None
            f["n_caracteres"] = len(text)
        print(f"  procesadas {i:,}/{len(fiches):,}", end="\r", flush=True)
    print()

    manifest_jsonl = Path(args.out) / "manifest.jsonl"
    with manifest_jsonl.open("w", encoding="utf-8") as fh:
        for f in fiches:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    manifest_csv = Path(args.out) / "manifest.csv"
    with manifest_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fiches[0].keys()))
        writer.writeheader()
        writer.writerows(fiches)
    print(f"Guardado: {manifest_csv} y {manifest_jsonl}")

    temas: dict[str, int] = {}
    for f in fiches:
        temas[f["tema"] or "?"] = temas.get(f["tema"] or "?", 0) + 1
    ok_txt = sum(1 for f in fiches if f.get("txt"))
    print(f"\nResumen: {len(fiches):,} fichas por tema: "
          + "  ".join(f"{k}:{v}" for k, v in sorted(temas.items())))
    if extract:
        print(f"  con texto extraído: {ok_txt:,}/{len(fiches):,}")


if __name__ == "__main__":
    main()
