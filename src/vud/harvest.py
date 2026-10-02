"""Harvesters for sources whose file list must be discovered (acquisition: harvest).

Each harvester saves every index/listing response it reads as an evidence file (so builds can run
offline and the crawl itself is reproducible) and returns the content-file jobs to download.
"""
from __future__ import annotations

import re
import urllib.parse

from . import fetch, paths

CC = "https://mlat.uzh.ch/php_modules/"


def _get_saved(sid: str, url: str, rel: str) -> str:
    """Download (once) an index response into evidence and return its text."""
    p = paths.evidence_dir(sid) / rel
    have = {(r["source_id"], r["path"]) for r in fetch.registry.read_manifest()}
    if not ((sid, rel) in have and p.exists()):
        meta = fetch._download(url, p)
        fetch._append_manifest([{"source_id": sid, "path": rel, **meta}])
    return p.read_text(encoding="utf-8", errors="replace")


def corpus_corporum(src: dict) -> list[tuple[str, str, str | None]]:
    sid = src["source_id"]
    root = _get_saved(sid, CC + "navigate.php?load=/&group_by=", "nav/root.xml")
    wanted = {str(n) for n in src["params"]["corpus_nrs"]}
    corpora = re.findall(r"<corpus type=\"corpus\">\s*<idno>(\d+)</idno>\s*<name>([^<]+)</name>\s*<nr>(\d+)</nr>", root)
    jobs = []

    def walk(path: str, depth: int):
        x = _get_saved(sid, CC + f"navigate.php?load={urllib.parse.quote(path)}&group_by=",
                       "nav" + path.replace("/", "_") + ".xml")
        for tid, acc in re.findall(r"<text type=\"text\">.*?<idno>(\d+)</idno>.*?<accessible>(\d)</accessible>", x, re.S):
            if acc == "1":
                jobs.append((CC + f"download.php?idno={tid}&type=file-xml", f"texts/{tid}.xml", None))
        if depth < 3:
            for kind in ("author", "work"):
                for child in re.findall(rf"<{kind} type=\"{kind}\"[^>]*>.*?<idno>(\d+)</idno>", x, re.S):
                    walk(f"{path}/{child}", depth + 1)

    for idno, name, nr in corpora:
        if nr in wanted:
            walk(f"/{idno}", 1)
    seen, out = set(), []
    for j in jobs:
        if j[1] not in seen:
            seen.add(j[1]); out.append(j)
    return out


def digital_scriptorium(src: dict) -> list[tuple[str, str, str | None]]:
    """Save DS search result pages (JSON) for each configured query; no further content files."""
    sid = src["source_id"]
    for q in src["params"]["queries"]:
        for page in range(1, src["params"].get("max_pages", 5) + 1):
            url = ("https://search.digital-scriptorium.org/?search_field=all_fields&per_page=100&format=json"
                   f"&q={urllib.parse.quote(q)}&page={page}")
            txt = _get_saved(sid, url, f"search/{re.sub(r'[^a-z0-9]+', '_', q.lower())}_p{page}.json")
            if '"next_page":null' in txt.replace(" ", ""):
                break
    return []


HARVESTERS = {"corpus_corporum": corpus_corporum, "digital_scriptorium": digital_scriptorium}
