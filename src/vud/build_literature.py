"""Extract page text from literature/specification PDFs so agents can search them.

Output: data/literature/pages.parquet (source_id, file, page, text, extraction) and one .txt per file.
Extraction is the PDF's own text layer (often OCR of a scan) — treat as noisy; the PDF is the evidence.
"""
from __future__ import annotations

import warnings

import pyarrow as pa
import pyarrow.parquet as pq
from pypdf import PdfReader

from . import paths, registry


def build() -> dict:
    out = paths.DATA / "literature"
    out.mkdir(parents=True, exist_ok=True)
    layers = {s["source_id"]: s for s in registry.load_sources()}
    rows = []
    for r in registry.read_manifest():
        if not r["path"].endswith(".pdf"):
            continue
        p = paths.evidence_dir(r["source_id"]) / r["path"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = PdfReader(p)
            texts = [(pg.extract_text() or "") for pg in reader.pages]
        for i, t in enumerate(texts, start=1):
            rows.append({"source_id": r["source_id"], "layer": layers.get(r["source_id"], {}).get("layer"),
                         "file": r["path"], "page": i, "text": t,
                         "extraction": "pdf_text_layer" if t.strip() else "none (scanned image; read the PDF)"})
        (out / f"{r['source_id']}__{p.stem}.txt").write_text(
            "\n".join(f"\n===== page {i} =====\n{t}" for i, t in enumerate(texts, start=1)))
    pq.write_table(pa.Table.from_pylist(rows), out / "pages.parquet")
    return {"pdf_pages": len(rows)}
