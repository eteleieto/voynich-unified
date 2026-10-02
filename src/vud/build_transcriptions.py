"""E2: build transliteration tables from every IVTFF / EVT source.

Outputs (data/annotations/):
  witnesses.parquet          one row per (source, transcriber) witness
  loci.parquet               one row per locus per witness, verbatim raw line retained
  units.parquet              every parsed unit (glyph, separator, comment, alternative...) in order
  tokens.parquet             glyph runs between separators, with boundary types
  page_variables.parquet     page header variables per source ($Q $I $L $H ...), as observations
  source_comments.parquet    every '#' comment line in every file (transcriber notes are evidence)
"""
from __future__ import annotations

import gzip
import json

import pyarrow as pa
import pyarrow.parquet as pq

from . import ivtff, paths, registry

IVTFF_SOURCES = {
    "zl3b": "ZL3b-n.txt",
    "it2a": "IT2a-n.txt",
    "cd2a": "CD2a-n.txt",
    "fg2a": "FG2a-n.txt",
    "gc2a": "GC2a-n.txt",
    "rf1b_e": "RF1b-e.txt",
    "rf1b_er": "RF1b-er.txt",
}
LEGACY_SOURCE = "voynich_nu_legacy_ivtff"
LSI_SOURCE = "lsi_16e6"

# Transcriber codes documented in the LSI file header (section <f0.I>), verbatim meaning.
LSI_TRANSCRIBERS = {
    "C": "Currier (+ later additions, voynich.now)",
    "F": "Friedman First Study Group (FSG.NEW)",
    "T": "John Tiltman (some pages)",
    "L": "Don Latham (some pages)",
    "R": "Mike Roe (some pages)",
    "K": "Karl Kluge (labels, from Petersen copies)",
    "J": "Jim Reeds (previously unreadable characters)",
    "D": "second choice from [|] in C lines",
    "G": "second choice from [|] in F lines",
    "I": "second choice from [|] in J lines",
    "Q": "second choice from [|] in K lines",
    "M": "second choice from [|] in L lines",
    "H": "Takeshi Takahashi (full transcription)",
    "N": "Gabriel Landini",
    "U": "Jorge Stolfi",
    "V": "John Grove",
    "P": "Father Th. Petersen (via K. Kluge)",
    "X": "Denis V. Mardle",
    "Z": "Rene Zandbergen",
}


def _witness_id(source_id: str, transcriber: str | None) -> str:
    return f"{source_id}:{transcriber}" if transcriber else source_id


def _locus_text(units, toks) -> str:
    """Compact reading: first alternatives, '.' certain / ',' uncertain / '-' drawing boundaries."""
    out = []
    for t in toks:
        b = t["boundary_before"]
        if out:
            out.append("," if "uncertain" in b else "-" if "drawing" in b else ".")
        out.append(t["text"])
    return "".join(out)


def _collect(source_id, pf, rows):
    loci, units, toks, pvars, comments = rows
    alphabet = pf.alphabet
    for p in pf.pages:
        for k, v in p.variables.items():
            pvars.append({"source_id": source_id, "page_id": p.page_id, "variable": k, "value": v,
                          "file_line": p.file_line, "raw_header": p.raw_header})
    for c in pf.comments:
        comments.append({"source_id": source_id, "page_id": c.page_id, "after_locus_id": c.after_locus,
                         "file_line": c.file_line, "text": c.text})
    for L in pf.loci:
        wid = _witness_id(source_id, L.transcriber)
        # LSI line numbers restart inside each unit (P1, L1, ...): keep the native id; IVTFF mapping is separate
        locus_id = f"{L.page_id}.{L.lsi_unit}.{L.locus_num}" if L.lsi_unit else f"{L.page_id}.{L.locus_num}"
        tk = ivtff.tokens(L.units)
        unit_tok = {}
        for ti, t in enumerate(tk):
            for k in range(t["unit_start"], t["unit_end"] + 1):
                unit_tok[k] = ti
        kinds = [u.kind for u in L.units]
        loci.append({
            "witness_id": wid, "source_id": source_id, "transcriber": L.transcriber,
            "alphabet": alphabet, "page_id": L.page_id, "locus_num": L.locus_num, "locus_id": locus_id,
            "ivtff_locus_id": None if L.lsi_unit else locus_id,
            "locator": L.locator, "locus_type": L.locus_type, "lsi_unit": L.lsi_unit,
            "file_line": L.file_line, "raw_line": L.raw_line, "text_raw": L.text_raw,
            "text": _locus_text(L.units, tk), "n_tokens": len(tk),
            "para_start": "para_start" in kinds, "para_end": "para_end" in kinds,
            "n_alt": kinds.count("alt"), "n_unread": kinds.count("unread") + kinds.count("unread_run"),
            "n_uncertain_space": sum(1 for u in L.units if u.kind == "sep" and u.value == "uncertain_space"),
            "tags_json": json.dumps(L.tags, sort_keys=True),
        })
        for ui, u in enumerate(L.units):
            units.append({
                "witness_id": wid, "source_id": source_id, "locus_id": locus_id, "unit_idx": ui,
                "kind": u.kind, "raw": u.raw, "value": u.value, "options": u.options,
                "char_start": u.start, "char_end": u.end, "token_idx": unit_tok.get(ui),
            })
        n = len(tk)
        for ti, t in enumerate(tk):
            toks.append({
                "witness_id": wid, "source_id": source_id, "alphabet": alphabet, "page_id": L.page_id,
                "locus_id": locus_id, "ivtff_locus_id": None if L.lsi_unit else locus_id,
                "locus_type": L.locus_type, "token_idx": ti,
                "is_line_initial": ti == 0, "is_line_final": ti == n - 1,
                **{k: t[k] for k in ("raw", "text", "boundary_before", "boundary_after", "n_glyph_units",
                                     "has_alt", "has_unread", "has_rare", "has_lig", "has_filler",
                                     "n_readings", "unit_start", "unit_end")},
            })


def map_lsi_to_ivtff(loci: list[dict]) -> dict[str, dict]:
    """Map native LSI loci (page.unit.num) to IVTFF loci (page.num).

    it2a is Zandbergen's IVTFF extraction of the LSI Takahashi ('H') lines, so the H text of an LSI line
    identifies its IVTFF locus. Per page: exact unique text match first, then best fuzzy match >= 0.85
    among still-unmatched IT2a loci. Lines without an H reading stay unmapped.
    """
    from rapidfuzz.distance import Levenshtein

    def norm(t: str) -> str:
        return t.replace(",", ".").replace("-", ".")

    it = {}
    for r in loci:
        if r["source_id"] == "it2a":
            it.setdefault(r["page_id"], []).append((r["locus_id"], norm(r["text"])))
    h = {}
    for r in loci:
        if r["witness_id"] == f"{LSI_SOURCE}:H":
            h.setdefault(r["page_id"], []).append((r["locus_id"], norm(r["text"])))
    out = {}
    for page, hl in h.items():
        cands = list(it.get(page, []))
        used = set()
        texts = {}
        for lid, t in cands:
            texts.setdefault(t, []).append(lid)
        pending = []
        for lid, t in hl:
            hits = [x for x in texts.get(t, []) if x not in used]
            if len(texts.get(t, [])) == 1 and hits:
                out[lid] = {"ivtff_locus_id": hits[0], "method": "exact_text_H_vs_it2a", "similarity": 1.0}
                used.add(hits[0])
            else:
                pending.append((lid, t))
        for lid, t in pending:
            best = max(((Levenshtein.normalized_similarity(t, ct), cid) for cid, ct in cands if cid not in used),
                       default=(0, None))
            if best[1] and best[0] >= 0.85:
                out[lid] = {"ivtff_locus_id": best[1], "method": "fuzzy_text_H_vs_it2a", "similarity": best[0]}
                used.add(best[1])
    return out


def build() -> dict:
    paths.ANNOTATIONS.mkdir(parents=True, exist_ok=True)
    rows = ([], [], [], [], [])
    witnesses = []
    problems = {}
    srcs = {s["source_id"]: s for s in registry.load_sources()}

    for sid, fname in IVTFF_SOURCES.items():
        pf = ivtff.parse_ivtff((paths.evidence_dir(sid) / fname).read_text(encoding="latin-1"))
        problems[sid] = pf.problems
        _collect(sid, pf, rows)
        witnesses.append({"witness_id": sid, "source_id": sid, "transcriber": None,
                          "alphabet": pf.alphabet, "file_header": pf.header,
                          "description": srcs[sid]["name"], "is_independent": sid not in ("rf1b_e", "rf1b_er")})

    raw = gzip.open(paths.evidence_dir(LSI_SOURCE) / "text16e6.evt.gz").read().decode("latin-1")
    pf = ivtff.parse_evt(raw)
    problems[LSI_SOURCE] = pf.problems
    _collect(LSI_SOURCE, pf, rows)
    for tr in sorted({L.transcriber for L in pf.loci}):
        witnesses.append({"witness_id": _witness_id(LSI_SOURCE, tr), "source_id": LSI_SOURCE, "transcriber": tr,
                          "alphabet": "Eva-", "file_header": None,
                          "description": LSI_TRANSCRIBERS.get(tr, "undocumented code"),
                          # D/G/I/Q/M are second readings of another witness, not independent witnesses
                          "is_independent": tr not in ("D", "G", "I", "Q", "M")})

    loci, units, toks, pvars, comments = rows
    lsi_map = map_lsi_to_ivtff(loci)
    for r in loci:
        if r["source_id"] == LSI_SOURCE:
            r["ivtff_locus_id"] = lsi_map.get(r["locus_id"], {}).get("ivtff_locus_id")
    for r in toks:
        if r["source_id"] == LSI_SOURCE:
            r["ivtff_locus_id"] = lsi_map.get(r["locus_id"], {}).get("ivtff_locus_id")
    unit_schema = pa.schema([
        ("witness_id", pa.string()), ("source_id", pa.string()), ("locus_id", pa.string()),
        ("unit_idx", pa.int32()), ("kind", pa.string()), ("raw", pa.string()), ("value", pa.string()),
        ("options", pa.list_(pa.string())), ("char_start", pa.int32()), ("char_end", pa.int32()),
        ("token_idx", pa.int32()),
    ])
    out = paths.ANNOTATIONS
    pq.write_table(pa.Table.from_pylist(witnesses), out / "witnesses.parquet")
    pq.write_table(pa.Table.from_pylist(loci), out / "loci.parquet")
    pq.write_table(pa.Table.from_pylist(units, schema=unit_schema), out / "units.parquet")
    pq.write_table(pa.Table.from_pylist(toks), out / "tokens.parquet")
    pq.write_table(pa.Table.from_pylist(pvars), out / "page_variables.parquet")
    pq.write_table(pa.Table.from_pylist(comments), out / "source_comments.parquet")
    pq.write_table(pa.Table.from_pylist(
        [{"lsi_locus_id": k, **v} for k, v in sorted(lsi_map.items())]), out / "lsi_locus_map.parquet")
    return {k: len(v) for k, v in zip(["loci", "units", "tokens", "page_variables", "comments"], rows)} | {
        "problems": sum(len(v) for v in problems.values())}
