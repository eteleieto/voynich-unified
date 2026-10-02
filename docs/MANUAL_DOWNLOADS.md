# Manual downloads (things only a human can get)

Everything that a script can fetch, `uv run vud fetch` already fetches. The items below are blocked
(anti-bot), need a request to an institution, or need an account. Check status with:

```bash
uv run vud manual
```

After placing files, register them (hashes them into `evidence/MANIFEST.tsv`, makes them read-only), then rebuild:

```bash
uv run vud register-manual <source_id>
```

```bash
uv run vud build
```

---

## 1. NSA Voynich index — `nsa_voynich_index`  (5 min)
nsa.gov rejects non-browser clients. In a normal browser open
<https://www.nsa.gov/portals/75/documents/news-features/declassified-documents/voynich/nsa-index-for-attempts-to-decipher-the-voynich-manuscript.pdf>
and save it as `evidence/nsa_voynich_index/nsa_voynich_index.pdf`.

## 2. Other NSA Voynich documents — `nsa_voynich_collection`  (15 min)
From the NSA declassified documents pages, save any Voynich items (e.g. *Proceedings of a Seminar on the
Voynich Manuscript*, 1976, ed. M. D'Imperio; Friedman collection Voynich items) into
`evidence/nsa_voynich_collection/`. Keep the original filenames. Already in the workspace (skip these):
D'Imperio *Elegant Enigma* (1978), Tiltman (1967), D'Imperio cluster-analysis paper.

## 3. Lossless TIFF masters — `beinecke_ms408_tiffs`  (request; days–weeks)
Ask Beinecke reproduction services for the archival TIFFs of Beinecke MS 408 (all 213 images of
Yale digital object 2002046). The IIIF JPEGs here are lossy; TIFFs share the same pixel grid, so all geometry
in this workspace stays valid. Save as `evidence/beinecke_ms408_tiffs/<seq>_<iiif-id>.tif` (same names as
`evidence/yale_ms408_iiif_2014/images/`, `.tif` extension).

## 4. Raw multispectral bands — `lazarus_msi_raw_2014`  (request)
Ask the Beinecke (and/or the Lazarus Project, Univ. of Rochester) for the 2014 multispectral captures of
f1r, f8r, f17r, f26r, f47r, f70v1, f71r, f93r, f102v1, f116v. Keep their folder structure under
`evidence/lazarus_msi_raw_2014/`. Processed composites published by L. F. Davis are already in
`evidence/msi_lazarus_2014_davis_2024/`.

---

### Suggested request text (items 3–4)
> I am assembling a provenance-tracked research dataset on Beinecke MS 408 for computational study
> (non-commercial). Could the Library supply (a) the archival TIFF masters for digital object 2002046 and
> (b) the 2014 multispectral image captures of folios 1r, 8r, 17r, 26r, 47r, 70v1, 71r, 93r, 102v1 and 116v,
> with any capture metadata (wavelengths, illumination, calibration)? I will cite the Library and observe
> any terms of use.
