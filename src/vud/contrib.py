"""Append-only contribution logs for agents and humans: E1 observations and H hypotheses.

Many agents may write concurrently: every append takes an exclusive flock on the target file.
Nothing here can modify evidence/, data/annotations/ or data/codicology/.

  contrib/observations/<author>.jsonl   -> data/observations/observations.parquet   (layer E1)
  hypotheses/<author>.jsonl             -> data/hypotheses/hypotheses.parquet        (layer H)

The separation rule: observations describe what is on the vellum / in a source, with a method that
another person could repeat. Anything that depends on an assumed meaning, language, cipher, plant
identity, or reading order preference is a hypothesis.
"""
from __future__ import annotations

import fcntl
import json
import re
import uuid
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from . import paths

CONTRIB_OBS = paths.ROOT / "contrib" / "observations"
HYP_DIR = paths.HYPOTHESES

TARGET_TYPES = {"page", "canvas", "canvas_region", "locus", "token", "unit", "glyph_annotation",
                "observation", "folio", "quire", "source", "text_row", "visual_object", "row_gap"}
REVIEW_VERDICTS = {"accepted", "rejected", "corrected", "uncertain"}
OBS_STATUS = {"proposed", "reviewed", "accepted", "rejected", "superseded"}
HYP_TYPES = {"plaintext_mapping", "language", "cipher_model", "glyph_identity", "segmentation",
             "reading_order", "plant_identification", "illustration_identification", "source_text",
             "scribal_hand", "codicological_reconstruction", "statistical_claim", "other"}
HYP_STATUS = {"proposed", "testing", "supported", "refuted", "abandoned"}
# Words that indicate an interpretive claim; rejected in observation properties/values.
INTERPRETIVE = re.compile(r"\b(means?|meaning|translat\w*|decipher\w*|plaintext|latin word|"
                          r"represents? the|is (the )?(plant|herb|species)|identified as)\b", re.I)

OBS_SCHEMA = pa.schema([
    ("observation_id", pa.string()), ("target_type", pa.string()), ("target_id", pa.string()),
    ("property", pa.string()), ("value_text", pa.string()), ("value_number", pa.float64()),
    ("value_json", pa.string()), ("unit", pa.string()), ("region_xywh", pa.list_(pa.float64())),
    ("method", pa.string()), ("author", pa.string()), ("model_version", pa.string()),
    ("confidence", pa.float64()), ("status", pa.string()), ("supersedes_id", pa.string()),
    ("source_ids", pa.list_(pa.string())), ("dataset_release", pa.string()), ("created_at", pa.string()),
    ("notes", pa.string()),
])
HYP_SCHEMA = pa.schema([
    ("hypothesis_id", pa.string()), ("type", pa.string()), ("title", pa.string()), ("claim", pa.string()),
    ("targets", pa.list_(pa.string())), ("proposed_value", pa.string()), ("model", pa.string()),
    ("author", pa.string()), ("status", pa.string()), ("evidence", pa.list_(pa.string())),
    ("falsification_test", pa.string()), ("train_pages", pa.list_(pa.string())),
    ("held_out_pages", pa.list_(pa.string())), ("result_summary", pa.string()),
    ("parent_hypothesis_id", pa.string()), ("dataset_release", pa.string()), ("created_at", pa.string()),
])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_author(author: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", author):
        raise ValueError("author must match [A-Za-z0-9_.-]{1,64}")
    return author


def _append(path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def _current_release() -> str | None:
    rel = sorted(paths.RELEASES.glob("VUD-*.json"))
    return rel[-1].stem if rel else None


def add_observation(*, author: str, target_type: str, target_id: str, property: str, method: str,
                    value_text: str | None = None, value_number: float | None = None,
                    value_json=None, unit: str | None = None, region_xywh=None,
                    confidence: float | None = None, source_ids=None, model_version: str | None = None,
                    supersedes_id: str | None = None, notes: str | None = None) -> str:
    if target_type not in TARGET_TYPES:
        raise ValueError(f"target_type must be one of {sorted(TARGET_TYPES)}")
    if value_text is None and value_number is None and value_json is None:
        raise ValueError("an observation needs a value")
    blob = " ".join(str(x) for x in (property, value_text, notes) if x)
    if INTERPRETIVE.search(blob):
        raise ValueError("this reads as an interpretation; record it with add_hypothesis instead")
    oid = "obs_" + uuid.uuid4().hex[:16]
    _append(CONTRIB_OBS / f"{_safe_author(author)}.jsonl", {
        "observation_id": oid, "target_type": target_type, "target_id": target_id, "property": property,
        "value_text": value_text, "value_number": value_number,
        "value_json": json.dumps(value_json) if value_json is not None else None, "unit": unit,
        "region_xywh": region_xywh, "method": method, "author": author, "model_version": model_version,
        "confidence": confidence, "status": "proposed", "supersedes_id": supersedes_id,
        "source_ids": source_ids or [], "dataset_release": _current_release(), "created_at": _now(),
        "notes": notes,
    })
    return oid


def add_hypothesis(*, author: str, type: str, title: str, claim: str, falsification_test: str,
                   targets=None, proposed_value: str | None = None, model: str | None = None,
                   evidence=None, train_pages=None, held_out_pages=None,
                   parent_hypothesis_id: str | None = None, status: str = "proposed",
                   result_summary: str | None = None) -> str:
    if type not in HYP_TYPES:
        raise ValueError(f"type must be one of {sorted(HYP_TYPES)}")
    if status not in HYP_STATUS:
        raise ValueError(f"status must be one of {sorted(HYP_STATUS)}")
    if set(train_pages or []) & set(held_out_pages or []):
        raise ValueError("train_pages and held_out_pages overlap (leakage)")
    hid = "hyp_" + uuid.uuid4().hex[:16]
    _append(HYP_DIR / f"{_safe_author(author)}.jsonl", {
        "hypothesis_id": hid, "type": type, "title": title, "claim": claim, "targets": targets or [],
        "proposed_value": proposed_value, "model": model, "author": author, "status": status,
        "evidence": evidence or [], "falsification_test": falsification_test,
        "train_pages": train_pages or [], "held_out_pages": held_out_pages or [],
        "result_summary": result_summary, "parent_hypothesis_id": parent_hypothesis_id,
        "dataset_release": _current_release(), "created_at": _now(),
    })
    return hid


def review_machine_observation(*, author: str, target_type: str, target_id: str, verdict: str,
                               method: str = "visual inspection of vud image overlay",
                               corrected_xywh=None, corrected_value=None, notes: str | None = None) -> str:
    """Human/agent review of a machine proposal (spatial alignment, text row, visual object, gap).

    target_type: 'locus' (its row alignment), 'text_row', 'visual_object' or 'row_gap'.
    verdict: accepted | rejected | corrected | uncertain. For 'corrected' give corrected_xywh (full-res px)
    and/or corrected_value (e.g. the right row_id). The machine table is never edited; views combine them.
    """
    if verdict not in REVIEW_VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(REVIEW_VERDICTS)}")
    if verdict == "corrected" and corrected_xywh is None and corrected_value is None:
        raise ValueError("a correction needs corrected_xywh or corrected_value")
    return add_observation(author=author, target_type=target_type, target_id=target_id,
                           property="machine_review", value_text=verdict,
                           value_json={"corrected_value": corrected_value} if corrected_value is not None else None,
                           region_xywh=corrected_xywh, method=method, notes=notes,
                           source_ids=["yale_ms408_iiif_2014"])


def update_hypothesis_status(*, author: str, hypothesis_id: str, status: str, result_summary: str) -> str:
    """Status changes are new rows (parent = previous id); history is never rewritten."""
    prev = {r["hypothesis_id"]: r for r in _read_jsonl(HYP_DIR)}.get(hypothesis_id)
    if not prev:
        raise KeyError(hypothesis_id)
    keep = {k: prev[k] for k in ("type", "title", "claim", "targets", "proposed_value", "model",
                                 "evidence", "falsification_test", "train_pages", "held_out_pages")}
    return add_hypothesis(author=author, status=status, result_summary=result_summary,
                          parent_hypothesis_id=hypothesis_id, **keep)


def _read_jsonl(d) -> list[dict]:
    rows = []
    for f in sorted(d.glob("*.jsonl")) if d.exists() else []:
        for line in f.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build() -> dict:
    (paths.OBSERVATIONS).mkdir(parents=True, exist_ok=True)
    (paths.DATA / "hypotheses").mkdir(parents=True, exist_ok=True)
    obs = _read_jsonl(CONTRIB_OBS)
    hyp = _read_jsonl(HYP_DIR)
    import os
    for tbl, dest in ((pa.Table.from_pylist(obs, schema=OBS_SCHEMA), paths.OBSERVATIONS / "observations.parquet"),
                      (pa.Table.from_pylist(hyp, schema=HYP_SCHEMA), paths.DATA / "hypotheses" / "hypotheses.parquet")):
        tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
        pq.write_table(tbl, tmp)
        os.replace(tmp, dest)  # atomic: concurrent readers never see a half-written file
    return {"observations": len(obs), "hypotheses": len(hyp)}
