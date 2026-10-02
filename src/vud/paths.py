"""Canonical filesystem layout. Everything else imports paths from here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REGISTRY = ROOT / "registry"
SOURCES_YAML = REGISTRY / "sources.yaml"

EVIDENCE = ROOT / "evidence"                  # E0: immutable, byte-for-byte source files
EVIDENCE_MANIFEST = EVIDENCE / "MANIFEST.tsv"  # sha256 of every evidence file

DATA = ROOT / "data"                          # built Parquet tables (E1/E2/E3 + codicology)
OBSERVATIONS = DATA / "observations"          # E1: measurements made on pixels
ANNOTATIONS = DATA / "annotations"            # E2: scholarly readings / labels with provenance
CODICOLOGY = DATA / "codicology"              # manuscript structure, canvases, material evidence
DERIVED = DATA / "derived"                    # E3: reproducible computed features
REGISTRY_DATA = DATA / "registry"

HYPOTHESES = ROOT / "hypotheses"              # H: never read by builders of E0–E3
EXPERIMENTS = ROOT / "experiments"
RELEASES = ROOT / "releases"
DB_PATH = ROOT / "voynich.duckdb"


def evidence_dir(source_id: str) -> Path:
    return EVIDENCE / source_id
