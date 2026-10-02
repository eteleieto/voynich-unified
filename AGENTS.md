# AGENTS.md — working in the Voynich Unified Dataset (VUD)

You are working on Beinecke MS 408 (the Voynich Manuscript). This workspace holds every obtainable
digital witness of it, organised so that **evidence, observations, scholarly readings, derived numbers
and hypotheses can never be confused**. Read this file fully before running experiments.

## The one rule

> **Pixels are evidence. Everything else is an observation, an annotation, a derived measurement, or a hypothesis.**

| Layer | Where | What | You may |
|---|---|---|---|
| **E0** raw evidence | `evidence/` | Yale scans, transliteration files, reports — byte-for-byte, sha256 in `evidence/MANIFEST.tsv`, files are read-only | read only |
| **E1** observations | `data/observations/` ← `contrib/observations/*.jsonl` | measurements of the vellum (gaps, boxes, colours…) with a repeatable method | **append** via `vud.contrib.add_observation` |
| **E2** annotations | `data/annotations/` | transliterations (ZL, IT, CD, FSG, v101, RF, LSI), page variables, Archetype glyph boxes — every row has `source_id` | read only |
| **E3** derived | `data/derived/` | agreement indices, frequencies — each table has a recipe in `derived.recipes` | read; add new derived tables only via code in `src/vud/` |
| **H** hypotheses | `data/hypotheses/` ← `hypotheses/*.jsonl` | decipherment claims, plant IDs, language guesses, mappings | **append** via `vud.contrib.add_hypothesis` |

Never edit `evidence/`, `data/`, `registry/sources.yaml` or `curation/` to make a hypothesis fit.
If you believe an E2/E1 value is wrong, record a new observation that supersedes it (`supersedes_id`)
and explain the method; do not overwrite.

## Quick start

```bash
uv run vud sources                      # what's in here, with provenance and licences
uv run vud page f1r                     # page attributes, image file(s), ZL3b lines
uv run vud page f1r --witness gc2a      # same page in Glen Claston's v101 alphabet
uv run vud locus f1r.3                  # one line in every witness, raw source line included
uv run vud grep '^qok.*dy$' -C 2        # regex over tokens (ZL3b by default), keyword-in-context
uv run vud image f68r3                  # writes views/f68r3_seq123.jpg → open it with your image viewer/Read tool
uv run vud image f1r --region 300,300,1200,500 --max 1600   # zoom on a region (full-canvas pixels)
uv run vud image f26r --glyphs          # overlay Archetype glyph polygons
uv run vud sql "select * from locus_readings where page_id='f1r'"
uv run vud sql "show all tables"        # every view in every layer
```

`voynich.duckdb` contains only views over the Parquet files; open it read-only from Python with
`duckdb.connect('voynich.duckdb', read_only=True)` (many agents can read concurrently).

## What is where (most-used views)

| View | One row per | Notes |
|---|---|---|
| `tokens` (main) | token per witness | `text` = first reading; `boundary_before/after` ∈ space, uncertain_space, drawing, drawing_misaligned, line_start, line_end, para_start, para_end; flags `has_alt/has_unread/has_rare/has_lig`; joined page context (section, Currier language, Davis hand, quire) |
| `annotations.units` | every parsed unit | glyph chars, alternatives (`options` list, rank order), separators, comments, LSI fillers — the lossless layer |
| `alternatives` (main) | alternative reading | `[a:b]` expanded with `rank` |
| `locus_readings` (main) | IVTFF locus | ZL / IT / v101 / Currier / FSG / RF / Stolfi / Grove side by side |
| `annotations.loci` | line per witness | `raw_line` is the verbatim source line; `ivtff_locus_id` aligns LSI lines to IVTFF |
| `annotations.witnesses` | witness | alphabet, independence flag (RF files and LSI D/G/I/Q/M are *not* independent witnesses) |
| `annotations.source_comments` | `#` comment line | ZL3b comments contain codicological notes, plant IDs proposed by others, Petersen references |
| `annotations.page_variables` | page × variable × source | `$Q $P $F $B $I $L $H $C $X` per source — sources disagree; that's data |
| `codicology.pages` | IVTFF page (227) | folio, side, panel, quire, section, Currier language/hand, Davis hand (authority: ZL3b) |
| `page_images` (main) | page × canvas | local JPEG path, foldout panel box (approximate, see `region_method`), map provenance |
| `codicology.canvases` | Yale canvas (213) | IIIF ids, sizes, sha256 |
| `annotations.glyph_annotations` | glyph polygon (1,684) | Archetype (Timm 2026): allograph iin/in/k/sh/weirdos, hand label, pixel polygon on the Yale canvas |
| `codicology.material_samples` | McCrone 2009 sample (20) | location in cm, constituents; conclusions are in a separate table |
| `codicology.radiocarbon` | AMS sample (4) + combined | calibrated 95% 1404–1438 (parchment, not ink) |
| `derived.witness_agreement` | locus × witness pair | exact match, Levenshtein similarity, boundary Jaccard under `eva_basic_v1` |
| `literature.pages` | PDF page | D'Imperio 1978, Tiltman 1967, D'Imperio cluster paper, IVTFF/STA specs (OCR text — noisy) |
| `observations.observations`, `hypotheses.hypotheses` | contributions | what agents have added |

Full column dictionary: `docs/SCHEMA.md`. Known gaps and caveats: `docs/KNOWN_ISSUES.md`.

## Identifiers

* **page_id** = IVTFF page name: `f1r`, `f68r3` (foldout panel), `fRos` (Rosettes). Order = `codicology.pages.ivtff_order`.
* **locus_id** = `page.num` (e.g. `f1r.3`), shared by all IVTFF files. LSI keeps its native `page.unit.num`
  (`f100r.L3.1`) with `ivtff_locus_id` resolved by text-matching Takahashi's lines.
* **witness_id** = `source_id` for IVTFF files; `lsi_16e6:<code>` for interlinear transcribers.
* **Yale canvas** = `seq` (1–213) in the IIIF manifest; images in `evidence/yale_ms408_iiif_2014/images/<seq>_<iiif-id>.jpg`.

## Alphabets — do not mix them silently

`zl3b`, `rf1b_*`, LSI = EVA (`Eva-`); `it2a` = Takahashi's EVA variant (`EvaT`); `gc2a` = v101 (finer than EVA);
`cd2a` = Currier; `fg2a` = FSG. LSI `C`/`F` lines are Stolfi's EVA *conversions* of Currier/FSG. Any cross-alphabet
comparison needs an explicit, versioned mapping recorded as a derived recipe — none is provided yet.
Rare glyphs are `@nnn;` codes (see `evidence/sta1_alphabet/`). `?` = one unreadable glyph, `???` = unknown run.

## Contributing (concurrency-safe, append-only)

```python
from vud import contrib
contrib.add_observation(author="agent-07", target_type="locus", target_id="f1r.3",
    property="mean_inter_token_gap", value_number=41.2, unit="px",
    method="binarize Otsu on canvas 3, connected components, median gap; code: experiments/gaps_v1.py",
    source_ids=["yale_ms408_iiif_2014", "zl3b"], confidence=0.7)

hid = contrib.add_hypothesis(author="agent-07", type="segmentation",
    title="EVA 'qo' is a single prefix unit", claim="...",
    falsification_test="predicts X on held-out pages; refuted if Y",
    train_pages=[...], held_out_pages=[...], evidence=["obs_…", "derived.witness_agreement"])
contrib.update_hypothesis_status(author="agent-07", hypothesis_id=hid, status="refuted", result_summary="…")
```
Then `uv run vud build contrib && uv run vud build db` to refresh the views.
The observation API refuses text that reads as interpretation ("means", "translates", "is the plant…") — that is a hypothesis.

## Experiment hygiene

* Record the release you used: `releases/VUD-*.json` hashes every table. Cut one with `uv run vud release 0.1.1`.
* Declare train/held-out pages *before* looking at results; the hypothesis API rejects overlap.
* Prefer independent witnesses. ZL3b is the most complete/careful, but it is still one reader's interpretation:
  ZL and IT agree token-for-token on only ~48% of shared lines (`derived.witness_agreement`).
* Section/language/hand labels are page variables from one authority. Davis's 5-scribe model is contested
  (the Archetype dataset author argues against it). Treat them as covariates, not truth.
* Put experiment code and outputs under `experiments/<your-name>/`; never under `data/`.

## Rebuilding

```bash
uv run vud fetch     # idempotent; downloads anything missing, records sha256, makes files read-only
uv run vud build     # registry → transcriptions → codicology → archetype → derived → literature → contrib → db (~25 s)
uv run vud verify    # re-hash all evidence
uv run pytest        # integrity tests (layer separation, lossless parsing, geometry registration …)
```
