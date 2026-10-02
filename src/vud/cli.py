"""`vud` command line: build the workspace and query it quickly.

Read commands never modify data. Write access for agents is through vud.contrib (Python API).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import paths

VIEWS = paths.ROOT / "views"  # rendered crops for looking at; disposable, git-ignored


# ----------------------------------------------------------------------------- build
def cmd_fetch(a):
    from . import fetch
    fetch.fetch(only=a.only or None, workers=a.workers)


def cmd_build(a):
    from . import (build_archetype, build_codicology, build_derived, build_literature,
                   build_transcriptions, contrib, db, registry)
    steps = {
        "registry": registry.build, "transcriptions": build_transcriptions.build,
        "codicology": build_codicology.build, "archetype": build_archetype.build,
        "derived": build_derived.build, "literature": build_literature.build,
        "contrib": contrib.build, "db": db.build,
    }
    todo = list(steps) if a.step == "all" else [a.step]
    for s in todo:
        res = steps[s]()
        print(f"[{s}] {res if not isinstance(res, list) else f'{len(res)} views'}", file=sys.stderr)


def cmd_verify(a):
    from . import fetch
    problems = fetch.verify_evidence()
    for p in problems:
        print(p)
    print(f"{'OK' if not problems else 'FAIL'}: evidence integrity ({len(problems)} problems)", file=sys.stderr)
    sys.exit(1 if problems else 0)


# ----------------------------------------------------------------------------- query
def _con():
    from . import db
    return db.connect()


def _print(rel, fmt="table", limit=None):
    if fmt == "json":
        cols = rel.columns
        print(json.dumps([dict(zip(cols, r)) for r in rel.fetchall()], default=str, ensure_ascii=False, indent=1))
    elif fmt == "csv":
        import csv
        w = csv.writer(sys.stdout)
        w.writerow(rel.columns)
        w.writerows(rel.fetchall())
    else:
        rel.show(max_rows=limit or 200, max_width=250)


def cmd_sql(a):
    import duckdb
    try:
        _print(_con().sql(a.query), a.format, a.limit)
    except duckdb.Error as e:
        sys.exit(f"SQL error: {e}\nTip: `vud sql \"show all tables\"` lists every view; see docs/SCHEMA.md")


def cmd_sources(a):
    _print(_con().sql("select source_id, layer, kind, acquisition, version, name from registry.sources order by layer, source_id"), a.format)


def cmd_page(a):
    con = _con()
    print("== page attributes (authority: zl3b page variables)")
    _print(con.sql("select * from codicology.pages where page_id = ?", params=[a.page_id]), a.format)
    print("== images")
    _print(con.sql("select seq, yale_label, local_path, role, region_xywh, map_method, confidence, note from page_images where page_id = ?", params=[a.page_id]), a.format)
    print(f"== loci ({a.witness})")
    _print(con.sql("""select locus_id, locator, locus_type, text from annotations.loci
                      where page_id = ? and witness_id = ? order by try_cast(locus_num as int), file_line""",
                   params=[a.page_id, a.witness]), a.format, 500)
    if a.comments:
        print("== transcriber comments (zl3b)")
        _print(con.sql("select file_line, after_locus_id, text from annotations.source_comments where source_id='zl3b' and page_id = ? order by file_line", params=[a.page_id]), a.format, 500)


def cmd_locus(a):
    con = _con()
    _print(con.sql("""select witness_id, alphabet, locus_id, locus_type, n_tokens, text, raw_line
                      from annotations.loci where coalesce(ivtff_locus_id, locus_id) = ? order by witness_id""",
                   params=[a.locus_id]), a.format)
    print("== alternatives / uncertain units")
    _print(con.sql("""select witness_id, unit_idx, token_idx, kind, raw, options from annotations.units u
                      join annotations.loci l using (witness_id, locus_id)
                      where coalesce(l.ivtff_locus_id, l.locus_id) = ? and u.kind in ('alt','unread','unread_run','rare','lig')
                      order by witness_id, unit_idx""", params=[a.locus_id]), a.format)


def cmd_grep(a):
    """Regex over token text (first reading) with keyword-in-context from the same line."""
    con = _con()
    rows = con.sql("""
        select t.witness_id, t.page_id, coalesce(t.ivtff_locus_id, t.locus_id) as locus_id, t.token_idx, t.text,
               l.text as line, p.illustration as section, p.currier_language as lang
        from annotations.tokens t join annotations.loci l using (witness_id, locus_id)
        left join codicology.pages p on p.page_id = t.page_id
        where t.witness_id = ? and regexp_full_match(t.text, ?)
        order by p.ivtff_order, t.locus_id, t.token_idx""", params=[a.witness, a.pattern]).fetchall()
    for w, page, lid, ti, text, line, sec, lang in rows[: a.limit]:
        toks = re.split(r"[.,-]", line)
        lo, hi = max(0, ti - a.context), ti + a.context + 1
        ctx = " ".join(("[" + x + "]") if i == ti else x for i, x in enumerate(toks[lo:hi], start=lo))
        print(f"{lid:14s} {sec or '':14s} {lang or '-'}  {ctx}")
    print(f"-- {len(rows)} match(es) in {a.witness}", file=sys.stderr)


def cmd_image(a):
    """Render a page (or panel, or region) to a viewable JPEG and print its path."""
    from PIL import Image, ImageDraw
    con = _con()
    rows = con.sql("select seq, local_path, region_xywh, role, width, height from page_images where page_id = ? order by seq",
                   params=[a.page_id]).fetchall()
    if not rows:
        sys.exit(f"no image for page {a.page_id}")
    VIEWS.mkdir(exist_ok=True)
    for seq, path, region, role, w, h in rows:
        if not path:
            sys.exit(f"canvas {seq} not downloaded yet: run `vud fetch`")
        im = Image.open(paths.ROOT / path)
        box = None
        if a.region:
            x, y, rw, rh = [int(v) for v in a.region.split(",")]
            box = (x, y, x + rw, y + rh)
        elif region and not a.full_canvas:
            box = (region[0], region[1], region[0] + region[2], region[1] + region[3])
        if a.glyphs:
            d = ImageDraw.Draw(im)
            for poly, allo in con.sql("select polygon_px, allograph from annotations.glyph_annotations where yale_seq = ?", params=[seq]).fetchall():
                d.polygon([tuple(p) for p in poly], outline=(255, 0, 0), width=4)
                d.text((poly[0][0], poly[0][1] - 18), allo or "", fill=(255, 0, 0))
        if box:
            im = im.crop(box)
        im.thumbnail((a.max, a.max))
        tag = f"_{a.region.replace(',', '-')}" if a.region else ""
        out = VIEWS / f"{a.page_id}_seq{seq}{tag}{'_glyphs' if a.glyphs else ''}.jpg"
        im.convert("RGB").save(out, quality=88)
        print(out)


TABLE_DOCS = {
    "registry.sources": "One row per registered source/version (registry/sources.yaml). Layer: E0/E2/H/LIT/CMP.",
    "registry.assets": "One row per evidence file: url, sha256, bytes, retrieval time (from evidence/MANIFEST.tsv).",
    "annotations.witnesses": "Transliteration witnesses (IVTFF files + LSI transcriber codes), alphabet, independence.",
    "annotations.loci": "One line/locus per witness. raw_line = verbatim source line. ivtff_locus_id aligns LSI.",
    "annotations.units": "Lossless parse: every glyph, alternative, separator, comment, filler, in order.",
    "annotations.tokens": "Glyph runs between separators with boundary kinds and uncertainty flags.",
    "annotations.page_variables": "IVTFF/EVT page-header variables ($Q quire, $I illustration, $L language, $H hand...) per source.",
    "annotations.source_comments": "Every '#' comment line from every transliteration file, anchored to page/locus.",
    "annotations.lsi_locus_map": "LSI native locus -> IVTFF locus, with match method and similarity.",
    "annotations.archetype_images": "Archetype image -> Yale canvas registration (exact pixel-size match).",
    "annotations.glyph_annotations": "Archetype glyph polygons in Yale canvas pixels (+normalized bbox), allograph, hand label.",
    "codicology.pages": "Canonical 227 IVTFF pages in ZL3b order; folio/side/panel; ZL3b page variables as columns.",
    "codicology.folios": "Folios 1-116, present/missing.",
    "codicology.quires": "Quires with page and folio membership.",
    "codicology.canvases": "213 Yale IIIF canvases: ids, label, size, local file, sha256.",
    "codicology.canvas_pages": "Canvas <-> page map; foldout panel boxes (approximate) with method/confidence.",
    "codicology.binding_canvases": "Canvases of covers, flyleaves, edges, spine.",
    "codicology.material_samples": "McCrone 2009 Table I: 20 ink/pigment samples with locations and constituents.",
    "codicology.material_conclusions": "McCrone 2009 conclusions (interpretive statements of the report authors).",
    "codicology.radiocarbon": "University of Arizona AMS results (4 samples + combined calibrated interval).",
    "derived.witness_agreement": "Pairwise per-locus agreement between EVA-alphabet witnesses (eva_basic_v1).",
    "derived.locus_coverage": "Which witnesses attest each IVTFF locus, with token counts.",
    "derived.token_frequencies": "Token type counts per witness (first reading).",
    "derived.recipes": "Provenance of each derived table: code hash, git commit, parameters, input sha256s.",
    "literature.pages": "Page text extracted from literature/spec PDFs (noisy OCR; PDF is the evidence).",
    "observations.observations": "E1 contributions (append-only, via vud.contrib.add_observation).",
    "hypotheses.hypotheses": "H contributions (append-only, via vud.contrib.add_hypothesis).",
}


def cmd_docs(a):
    """Regenerate docs/SCHEMA.md from the live database."""
    con = _con()
    out = ["# VUD schema (generated by `vud docs` — do not edit by hand)", ""]
    tabs = con.sql("""select table_schema, table_name from information_schema.tables
                      where table_schema <> 'information_schema' order by table_schema <> 'main', 1, 2""").fetchall()
    for sch, name in tabs:
        key = f"{sch}.{name}"
        try:
            n = con.sql(f'select count(*) from {sch}."{name}"').fetchone()[0]
        except Exception:  # noqa: BLE001
            n = "?"
        out += [f"## `{key}`  ({n:,} rows)" if isinstance(n, int) else f"## `{key}`", ""]
        if key in TABLE_DOCS:
            out += [TABLE_DOCS[key], ""]
        out += ["| column | type |", "|---|---|"]
        for col, typ in con.sql("""select column_name, data_type from information_schema.columns
                                   where table_schema = ? and table_name = ? order by ordinal_position""",
                                params=[sch, name]).fetchall():
            out.append(f"| {col} | {typ} |")
        out.append("")
    (paths.ROOT / "docs").mkdir(exist_ok=True)
    (paths.ROOT / "docs" / "SCHEMA.md").write_text("\n".join(out))
    print(paths.ROOT / "docs" / "SCHEMA.md")


def cmd_release(a):
    """Freeze: hash every built table + the evidence manifest into releases/VUD-<version>.json."""
    def h(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    tables = {str(p.relative_to(paths.ROOT)): h(p) for p in sorted(paths.DATA.rglob("*.parquet"))}
    import subprocess
    try:
        commit = subprocess.check_output(["git", "-C", str(paths.ROOT), "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", str(paths.ROOT), "status", "--porcelain", "src", "registry", "curation"], text=True).strip())
    except Exception:  # noqa: BLE001
        commit, dirty = None, None
    rel = {"release": f"VUD-{a.version}", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "git_commit": commit, "code_dirty": dirty, "evidence_manifest_sha256": h(paths.EVIDENCE_MANIFEST),
           "tables": tables, "notes": a.notes}
    paths.RELEASES.mkdir(exist_ok=True)
    out = paths.RELEASES / f"VUD-{a.version}.json"
    if out.exists():
        sys.exit(f"{out} exists; releases are immutable — bump the version")
    out.write_text(json.dumps(rel, indent=1))
    print(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog="vud", description="Voynich Unified Dataset workspace")
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("fetch", help="download registered sources into evidence/")
    s.add_argument("--only", nargs="*"); s.add_argument("--workers", type=int, default=4); s.set_defaults(f=cmd_fetch)
    s = sp.add_parser("build", help="build tables from evidence (default: all steps)")
    s.add_argument("step", nargs="?", default="all"); s.set_defaults(f=cmd_build)
    sp.add_parser("verify", help="re-hash every evidence file").set_defaults(f=cmd_verify)

    def fmt(s):
        s.add_argument("--format", "-f", choices=["table", "json", "csv"], default="table")
    s = sp.add_parser("sql", help="run SQL against voynich.duckdb"); s.add_argument("query")
    s.add_argument("--limit", type=int); fmt(s); s.set_defaults(f=cmd_sql)
    s = sp.add_parser("sources", help="list registered sources"); fmt(s); s.set_defaults(f=cmd_sources)
    s = sp.add_parser("page", help="everything about one page"); s.add_argument("page_id")
    s.add_argument("--witness", "-w", default="zl3b"); s.add_argument("--comments", action="store_true"); fmt(s)
    s.set_defaults(f=cmd_page)
    s = sp.add_parser("locus", help="all witness readings of one locus (e.g. f1r.3)"); s.add_argument("locus_id"); fmt(s)
    s.set_defaults(f=cmd_locus)
    s = sp.add_parser("grep", help="regex over tokens, keyword-in-context"); s.add_argument("pattern")
    s.add_argument("--witness", "-w", default="zl3b"); s.add_argument("--context", "-C", type=int, default=3)
    s.add_argument("--limit", type=int, default=200); s.set_defaults(f=cmd_grep)
    s = sp.add_parser("image", help="render a page/panel/region to views/ and print the path")
    s.add_argument("page_id"); s.add_argument("--region", help="x,y,w,h in full-canvas pixels")
    s.add_argument("--max", type=int, default=1600, help="longest side of output (px)")
    s.add_argument("--full-canvas", action="store_true", help="ignore the foldout panel box")
    s.add_argument("--glyphs", action="store_true", help="overlay Archetype glyph polygons"); s.set_defaults(f=cmd_image)
    sp.add_parser("docs", help="regenerate docs/SCHEMA.md").set_defaults(f=cmd_docs)
    s = sp.add_parser("release", help="freeze a hashed release manifest"); s.add_argument("version")
    s.add_argument("--notes", default=""); s.set_defaults(f=cmd_release)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
