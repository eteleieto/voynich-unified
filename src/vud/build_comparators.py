"""CMP: comparator corpora in one schema (data/comparative/).

  documents.parquet   doc_id, source_id, kind, language, title, author, date, place, n_segments, n_words,
                      file, url — kind ∈ natural_language | ciphertext | cipher_plaintext | translation |
                      pseudo_text | manuscript_record
  segments.parquet    doc_id, segment_idx, page_ref, text  (paragraphs / verse lines / document lines)
  token_freq.parquet  doc_id, token, n  (lower-cased, letters only; ciphertext tokens kept verbatim)

Comparators are never mixed into Voynich tables. Use them as controls: compare a Voynich statistic
against natural languages, a real cipher with known plaintext, and a meaningless generator.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter

import pyarrow as pa
import pyarrow.parquet as pq

from . import paths, registry

OUT = paths.DATA / "comparative"
TEI = "{http://www.tei-c.org/ns/1.0}"
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def _docs_cc(docs, segs):
    sid = "cmp_corpus_corporum"
    d = paths.evidence_dir(sid) / "texts"
    if not d.exists():
        return
    for f in sorted(d.glob("*.xml")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        def first(path):
            el = root.find(path)
            return " ".join("".join(el.itertext()).split()) if el is not None else None
        title = first(f".//{TEI}titleStmt/{TEI}title") or f.stem
        author = first(f".//{TEI}titleStmt/{TEI}author")
        date = first(f".//{TEI}creation//{TEI}date") or first(f".//{TEI}profileDesc//{TEI}date")
        body = root.find(f".//{TEI}body")
        lang = root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang") or \
            (root.find(f".//{TEI}language").attrib.get("ident") if root.find(f".//{TEI}language") is not None else "la")
        lang = {"la": "lat", "lat": "lat"}.get(lang, lang)
        doc_id = f"cc:{f.stem}"
        units = []
        if body is not None:
            for el in body.iter():
                tag = el.tag.replace(TEI, "")
                if tag in ("p", "l", "ab", "head"):
                    t = " ".join("".join(el.itertext()).split())
                    if t:
                        units.append(t)
        for i, t in enumerate(units):
            segs.append({"doc_id": doc_id, "segment_idx": i, "page_ref": None, "text": t})
        docs.append({"doc_id": doc_id, "source_id": sid, "kind": "natural_language", "language": lang,
                     "title": title, "author": author, "date": date, "place": None, "file": f"texts/{f.name}",
                     "url": f"https://mlat.uzh.ch/php_modules/download.php?idno={f.stem}&type=file-xml",
                     "n_segments": len(units), "n_words": sum(len(WORD.findall(u)) for u in units)})


def _plain_lines(text, skip_comment=True):
    page, out = None, []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"#+\s*(?:PAGE\s*)?(\d+)\s*$", s, re.I)
        if m:
            page = m.group(1); continue
        if skip_comment and (s.startswith("#") or s.startswith("==")):
            continue
        out.append((page, s))
    return out


def _docs_simple(docs, segs):
    specs = [
        ("cmp_copiale_cipher", "copiale-transcription.txt", "ciphertext", "copiale-cipher", "Copiale cipher (ciphertext transcription)"),
        ("cmp_copiale_cipher", "copiale-deciphered.txt", "cipher_plaintext", "de", "Copiale cipher (deciphered German plaintext)"),
        ("cmp_copiale_cipher", "copiale-translation.txt", "translation", "en", "Copiale cipher (English translation)"),
        ("cmp_copiale_cipher", "copiale-master-transcription.txt", "ciphertext", "copiale-cipher", "Copiale 'master' document (ciphertext)"),
        ("cmp_copiale_cipher", "copiale-master-deciphered.txt", "cipher_plaintext", "de", "Copiale 'master' document (deciphered)"),
        ("cmp_timm_selfcitation", "generated_text.txt", "pseudo_text", "eva-like", "Self-citation generated text (default properties)"),
    ]
    for sid, fname, kind, lang, title in specs:
        p = paths.evidence_dir(sid) / fname
        if not p.exists():
            continue
        lines = _plain_lines(p.read_text(encoding="utf-8", errors="replace"))
        doc_id = f"{sid}:{fname}"
        for i, (pg, t) in enumerate(lines):
            segs.append({"doc_id": doc_id, "segment_idx": i, "page_ref": pg, "text": t})
        docs.append({"doc_id": doc_id, "source_id": sid, "kind": kind, "language": lang, "title": title,
                     "author": None, "date": None, "place": None, "file": fname, "url": None,
                     "n_segments": len(lines), "n_words": sum(len(t.split()) for _, t in lines)})
    sid = "cmp_gutenberg_vernaculars"
    for p in sorted(paths.evidence_dir(sid).glob("pg*.txt")) if paths.evidence_dir(sid).exists() else []:
        txt = p.read_text(encoding="utf-8", errors="replace")
        a, b = txt.find("*** START OF"), txt.find("*** END OF")
        body = txt[txt.find("\n", a) + 1:b] if a >= 0 and b > a else txt
        paras = [" ".join(x.split()) for x in re.split(r"\n\s*\n", body) if x.strip()]
        lang = p.stem.rsplit("_", 1)[-1]
        doc_id = f"{sid}:{p.stem}"
        for i, t in enumerate(paras):
            segs.append({"doc_id": doc_id, "segment_idx": i, "page_ref": None, "text": t})
        docs.append({"doc_id": doc_id, "source_id": sid, "kind": "natural_language", "language": lang,
                     "title": p.stem, "author": None, "date": None, "place": None, "file": p.name,
                     "url": f"https://www.gutenberg.org/ebooks/{p.stem[2:].split('_')[0]}",
                     "n_segments": len(paras), "n_words": sum(len(WORD.findall(t)) for t in paras)})


def _docs_ds(docs):
    sid = "cmp_digital_scriptorium"
    d = paths.evidence_dir(sid) / "search"
    seen = {}
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        q = f.stem.rsplit("_p", 1)[0]
        for r in data.get("data", []):
            a = r.get("attributes", {})
            val = lambda k: (a.get(k, {}).get("attributes", {}).get("value") if isinstance(a.get(k), dict) else a.get(k))  # noqa: E731
            rid = r.get("id")
            if rid in seen:
                seen[rid]["matched_queries"].append(q); continue
            row = {"doc_id": f"ds:{rid}", "source_id": sid, "kind": "manuscript_record", "language": None,
                   "title": val("title_facet"), "author": None, "date": val("date_meta"), "place": val("place_facet"),
                   "file": f"search/{f.name}", "url": (r.get("links") or {}).get("self"),
                   "n_segments": 0, "n_words": 0, "shelfmark": val("title"), "matched_queries": [q]}
            seen[rid] = row
    docs += list(seen.values())


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    docs, segs = [], []
    _docs_cc(docs, segs)
    _docs_simple(docs, segs)
    _docs_ds(docs)
    for d in docs:
        d.setdefault("shelfmark", None); d.setdefault("matched_queries", None)
    pq.write_table(pa.Table.from_pylist(docs), OUT / "documents.parquet")
    pq.write_table(pa.Table.from_pylist(segs, schema=pa.schema([
        ("doc_id", pa.string()), ("segment_idx", pa.int32()), ("page_ref", pa.string()), ("text", pa.string())])),
        OUT / "segments.parquet")
    kinds = {d["doc_id"]: d["kind"] for d in docs}
    freq = {}
    for s in segs:
        toks = s["text"].split() if kinds[s["doc_id"]] in ("ciphertext", "pseudo_text") else \
            [w.lower() for w in WORD.findall(s["text"])]
        freq.setdefault(s["doc_id"], Counter()).update(toks)
    pq.write_table(pa.Table.from_pylist([{"doc_id": d, "token": t, "n": n} for d, c in freq.items() for t, n in c.items()]),
                   OUT / "token_freq.parquet")
    return {"documents": len(docs), "segments": len(segs)}
