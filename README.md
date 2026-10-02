# Voynich Unified Dataset (VUD)

A provenance-first evidence workspace for Beinecke MS 408, built so that many agents can query, view and
annotate the manuscript concurrently **without ever contaminating evidence with interpretation**.

> Pixels are evidence. Everything else is an observation, annotation, transformation, or hypothesis.

* **Agents and humans: start with [AGENTS.md](AGENTS.md).**
* Running a team of agents: [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md) (roles in `.claude/agents/`); the 100-area program: [docs/MUSE_PROMPT.md](docs/MUSE_PROMPT.md) + [docs/RESEARCH_AREAS.md](docs/RESEARCH_AREAS.md).
* Columns: [docs/SCHEMA.md](docs/SCHEMA.md) · caveats: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) ·
  next: [docs/ROADMAP.md](docs/ROADMAP.md) · human-only downloads: [docs/MANUAL_DOWNLOADS.md](docs/MANUAL_DOWNLOADS.md)

## What's in VUD 0.2

| Area | Contents |
|---|---|
| Scans | all 213 Yale canvases (full resolution, sha256-pinned); Davis 2024 multispectral composites |
| Transliterations | ZL3b, IT2a, CD2a, FG2a, GC2a, RF1b, Landini–Stolfi interlinear (19 transcriber codes), all STA1 renderings, 9 superseded releases — lossless, uncertainty preserved |
| Common alphabet | every tradition converted with Zandbergen's own `bitrans` + rules → cross-tradition agreement index |
| Spatial (machine) | 584k ink components, 6.7k text rows, 4,093 paragraph lines aligned, 117k gaps, word-boundary→gap matching, 187k token pixel boxes |
| Visual (machine) | 5k pigment/drawing regions with raw + normalised colour; row/object layout graph |
| Codicology | 227 pages ↔ canvases (curated foldouts), quires, bifolios, binding; McCrone samples; radiocarbon |
| Palaeography | Archetype (Timm 2026) 1,684 glyph polygons + measured features |
| History | Beinecke MS 408A: Marci letter, provenance files, Ethel Voynich's plant IDs & notes; D'Imperio, Tiltman |
| Comparators | 6.2M words of medieval Latin science/medicine/scripture, Dante/Chaucer/Nibelungenlied/Roman de la Rose, Copiale cipher (+plaintext), self-citation pseudo-text, Digital Scriptorium index, *Opera medicinalia* (N. Italy, 1448) images |
| Collaboration | append-only observations/hypotheses/reviews, shared task queue, 6 subagent roles, guard rails |

## Setup

```bash
uv sync
uv run vud fetch     # ~2.5 GB; idempotent and resumable
uv run vud build     # ~3 min (needs a C compiler for bitrans)
uv run pytest
```

`evidence/` and `data/` are git-ignored; `evidence/MANIFEST.tsv` (committed) pins every file by sha256.
