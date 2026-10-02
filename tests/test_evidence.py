"""E0 integrity: evidence files are exactly what was downloaded, and nothing else is in evidence/."""
import os
import stat

from vud import fetch, paths, registry


def test_every_evidence_file_matches_its_recorded_hash():
    assert fetch.verify_evidence() == []


def test_evidence_files_are_read_only():
    for r in registry.read_manifest():
        p = paths.evidence_dir(r["source_id"]) / r["path"]
        assert not (os.stat(p).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)), p


def test_auto_sources_fully_acquired():
    have = {(r["source_id"], r["path"]) for r in registry.read_manifest()}
    for s in registry.load_sources():
        if s["acquisition"] in ("auto", "iiif"):  # harvest sources list files dynamically
            for f in s.get("files") or []:
                assert (s["source_id"], f["path"]) in have, f"{s['source_id']}/{f['path']} not fetched"


def test_iiif_every_canvas_downloaded():
    import json
    man = json.loads((paths.evidence_dir("yale_ms408_iiif_2014") / "iiif-manifest.json").read_text())
    n = len(fetch.iiif_canvases(man))
    got = [r for r in registry.read_manifest() if r["source_id"] == "yale_ms408_iiif_2014" and r["path"].startswith("images/")]
    assert len(got) == n == 213
