# Known issues, gaps and judgement calls (VUD 0.1)

Everything here is deliberate or unresolved. Nothing has been silently "fixed" in the data.

## Registration / mapping
- **Yale canvas 165 is labelled "90r" by Yale** but 90r is on canvas 164. Archetype labels the same image
  `90v2`, and its 8 visible text lines match ZL3b f90v2 (8 loci). Mapped to `f90v2`, confidence 0.8.
- **Foldout panel boxes** (`codicology.canvas_pages.region_xywh`) are by-eye estimates of fold-crease positions
  from decile-ticked previews (±3% of canvas width). Full canvas height is assumed. Good enough to crop a
  panel for viewing; **not** good enough for geometry-sensitive measurement. Use `vud image <page> --full-canvas`.
- **ZL3b treats f101r1+f101r2 as one logical page `f101r`, and likewise `f101v`.** Yale photographs f101v in
  two pieces (canvases 179 and 180): both are mapped with role `partial`.
- **Archetype image "54v"** is 2979 px wide vs Yale's 54v at 2999 px. It is a different capture, so its 12 glyph
  polygons are left unregistered (`canvas_id` null) rather than guessed.
- **LSI → IVTFF locus map**: 399 of 17,357 LSI lines have no `ivtff_locus_id` (no Takahashi line to anchor them,
  or text too different). LSI also uses 3 page names that IVTFF does not (`f85v2`, `f101r1`, `f101v2`).

## Transliterations
- Only the **current** IVTFF releases are parsed into tables. Superseded releases (ZL3a, ZL 2b/1r, IT 1a, …) are
  stored byte-for-byte in `evidence/voynich_nu_legacy_ivtff/` but not yet parsed. They use IVTFF ≤1.7 conventions.
- **No cross-alphabet mapping** (Currier / FSG / v101 → EVA) is provided. LSI C/F lines are Stolfi's 1990s EVA
  conversions of Currier/FSG and are the only EVA view of those witnesses.
- `rf1b_e` / `rf1b_er` are database-generated reference files (one reading per position), not independent witnesses.
- `derived.witness_agreement` uses one normalization (`eva_basic_v1`). Agreement rates depend heavily on
  normalization; e.g. ZL3b vs IT2a = 47.5% token-identical lines here. Notes circulating online quoting
  "29.3% fully identical" (attributed to a "VCAT" project) could not be traced to any public source.

## Evidence not obtained
- **NSA Voynich index PDF**: nsa.gov blocks non-browser clients and there is no Wayback snapshot. Registered;
  download by hand into `evidence/nsa_voynich_index/` and change `acquisition` to `manual`.
- **Multispectral imaging** (Beinecke; L. F. Davis 2024 work on f1r) — raw data not public. Registered.
- **McCrone figures/spectra** were never released by Yale; only the text + Table I. The PDF is a scan (no text
  layer): Table I was transcribed by hand into `curation/material_evidence.yaml` (`review_status: unreviewed`).
- **Radiocarbon** numbers come from a secondary source (voynich.nu, quoting Hodgins' 2012 presentation).
  The calibrated 95% interval there is **1404–1438**. The figure "1435" on the same page is the mean of the
  *uncalibrated* dates; "1404–1435" is a misquote.
- McCrone samples on **f70v** and **f86v** don't say which foldout panel; `page_id` is null.
- Yale masters are the IIIF full-size **JPEGs** (same pixel dimensions as the TIFFs Archetype used, but lossy).
- The Archetype 1.9 GB image tarball was not fetched (duplicates Yale; dimensions match exactly).

## Not built yet (see ROADMAP.md)
- Line/path polygons, glyph boxes and gap measurements for transliteration loci (only Archetype's 1,684 glyphs exist).
- Illustration object layer, colour measurements, layout graph, reading-order schemes.
- Comparator corpora (registered as `deferred`).
