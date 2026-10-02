# Roadmap

Ordered by value to decipherment work. Each phase lands as new E1/E2/E3 tables plus tests and a release bump.

## 0.2 — Spatial registration of the text (the largest gap)
1. **Line/path detection** per canvas (machine proposals as E1 observations, `method` + `model_version` recorded):
   ink binarization, baseline estimation, line polygons; radial/circular paths for C/R loci.
2. **Locus ↔ path alignment**: assign each ZL3b locus to a path polygon (order constraints from locator codes
   `@ + * = & ~ /` make this a constrained alignment problem). Human review status per row.
3. **Glyph candidate boxes** within paths (connected components + over/under-segmentation hypotheses kept as
   alternatives), aligned to ZL3b units; Archetype's 1,684 hand-checked glyphs serve as a validation set.
4. **Gap measurements** for every adjacent glyph pair (ink-to-ink distance, baseline gap, local median), then
   `boundary_observations` linking each gap to how ZL/IT/v101/FSG/Currier/LSI transcribed it (`.`, `,`, none).

## 0.3 — Illustrations and layout
- `visual_objects` (plant parts, stars, figures, containers, tubes, circles/sectors) as neutral polygons.
- `layout_relations` graph (above/inside/touches/nearest_label/connected_by_line) between objects and loci.
- `reading_order_schemes`: plural, explicit orderings for labels, wheels and the Rosettes.
- `color_measurements`: raw RGB samples + documented Lab normalization.

## 0.4 — Palaeography & codicology depth
- Parse legacy IVTFF releases; editorial-change diff tables between versions.
- Stroke-level features (slant, height, gallows geometry) on registered glyphs; competing hand assignments.
- Codicology: conjugate leaves, stubs, ruling, damage — each with source attribution.

## 0.5 — Comparators
- `comparative_documents` / `comparative_segments` schema populated from Curious Cures, Corpus Corporum,
  Digital Scriptorium, Biblissima; plus cipher/shorthand/abbreviation controls tagged by kind.

## Always
- Every new derived table registers a recipe; every release is frozen with `vud release`.
