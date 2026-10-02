"""Comparators, shared task queue, review API, manual-download registration."""
import json

import pytest
from conftest import scalar

from vud import contrib, fetch, tasks


def test_comparator_panel_present(con):
    kinds = {r[0] for r in con.sql("select distinct kind from comparative.documents").fetchall()}
    assert {"natural_language", "ciphertext", "cipher_plaintext", "pseudo_text", "manuscript_record"} <= kinds
    assert scalar(con, "select sum(n_words) from comparative.documents where language = 'lat'") > 1_000_000
    # comparators never leak into Voynich tables
    assert scalar(con, "select count(*) from annotations.tokens where source_id like 'cmp_%'") == 0


def test_review_api_validates(tmp_path, monkeypatch):
    monkeypatch.setattr(contrib, "CONTRIB_OBS", tmp_path)
    with pytest.raises(ValueError):
        contrib.review_machine_observation(author="t", target_type="locus", target_id="f1r.3", verdict="maybe")
    with pytest.raises(ValueError):
        contrib.review_machine_observation(author="t", target_type="locus", target_id="f1r.3", verdict="corrected")
    oid = contrib.review_machine_observation(author="t", target_type="locus", target_id="f1r.3",
                                             verdict="corrected", corrected_xywh=[1, 2, 3, 4])
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[0])
    assert row["observation_id"] == oid and row["property"] == "machine_review" and row["region_xywh"] == [1, 2, 3, 4]


def test_task_queue_never_double_assigns(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "CLAIMS", tmp_path / "claims.jsonl")
    a = tasks.claim_next("review_alignment", "agent-a")
    b = tasks.claim_next("review_alignment", "agent-b")
    assert a and b and a != b
    assert not tasks.claim(a, "agent-b")
    tasks.complete(a, "agent-a", "done")
    assert tasks.claim_next("review_alignment", "agent-c") not in (a, b)


def test_register_manual(tmp_path, monkeypatch):
    from vud import paths
    monkeypatch.setattr(paths, "EVIDENCE", tmp_path)
    monkeypatch.setattr(paths, "EVIDENCE_MANIFEST", tmp_path / "MANIFEST.tsv")
    (tmp_path / "x_src").mkdir()
    (tmp_path / "x_src" / "a.pdf").write_bytes(b"%PDF-1.4 test")
    assert fetch.register_manual("x_src") == ["a.pdf"]
    assert fetch.register_manual("x_src") == []  # idempotent
