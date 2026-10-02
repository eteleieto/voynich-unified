# Roadmap

## Done
- **0.1** source registry, sha256 evidence, lossless IVTFF/EVT parsing (25 witnesses), codicology + foldout
  canvas map, Archetype glyph registration, material science, agreement index, contribution layers, CLI, tests.
- **0.2** legacy releases + version diffs; STA1 witnesses + author's bitrans common alphabet (all traditions
  comparable); conjugate leaves; spatial-v1 (ink components, text rows, paragraph-locus alignment, gaps,
  boundary→gap matching); visual-v1 (pigment/drawing objects, colour raw+normalised, layout graph); plural
  reading orders; glyph palaeographic features; comparator corpora (Latin science/medicine, vernaculars, Copiale,
  pseudo-text, Digital Scriptorium, Opera medicinalia 1448); MS 408A papers incl. the Marci letter; Davis 2024 MSI
  composites; task queue, review API, subagent roles, orchestration guide; manual-download workflow.

## Next (highest value first)
1. **Review loop on the machine layers** — run the review_alignment / review_objects queues (see
   docs/ORCHESTRATION.md, Wave 0); then train spatial-v2 on reviewed rows.
2. **Label / circular / radial loci** — locate L*, C*, R* loci (ring detection on cosmological pages, label
   clustering near objects) and align them; currently only paragraph text is aligned.
3. **Glyph candidates within rows** — connected components → glyph hypotheses aligned to ZL units (DP on
   cumulative glyph counts), with Archetype's 1,684 glyphs as validation; then per-glyph palaeographic features.
4. **Register the MSI composites** onto Yale canvases (feature matching), and the lossless TIFFs when obtained.
5. **Comparators** — Curious Cures harvester; more cipher/shorthand controls (DECODE database needs an account);
   more vernaculars (Old Czech, Occitan, Catalan, Hebrew); IIIF images of further 15th-c. herbals.
6. **Codicology** — ruling, damage, stubs, sewing stations from visual inspection (observations with sources).

## Always
- Every new derived table registers a recipe; every release is frozen with `vud release`.
