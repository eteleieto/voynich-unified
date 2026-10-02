# Known issues, gaps and judgement calls (VUD 0.2)

Everything here is deliberate or unresolved. Nothing has been silently "fixed" in the data.

## Machine layers (spatial-v1, visual-v1) — unreviewed proposals
- **Coverage:** ZL3b *paragraph* loci (types P*) are aligned to detected rows (4,093 of 4,140). Labels (L*),
  circular (C*) and radial (R*) text are not aligned; their ink is in `spatial_ink_components`/`spatial_text_rows`.
- **Row geometry:** rows are found by a deskewed baseline projection; boxes include ascenders, may clip a word
  or straddle a neighbouring line on dense pages, and occasionally include a sliver of the facing page
  (fragments outside the page's text block are flagged `fragments_detached`). Check `spatial_page_qa`.
- **Alignment:** monotone DP on row width vs. glyph count. Median per-page width/glyph-count correlation 0.69;
  101 pages > 0.7. Pages with drawings interleaved with text are the weakest. `confidence = exp(-2.5·cost)`.
- **Boundary → gap matching** prefers large gaps by construction (it explains k boundaries with k gaps). Use it
  for *relative* comparisons between boundary kinds/witnesses/scribes; the `nearest_gap_*` columns are the
  naive proportional baseline. Gap sizes are in units of the page's median glyph height (`gap_norm`).
- **Visual objects:** colour-threshold segmentation at ¼ resolution. Faint washes, offsets and stains are mostly
  (not always) excluded; touching leaves merge; `n_lobes_convexity` is a crude shape count.
- Review them: `vud.contrib.review_machine_observation`, queue `vud task next --kind review_alignment`.

## Registration / mapping
- **Yale canvas 165 is labelled "90r" by Yale** but 90r is on canvas 164. Archetype labels it `90v2` and its 8
  visible lines match ZL3b f90v2. Mapped to `f90v2`, confidence 0.8.
- **Foldout panel boxes** (`codicology.canvas_pages.region_xywh`) are by-eye estimates (±3% of canvas width).
- **f101r / f101v** are single logical pages in ZL3b; Yale photographs f101v in two pieces (role `partial`).
- **Archetype image "54v"** (2979 px wide) ≠ Yale 54v (2999 px): 12 glyph polygons left unregistered.
- **LSI → IVTFF locus map:** 399 of 17,357 LSI lines unmapped; LSI uses 3 page names IVTFF does not.
- **Davis 2024 MSI composites** are not yet registered geometrically onto the Yale canvases.

## Transliterations
- STA1 files and `bitrans` are Zandbergen's; the `beva:*` common-alphabet witnesses use his STA→basic-Eva
  rules, which deliberately merge rare glyphs. Use `sta1:*` when a rare-glyph distinction matters.
- `VT0e` (STA "VT", source no. 4) is undocumented on voynich.nu; empirically 97.9% token-identical to IT2a.
- `rf1b_*`, STA renderings, LSI D/G/I/Q/M and VT0e are not independent witnesses (`annotations.witnesses`).
- Agreement rates depend on normalization; ZL3b vs IT2a = 47.5% token-identical lines (native) / 48.2%
  (common basic Eva). A "29.3% identical (VCAT)" figure circulating online could not be traced to any source.

## Evidence not obtained (see docs/MANUAL_DOWNLOADS.md, `uv run vud manual`)
- NSA Voynich index and other NSA PDFs (nsa.gov blocks scripts), lossless Beinecke TIFFs, raw 2014 MSI bands.
- McCrone figures/spectra were never released; Table I was transcribed by hand (`review_status: unreviewed`).
- Radiocarbon numbers come from a secondary source (voynich.nu quoting Hodgins 2012): calibrated 95%
  **1404–1438** ("1435" on that page is the mean of the *uncalibrated* dates).
- McCrone samples on f70v and f86v don't state the foldout panel (`page_id` null).
- Yale masters are lossy IIIF JPEGs (same pixel grid as the TIFFs).

## Comparators
- Corpus Corporum: only texts the site marks accessible were harvested (89 Latin texts, ~6.2 M words).
- Gutenberg editions are modern editions of medieval texts (normalised spelling in places).
- Digital Scriptorium is a finding aid only (id, shelfmark, title, place, date).
- Curious Cures and Biblissima remain `deferred` (no bulk export found).
