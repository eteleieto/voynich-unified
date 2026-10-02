# Voynich Unified Dataset (VUD)

A provenance-first evidence workspace for Beinecke MS 408, built so that many agents can query, view and
annotate the manuscript concurrently **without ever contaminating evidence with interpretation**.

> Pixels are evidence. Everything else is an observation, annotation, transformation, or hypothesis.

**Agents and humans: start with [AGENTS.md](AGENTS.md).** Column reference: [docs/SCHEMA.md](docs/SCHEMA.md).
Caveats: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md). Next phases: [docs/ROADMAP.md](docs/ROADMAP.md).

## What's in VUD 0.1

| | |
|---|---|
| Yale IIIF scans | all 213 canvases at full resolution (613 MB), sha256-verified, read-only |
| Transliterations | ZL3b, IT2a, CD2a (Currier), FG2a (FSG), GC2a (v101), RF1b-e/-er, Landini–Stolfi interlinear (19 transcriber codes) — 25 witnesses, 50k lines, 366k tokens, 2.1M parsed units, all uncertainty preserved |
| Version history | 9 superseded IVTFF releases stored byte-for-byte |
| Codicology | 227 pages ↔ 213 canvases (incl. hand-curated foldout panels), folios, quires, binding images |
| Palaeography | Archetype (Timm 2026): 1,684 glyph polygons registered onto Yale pixels |
| Material science | McCrone 2009 Table I (20 samples), Arizona radiocarbon (4 samples + calibrated interval) |
| Literature | D'Imperio 1978, Tiltman 1967, D'Imperio cluster analysis, IVTFF/IVTT/STA specs — page text searchable |
| Derived | cross-witness agreement index, locus coverage, token frequencies — each with a recipe |
| Contribution layers | append-only, lock-safe E1 observations and H hypotheses with leakage/interpretation guards |
| Tests | 32 integrity tests (hashes, lossless parsing, layer separation, geometry registration) |

## Setup

```bash
uv sync
uv run vud fetch     # ~615 MB; idempotent
uv run vud build     # ~25 s
uv run pytest
```

`evidence/` and `data/` are git-ignored; `evidence/MANIFEST.tsv` (committed) pins every file by sha256.
