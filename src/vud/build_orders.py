"""E3: plural reading orders + palaeographic glyph features.

derived/reading_order_schemes.parquet   scheme_id, scope (loci|pages), description, authority
derived/reading_order_items.parquet     scheme_id, page_id (null for page schemes), position, item_id
    Locus schemes: each transliteration's own file order; LSI file order (mapped to IVTFF ids);
    'spatial_v1_top_down' (aligned paragraph loci by detected baseline). Page schemes: current binding
    (IVTFF order) and Yale photography sequence. Add alternatives (clockwise vs anticlockwise wheels,
    Rosettes circle orders...) as new schemes; never reorder the loci tables themselves.
derived/glyph_features.parquet          per Archetype glyph: ink area, bbox aspect, stroke-width proxy
    (2 x mean distance transform), slant (ink second-moment orientation), height/width in px and in
    units of the page glyph height (from spatial rows).
"""
from __future__ import annotations

import cv2
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import paths

LOCUS_SCHEME_WITNESSES = ["zl3b", "it2a", "gc2a", "fg2a", "cd2a"]


def build_orders() -> dict:
    con = duckdb.connect()
    A, O, C = paths.ANNOTATIONS, paths.OBSERVATIONS, paths.CODICOLOGY
    schemes, items = [], []
    for w in LOCUS_SCHEME_WITNESSES:
        sid = f"{w}_file_order"
        schemes.append({"scheme_id": sid, "scope": "loci", "authority": w,
                        "description": f"order of loci as written in the {w} transliteration file"})
        for page, lid, pos in con.sql(f"""select page_id, locus_id, row_number() over (partition by page_id order by file_line)
                                           from '{A / "loci.parquet"}' where witness_id = ?""", params=[w]).fetchall():
            items.append({"scheme_id": sid, "page_id": page, "position": pos, "item_id": lid})
    schemes.append({"scheme_id": "lsi_file_order", "scope": "loci", "authority": "lsi_16e6 (H lines)",
                    "description": "Landini-Stolfi interlinear order of units/lines, mapped to IVTFF locus ids"})
    for page, lid, pos in con.sql(f"""select page_id, ivtff_locus_id, row_number() over (partition by page_id order by min(file_line))
                                       from '{A / "loci.parquet"}' where witness_id = 'lsi_16e6:H' and ivtff_locus_id is not null
                                       group by page_id, ivtff_locus_id""").fetchall():
        items.append({"scheme_id": "lsi_file_order", "page_id": page, "position": pos, "item_id": lid})
    if (O / "spatial_locus_alignment.parquet").exists():
        schemes.append({"scheme_id": "spatial_v1_top_down", "scope": "loci", "authority": "vud.spatial spatial-v1",
                        "description": "aligned paragraph loci sorted by detected row baseline (machine, unreviewed)"})
        for page, lid, pos in con.sql(f"""
                select a.page_id, a.locus_id, row_number() over (partition by a.page_id order by r.baseline_intercept + r.baseline_slope * (r.x0 + r.x1) / 2, r.x0)
                from '{O / "spatial_locus_alignment.parquet"}' a join '{O / "spatial_text_rows.parquet"}' r using (row_id)""").fetchall():
            items.append({"scheme_id": "spatial_v1_top_down", "page_id": page, "position": pos, "item_id": lid})
    schemes.append({"scheme_id": "binding_current", "scope": "pages", "authority": "zl3b page order",
                    "description": "pages in the current binding order (IVTFF / ZL3b)"})
    for page, pos in con.sql(f"select page_id, ivtff_order from '{C / 'pages.parquet'}'").fetchall():
        items.append({"scheme_id": "binding_current", "page_id": None, "position": pos, "item_id": page})
    schemes.append({"scheme_id": "yale_photo_sequence", "scope": "pages", "authority": "yale_ms408_iiif_2014",
                    "description": "pages in Yale IIIF canvas order (panel order within a canvas left->right)"})
    for page, pos in con.sql(f"""select page_id, row_number() over (order by min(seq), min(coalesce(region_xywh[1], 0)))
                                  from '{C / 'canvas_pages.parquet'}' group by page_id""").fetchall():
        items.append({"scheme_id": "yale_photo_sequence", "page_id": None, "position": pos, "item_id": page})
    pq.write_table(pa.Table.from_pylist(schemes), paths.DERIVED / "reading_order_schemes.parquet")
    pq.write_table(pa.Table.from_pylist(items), paths.DERIVED / "reading_order_items.parquet")
    return {"schemes": len(schemes), "items": len(items)}


def build_glyph_features() -> dict:
    con = duckdb.connect()
    rows = con.sql(f"""
        select g.annotation_id, g.yale_seq, c.local_path, g.x_min, g.y_min, g.x_max, g.y_max, g.allograph,
               g.hand_label, g.scribe
        from '{paths.ANNOTATIONS / "glyph_annotations.parquet"}' g
        join '{paths.CODICOLOGY / "canvases.parquet"}' c on c.seq = g.yale_seq order by g.yale_seq""").fetchall()
    hm = {}
    rp = paths.OBSERVATIONS / "spatial_text_rows.parquet"
    if rp.exists():
        hm = dict(con.sql(f"select seq, median(glyph_height_px) from '{rp}' group by 1").fetchall())
    out, cache = [], {}
    for aid, seq, path, x0, y0, x1, y1, allo, hand, scribe in rows:
        if path not in cache:
            cache = {path: cv2.imread(str(paths.ROOT / path), cv2.IMREAD_GRAYSCALE)}
        g = cache[path]
        pad = 6
        crop = g[max(0, int(y0) - pad):int(y1) + pad, max(0, int(x0) - pad):int(x1) + pad]
        if crop.size == 0:
            continue
        thr, ink = cv2.threshold(crop, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ys, xs = np.nonzero(ink)
        if len(xs) < 10:
            continue
        dt = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)
        cov = np.cov(np.vstack([xs, ys]))
        ev, evec = np.linalg.eigh(cov)
        major = evec[:, 1]
        slant = float(np.degrees(np.arctan2(major[0], major[1])))  # 0 = vertical, + = leaning right
        h_, w_ = float(np.ptp(ys) + 1), float(np.ptp(xs) + 1)
        out.append({"annotation_id": aid, "yale_seq": seq, "allograph": allo, "hand_label": hand, "scribe": scribe,
                    "ink_pixels": int(len(xs)), "ink_height_px": h_, "ink_width_px": w_, "aspect_w_h": w_ / h_,
                    "stroke_width_px": float(2 * dt[dt > 0].mean()), "slant_deg": slant,
                    "elongation": float(np.sqrt(ev[1] / max(ev[0], 1e-6))), "otsu_threshold": float(thr),
                    "height_rel_page_glyph": h_ / hm[seq] if hm.get(seq) else None,
                    "method_version": "glyphfeat-v1"})
    pq.write_table(pa.Table.from_pylist(out), paths.DERIVED / "glyph_features.parquet")
    return {"glyph_features": len(out)}


def build() -> dict:
    return {**build_orders(), **build_glyph_features()}
