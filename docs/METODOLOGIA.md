# Metodología: extracción, normalización y cruce de datos

> English version: [METHODOLOGY.md](METHODOLOGY.md)

Este documento explica **cómo** se construyó el pipeline: de dónde y con qué
técnica se extrajo cada dato, cómo se normalizó y con qué claves se cruzaron
las fuentes entre sí. Complementa al `README.md` (visión general y resultados)
y al `INVENTARIO.md` (qué ficheros hay y qué contienen).

Todo se verificó en vivo el 11 de junio de 2026.

---

## 1. Extracción: técnica por fuente

Cada fuente expone los datos de una manera distinta. Esta tabla resume el
método de acceso real que funcionó (que no siempre coincide con el documentado):

| Fuente | Técnica de extracción | Particularidad descubierta |
|---|---|---|
| DPE ADEME (FR) | API REST data-fair, paginada con cursor `next` | Permite `select=` de columnas y filtro `qs=` por departamento; límite 600 req/min anónimo |
| RNB (FR) | API REST, una petición por `rnb_id` | El bbox exige orden (lat_max primero); paginación por cursor |
| BDNB (FR) | API PostgREST, filtro en lote `campo=in.(v1,v2,…)` | **Tope silencioso de 10 filas/respuesta** (ignora `limit`); se pagina con `offset` dentro de cada lote |
| Géorisques RGA (FR) | API REST por coordenada `?latlon=lon,lat` | `200` con cuerpo **vacío** = punto fuera de zona cartografiada (no es error) |
| geoportail.lu (LU) | WFS 2.0 (GeoServer), `outputFormat=application/json` | Sirve GeoJSON directo — no hace falta parsear GML; paginación `startIndex` |
| Bâtiments 3D 2023 (LU) | Descarga del zip por comuna vía API udata de data.public.lu + extracción del `.gml` interno | La altura solo existe en el CityGML (`bldg:measuredHeight`); las huellas 2D "ligeras" solo traen la cota del suelo |
| Ortofoto 2025 (LU) | WMS GetMap, chips de 40×40 m a 400×400 px | El WMS abierto sirve todas las milésimas 1967–2025 sin registro; evita descargar los JP2 |
| UrbIS (BE-Bruselas) | WFS 2.0 GeoServer | El GeoServer "histórico" está vacío; el vigente (`geoservices-vector.irisnet.be`) se localizó vía el GeoNetwork del portal |
| GRB (BE-Flandes) | WFS 2.0 | Funciona **sin** la cuenta que exige la descarga masiva |
| VEKA (BE-Flandes) | Descarga directa de CSV bajo `/Data/` | La raíz del portal responde 403 (WAF) pero los ficheros sirven; rutas halladas en el catálogo DCAT de metadata.vlaanderen.be |
| Fichas AQC (corpus) | API REST de WordPress (`/wp-json/wp/v2/media`) + descarga de PDFs | Sin scraping de HTML; el texto se extrae con `pdftotext -layout` |
| Prescripciones ITM (corpus) | Parseo HTML de la página conditions-types + descarga directa de PDFs | Página estable, sin API; títulos extraídos de la cabecera de cada PDF; el plan original incluía los informes JRC Eurocodes pero su repositorio (DSpace) bloquea con WAF a los clientes no-navegador |

Convenciones comunes de extracción en todos los scripts:

- **Sin claves ni registro**: todas las fuentes se consultan anónimamente.
- **Pausas de cortesía** (0,2–0,5 s) entre peticiones, por debajo de cualquier
  límite documentado.
- **User-Agent identificable** (`ingest-test/0.1`); algunos portales (AQC,
  UrbIS, VEKA) exigen un UA de navegador.
- **Caché de descargas grandes**: los zips (CityGML, ortofotos) no se
  re-descargan si ya existen en `downloads/`.

---

## 2. Normalización

### 2.1 Formatos de salida

Toda salida tabular se escribe **por duplicado**:

- **CSV** — para análisis humano (Excel, pandas).
- **JSONL** (un objeto JSON por línea) — para encadenar scripts: cada paso del
  pipeline lee el JSONL del anterior. Es el formato canónico del proyecto.

Las geometrías se guardan aparte como **GeoJSON** (WGS84), directamente
utilizables en QGIS/kepler.gl. Los índices (RAG) van en **SQLite**.

### 2.2 Sistemas de coordenadas

Todas las fuentes se piden o convierten a **EPSG:4326 (WGS84, lon/lat)**:

- Las APIs francesas ya sirven WGS84.
- Los WFS (LU, BE) se piden con `srsName=EPSG:4326`, evitando reproyectar
  desde LUREF (EPSG:2169) o Lambert belga (EPSG:31370) en cliente.
- La única fuente que quedó en su CRS nativo es el GPKG luxemburgués
  explorado y descartado (no se usa en ningún cruce).

### 2.3 Selección y renombrado de campos

- **DPE**: de los 230 campos del dataset se seleccionan 14 relevantes
  (identidad, dirección BAN normalizada, características, etiquetas, consumo).
  La selección se hace en la propia API (`select=`), no en cliente.
- **Prefijos por fuente**: al cruzar, cada fuente aporta sus columnas con
  prefijo (`rnb_*`, `bdnb_*`) para que el origen de cada dato sea evidente
  y no haya colisiones (p. ej. `annee_construction` del DPE vs
  `bdnb_annee_construction` de Fichiers Fonciers, que pueden discrepar y
  se conservan ambos deliberadamente).
- **Geometrías aplanadas**: para el CSV, los polígonos se reducen a
  centroide (`lon`, `lat`) y atributos escalares (superficie, nº direcciones);
  la geometría completa vive en el GeoJSON.

### 2.4 Vocabularios y valores especiales

- **Riesgo de arcillas**: Géorisques responde "Exposition faible/moyenne/forte"
  y la BDNB "Faible/Moyen/Fort". Se normaliza **al vocabulario BDNB**
  (`Faible | Moyen | Fort`), y el cuerpo vacío de Géorisques se codifica como
  **`Non exposé`** — distinto de nulo, que significa "no consultado".
- **Trazabilidad**: la columna consolidada va acompañada de su fuente
  (`alea_argiles_source = BDNB | Géorisques`). Regla general del proyecto:
  cuando un valor puede venir de dos sitios, se guarda de dónde vino.
- **IDs como texto**, nunca como número (los CAPAKEY y NIS belgas llevan
  ceros a la izquierda; los rnb_id son alfanuméricos).
- **Codificación**: todo UTF-8; los CSV de VEKA llegan con BOM
  (`utf-8-sig`) y los GML/XML se leen con `errors="replace"` por bytes
  inválidos ocasionales.

### 2.5 Normalización del corpus (RAG)

- **Texto**: `pdftotext -layout` conserva la estructura visual de las fichas.
- **Troceado**: por párrafos, acumulando hasta ~1.200 caracteres con
  **solape de 200** para que ningún concepto quede cortado entre fragmentos.
- **Embeddings**: `intfloat/multilingual-e5-small` (384 dims), con la
  convención del modelo: documentos con prefijo `passage:` y consultas con
  `query:`. Vectores **normalizados** → el producto punto es directamente la
  similitud coseno.
- **Metadatos por fragmento**: código de ficha (A.01–G.13), tema (letra),
  título y fichero de origen — lo necesario para citar la fuente en
  cualquier respuesta.

---

## 3. Cruces: las claves que unen las fuentes

### 3.1 Francia — cruce por identificador (exacto)

```
DPE ──(id_rnb)──> RNB ──(id_rnb)──> BDNB[batiment_construction]
                                        │ (batiment_groupe_id)
                                        ├──> BDNB[ffo_bat]      materiales, plantas
                                        └──> BDNB[argiles]      riesgo arcillas
DPE+RNB+BDNB ──(rnb_lon, rnb_lat)──> Géorisques RGA   (solo si BDNB no tenía dato)
```

- **`id_rnb`** es el identificador pivote nacional (lo recomienda el propio
  reporte). Está presente en el 17–52 % de los DPE recientes según territorio.
- **Fallback por dirección** para los DPE sin `id_rnb`: el `identifiant_ban`
  del DPE es, cuando está completo (comuna_calle_número, p.ej.
  `33249_0271_00001`), la misma clave de interoperabilidad BAN que la API
  del RNB acepta como `cle_interop_ban` — sin geocodificador. Las claves de
  solo calle (2 segmentos) no resuelven a un edificio y se descartan. Si una
  clave devuelve varios edificios se prefiere el `constructed`. `rnb_match`
  registra la vía del cruce (`id_rnb` | `adresse_ban`) por registro.
  Mejora medida: París 17%→98%, Gironda 52%→90%.
- En la BDNB el cruce es en dos saltos: `rnb_id → batiment_groupe_id` (tabla
  `batiment_construction`) y de ahí a las tablas de atributos. Las consultas
  van **en lotes de 50 IDs** (`in.(...)`) paginados con `offset`.
- **Deduplicación previa**: varios DPE (pisos) comparten edificio; cada
  `rnb_id` se consulta una sola vez y el resultado se reparte a todas sus
  filas DPE.
- El cruce con Géorisques es **por coordenada**, solo para los huecos, y es
  el único cruce espacial de la cadena francesa.
- **Cardinalidad**: el dataset final es 1 fila = 1 DPE (no 1 edificio);
  un edificio con 3 DPE aparece 3 veces con los mismos atributos de edificio.

### 3.2 Luxemburgo — cruce espacial + cruce por ID

```
WFS edificios (polígonos)
   ▲ point-in-polygon              ▲ point-in-polygon
direcciones (puntos)         centroide del edificio → parcelas (polígonos)

edificio INSPIRE "Building2D.ACT_<uuid>"  ──(quitar prefijo)──>  CityGML "ACT_<uuid>" → altura
edificio (lon, lat) ──(GetMap bbox)──> chip de ortofoto
```

- **Point-in-polygon propio** (ray casting en Python puro, sin dependencias):
  cada punto de dirección se asigna al edificio que lo contiene; el
  centroide de cada edificio, a su parcela. Solo se evalúa el anillo
  exterior de los polígonos (suficiente en la práctica para este uso).
- **El hallazgo que evitó el matching espacial con el 3D**: los UUID de la
  capa WFS (`Building2D.ACT_x`) y del CityGML (`ACT_x`) son el mismo ID con
  prefijo distinto → el cruce de alturas es un join exacto tras
  `removeprefix("Building2D.")`.
- Los **chips de ortofoto** se generan por bbox métrico alrededor del
  centroide (40×40 m → 400×400 px ≈ resolución nativa de 10 cm/píxel), y el
  manifiesto arrastra las etiquetas estructuradas (altura, parcela, dirección).

### 3.3 Bélgica — mismo patrón espacial, clave catastral nacional

- Mismo point-in-polygon que Luxemburgo (Bruselas: direcciones + parcelas;
  Flandes: solo parcelas, el GRB no expone capa de direcciones).
- La clave de salida es el **CAPAKEY** (clave catastral nacional belga,
  presente en UrbIS y GRB) y el **código NIS** de comuna — los ganchos para
  cruces futuros con Statbel y con el e-peil de VEKA (que está agregado por
  NIS de comuna).

### 3.4 Cruce semántico — datos estructurados ↔ corpus

El conector (`informe_edificio.py`) une las dos mitades sin ninguna clave
común, por **significado**:

```
atributo estructurado            consulta de patología (FR)                 fichas recuperadas
alea_argiles ∈ {Fort, Moyen} →  "retrait-gonflement des argiles…"      →  [A.02] [A.05]
etiquette_dpe ∈ {F, G}       →  "condensations moisissures logements…" →  [E.09]
mat_mur ~ PIERRE/MEULIERE    →  "remontées capillaires murs pierre"    →  [B.01]
mat_toit ~ TUILES/ZINC/ARD.  →  "infiltrations couverture…"            →  [C.06]/[C.07]
periode = avant 1948         →  "structure plancher bois ancien"       →  [B.11]
```

Cada regla es un par (condición sobre el registro, consulta en francés).
Las consultas se **afinaron empíricamente**: la primera versión de dos de
ellas recuperaba fichas poco pertinentes; se probaron variantes contra el
índice y se sustituyeron. Lección: en RAG, la redacción de la consulta es
tan determinante como el modelo de embeddings.

El informe resultante cita cada patología con su ficha `[código]` y su
score de similitud — el dato estructurado dice *cuánto* riesgo hay y la
ficha explica *qué* es y *cómo* se manifiesta.

**Diseño de idiomas de los informes** (`--idiomas es,en,fr`): tres capas con
reglas distintas. (1) Los *textos fijos* (título, etiquetas de identidad,
cabeceras de señal, pie) se traducen con un diccionario por idioma en
`informe_edificio.py`. (2) Las *consultas al RAG* van siempre en francés —
el idioma del corpus — para que el retrieval sea idéntico en cualquier
idioma de informe. (3) Los *extractos AQC* no se traducen nunca: son citas
literales y traducirlas falsearía la fuente. En modo `--llm` el idioma de
salida se instruye en el prompt; las reglas de grounding (citar `[código]`,
no inventar patologías) son independientes del idioma. `--pdf` exporta cada
Markdown a PDF (`markdown-pdf`), conservando siempre el `.md`.

---

## 4. Validaciones aplicadas

1. **Cobertura de cada cruce medida y reportada** (los scripts imprimen
   resumen): 100 % RNB, 93–100 % BDNB, 99–100 % parcelas, 63–88 % direcciones,
   69 % alturas (explicable: bbox mayor que la comuna + umbral de 20 m² del
   CityGML).
2. **Validación cruzada entre fuentes independientes**: un edificio control
   con `Fort` en BDNB devolvió "Exposition forte" en Géorisques.
3. **Plausibilidad regional**: materiales dominantes coherentes (zinc en
   París, teja en Gironda); alturas con mediana 9,4 m en un pueblo.
4. **Verificación visual**: GeoJSON inspeccionables en QGIS; chips de
   ortofoto revisados a ojo (tejado centrado, nitidez).
5. **Búsqueda translingüe verificada**: consulta en español recupera la
   ficha francesa correcta.

---

## 5. Trabajo futuro (pendiente)

Ordenado por valor/esfuerzo estimado:

1. ~~Cruce por dirección para los DPE sin `id_rnb`~~ — **hecho**: el
   `identifiant_ban` del DPE se usa como `cle_interop_ban` en la API del RNB;
   la cobertura subió al 90–98 % con trazabilidad por registro (`rnb_match`).
2. ~~Probar el modo `--llm` del generador de informes~~ — **hecho**:
   verificado de punta a punta con Gemini (free tier) y soporte
   multi-proveedor añadido (anthropic / gemini / openrouter).
3. **Escalar a volumen**: sustituir las APIs por descargas masivas
   (BDNB GPKG por departamento, dump del RNB) y hacer los joins localmente;
   fijar millésimes de todas las fuentes para reproducibilidad (se observó
   desfase RNB actual vs BDNB 2025-07).
4. **Cruces belgas de segundo nivel**: CAPAKEY → catastro federal;
   NIS → Statbel (parque, permisos) y e-peil VEKA por comuna, replicando el
   esquema de enriquecimiento francés.
5. **Módulo CV**: entrenar/evaluar un clasificador sobre los chips de
   ortofoto (estado de cubierta) con transferencia desde SDNET2018/METU
   (ambos CC-BY, aptos para uso comercial según el reporte). Los chips ya
   salen etiquetados con altura/parcela/dirección.
6. **Ampliar el corpus RAG** — *parcialmente hecho*: las prescripciones ITM
   (LU, 143 docs FR/DE) están indexadas con fuente/idioma por fragmento.
   Queda abierto: Legilux XML, TABULA/EPISCOPE y los informes JRC Eurocodes
   (bloqueados: su repositorio rechaza clientes no-navegador).
7. **Robustez de ingeniería** (deuda consciente del prototipo): reintentos
   con backoff, point-in-polygon con índice espacial (R-tree) para zonas
   grandes, anillos interiores de polígonos, tests automatizados, y un
   orquestador que encadene los pasos sin invocación manual.
8. **Wallonie**: única región sin cubrir; el reporte la daba como
   incompleta en open data (portal ODWB por explorar).

---

## 6. Mapa de documentos del proyecto

| Documento | Contenido |
|---|---|
| `README.md` | Visión general, arquitectura, resultados, hallazgos, licencias |
| `METODOLOGIA.md` | Este documento: extracción, normalización, cruces, validación, pendientes |
| `INVENTARIO.md` | Qué ficheros de datos existen, de qué fuente y qué contienen |
| `compass_artifact_*.md` | El reporte de fuentes original que guió todo el trabajo |
| Docstrings de cada script | Uso, fuente, licencia y particularidades (`--help`) |
