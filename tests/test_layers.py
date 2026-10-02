"""The separation rule: hypotheses can never flow back into evidence/observation/derived layers."""
import re
from pathlib import Path

import pytest
from conftest import scalar

from vud import contrib, paths

SRC = Path(paths.ROOT / "src" / "vud")
ALLOWED_TO_TOUCH_HYPOTHESES = {"contrib.py", "db.py", "paths.py", "cli.py"}


def test_builders_never_read_hypotheses():
    for f in SRC.glob("*.py"):
        if f.name in ALLOWED_TO_TOUCH_HYPOTHESES:
            continue
        assert not re.search(r"HYPOTHESES|['\"]hypotheses", f.read_text()), f"{f.name} references the hypothesis layer"


def test_no_interpretive_columns_in_evidence_tables(con):
    bad = con.sql("""select table_schema, table_name, column_name from information_schema.columns
                     where table_schema in ('annotations', 'codicology', 'observations', 'derived')
                       and regexp_matches(lower(column_name), 'plaintext|translation|decipher|proposed_value|meaning')""").fetchall()
    assert bad == []


def test_observation_api_rejects_interpretation(tmp_path, monkeypatch):
    monkeypatch.setattr(contrib, "CONTRIB_OBS", tmp_path)
    with pytest.raises(ValueError):
        contrib.add_observation(author="t", target_type="token", target_id="x", property="meaning",
                                value_text="this word means water", method="guess")
    oid = contrib.add_observation(author="t", target_type="page", target_id="f1r", property="ink_gap_px",
                                  value_number=12.5, unit="px", method="manual measurement")
    assert oid.startswith("obs_")


def test_hypothesis_api_rejects_train_test_leakage(tmp_path, monkeypatch):
    monkeypatch.setattr(contrib, "HYP_DIR", tmp_path)
    with pytest.raises(ValueError):
        contrib.add_hypothesis(author="t", type="cipher_model", title="x", claim="y", falsification_test="z",
                               train_pages=["f1r", "f2r"], held_out_pages=["f2r"])


def test_derived_tables_have_recipes(con):
    tables = {r[0] for r in con.sql("select table_name from information_schema.tables where table_schema='derived'").fetchall()}
    recipes = {r[0] for r in con.sql("select \"table\" from derived.recipes").fetchall()}
    assert tables - {"recipes"} <= recipes
