"""A tiny shared work queue so many agents can split work without colliding.

Tasks are generated from the data (deterministic ids); claims are appended to contrib/claims.jsonl under
an exclusive lock and expire after CLAIM_HOURS unless completed. Kinds:

  review_alignment   one page: check machine row alignment / boundaries (worst QA first)
  review_objects     one canvas: check machine pigment / drawing objects
  disputed_loci      one page: loci where witnesses disagree most (reading check against the image)
  hand_survey        one page: palaeographic features (hand, ductus, ink) as observations
  experiment         free-form: claim an experiment name so two agents don't run the same one
"""
from __future__ import annotations

import fcntl
import json
from datetime import datetime, timedelta, timezone

import duckdb

from . import paths

CLAIMS = paths.ROOT / "contrib" / "claims.jsonl"
CLAIM_HOURS = 6
KINDS = ("review_alignment", "review_objects", "disputed_loci", "hand_survey")


def _now():
    return datetime.now(timezone.utc)


def candidates(kind: str) -> list[str]:
    con = duckdb.connect(str(paths.DB_PATH), read_only=True)
    if kind == "review_alignment":
        q = """select page_id from observations.spatial_page_qa where n_p_loci > 0
               order by coalesce(width_units_corr, -1) asc, mean_cost desc"""
    elif kind == "review_objects":
        q = "select distinct cast(seq as varchar) from observations.visual_objects order by 1"
    elif kind == "disputed_loci":
        q = """select page_id from derived.witness_agreement where comparison_space = 'native_eva'
               and witness_a = 'it2a' and witness_b = 'zl3b' group by page_id order by avg(glyph_similarity) asc"""
    elif kind == "hand_survey":
        q = "select page_id from codicology.pages order by ivtff_order"
    else:
        raise ValueError(kind)
    return [r[0] for r in con.sql(q).fetchall()]


def _read() -> list[dict]:
    if not CLAIMS.exists():
        return []
    return [json.loads(x) for x in CLAIMS.read_text().splitlines() if x.strip()]


def _state() -> dict[str, dict]:
    st: dict[str, dict] = {}
    for c in _read():
        st[c["task_id"]] = c
    return st


def claim_next(kind: str, author: str) -> str | None:
    """Atomically claim the next open task of this kind; returns task_id like 'review_alignment:f68r3'."""
    CLAIMS.parent.mkdir(parents=True, exist_ok=True)
    with open(CLAIMS, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        st = _state()
        for target in candidates(kind):
            tid = f"{kind}:{target}"
            c = st.get(tid)
            if c and (c["status"] == "done" or
                      (c["status"] == "claimed" and _now() - datetime.fromisoformat(c["at"]) < timedelta(hours=CLAIM_HOURS))):
                continue
            f.write(json.dumps({"task_id": tid, "kind": kind, "target": target, "author": author,
                                "status": "claimed", "at": _now().isoformat(timespec="seconds")}) + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
            return tid
        fcntl.flock(f, fcntl.LOCK_UN)
    return None


def claim(task_id: str, author: str) -> bool:
    """Claim a specific (e.g. experiment:<name>) task; False if someone else holds it."""
    CLAIMS.parent.mkdir(parents=True, exist_ok=True)
    with open(CLAIMS, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        c = _state().get(task_id)
        busy = c and c["author"] != author and (c["status"] == "done" or
               _now() - datetime.fromisoformat(c["at"]) < timedelta(hours=CLAIM_HOURS))
        if not busy:
            f.write(json.dumps({"task_id": task_id, "kind": task_id.split(":")[0], "target": task_id.split(":", 1)[-1],
                                "author": author, "status": "claimed", "at": _now().isoformat(timespec="seconds")}) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
        return not busy


def complete(task_id: str, author: str, summary: str = "") -> None:
    with open(CLAIMS, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps({"task_id": task_id, "kind": task_id.split(":")[0], "target": task_id.split(":", 1)[-1],
                            "author": author, "status": "done", "summary": summary,
                            "at": _now().isoformat(timespec="seconds")}) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def board() -> list[dict]:
    return sorted(_state().values(), key=lambda c: c["at"], reverse=True)
