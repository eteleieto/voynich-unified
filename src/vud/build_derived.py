"""E3: derived, exactly reproducible features. Every table gets a recipe row in derived/_recipes.parquet.

  witness_agreement.parquet   per locus, per pair of EVA-alphabet witnesses: exact match, normalized
                              Levenshtein similarity, token-count agreement, boundary-position agreement
  locus_coverage.parquet      per locus: which witnesses (all alphabets) attest it and their token counts
  token_frequencies.parquet   token type frequencies per witness under a named normalization
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import subprocess
from datetime import datetime, timezone
from itertools import combinations

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from rapidfuzz.distance import Levenshtein

from . import paths, registry

# Witnesses that write (some variant of) EVA and can be compared character-by-character.
EVA_WITNESSES = ["zl3b", "it2a", "rf1b_er", "lsi_16e6:H", "lsi_16e6:U", "lsi_16e6:V", "lsi_16e6:N",
                 "lsi_16e6:C", "lsi_16e6:F"]
# NB: LSI C and F are EVA *conversions* (by Stolfi) of Currier and FSG transcriptions; cd2a / fg2a are the
# same transcriptions in their native alphabets.

NORMALIZATIONS = {
    "eva_basic_v1": "first alternative; ligature braces dropped; rare glyphs @nnn; -> '*'; unreadable -> '?'; "
                    "lower-case; separators removed for glyph comparison",
}


def norm_eva_basic_v1(tok_text: str) -> str:
    return re.sub(r"@\d{3};|&[^ ]*", "*", tok_text).lower()


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(paths.ROOT), "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def _input_hashes(source_ids) -> dict:
    return {r["path"]: r["sha256"] for r in registry.read_manifest() if r["source_id"] in source_ids}


def _code_hash(fn) -> str:
    return hashlib.sha256(inspect.getsource(fn).encode()).hexdigest()[:16]


def _boundaries(tokens: list[str]) -> set[int]:
    """Character offsets (in the separator-free glyph string) at which a word boundary falls."""
    out, pos = set(), 0
    for t in tokens[:-1]:
        pos += len(t)
        out.add(pos)
    return out


def build() -> dict:
    paths.DERIVED.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    tok = con.sql(f"""
        select witness_id, ivtff_locus_id, list(text order by token_idx) as toks
        from '{paths.ANNOTATIONS / "tokens.parquet"}'
        where ivtff_locus_id is not null and witness_id in ({",".join(repr(w) for w in EVA_WITNESSES)})
        group by 1, 2""").fetchall()
    by_locus: dict[tuple[str, str], dict[str, list[str]]] = {}
    for wid, lid, toks in tok:
        by_locus.setdefault(("native_eva", lid), {})[wid] = [norm_eva_basic_v1(t) for t in toks]
    common = paths.DERIVED / "common_eva_tokens.parquet"
    if common.exists():
        for wid, lid, toks in con.sql(f"""select witness_id, locus_id, list(text order by token_idx)
                                          from '{common}' group by 1, 2""").fetchall():
            by_locus.setdefault(("common_basic_eva", lid), {})[wid] = [norm_eva_basic_v1(t) for t in toks]

    rows = []
    for (space, lid), wit in by_locus.items():
        for a, b in combinations(sorted(wit), 2):
            ta, tb = wit[a], wit[b]
            sa, sb = "".join(ta), "".join(tb)
            ba, bb = _boundaries(ta), _boundaries(tb)
            union = ba | bb
            rows.append({
                "locus_id": lid, "page_id": lid.rsplit(".", 1)[0], "witness_a": a, "witness_b": b,
                "glyphs_a": sa, "glyphs_b": sb,
                "exact_glyphs": sa == sb, "exact_tokens": ta == tb,
                "glyph_similarity": Levenshtein.normalized_similarity(sa, sb),
                "glyph_edit_distance": Levenshtein.distance(sa, sb),
                "n_tokens_a": len(ta), "n_tokens_b": len(tb),
                # boundary agreement is only meaningful when the glyph strings are identical
                "boundary_jaccard": (len(ba & bb) / len(union) if union else 1.0) if sa == sb else None,
                "normalization": "eva_basic_v1", "comparison_space": space,
            })
    pq.write_table(pa.Table.from_pylist(rows), paths.DERIVED / "witness_agreement.parquet")

    con.sql(f"""
        copy (
          select ivtff_locus_id as locus_id, any_value(page_id) as page_id,
                 list(distinct witness_id order by witness_id) as witnesses,
                 count(distinct witness_id) as n_witnesses,
                 map_from_entries(list((witness_id, n_tokens))) as n_tokens_by_witness
          from (select ivtff_locus_id, any_value(page_id) page_id, witness_id, sum(n_tokens) n_tokens
                from '{paths.ANNOTATIONS / "loci.parquet"}' where ivtff_locus_id is not null group by 1, 3)
          group by ivtff_locus_id
        ) to '{paths.DERIVED / "locus_coverage.parquet"}' (format parquet)""")

    tf = con.sql(f"""
        select witness_id, text as token, count(*) as n
        from '{paths.ANNOTATIONS / "tokens.parquet"}' group by 1, 2""").fetchall()
    pq.write_table(pa.Table.from_pylist([
        {"witness_id": w, "token_raw_first_reading": t, "n": n} for w, t, n in tf
    ]), paths.DERIVED / "token_frequencies.parquet")

    recipes = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    srcs = ["zl3b", "it2a", "rf1b_er", "lsi_16e6", "cd2a", "fg2a", "gc2a", "rf1b_e", "sta1_transliterations",
            "bitrans_tool", "voynich_nu_legacy_ivtff"]
    for name, params in [
        ("witness_agreement", {"witnesses": EVA_WITNESSES, "plus": "all beva:* witnesses (comparison_space=common_basic_eva)",
                               "normalization": "eva_basic_v1",
                               "normalization_desc": NORMALIZATIONS["eva_basic_v1"],
                               "similarity": "rapidfuzz Levenshtein.normalized_similarity"}),
        ("locus_coverage", {"all_witnesses": True}),
        ("token_frequencies", {"token_text": "ivtff.plain(first alternative)"}),
        ("common_eva_loci", {"tool": "bitrans (compiled from evidence)", "rules": "STA-Eva_Bint.bit",
                             "see": "data/derived/common_eva/_recipe.txt"}),
        ("common_eva_tokens", {"tool": "bitrans", "rules": "STA-Eva_Bint.bit"}),
        ("version_diffs", {"code": "vud.build_legacy", "lineages": "ZL, IT/TT, CD, FG, GC, RF"}),
        ("reading_order_schemes", {"code": "vud.build_orders.build_orders"}),
        ("reading_order_items", {"code": "vud.build_orders.build_orders",
                                 "inputs": "annotations.loci file order; observations.spatial_*"}),
        ("glyph_features", {"code": "vud.build_orders.build_glyph_features", "method_version": "glyphfeat-v1",
                            "binarization": "Otsu on 6px-padded bbox crop of the full-res canvas"}),
    ]:
        recipes.append({"table": name, "code": "vud.build_derived.build", "code_sha": _code_hash(build),
                        "git_commit": _git_commit(), "parameters_json": json.dumps(params),
                        "input_sha256_json": json.dumps(_input_hashes(srcs)), "created_at": now})
    pq.write_table(pa.Table.from_pylist(recipes), paths.DERIVED / "_recipes.parquet")
    return {"agreement_rows": len(rows), "loci": len(by_locus)}
