"""E1 (machine): neutral visual-object, colour and layout observations. Nothing here names what a
shape depicts — 'green region with 5 lobes' is an observation, 'Artemisia' is a hypothesis.

data/observations/
  visual_objects.parquet     connected pigment regions (green / blue / red) and large ink drawings:
                             polygon (full-res px), bbox, area, solidity, n_holes, n_lobes (convexity defects)
  color_measurements.parquet per object: raw mean/std RGB from the unmodified scan + CIE Lab, and a
                             parchment-normalised Lab (von Kries scaling to the page's median parchment
                             colour) — method recorded; never written back over the source values
  layout_relations.parquet   text row -> nearby object (above/below/left/right/overlaps, distance) and
                             object <-> object (touches / inside)
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import cv2
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import paths, spatial

METHOD_VERSION = "visual-v1"
SCALE = 0.25  # pigment regions are large; quarter resolution is plenty
CLASSES = {
    "pigment_green": lambda a, b: a < -10,
    "pigment_blue": lambda a, b: (b < -8) & (a > -25),
    "pigment_red": lambda a, b: (a > 20),
}


def _rgb_lab_stats(img_bgr, lab, mask, white_lab):
    px = img_bgr[mask > 0].astype(np.float32)
    lp = lab[mask > 0].astype(np.float32)
    rgb_mean, rgb_std = px[:, ::-1].mean(0), px[:, ::-1].std(0)
    L = lp[:, 0] * 100 / 255; a = lp[:, 1] - 128; b = lp[:, 2] - 128
    # von Kries-like normalisation in Lab: shift a*/b* by the parchment cast, scale L* to parchment L*=95
    Ln = L * (95.0 / max(1.0, white_lab[0]))
    an, bn = a - white_lab[1], b - white_lab[2]
    return {"rgb_mean": rgb_mean.tolist(), "rgb_std": rgb_std.tolist(),
            "lab_mean": [float(L.mean()), float(a.mean()), float(b.mean())],
            "lab_norm_mean": [float(Ln.mean()), float(an.mean()), float(bn.mean())],
            "n_pixels_sampled": int(mask.sum())}


def process(job: dict) -> dict:
    inv = 1.0 / SCALE
    full = cv2.imread(str(paths.ROOT / job["local_path"]), cv2.IMREAD_COLOR)
    img = cv2.resize(full, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L, a, b = lab[..., 0], lab[..., 1].astype(np.int16) - 128, lab[..., 2].astype(np.int16) - 128
    leaf = (cv2.medianBlur(L, 31) > 60).astype(np.uint8)
    leaf = cv2.erode(leaf, np.ones((9, 9), np.uint8))
    # parchment reference: leaf pixels that are neither dark nor pigmented
    bg = cv2.medianBlur(L, 31)
    parch = (leaf > 0) & ((bg.astype(np.int16) - L) < 8) & (np.abs(a) < 12) & (b > -2)
    white = [float(np.median(L[parch])) * 100 / 255, float(np.median(a[parch])), float(np.median(b[parch]))] \
        if parch.any() else [90.0, 0.0, 10.0]
    objs, colors = [], []
    seq = job["seq"]
    k = 0
    masks = {}
    for cls, rule in CLASSES.items():
        m = (rule(a, b) & (leaf > 0)).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        masks[cls] = m
    # large ink drawings: dark, unpigmented, components much bigger than glyphs
    ink, _ = spatial.ink_mask(img)
    n, lab_, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    big = np.zeros_like(ink)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_HEIGHT] > 40 or st[i, cv2.CC_STAT_WIDTH] > 60:
            big[lab_ == i] = 1
    masks["ink_drawing"] = big
    for cls, m in masks.items():
        cnts, hier = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hier is None:
            continue
        for ci, c in enumerate(cnts):
            if hier[0][ci][3] != -1:  # holes are counted on their parent
                continue
            area = cv2.contourArea(c)
            if area < (60 if cls != "ink_drawing" else 150):
                continue
            x, y, w, h = cv2.boundingRect(c)
            hull = cv2.convexHull(c)
            solidity = float(area / max(1.0, cv2.contourArea(hull)))
            holes = sum(1 for j in range(len(cnts)) if hier[0][j][3] == ci)
            lobes = 0
            if len(c) > 5:
                hi = cv2.convexHull(c, returnPoints=False)
                try:
                    d = cv2.convexityDefects(c, hi)
                    lobes = int((d.reshape(-1, 4)[:, 3] / 256.0 > 0.08 * max(w, h)).sum()) if d is not None else 0
                except cv2.error:
                    lobes = 0
            poly = cv2.approxPolyDP(c, 1.5, True)[:, 0, :] * inv
            oid = f"{seq}:{cls}:{k}"; k += 1
            single = np.zeros_like(m); cv2.drawContours(single, [c], -1, 1, -1)
            objs.append({"object_id": oid, "seq": seq, "object_class": cls,
                         "x0": x * inv, "y0": y * inv, "x1": (x + w) * inv, "y1": (y + h) * inv,
                         "area_px": float(area * inv * inv), "solidity": solidity, "n_holes": int(holes),
                         "n_lobes_convexity": lobes, "polygon_px": poly.astype(float).tolist(),
                         "method_version": METHOD_VERSION, "review_status": "unreviewed"})
            st_ = _rgb_lab_stats(img, lab, single & m, white)
            colors.append({"object_id": oid, "seq": seq, "object_class": cls, **st_,
                           "parchment_lab_reference": white,
                           "normalisation": "L*95/L*parchment; a*,b* minus parchment a*,b* (page median)",
                           "method_version": METHOD_VERSION})
    return {"objects": objs, "colors": colors}


def _relations(objs: list[dict], rows: list[dict]) -> list[dict]:
    rel = []
    by_seq: dict[int, list[dict]] = {}
    for o in objs:
        by_seq.setdefault(o["seq"], []).append(o)
    for r in rows:
        cands = []
        for o in by_seq.get(r["seq"], []):
            if o["area_px"] < 2000:
                continue
            dx = max(0.0, o["x0"] - r["x1"], r["x0"] - o["x1"])
            dy = max(0.0, o["y0"] - r["y1"], r["y0"] - o["y1"])
            d = float((dx * dx + dy * dy) ** 0.5)
            if dx == 0 and dy == 0:
                rel_ = "overlaps"
            elif dy >= dx:
                rel_ = "object_below_row" if o["y0"] >= r["y1"] else "object_above_row"
            else:
                rel_ = "object_right_of_row" if o["x0"] >= r["x1"] else "object_left_of_row"
            cands.append((d, rel_, o))
        for d, rel_, o in sorted(cands, key=lambda t: t[0])[:3]:
            rel.append({"source_type": "text_row", "source_id": r["row_id"], "relation": rel_,
                        "target_type": "visual_object", "target_id": o["object_id"], "target_class": o["object_class"],
                        "distance_px": d, "distance_norm": d / max(1.0, r["glyph_height_px"]),
                        "page_id": r["page_id"], "seq": r["seq"], "method_version": METHOD_VERSION})
    for seq, os_ in by_seq.items():
        big = [o for o in os_ if o["area_px"] >= 2000]
        for i, p in enumerate(big):
            for q in big[i + 1:]:
                inside = p["x0"] <= q["x0"] and p["y0"] <= q["y0"] and p["x1"] >= q["x1"] and p["y1"] >= q["y1"]
                inside2 = q["x0"] <= p["x0"] and q["y0"] <= p["y0"] and q["x1"] >= p["x1"] and q["y1"] >= p["y1"]
                touch = not (p["x1"] + 8 < q["x0"] or q["x1"] + 8 < p["x0"] or p["y1"] + 8 < q["y0"] or q["y1"] + 8 < p["y0"])
                if inside or inside2 or touch:
                    rel.append({"source_type": "visual_object", "source_id": p["object_id"],
                                "relation": "contains_bbox" if inside else "inside_bbox" if inside2 else "bbox_touches",
                                "target_type": "visual_object", "target_id": q["object_id"], "target_class": q["object_class"],
                                "distance_px": 0.0, "distance_norm": None, "page_id": None, "seq": seq,
                                "method_version": METHOD_VERSION})
    return rel


def build(workers: int | None = None) -> dict:
    jobs = [{"seq": s, "local_path": p} for s, p in duckdb.sql(
        f"select seq, local_path from '{paths.CODICOLOGY / 'canvases.parquet'}' order by seq").fetchall()]
    objs, colors = [], []
    with ProcessPoolExecutor(max_workers=workers or max(1, (os.cpu_count() or 2) - 1)) as ex:
        for res in ex.map(process, jobs, chunksize=2):
            objs += res["objects"]; colors += res["colors"]
    out = paths.OBSERVATIONS
    pq.write_table(pa.Table.from_pylist(objs), out / "visual_objects.parquet")
    pq.write_table(pa.Table.from_pylist(colors), out / "color_measurements.parquet")
    rows_path = out / "spatial_text_rows.parquet"
    rows = pq.read_table(rows_path).to_pylist() if rows_path.exists() else []
    rel = _relations(objs, rows)
    pq.write_table(pa.Table.from_pylist(rel), out / "layout_relations.parquet")
    return {"objects": len(objs), "relations": len(rel)}
