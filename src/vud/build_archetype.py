"""E2: import Torsten Timm's Archetype (DigiPal) palaeography database without running PostgreSQL.

The SQL dump's COPY blocks are parsed directly. Geometry is converted from OpenLayers map
coordinates (origin bottom-left, y up) to image pixel coordinates (origin top-left, y down):
    px_x = x ;  px_y = image_height - y
That convention is verified by tests/test_archetype_geometry.py against Yale pixels.

Outputs (data/annotations/):
  archetype_images.parquet       Archetype image -> Yale canvas (joined on exact pixel size)
  glyph_annotations.parquet      one row per annotated glyph ('graph'): polygon, bbox, allograph,
                                 hand label (authority: Timm/Archetype following Davis's model)
"""
from __future__ import annotations

import ast
import tarfile

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from . import paths

SOURCE = "archetype_timm_2026"
TARBALL = "archetype-voynich-palaeography-project.tar.gz"


def _sql_text() -> str:
    with tarfile.open(paths.evidence_dir(SOURCE) / TARBALL) as tf:
        return tf.extractfile("digipal_project/archetype.sql").read().decode("utf-8")


def _unescape(v: str):
    if v == r"\N":
        return None
    return v.replace(r"\t", "\t").replace(r"\n", "\n").replace("\\\\", "\\")


def copy_tables(sql: str, wanted: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    lines = sql.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("COPY "):
            head = line[5:]
            name = head.split(" ", 1)[0].removeprefix("public.")
            cols = [c.strip().strip('"') for c in head[head.index("(") + 1:head.index(")")].split(",")]
            i += 1
            rows = []
            while lines[i] != r"\.":
                if name in wanted:
                    rows.append(dict(zip(cols, (_unescape(v) for v in lines[i].split("\t")))))
                i += 1
            if name in wanted:
                out[name] = rows
        i += 1
    return out


def build() -> dict:
    t = copy_tables(_sql_text(), {
        "digipal_image", "digipal_annotation", "digipal_graph", "digipal_idiograph",
        "digipal_allograph", "digipal_character", "digipal_hand", "digipal_scribe",
    })
    canv = duckdb.sql(f"select seq, canvas_id, label, width, height from '{paths.CODICOLOGY / 'canvases.parquet'}'").fetchall()
    page_canvases = {}
    for seq, pid in duckdb.sql(f"select seq, page_id from '{paths.CODICOLOGY / 'canvas_pages.parquet'}'").fetchall():
        page_canvases.setdefault(pid, set()).add(seq)
    by_size = {}
    for seq, cid, label, w, h in canv:
        by_size.setdefault((w, h), []).append((seq, cid, label))

    images = {}
    img_rows = []
    for r in t["digipal_image"]:
        w, h = int(r["width"]), int(r["height"])
        cands = by_size.get((w, h), [])
        # size collisions are possible for standard leaves; disambiguate by label equality
        exact = [c for c in cands if c[2] == r["locus"]]
        pick = exact[0] if exact else (cands[0] if len(cands) == 1 else None)
        if pick is None and cands:
            # foldout panels share sizes: break ties with the curated canvas<->page map
            hits = [c for c in cands if c[0] in page_canvases.get("f" + r["locus"], set())]
            pick = hits[0] if len(hits) == 1 else None
        images[r["id"]] = {"w": w, "h": h, "locus": r["locus"], "canvas": pick}
        img_rows.append({
            "archetype_image_id": int(r["id"]), "archetype_locus": r["locus"], "width": w, "height": h,
            "keywords": r.get("keywords_string"), "yale_seq": pick[0] if pick else None,
            "canvas_id": pick[1] if pick else None, "yale_label": pick[2] if pick else None,
            "match": "size+label" if exact else ("size_unique" if pick and len(cands) == 1 else
                                                 "size+curated_page" if pick else
                                                ("ambiguous" if cands else "none")),
            "n_size_candidates": len(cands),
        })

    allo = {r["id"]: r["name"] for r in t["digipal_allograph"]}
    idio = {r["id"]: r for r in t["digipal_idiograph"]}
    scribe = {r["id"]: r["name"] for r in t["digipal_scribe"]}
    hand = {r["id"]: {"label": r["label"], "scribe": scribe.get(r["scribe_id"])} for r in t["digipal_hand"]}
    graph = {r["id"]: r for r in t["digipal_graph"]}

    rows = []
    for a in t["digipal_annotation"]:
        g = graph.get(a["graph_id"])
        img = images[a["image_id"]]
        geo = ast.literal_eval(a["geo_json"])  # stored as a python-literal dict (single quotes)
        ring = geo["geometry"]["coordinates"][0]
        px = [[float(x), img["h"] - float(y)] for x, y in ring]
        xs, ys = [p[0] for p in px], [p[1] for p in px]
        hd = hand.get(g["hand_id"]) if g else None
        idg = idio.get(g["idiograph_id"]) if g else None
        rows.append({
            "annotation_id": f"{SOURCE}:{a['id']}", "source_id": SOURCE,
            "archetype_annotation_id": int(a["id"]), "archetype_graph_id": int(a["graph_id"]) if a["graph_id"] else None,
            "yale_seq": img["canvas"][0] if img["canvas"] else None,
            "canvas_id": img["canvas"][1] if img["canvas"] else None,
            "archetype_locus": img["locus"],
            "polygon_px": px, "x_min": min(xs), "y_min": min(ys), "x_max": max(xs), "y_max": max(ys),
            "x_min_norm": min(xs) / img["w"], "y_min_norm": min(ys) / img["h"],
            "x_max_norm": max(xs) / img["w"], "y_max_norm": max(ys) / img["h"],
            "rotation": float(a["rotation"]) if a["rotation"] else 0.0,
            "allograph": allo.get(idg["allograph_id"]) if idg else None,
            "hand_label": hd["label"] if hd else None, "scribe": hd["scribe"] if hd else None,
            "graph_display_label": g["display_label"] if g else None,
            "hand_authority": "Archetype/Timm 2026 applying Davis section-based scribe model",
            "created": a["created"], "modified": a["modified"],
        })
    out = paths.ANNOTATIONS
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(img_rows), out / "archetype_images.parquet")
    pq.write_table(pa.Table.from_pylist(rows), out / "glyph_annotations.parquet")
    return {"images": len(img_rows), "annotations": len(rows),
            "unmatched_images": sum(1 for r in img_rows if r["canvas_id"] is None)}
