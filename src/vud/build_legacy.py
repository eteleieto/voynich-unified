"""E2 (history): superseded IVTFF releases, kept apart from current witnesses.

  annotations/legacy_loci.parquet      every locus of every superseded release (raw line + compact text)
  derived/version_diffs.parquet        per lineage step (older -> newer release) and locus: changed?, texts,
                                       edit distance. Editorial change between releases is itself evidence
                                       of where readings are hard.
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
from rapidfuzz.distance import Levenshtein

from . import ivtff, paths
from .build_transcriptions import IVTFF_SOURCES, _locus_text

LEGACY = "voynich_nu_legacy_ivtff"
# (lineage, release label, file, source_id); ordered oldest -> newest within each lineage
LINEAGES = {
    "ZL": [("ZL 1r", "ZL_ivtff_1r.txt", LEGACY), ("ZL 2b", "ZL_ivtff_2b.txt", LEGACY),
           ("ZL 3a", "ZL3a-n.txt", LEGACY), ("ZL 3b", IVTFF_SOURCES["zl3b"], "zl3b")],
    "IT": [("TT v0a", "TT_ivtff_v0a.txt", LEGACY), ("IT 1a", "IT_ivtff_1a.txt", LEGACY),
           ("IT 2a", IVTFF_SOURCES["it2a"], "it2a")],
    "CD": [("CD 1a", "CD_ivtff_1a.txt", LEGACY), ("CD 2a", IVTFF_SOURCES["cd2a"], "cd2a")],
    "FG": [("FG 1e", "FG_ivtff_1e.txt", LEGACY), ("FG 2a", IVTFF_SOURCES["fg2a"], "fg2a")],
    "GC": [("GC 1b", "GC_ivtff_1b.txt", LEGACY), ("GC 2a", IVTFF_SOURCES["gc2a"], "gc2a")],
    "RF": [("RF 1a", "RF1a-n.txt", LEGACY), ("RF 1b", IVTFF_SOURCES["rf1b_e"], "rf1b_e")],
}


def _parse(fname, sid):
    pf = ivtff.parse_ivtff((paths.evidence_dir(sid) / fname).read_text(encoding="latin-1"))
    out = {}
    for L in pf.loci:
        tk = ivtff.tokens(L.units)
        out[f"{L.page_id}.{L.locus_num}"] = (L, _locus_text(L.units, tk), len(tk))
    return pf, out


def build() -> dict:
    loci_rows, diff_rows = [], []
    for lineage, steps in LINEAGES.items():
        parsed = []
        for label, fname, sid in steps:
            pf, loci = _parse(fname, sid)
            parsed.append((label, loci))
            if sid == LEGACY:
                for lid, (L, text, n) in loci.items():
                    loci_rows.append({"source_id": sid, "release_file": fname, "release": label, "lineage": lineage,
                                      "file_header": pf.header, "alphabet": pf.alphabet, "page_id": L.page_id,
                                      "locus_id": lid, "locator": L.locator, "locus_type": L.locus_type,
                                      "file_line": L.file_line, "raw_line": L.raw_line, "text_raw": L.text_raw,
                                      "text": text, "n_tokens": n})
        for (la, A), (lb, B) in zip(parsed, parsed[1:]):
            for lid in sorted(set(A) | set(B)):
                ta = A[lid][1] if lid in A else None
                tb = B[lid][1] if lid in B else None
                diff_rows.append({
                    "lineage": lineage, "from_release": la, "to_release": lb, "locus_id": lid,
                    "page_id": lid.rsplit(".", 1)[0],
                    "change": "added" if ta is None else "removed" if tb is None else
                              ("unchanged" if ta == tb else "edited"),
                    "text_from": ta, "text_to": tb,
                    "edit_distance": Levenshtein.distance(ta, tb) if ta is not None and tb is not None else None,
                    "raw_from": A[lid][0].text_raw if lid in A else None,
                    "raw_to": B[lid][0].text_raw if lid in B else None,
                })
    pq.write_table(pa.Table.from_pylist(loci_rows), paths.ANNOTATIONS / "legacy_loci.parquet")
    paths.DERIVED.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(diff_rows), paths.DERIVED / "version_diffs.parquet")
    return {"legacy_loci": len(loci_rows), "diff_rows": len(diff_rows),
            "edited": sum(r["change"] == "edited" for r in diff_rows)}
