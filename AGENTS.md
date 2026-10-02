# AGENTS.md — working in the Voynich Unified Dataset (VUD)

You are working on Beinecke MS 408 (the Voynich Manuscript). This workspace holds every obtainable
digital witness of it, organised so that **evidence, observations, scholarly readings, derived numbers
and hypotheses can never be confused**. Read this file fully before running experiments.
Running many agents? Also read `docs/ORCHESTRATION.md`; roles are in `.claude/agents/`.

## The one rule

> **Pixels are evidence. Everything else is an observation, an annotation, a derived measurement, or a hypothesis.**

| Layer | Where | What | You may |
|---|---|---|---|
| **E0** raw evidence | `evidence/` | Yale scans, transliteration files, reports, MS 408A papers — byte-for-byte, sha256 in `evidence/MANIFEST.tsv`, read-only | read only |
| **E1** observations | `data/observations/` | machine proposals (`spatial_*`, `visual_objects`, `color_measurements`, `layout_relations`; `review_status='unreviewed'`) + contributions from `contrib/observations/*.jsonl` | **append** via `vud.contrib` |
| **E2** annotations | `data/annotations/` | transliterations (ZL, IT, CD, FSG, v101, RF, LSI, STA1, legacy releases), page variables, Archetype glyph boxes — every row has `source_id` | read only |
| **E3** derived | `data/derived/` | agreement indices, common-alphabet conversions, version diffs, reading orders, glyph features — recipes in `derived.recipes` | read; add tables only via code in `src/vud/` |
| **H** hypotheses | `data/hypotheses/` ← `hypotheses/*.jsonl` | decipherment claims, plant IDs, language guesses, mappings | **append** via `vud.contrib.add_hypothesis` |
| **CMP** comparators | `data/comparative/` | Latin science/medicine, vernaculars, Copiale cipher, self-citation pseudo-text, MS indexes, Opera medicinalia (1448) images | read only |

Never edit `evidence/`, `data/`, `registry/sources.yaml` or `curation/` (the harness denies it). If you believe a
value is wrong, record an observation or review that supersedes it and explain the method.

## Quick start

```bash
uv run vud status                        # one-screen orientation: release, layers, reviews, open tasks
uv run vud sources                       # what's in here, with provenance and licences
uv run vud page f1r --comments           # page attributes, image(s), ZL3b lines, Zandbergen's notes
uv run vud locus f1r.3                   # one line in every witness, raw source lines included
uv run vud grep '^qok.*dy$' -C 2         # regex over tokens (ZL3b default; -w it2a / -w gc2a / -w sta1:ZL3b ...)
uv run vud image f68r3                   # views/f68r3_seq123.jpg → open it with your Read/image tool
uv run vud image f1r --region 300,300,1200,500 --max 1600     # zoom (full-canvas pixel coordinates)
uv run vud image f26r --boundaries zl3b  # machine text rows + that witness's word breaks on measured gaps
uv run vud image f26r --glyphs --objects # Archetype glyph polygons; machine pigment/drawing regions
uv run vud gallery '^daiin$' --limit 60   # contact sheet of the actual ink of every matching token (best spans first)
uv run vud canvas yale_ms408a_marci_letter 1                # any other IIIF item (Marci letter, Voynich papers, Opera medicinalia)
uv run vud sql "select * from locus_readings where page_id='f1r'"
uv run vud sql "show all tables"         # every view in every schema; columns in docs/SCHEMA.md
uv run vud task next --kind review_alignment --author <you>  # shared work queue (see Contributing)
```

`voynich.duckdb` holds only views over Parquet files; open it read-only from Python with
`duckdb.connect('voynich.duckdb', read_only=True)` (many agents can read concurrently).

## What is where (most-used views)

**Text (E2)**
| View | One row per | Notes |
|---|---|---|
| `tokens` (main) | token per witness | `text` = first reading; `boundary_before/after` ∈ space, uncertain_space, drawing, drawing_misaligned, line_start/end, para_start/end; flags `has_alt/has_unread/has_rare/has_lig`; page context (section, Currier language, Davis hand, quire) |
| `annotations.units` | parsed unit | lossless: glyphs, alternatives (`options`, rank order), separators, comments, LSI fillers |
| `alternatives`, `boundaries` (main) | alt option / separator | `[a:b]` expanded with rank; every word-boundary mark |
| `locus_readings` (main) | IVTFF locus | ZL / IT / v101 / Currier / FSG / RF / Stolfi / Grove side by side |
| `annotations.loci` | line per witness | `raw_line` verbatim; `ivtff_locus_id` aligns LSI lines to IVTFF |
| `annotations.witnesses` | witness | alphabet + `is_independent` (RF, STA renderings, LSI D/G/I/Q/M, VT0e are not independent) |
| `annotations.source_comments` | `#` comment line | Zandbergen's page notes: codicology, Petersen refs, others' plant IDs |
| `annotations.legacy_loci`, `derived.version_diffs` | superseded releases | how ZL/IT/CD/FSG/GC/RF readings changed between releases |
| `derived.common_eva_loci/_tokens` | line/token per `beva:*` witness | **every tradition (Currier, FSG, v101, ZL, IT, RF, VT) in one alphabet**, via the author's own `bitrans` + STA→basic-Eva rules |
| `derived.witness_agreement` | locus × witness pair | exact / Levenshtein / boundary agreement; `comparison_space` = native_eva or common_basic_eva |

**Pixels, layout, codicology**
| View | One row per | Notes |
|---|---|---|
| `codicology.pages` | IVTFF page (227) | folio/side/panel/quire/section/Currier language & hand/Davis hand (authority ZL3b) |
| `page_images` (main) | page × canvas | local JPEG, foldout panel box (approximate), map provenance |
| `codicology.bifolios`, `folios`, `quires` | structure | conjugate leaves; inferred missing conjugates flagged `is_reconstruction` |
| `observations.spatial_text_rows` | detected text row | bbox, baseline, fragments, glyph height (px) |
| `alignment_reviewed` (main) | ZL paragraph locus → row | machine alignment + confidence + latest review verdict |
| `observations.spatial_row_gaps` | gap between ink clusters | px and in glyph-heights (`gap_norm`) |
| `observations.spatial_boundary_gaps` | witness boundary → gap | which physical gap each `.`/`,`/`<->` most likely corresponds to |
| `observations.spatial_token_spans` | witness token on an aligned row | pixel box between its matched gaps; `token_confidence` (top-ranked spans are mostly right, low ones often wrong) |
| `observations.spatial_ink_components` | ink blob (584k) | bbox, area, mean Lab |
| `observations.visual_objects`, `color_measurements` | pigment region / ink drawing | neutral shape descriptors; raw + parchment-normalised colour |
| `observations.layout_relations` | row→object, object↔object | above/below/overlaps/touches, distance |
| `derived.reading_order_schemes/_items` | ordering | plural: each transliteration's order, LSI order, spatial top-down, binding vs photo sequence |
| `annotations.glyph_annotations`, `derived.glyph_features` | Archetype glyph (1,684) | polygon on Yale pixels; allograph, hand label; stroke width, slant, size |
| `codicology.material_samples`, `radiocarbon` | McCrone sample (20) / AMS sample (4) | calibrated 95% 1404–1438 (parchment) |
| `codicology.other_canvases` | canvas of MS 408A papers & comparator MSS | Marci letter, provenance files, Ethel Voynich's plant IDs, Opera medicinalia 1448 |

**Context**
| View | Notes |
|---|---|
| `literature.pages` | D'Imperio 1978, Tiltman 1967, D'Imperio cluster paper, IVTFF/IVTT/STA/bitrans docs, Copiale paper (OCR — noisy) |
| `comparative.documents / segments / token_freq` | kind ∈ natural_language, ciphertext, cipher_plaintext, translation, pseudo_text, manuscript_record |
| `observations.observations`, `hypotheses.hypotheses` | what agents have added |

## How much to trust the machine layers (spatial-v1, visual-v1)

* Row detection + ZL paragraph alignment cover 4,093 of 4,140 paragraph loci; per-page quality is in
  `observations.spatial_page_qa` (`width_units_corr`, `mean_cost`). Labels, circular and radial text are **not** aligned.
* Row boxes include ascenders and can clip or straddle neighbouring lines; panel boxes on foldouts are ±3%.
* Boundary→gap matching is an order-preserving optimisation that *prefers* large gaps: use it for relative
  comparisons (e.g. `,` vs `.`), not as proof that spaces are physically large. `nearest_gap_*` columns are the naive baseline.
* Everything is `review_status='unreviewed'`. Prefer reviewed rows when they exist (`main.alignment_reviewed`).

## Identifiers

* **page_id** = IVTFF page name: `f1r`, `f68r3` (foldout panel), `fRos` (Rosettes). Order = `codicology.pages.ivtff_order`.
* **locus_id** = `page.num` (e.g. `f1r.3`), shared by all IVTFF/STA files. LSI keeps `page.unit.num` with `ivtff_locus_id`.
* **witness_id** = source id (`zl3b`), `lsi_16e6:<code>`, `sta1:<file>`, or derived `beva:<file>`.
* **Yale canvas** = `seq` (1–213); other IIIF items: (`source_id`, `seq`) in `codicology.other_canvases`.

## Alphabets — do not mix them silently

`zl3b`, `rf1b_*`, LSI = EVA; `it2a` = Takahashi's EVA variant; `gc2a` = v101; `cd2a` = Currier; `fg2a` = FSG;
`sta1:*` = STA1 (2-character glyph codes). For cross-tradition work use `beva:*` (common basic Eva) or `sta1:*`.
Rare glyphs are `@nnn;`. `?` = one unreadable glyph, `???` = unknown run.

## Contributing (concurrency-safe, append-only)

```python
from vud import contrib, tasks
tid = tasks.claim_next("review_alignment", author="palaeo-03")      # or: uv run vud task next ...
contrib.review_machine_observation(author="palaeo-03", target_type="locus", target_id="f1r.3",
    verdict="corrected", corrected_xywh=[410, 820, 1900, 95], notes="row box clipped the last word")
contrib.add_observation(author="palaeo-03", target_type="locus", target_id="f1r.3",
    property="gallows_loop_closed", value_text="yes", method="visual, 1600px crop of row",
    source_ids=["yale_ms408_iiif_2014"], confidence=0.8)
hid = contrib.add_hypothesis(author="analyst-01", type="segmentation", title="...", claim="...",
    falsification_test="refuted if ... on held-out pages", train_pages=[...], held_out_pages=[...])
contrib.update_hypothesis_status(author="analyst-01", hypothesis_id=hid, status="refuted", result_summary="...")
tasks.complete(tid, author="palaeo-03", summary="8 rows accepted, 2 corrected")
```
Then `uv run vud build contrib && uv run vud build db`. The observation API refuses interpretive wording
("means", "translates", "is the plant…") — that is a hypothesis. A worked example experiment lives in
`experiments/_example_gap_widths/run.py`.

## Experiment hygiene

* Cite the release you used (`releases/VUD-*.json`; cut one with `uv run vud release <version>`).
* Declare train/held-out pages *before* looking; the hypothesis API rejects overlap.
* Replicate on ≥2 independent witnesses; vary alternatives, unreadables and uncertain spaces.
* Run controls: Latin (`cc:*`), a vernacular, the Copiale ciphertext, and Timm's pseudo-text. If the
  pseudo-text shows the effect too, it says nothing about language.
* Section/language/hand labels are one authority's page variables (Davis's 5-scribe model is contested).
* Code and outputs go under `experiments/<your-name>/`; never under `data/`.

## Rebuilding

```bash
uv run vud fetch      # idempotent; downloads anything missing, records sha256, makes files read-only
uv run vud build      # all steps (~3 min): registry → transcriptions → legacy → codicology → archetype → common
                      #   → spatial → visual → derived → orders → comparators → literature → contrib → db
uv run vud verify     # re-hash all evidence
uv run vud manual     # what still needs a human download (docs/MANUAL_DOWNLOADS.md)
uv run pytest         # integrity tests
```
