"""Helper HTTP compartido por los scripts de ingestión: reintentos con backoff.

Solo librería estándar. Política:
  - Reintenta errores de red (URLError/timeout), HTTP 429 y HTTP 5xx,
    con backoff exponencial + jitter (1.5s, 3s, 6s… por defecto 3 intentos).
  - NO reintenta los 4xx distintos de 429 (un 404 o 400 no va a mejorar
    por insistir) — se relanzan inmediatamente.
  - Tras agotar los reintentos, relanza la última excepción.

Uso:
    from red import http_get, http_json, descargar
    data = http_json(url)                       # dict/list parseado
    crudo = http_get(url, timeout=120)          # bytes
    descargar(url, Path("downloads/x.zip"))     # streaming a fichero
"""

import json
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

UA_DEFECTO = "Mozilla/5.0 (compatible; ingest-test/0.1)"


def _request(url: str, headers: dict | None) -> urllib.request.Request:
    h = {"User-Agent": UA_DEFECTO}
    h.update(headers or {})
    return urllib.request.Request(url, headers=h)


def http_get(url: str, *, headers: dict | None = None, timeout: float = 60,
             reintentos: int = 3, backoff: float = 1.5) -> bytes:
    """GET con reintentos; devuelve el cuerpo en bytes."""
    ultimo: Exception | None = None
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(_request(url, headers),
                                        timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise               # 4xx "de verdad": no insistir
            ultimo = e
        except (urllib.error.URLError, TimeoutError) as e:
            ultimo = e
        if intento < reintentos - 1:
            espera = backoff * (2 ** intento) + random.uniform(0, 0.5)
            print(f"  red: reintento {intento + 1}/{reintentos - 1} "
                  f"en {espera:.1f}s ({type(ultimo).__name__})", flush=True)
            time.sleep(espera)
    raise ultimo  # type: ignore[misc]


def http_json(url: str, **kw):
    """GET con reintentos; devuelve el JSON parseado."""
    return json.loads(http_get(url, **kw))


def descargar(url: str, dest: Path, *, headers: dict | None = None,
              timeout: float = 600, reintentos: int = 3,
              backoff: float = 1.5) -> None:
    """Descarga en streaming a un fichero, con reintentos por intento completo."""
    ultimo: Exception | None = None
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(_request(url, headers),
                                        timeout=timeout) as resp, \
                 dest.open("wb") as f:
                while chunk := resp.read(1 << 20):
                    f.write(chunk)
            return
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise
            ultimo = e
        except (urllib.error.URLError, TimeoutError) as e:
            ultimo = e
        dest.unlink(missing_ok=True)  # no dejar descargas a medias
        if intento < reintentos - 1:
            espera = backoff * (2 ** intento) + random.uniform(0, 0.5)
            print(f"  red: reintento {intento + 1}/{reintentos - 1} "
                  f"en {espera:.1f}s ({type(ultimo).__name__})", flush=True)
            time.sleep(espera)
    raise ultimo  # type: ignore[misc]
