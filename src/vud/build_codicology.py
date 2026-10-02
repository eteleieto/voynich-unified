"""Codicology & image-registry tables (data/codicology/).

  pages.parquet              canonical page list (IVTFF page names, ZL3b order) + parsed folio/side/panel,
                             with ZL3b page variables as convenience columns (authority = zl3b)
  folios.parquet             folio numbers 1..116 with present/missing status
  quires.parquet             quire letters/numbers with page membership
  canvases.parquet           every Yale IIIF canvas: ids, label, size, local file, sha256
  canvas_pages.parquet       many-to-many canvas <-> page correspondence (method + provenance per row)
  material_samples.parquet   McCrone 2009 Table I (20 ink/pigment samples), transcribed
  material_conclusions.parquet  report conclusions, kept separate from measured constituents
  radiocarbon.parquet        4 AMS samples + combined calibrated interval
"""
from __future__ import annotations

import json
import re

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from . import fetch, paths, registry

YALE = "yale_ms408_iiif_2014"
QUIRE_LETTERS = "ABCDEFGHIJKLMNOPQRST"  # $Q: A=1 ... T=20 (P=16 and R=18 unused)
CURATION = paths.ROOT / "curation"

ILLUSTRATION = {"A": "astronomical", "B": "biological", "C": "cosmological", "H": "herbal",
                "P": "pharmaceutical", "S": "marginal_stars", "T": "text_only", "Z": "zodiac"}


def parse_page_id(page_id: str) -> dict:
    if page_id == "fRos":
        return {"folio_num": None, "side": None, "panel": None, "is_foldout_panel": True,
                "note": "Rosettes foldout: f85v + f86r as one drawing"}
    m = re.fullmatch(r"f(\d+)([rv])(\d)?", page_id)
    if not m:
        raise ValueError(page_id)
    return {"folio_num": int(m[1]), "side": m[2], "panel": int(m[3]) if m[3] else None,
            "is_foldout_panel": bool(m[3]), "note": None}


def _write(rows, name, schema=None):
    paths.CODICOLOGY.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), paths.CODICOLOGY / name)


def build_pages() -> list[dict]:
    import duckdb
    pv = duckdb.sql(f"""
        select page_id, min(file_line) as file_line, map_from_entries(list((variable, value))) as vars
        from '{paths.ANNOTATIONS / "page_variables.parquet"}' where source_id = 'zl3b'
        group by page_id order by file_line""").fetchall()
    # pages that have a header but no variables are still pages
    loci_pages = duckdb.sql(f"""
        select page_id, min(file_line) from '{paths.ANNOTATIONS / "loci.parquet"}'
        where source_id='zl3b' group by 1""").fetchall()
    seen = {p for p, *_ in pv}
    pv += [(p, fl, {}) for p, fl in loci_pages if p not in seen]
    pv.sort(key=lambda r: r[1])
    rows = []
    for order, (page_id, _fl, v) in enumerate(pv, start=1):
        q = v.get("Q")
        rows.append({
            "page_id": page_id, "ivtff_order": order, **parse_page_id(page_id),
            "quire_letter": q, "quire_num": QUIRE_LETTERS.index(q) + 1 if q else None,
            "page_in_quire": v.get("P"), "folio_in_quire": v.get("F"), "bifolio_in_quire": v.get("B"),
            "illustration_code": v.get("I"), "illustration": ILLUSTRATION.get(v.get("I")),
            "currier_language": v.get("L"), "davis_hand": v.get("H"), "currier_hand": v.get("C"),
            "extraneous_writing": v.get("X"),
            "attributes_source_id": "zl3b",
        })
    _write(rows, "pages.parquet")
    return rows


def build_folios(pages: list[dict]) -> None:
    present = {p["folio_num"] for p in pages if p["folio_num"]} | {85, 86}
    quire_of = {}
    for p in pages:
        if p["folio_num"]:
            quire_of.setdefault(p["folio_num"], p["quire_num"])
    rows = [{"folio_num": n, "present": n in present, "quire_num": quire_of.get(n),
             "n_pages": sum(1 for p in pages if p["folio_num"] == n),
             "has_foldout_panels": any(p["folio_num"] == n and p["is_foldout_panel"] for p in pages)}
            for n in range(1, 117)]
    _write(rows, "folios.parquet")
    quires = {}
    for p in pages:
        if p["quire_num"]:
            quires.setdefault((p["quire_num"], p["quire_letter"]), []).append(p["page_id"])
    _write([{"quire_num": q, "quire_letter": l, "pages": pg, "n_pages": len(pg),
             "folios": sorted({parse_page_id(x)["folio_num"] for x in pg if x != "fRos"})}
            for (q, l), pg in sorted(quires.items())], "quires.parquet")


def build_bifolios(pages: list[dict]) -> None:
    """Conjugate leaves from ZL3b $Q/$B/$F. Missing conjugates are *inferred* by folio-number arithmetic
    and flagged as reconstructions (method + authority recorded), never mixed with observed leaves."""
    groups: dict[tuple, dict] = {}
    for p in pages:
        if p["folio_num"] is None or p["bifolio_in_quire"] is None:
            continue
        g = groups.setdefault((p["quire_num"], p["quire_letter"], int(p["bifolio_in_quire"])), {})
        g[p["folio_num"]] = p["folio_in_quire"]
    present = {p["folio_num"] for p in pages if p["folio_num"]}
    rows = []
    for (q, ql, b), fol in sorted(groups.items()):
        fs = sorted(fol)
        inferred = None
        if len(fs) == 1:
            # first-half leaves are a-f, second-half u-z; the lost partner sits on the other side
            f = fs[0]
            first_half = fol[f] in "abcdef"
            cand = [n for n in (range(f + 1, f + 12) if first_half else range(f - 1, f - 12, -1))
                    if 1 <= n <= 116 and n not in present]
            inferred = cand[0] if cand else None
        rows.append({
            "quire_num": q, "quire_letter": ql, "bifolio_in_quire": b, "folios_present": fs,
            "status": "complete" if len(fs) == 2 else "singleton",
            "inferred_missing_conjugate": inferred,
            "inference_method": "nearest missing folio number on the opposite half of the quire" if inferred else None,
            "is_reconstruction": inferred is not None,
            "authority": "zl3b page variables $Q $B $F",
        })
    _write(rows, "bifolios.parquet")


def build_canvases(pages: list[dict]) -> None:
    man = json.loads((paths.evidence_dir(YALE) / "iiif-manifest.json").read_text())
    have = {r["path"]: r for r in registry.read_manifest() if r["source_id"] == YALE}
    rows = []
    for c in fetch.iiif_canvases(man):
        rel = f"images/{c['seq']:03d}_{c['image_id']}.jpg"
        a = have.get(rel)
        rows.append({**c, "source_id": YALE, "local_path": f"evidence/{YALE}/{rel}" if a else None,
                     "sha256": a["sha256"] if a else None, "bytes": int(a["bytes"]) if a else None})
    _write(rows, "canvases.parquet")

    page_ids = {p["page_id"] for p in pages}
    curated = yaml.safe_load((CURATION / "canvas_pages.yaml").read_text())
    by_seq = {c["seq"]: c for c in rows}
    maps = []
    for c in rows:
        m = re.fullmatch(r"(\d+)([rv])", c["label"])
        if m and f"f{m[1]}{m[2]}" in page_ids and c["seq"] not in curated["canvases"]:
            maps.append({"seq": c["seq"], "canvas_id": c["canvas_id"], "page_id": f"f{m[1]}{m[2]}",
                         "role": "whole", "region_xywh": None, "region_method": None,
                         "method": "label_exact", "confidence": 1.0, "note": None,
                         "curated_by": None})
    for seq, entry in curated["canvases"].items():
        for item in entry.get("pages", []):
            if item.get("x_frac"):
                w, h = by_seq[seq]["width"], by_seq[seq]["height"]
                a, b = item["x_frac"]
                item["region_xywh"] = [round(a * w), 0, round((b - a) * w), h]
                item["region_method"] = "visual_estimate_from_preview (x_frac %.3f-%.3f, +-3%%)" % (a, b)
            maps.append({"seq": seq, "canvas_id": by_seq[seq]["canvas_id"], "page_id": item["page_id"],
                         "role": item.get("role", "whole"),
                         "region_xywh": item.get("region_xywh"), "region_method": item.get("region_method"),
                         "method": "curated", "confidence": item.get("confidence", 0.9),
                         "note": item.get("note") or entry.get("note"),
                         "curated_by": curated.get("curated_by")})
    schema = pa.schema([("seq", pa.int32()), ("canvas_id", pa.string()), ("page_id", pa.string()),
                        ("role", pa.string()), ("region_xywh", pa.list_(pa.int32())),
                        ("region_method", pa.string()), ("method", pa.string()),
                        ("confidence", pa.float32()), ("note", pa.string()), ("curated_by", pa.string())])
    _write(maps, "canvas_pages.parquet", schema)

    binding = curated.get("binding", {})
    _write([{"seq": int(s), "canvas_id": by_seq[int(s)]["canvas_id"], "label": by_seq[int(s)]["label"],
             "object": v} for s, v in binding.items()], "binding_canvases.parquet")


def build_materials() -> None:
    doc = yaml.safe_load((CURATION / "material_evidence.yaml").read_text())
    mc = doc["mccrone_samples"]
    samples = []
    for r in mc["rows"]:
        samples.append({
            "source_id": mc["source_id"], "locator": mc["locator"], "sample_no": r["sample"],
            "folio_ref": r["folio_ref"], "page_id": r["page_id"], "item": r["item"],
            "material_class": r["material_class"], "location_vertical": r["v"],
            "location_horizontal": r["h"], "constituents": r["constituents"], "figures": r["figures"],
            "techniques": mc["techniques"], "note": r.get("note"),
            "transcribed_by": doc["transcribed_by"], "review_status": doc["review_status"],
        })
    _write(samples, "material_samples.parquet")
    _write([{"source_id": mc["source_id"], **c} for c in mc["source_conclusions"]], "material_conclusions.parquet")
    rc = doc["radiocarbon"]
    rows = [{"source_id": rc["source_id"], "locator": rc["locator"], "lab": rc["lab"], "material": rc["material"],
             "kind": "sample", **r, "cal95_from_ad": None, "cal95_to_ad": None} for r in rc["rows"]]
    comb = rc["combined"]["calibrated_95pct"]
    rows.append({"source_id": rc["source_id"], "locator": comb["locator"], "lab": rc["lab"],
                 "material": rc["material"], "kind": "combined", "folio": None, "page_id": None,
                 "description": rc["combined"]["note"].strip(), "f14c": None, "f14c_sigma": None,
                 "age_bp": None, "uncal_year_ad": None, "sigma_years": None,
                 "cal95_from_ad": comb["from_ad"], "cal95_to_ad": comb["to_ad"]})
    _write(rows, "radiocarbon.parquet")


def build() -> dict:
    pages = build_pages()
    build_folios(pages)
    build_bifolios(pages)
    build_canvases(pages)
    build_materials()
    return {"pages": len(pages)}
