"""Load the hand-curated source registry and materialize it as Parquet."""
from __future__ import annotations

import csv
import json

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from . import paths

SOURCE_COLUMNS = [
    "source_id", "name", "creator", "version", "layer", "kind", "acquisition",
    "alphabet", "format", "canonical_location", "license", "parent_source_id", "notes",
]


def load_sources() -> list[dict]:
    with open(paths.SOURCES_YAML) as f:
        doc = yaml.safe_load(f)
    sources = doc["sources"]
    ids = [s["source_id"] for s in sources]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate source_id in registry: {sorted(dupes)}")
    return sources


def source(source_id: str) -> dict:
    for s in load_sources():
        if s["source_id"] == source_id:
            return s
    raise KeyError(source_id)


def read_manifest() -> list[dict]:
    """Rows of evidence/MANIFEST.tsv (one per evidence file)."""
    if not paths.EVIDENCE_MANIFEST.exists():
        return []
    with open(paths.EVIDENCE_MANIFEST, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def build() -> None:
    """data/registry/sources.parquet and assets.parquet."""
    paths.REGISTRY_DATA.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in load_sources():
        row = {c: (str(s[c]) if s.get(c) is not None else None) for c in SOURCE_COLUMNS}
        extra = {k: v for k, v in s.items() if k not in SOURCE_COLUMNS and k != "files"}
        row["extra_json"] = json.dumps(extra, default=str) if extra else None
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows), paths.REGISTRY_DATA / "sources.parquet")

    assets = read_manifest()
    schema = pa.schema([
        ("source_id", pa.string()), ("path", pa.string()), ("url", pa.string()),
        ("sha256", pa.string()), ("bytes", pa.int64()), ("media_type", pa.string()),
        ("retrieved_at", pa.string()), ("http_last_modified", pa.string()), ("http_etag", pa.string()),
    ])
    for a in assets:
        a["bytes"] = int(a["bytes"])
    pq.write_table(pa.Table.from_pylist(assets, schema=schema), paths.REGISTRY_DATA / "assets.parquet")
