"""E3: every transliteration tradition in ONE alphabet, using the author's own tool and rules.

Pipeline (fully reproducible from evidence):
  evidence/bitrans_tool/bitrans.c  --cc-->  tools/bin/bitrans
  evidence/sta1_transliterations/*.txt  --bitrans + STA-Eva_Bint.bit (from bitfiles.zip)-->  basic Eva
Outputs (data/derived/):
  common_eva/<stem>.txt            converted IVTFF files (so they can be inspected/diffed)
  common_eva_loci.parquet          loci per converted witness (witness_id 'beva:<stem>')
  common_eva_tokens.parquet        tokens per converted witness
The rules map many rare STA glyphs onto their 'nearest basic Eva' — a deliberate, lossy simplification.
Use annotations (STA1 witnesses) when the distinction matters.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from . import ivtff, paths
from .build_transcriptions import STA_FILES, STA_SOURCE, _locus_text

TOOLS = paths.ROOT / "tools" / "bin"
RULES = "STA-Eva_Bint.bit"


def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bitrans_binary():
    exe = TOOLS / "bitrans"
    src = paths.evidence_dir("bitrans_tool") / "bitrans.c"
    stamp = TOOLS / "bitrans.src.sha256"
    if not exe.exists() or not stamp.exists() or stamp.read_text() != _sha(src):
        TOOLS.mkdir(parents=True, exist_ok=True)
        cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if not cc:
            raise RuntimeError("a C compiler is needed to build bitrans")
        subprocess.run([cc, "-O2", "-w", "-o", str(exe), str(src)], check=True)
        stamp.write_text(_sha(src))
    return exe


def rules_file():
    TOOLS.mkdir(parents=True, exist_ok=True)
    out = TOOLS / RULES
    with zipfile.ZipFile(paths.evidence_dir("bitrans_tool") / "bitfiles.zip") as z:
        out.write_bytes(z.read(RULES))
    return out


def build() -> dict:
    exe, rules = bitrans_binary(), rules_file()
    outdir = paths.DERIVED / "common_eva"
    outdir.mkdir(parents=True, exist_ok=True)
    loci, toks = [], []
    for stem, (fname, renders) in STA_FILES.items():
        src = paths.evidence_dir(STA_SOURCE) / fname
        dst = outdir / f"{stem}.txt"
        subprocess.run([str(exe), "-m2", "-f", str(rules), str(src), str(dst)], check=True)
        pf = ivtff.parse_ivtff(dst.read_text(encoding="latin-1"))
        wid = f"beva:{stem}"
        for L in pf.loci:
            tk = ivtff.tokens(L.units)
            lid = f"{L.page_id}.{L.locus_num}"
            loci.append({"witness_id": wid, "renders": renders, "page_id": L.page_id, "locus_id": lid,
                         "locus_type": L.locus_type, "text": _locus_text(L.units, tk), "n_tokens": len(tk),
                         "raw_line": L.raw_line})
            for i, t in enumerate(tk):
                toks.append({"witness_id": wid, "renders": renders, "page_id": L.page_id, "locus_id": lid,
                             "token_idx": i, "text": t["text"], "raw": t["raw"],
                             "boundary_before": t["boundary_before"], "boundary_after": t["boundary_after"],
                             "has_alt": t["has_alt"], "has_unread": t["has_unread"]})
    pq.write_table(pa.Table.from_pylist(loci), paths.DERIVED / "common_eva_loci.parquet")
    pq.write_table(pa.Table.from_pylist(toks), paths.DERIVED / "common_eva_tokens.parquet")
    (outdir / "_recipe.txt").write_text(
        f"bitrans.c sha256 {_sha(paths.evidence_dir('bitrans_tool') / 'bitrans.c')}\n"
        f"{RULES} sha256 {_sha(rules)}\ncommand: bitrans -m2 -f {RULES} <STA file> <out>\n")
    return {"witnesses": len(STA_FILES), "loci": len(loci), "tokens": len(toks)}
