"""E1 (machine): run vud.spatial over every canvas and write observation tables.

data/observations/
  spatial_ink_components.parquet   every ink blob on every canvas (full-res px, mean Lab)
  spatial_text_rows.parquet        detected text rows (bbox, baseline, fragments, glyph height)
  spatial_locus_alignment.parquet  ZL3b paragraph locus -> row, with cost and confidence
  spatial_row_gaps.parquet         gaps between ink clusters along each aligned row
  spatial_boundary_gaps.parquet    each witness's token boundary -> physical gap (size, rank, in_top_k)
  spatial_page_qa.parquet          per page: rows, aligned loci, mean cost, width/units correlation
  spatial_token_spans.parquet      per witness token on aligned rows: pixel box between its matched gaps
All rows: method=vud.spatial, method_version=spatial-v1, review_status=unreviewed.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from . import paths, spatial

WITNESSES = ["zl3b", "it2a", "gc2a", "fg2a", "cd2a", "rf1b_er"]


def _jobs() -> list[dict]:
    con = duckdb.connect()
    A, C = paths.ANNOTATIONS, paths.CODICOLOGY
    loci = con.sql(f"""
        select l.page_id, l.locus_id, l.locus_type, l.locus_num,
               (select count(*) from '{A / "units.parquet"}' u
                 where u.witness_id = 'zl3b' and u.locus_id = l.locus_id
                   and u.kind in ('char','rare','lig','alt','unread','unread_run')) as n_units
        from '{A / "loci.parquet"}' l where l.witness_id = 'zl3b'
        order by l.page_id, try_cast(l.locus_num as int)""").fetchall()
    toks = con.sql(f"""
        select witness_id, locus_id, list(n_glyph_units order by token_idx), list(boundary_after order by token_idx)
        from '{A / "tokens.parquet"}' where witness_id in ({",".join(repr(w) for w in WITNESSES)})
        group by 1, 2""").fetchall()
    by_locus = {}
    for wid, lid, units, after in toks:
        by_locus.setdefault(lid, []).append({"witness_id": wid, "token_units": units, "boundary_kinds": after[:-1]})
    page_loci = {}
    for page_id, lid, ltype, _num, n in loci:
        page_loci.setdefault(page_id, []).append({"locus_id": lid, "locus_type": ltype, "n_units": n,
                                                  "witnesses": by_locus.get(lid, [])})
    jobs = {}
    for seq, path, w, h, page_id, region, role in con.sql(f"""
            select c.seq, c.local_path, c.width, c.height, m.page_id, m.region_xywh, m.role
            from '{C / "canvas_pages.parquet"}' m join '{C / "canvases.parquet"}' c using (seq)
            order by seq""").fetchall():
        j = jobs.setdefault(seq, {"seq": seq, "local_path": path, "width": w, "height": h, "pages": []})
        j["pages"].append({"page_id": page_id, "region_xywh": region, "role": role,
                           "loci": page_loci.get(page_id, [])})
    return list(jobs.values())


def build(workers: int | None = None) -> dict:
    jobs = _jobs()
    agg = {k: [] for k in ("components", "rows", "alignment", "gaps", "boundaries", "qa", "tokens")}
    with ProcessPoolExecutor(max_workers=workers or max(1, (os.cpu_count() or 2) - 1)) as ex:
        for res in ex.map(spatial.process_canvas, jobs, chunksize=1):
            for k in agg:
                agg[k] += res[k]
    out = paths.OBSERVATIONS
    out.mkdir(parents=True, exist_ok=True)
    meta = {"method": spatial.METHOD, "method_version": spatial.METHOD_VERSION, "review_status": "unreviewed"}

    cols = ["seq", "component_idx", "x0", "y0", "w", "h", "area_px", "cx", "cy", "lab_L", "lab_a", "lab_b"]
    comp_tbl = pa.table({c: [r[i] for r in agg["components"]] for i, c in enumerate(cols)})
    pq.write_table(comp_tbl, out / "spatial_ink_components.parquet")
    for name, key in [("spatial_text_rows", "rows"), ("spatial_locus_alignment", "alignment"),
                      ("spatial_row_gaps", "gaps"), ("spatial_boundary_gaps", "boundaries"),
                      ("spatial_page_qa", "qa"), ("spatial_token_spans", "tokens")]:
        rows = [{**r, **meta} for r in agg[key]]
        pq.write_table(pa.Table.from_pylist(rows), out / f"{name}.parquet")
    return {k: len(v) for k, v in agg.items()}
