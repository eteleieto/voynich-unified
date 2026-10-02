"""Acquire E0 evidence files listed in registry/sources.yaml.

Invariants:
  * A file is downloaded once. If it is already in MANIFEST.tsv and on disk, it is skipped.
  * Files are written read-only (0444) after their sha256 is recorded.
  * `vud verify` (see verify_evidence) recomputes every hash; tests fail on any drift.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import paths, registry

UA = "voynich-unified-dataset/0.1 (research archive; contact via repository)"
MANIFEST_FIELDS = ["source_id", "path", "url", "sha256", "bytes", "media_type",
                   "retrieved_at", "http_last_modified", "http_etag"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, md5: str | None = None, retries: int = 4) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=120, headers={"User-Agent": UA}) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "")
                fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
                h, hm, n = hashlib.sha256(), hashlib.md5(), 0
                with os.fdopen(fd, "wb") as out:
                    for chunk in r.iter_content(1 << 20):
                        out.write(chunk); h.update(chunk); hm.update(chunk); n += len(chunk)
                if md5 and hm.hexdigest() != md5:
                    os.unlink(tmp)
                    raise ValueError(f"md5 mismatch for {url}: {hm.hexdigest()} != {md5}")
                if dest.suffix == ".pdf" and "html" in ctype:
                    os.unlink(tmp)
                    raise ValueError(f"expected PDF, server returned {ctype} for {url}")
                os.replace(tmp, dest)
                os.chmod(dest, 0o444)
                return {
                    "url": url, "sha256": h.hexdigest(), "bytes": n,
                    "media_type": ctype.split(";")[0].strip(),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "http_last_modified": r.headers.get("Last-Modified", ""),
                    "http_etag": r.headers.get("ETag", ""),
                }
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed {url}: {last_err}")


def _manifest_index() -> dict[tuple[str, str], dict]:
    return {(r["source_id"], r["path"]): r for r in registry.read_manifest()}


def _append_manifest(rows: list[dict]) -> None:
    if not rows:
        return
    paths.EVIDENCE.mkdir(parents=True, exist_ok=True)
    new = not paths.EVIDENCE_MANIFEST.exists()
    with open(paths.EVIDENCE_MANIFEST, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, delimiter="\t")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in MANIFEST_FIELDS})


def _jobs_for(src: dict, have: dict) -> list[tuple[str, str, str | None]]:
    """(url, relative path, md5) triples still needed for this source."""
    sid = src["source_id"]
    jobs = []
    for f in src.get("files", []) or []:
        if (sid, f["path"]) in have and (paths.evidence_dir(sid) / f["path"]).exists():
            continue
        jobs.append((f["url"], f["path"], f.get("md5")))
    if src["acquisition"] == "iiif":
        man = paths.evidence_dir(sid) / "iiif-manifest.json"
        if man.exists():
            for c in iiif_canvases(json.loads(man.read_text())):
                rel = f"images/{c['seq']:03d}_{c['image_id']}.jpg"
                if (sid, rel) in have and (paths.evidence_dir(sid) / rel).exists():
                    continue
                jobs.append((c["image_url"], rel, None))
    return jobs


def iiif_canvases(manifest: dict) -> list[dict]:
    """Flatten a IIIF Presentation 3 manifest to one dict per canvas."""
    out = []
    for seq, canvas in enumerate(manifest["items"], start=1):
        body = canvas["items"][0]["items"][0]["body"]
        svc = body.get("service", [{}])[0]
        svc_id = svc.get("@id") or svc.get("id")
        label = canvas.get("label", {})
        label = (label.get("none") or label.get("en") or [""])[0]
        out.append({
            "seq": seq,
            "canvas_id": canvas["id"],
            "label": label,
            "image_url": body["id"],
            "image_service": svc_id,
            "image_id": svc_id.rstrip("/").split("/")[-1] if svc_id else str(seq),
            "width": body.get("width"),
            "height": body.get("height"),
        })
    return out


def fetch(only: list[str] | None = None, workers: int = 4) -> None:
    for src in registry.load_sources():
        sid = src["source_id"]
        if only and sid not in only:
            continue
        if src["acquisition"] not in ("auto", "iiif", "harvest"):
            continue
        if src["acquisition"] == "harvest":
            from . import harvest
            have = _manifest_index()
            found = harvest.HARVESTERS[src["harvester"]](src)
            src = {**src, "files": (src.get("files") or []) + [
                {"url": u, "path": p, "md5": m} for u, p, m in found]}
        # two passes for IIIF: manifest first, then the canvases it lists
        for _pass in range(2 if src["acquisition"] == "iiif" else 1):  # IIIF: manifest, then canvases
            jobs = _jobs_for(src, _manifest_index())
            if not jobs:
                continue
            print(f"[{sid}] {len(jobs)} file(s) to fetch", file=sys.stderr)
            known = _manifest_index()  # files recorded by a previous acquisition (e.g. on another machine)
            done, failed = [], []
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_download, url, paths.evidence_dir(sid) / rel, md5): rel
                        for url, rel, md5 in jobs}
                for i, fut in enumerate(as_completed(futs), 1):
                    rel = futs[fut]
                    try:
                        meta = fut.result()
                        prev = known.get((sid, rel))
                        if prev is None:
                            done.append({"source_id": sid, "path": rel, **meta})
                        elif prev["sha256"] != meta["sha256"]:
                            # keep the recorded hash: `vud verify` will flag this file until it is resolved
                            print(f"  HASH DRIFT {sid}/{rel}: upstream bytes differ from the recorded sha256 "
                                  f"(recorded {prev['sha256'][:12]}…, got {meta['sha256'][:12]}…)", file=sys.stderr)
                    except Exception as e:  # noqa: BLE001
                        failed.append((rel, str(e)))
                        print(f"  FAIL {rel}: {e}", file=sys.stderr)
                    if i % 25 == 0:
                        print(f"  {i}/{len(jobs)}", file=sys.stderr)
                        _append_manifest(done); done = []
            _append_manifest(done)
            if failed:
                print(f"[{sid}] {len(failed)} failure(s); re-run `vud fetch` to retry", file=sys.stderr)


def verify_evidence() -> list[str]:
    """Return a list of problems (empty == every evidence file matches its recorded hash)."""
    problems = []
    seen = set()
    for r in registry.read_manifest():
        p = paths.evidence_dir(r["source_id"]) / r["path"]
        seen.add(p.resolve())
        if not p.exists():
            problems.append(f"missing: {p}")
        elif sha256_file(p) != r["sha256"]:
            problems.append(f"hash drift: {p}")
    if paths.EVIDENCE.exists():
        for p in paths.EVIDENCE.rglob("*"):
            if p.is_file() and p != paths.EVIDENCE_MANIFEST and not p.name.startswith(".") \
                    and p.resolve() not in seen:
                problems.append(f"unregistered file in evidence/: {p}")
    return problems


def register_manual(source_id: str) -> list[str]:
    """Hash + register every not-yet-registered file a human placed in evidence/<source_id>/."""
    import mimetypes
    d = paths.evidence_dir(source_id)
    if not d.exists():
        raise FileNotFoundError(f"put the files in {d} first")
    have = {r["path"] for r in registry.read_manifest() if r["source_id"] == source_id}
    rows = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            rel = str(p.relative_to(d))
            if rel in have:
                continue
            rows.append({"source_id": source_id, "path": rel, "url": "manual", "sha256": sha256_file(p),
                         "bytes": p.stat().st_size, "media_type": mimetypes.guess_type(p.name)[0] or "",
                         "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "http_last_modified": "", "http_etag": ""})
            os.chmod(p, 0o444)
    _append_manifest(rows)
    return [r["path"] for r in rows]
