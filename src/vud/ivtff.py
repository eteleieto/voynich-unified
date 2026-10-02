"""Lossless parsers for IVTFF 2.0 and legacy EVT (Landini–Stolfi interlinear) files.

Design rules
  * Every locus keeps its verbatim source line (`raw_line`) and file line number.
  * Markup is converted to *units*, never discarded:
        char        one transliteration-alphabet character (alphabet-native; NOT converted to EVA)
        rare        high-ascii / 'weirdo' glyph:  IVTFF @nnn;   EVT {&nnn} or 8-bit byte  -> value '@nnn;'
                    EVT descriptive weirdos like {&o'} keep value '&o''
        lig         IVTFF ligature {..}; value = inner text
        alt         IVTFF [a:b:c]; options = ['a','b','c'] in the transcriber's preference order
        unread      single unreadable character (IVTFF '?', EVT '*')
        unread_run  unknown number of unreadable characters (IVTFF '???')
        sep         word-boundary-like separator; value in
                      'space' (.), 'uncertain_space' (,), 'drawing' (<-> / EVT mid-line '-'),
                      'drawing_misaligned' (<~>)
        filler      EVT alignment filler: value 'skip' (!) = "one vote for no character here",
                    'nodata' (%) = "this transcriber gives no information here"
        comment     inline comment (<!..> or EVT {..}); value = comment text
        tag         IVTFF text tag <@X=y>; value = 'X=y'
        para_start  <%>
        para_end    <$> or EVT line-final '='
        line_end    EVT line-final '-'
  * Tokens are maximal runs of glyph-bearing units between separators. Their boundaries
    record *which* separator (or line edge / paragraph mark) bounds them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

GLYPH_KINDS = {"char", "rare", "lig", "alt", "unread", "unread_run"}

IVTFF_PAGE_RE = re.compile(r"^<(?P<page>f[0-9]+[rv][0-9]?|fRos)>\s*(?:<!(?P<vars>[^>]*)>)?\s*$")
IVTFF_LOCUS_RE = re.compile(
    r"^<(?P<page>f[0-9]+[rv][0-9]?|fRos)\.(?P<num>[0-9]+[a-z]?),(?P<locator>.)(?P<ltype>[A-Z][a-z0-9])"
    r"(?:;(?P<tr>[A-Z]))?>"
)
EVT_PAGE_RE = re.compile(r"^(?:## )?<(?P<page>f[0-9]+[rv][0-9]?|fRos)>\s*(?:\{(?P<vars>[^}]*)\})?")
EVT_LOCUS_RE = re.compile(
    r"^<(?P<page>f[0-9]+[rv][0-9]?|fRos)\.(?P<unit>[A-Za-z][A-Za-z0-9]*)\.(?P<num>[0-9]+[a-e]?);(?P<tr>[A-Z])>"
)
VAR_RE = re.compile(r"\$([A-Z])=(\S)")


@dataclass
class Unit:
    kind: str
    raw: str
    value: str | None = None
    options: list[str] | None = None
    start: int = 0
    end: int = 0


@dataclass
class Locus:
    page_id: str
    locus_num: str
    locator: str | None
    locus_type: str | None
    transcriber: str | None
    raw_line: str
    text_raw: str
    file_line: int
    lsi_unit: str | None = None
    units: list[Unit] = field(default_factory=list)
    tags: dict = field(default_factory=dict)


@dataclass
class Page:
    page_id: str
    raw_header: str
    file_line: int
    variables: dict


@dataclass
class Comment:
    page_id: str | None
    after_locus: str | None
    file_line: int
    text: str


@dataclass
class ParsedFile:
    header: str
    alphabet: str | None
    pages: list[Page]
    loci: list[Locus]
    comments: list[Comment]
    problems: list[str]


# ----------------------------------------------------------------------------- IVTFF text

def _split_options(s: str) -> list[str]:
    """Split alternatives on ':' that are not inside {} ligatures."""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == ":" and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def tokenize_ivtff_text(text: str, problems: list[str] | None = None) -> list[Unit]:
    units: list[Unit] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "<":
            j = text.find(">", i)
            if j < 0:
                (problems or []).append(f"unclosed '<' in {text!r}")
                units.append(Unit("char", text[i:], text[i:], start=i, end=n)); break
            inner = text[i + 1:j]
            raw = text[i:j + 1]
            if inner.startswith("!"):
                units.append(Unit("comment", raw, inner[1:].strip(), start=i, end=j + 1))
            elif inner.startswith("@"):
                units.append(Unit("tag", raw, inner[1:], start=i, end=j + 1))
            elif inner == "-":
                units.append(Unit("sep", raw, "drawing", start=i, end=j + 1))
            elif inner == "~":
                units.append(Unit("sep", raw, "drawing_misaligned", start=i, end=j + 1))
            elif inner == "%":
                units.append(Unit("para_start", raw, start=i, end=j + 1))
            elif inner == "$":
                units.append(Unit("para_end", raw, start=i, end=j + 1))
            else:
                units.append(Unit("comment", raw, inner, start=i, end=j + 1))
                (problems or []).append(f"unknown markup {raw!r}")
            i = j + 1
        elif c == "[":
            j = text.find("]", i)
            if j < 0:
                (problems or []).append(f"unclosed '[' in {text!r}")
                j = n - 1
            raw = text[i:j + 1]
            units.append(Unit("alt", raw, None, _split_options(text[i + 1:j]), start=i, end=j + 1))
            i = j + 1
        elif c == "{":
            j = text.find("}", i)
            if j < 0:
                (problems or []).append(f"unclosed '{{' in {text!r}")
                j = n - 1
            units.append(Unit("lig", text[i:j + 1], text[i + 1:j], start=i, end=j + 1))
            i = j + 1
        elif c == "@" and re.match(r"@\d{3};", text[i:i + 5]):
            units.append(Unit("rare", text[i:i + 5], text[i:i + 5], start=i, end=i + 5))
            i += 5
        elif c == ".":
            units.append(Unit("sep", c, "space", start=i, end=i + 1)); i += 1
        elif c == ",":
            units.append(Unit("sep", c, "uncertain_space", start=i, end=i + 1)); i += 1
        elif text.startswith("???", i):
            units.append(Unit("unread_run", "???", start=i, end=i + 3)); i += 3
        elif c == "?":
            units.append(Unit("unread", "?", start=i, end=i + 1)); i += 1
        elif c.isspace():
            i += 1
        else:
            units.append(Unit("char", c, c, start=i, end=i + 1)); i += 1
    return units


def regroup_sta(units: list[Unit]) -> list[Unit]:
    """STA1 glyphs are 2-character codes (family letter + member, e.g. 'A1', 'Ba'): merge char pairs."""
    out: list[Unit] = []
    i = 0
    while i < len(units):
        u = units[i]
        if (u.kind == "char" and u.value.isupper() and i + 1 < len(units) and units[i + 1].kind == "char"
                and units[i + 1].start == u.end):
            v = units[i + 1]
            out.append(Unit("char", u.raw + v.raw, u.value + v.value, start=u.start, end=v.end))
            i += 2
        else:
            out.append(u)
            i += 1
    return out


# ----------------------------------------------------------------------------- EVT text

def tokenize_evt_text(text: str, problems: list[str] | None = None) -> list[Unit]:
    units: list[Unit] = []
    stripped = text.rstrip()
    n = len(stripped)
    i = 0
    while i < n:
        c = stripped[i]
        if c == "{":
            j = stripped.find("}", i)
            if j < 0:
                (problems or []).append(f"unclosed '{{' in {text!r}")
                j = n - 1
            inner = stripped[i + 1:j]
            raw = stripped[i:j + 1]
            m = re.fullmatch(r"&(\d{3})", inner)
            if m:
                units.append(Unit("rare", raw, f"@{m.group(1)};", start=i, end=j + 1))
            elif inner.startswith("&"):
                units.append(Unit("rare", raw, inner, start=i, end=j + 1))
            else:
                units.append(Unit("comment", raw, inner, start=i, end=j + 1))
            i = j + 1
        elif c == "[":
            j = stripped.find("]", i)
            j = n - 1 if j < 0 else j
            units.append(Unit("alt", stripped[i:j + 1], None, stripped[i + 1:j].split("|"), start=i, end=j + 1))
            i = j + 1
        elif c == ".":
            units.append(Unit("sep", c, "space", start=i, end=i + 1)); i += 1
        elif c == ",":
            units.append(Unit("sep", c, "uncertain_space", start=i, end=i + 1)); i += 1
        elif c == "-":
            if i == n - 1:
                units.append(Unit("line_end", c, start=i, end=i + 1))
            else:
                units.append(Unit("sep", c, "drawing", start=i, end=i + 1))
            i += 1
        elif c == "=":
            units.append(Unit("para_end", c, start=i, end=i + 1)); i += 1
        elif c == "!":
            units.append(Unit("filler", c, "skip", start=i, end=i + 1)); i += 1
        elif c == "%":
            units.append(Unit("filler", c, "nodata", start=i, end=i + 1)); i += 1
        elif c == "*":
            units.append(Unit("unread", c, start=i, end=i + 1)); i += 1
        elif ord(c) > 127:
            units.append(Unit("rare", c, f"@{ord(c):03d};", start=i, end=i + 1)); i += 1
        elif c.isspace():
            i += 1
        else:
            units.append(Unit("char", c, c, start=i, end=i + 1)); i += 1
    return units


# ----------------------------------------------------------------------------- tokens

def plain(units: list[Unit], choice: int = 0) -> str:
    """Render glyph units as a string, taking alternative `choice` (0 = transcriber's first)."""
    out = []
    for u in units:
        if u.kind == "char":
            out.append(u.value)
        elif u.kind == "rare":
            out.append(u.value)
        elif u.kind == "lig":
            out.append(_strip_markup(u.value))
        elif u.kind == "alt":
            opts = u.options or [""]
            out.append(_strip_markup(opts[min(choice, len(opts) - 1)]))
        elif u.kind == "unread":
            out.append("?")
        elif u.kind == "unread_run":
            out.append("???")
    return "".join(out)


def _strip_markup(s: str) -> str:
    return s.replace("{", "").replace("}", "")


def tokens(units: list[Unit]) -> list[dict]:
    """Group glyph units into tokens bounded by separators / line edges / paragraph marks."""
    toks: list[dict] = []
    cur: list[int] = []
    before = "line_start"

    def flush(after: str):
        nonlocal cur, before
        glyph_units = [units[k] for k in cur if units[k].kind in GLYPH_KINDS]
        if glyph_units:
            n_alt = 1
            for u in glyph_units:
                if u.kind == "alt":
                    n_alt *= len(u.options or [1])
            toks.append({
                "unit_start": cur[0], "unit_end": cur[-1],
                "raw": "".join(units[k].raw for k in cur),
                "text": plain(glyph_units),
                "boundary_before": before, "boundary_after": after,
                "n_glyph_units": len(glyph_units),
                "has_alt": any(u.kind == "alt" for u in glyph_units),
                "has_unread": any(u.kind in ("unread", "unread_run") for u in glyph_units),
                "has_rare": any(u.kind == "rare" for u in glyph_units),
                "has_lig": any(u.kind == "lig" for u in glyph_units),
                "has_filler": any(units[k].kind == "filler" for k in cur),
                "n_readings": n_alt,
            })
            before = after
        elif after != "line_end":
            # separator with no glyphs since previous one: keep the stronger boundary info
            before = after if before in ("line_start",) else before + "+" + after
        cur = []

    for k, u in enumerate(units):
        if u.kind == "sep":
            flush(u.value)
        elif u.kind in ("para_end", "line_end"):
            flush(u.kind)
        elif u.kind == "para_start":
            if cur:
                flush("para_start")
            before = "para_start"
        else:
            cur.append(k)
    flush("line_end")
    return toks


# ----------------------------------------------------------------------------- file parsers

def _parse_vars(s: str | None) -> dict:
    return dict(VAR_RE.findall(s or ""))


def parse_ivtff(text: str) -> ParsedFile:
    lines = text.splitlines()
    header = lines[0] if lines else ""
    m = re.match(r"#=IVTFF (\S{4})", header)
    alphabet = m.group(1) if m else None
    pages: list[Page] = []
    loci: list[Locus] = []
    comments: list[Comment] = []
    problems: list[str] = []
    cur_page: str | None = None
    page_vars: dict = {}
    active_tags: dict = {}
    last_locus: str | None = None
    pending: tuple | None = None  # (locus_match, raw_line, text, line_no) for continuation

    def emit(mm, raw_line, txt, line_no):
        nonlocal last_locus
        units = tokenize_ivtff_text(txt, problems)
        if alphabet == "STA1":
            units = regroup_sta(units)
        for u in units:
            if u.kind == "tag" and "=" in u.value:
                k, v = u.value.split("=", 1)
                active_tags[k] = v
        loc = Locus(
            page_id=mm["page"], locus_num=mm["num"], locator=mm["locator"], locus_type=mm["ltype"],
            transcriber=mm["tr"], raw_line=raw_line, text_raw=txt, file_line=line_no, units=units,
            tags={**page_vars, **{k: v for k, v in active_tags.items() if v != "@"}},
        )
        if mm["page"] != cur_page:
            problems.append(f"line {line_no}: locus page {mm['page']} != current page {cur_page}")
        loci.append(loc)
        last_locus = f"{loc.page_id}.{loc.locus_num}"

    for ln, line in enumerate(lines[1:], start=2):
        if pending is not None:
            mm, raw, txt, start_ln = pending
            if not line.startswith("/"):
                problems.append(f"line {ln}: expected continuation line")
                emit(mm, raw, txt, start_ln); pending = None
            else:
                cont = line[1:].lstrip()
                raw = raw + "\n" + line
                if cont.rstrip().endswith("/"):
                    pending = (mm, raw, txt + cont.rstrip()[:-1].rstrip(), start_ln); continue
                emit(mm, raw, txt + cont, start_ln); pending = None
                continue
        if not line.strip():
            continue
        if line.startswith("#"):
            comments.append(Comment(cur_page, last_locus, ln, line[1:].strip()))
            continue
        pm = IVTFF_PAGE_RE.match(line)
        if pm:
            cur_page = pm["page"]
            page_vars = _parse_vars(pm["vars"])
            active_tags = {}
            last_locus = None
            pages.append(Page(cur_page, line, ln, page_vars))
            continue
        lm = IVTFF_LOCUS_RE.match(line)
        if lm:
            txt = line[lm.end():].strip()
            if txt.endswith("/"):
                pending = (lm.groupdict(), line, txt[:-1].rstrip(), ln)
                continue
            emit(lm.groupdict(), line, txt, ln)
            continue
        problems.append(f"line {ln}: unrecognised line {line[:60]!r}")
    return ParsedFile(header, alphabet, pages, loci, comments, problems)


def parse_evt(text: str) -> ParsedFile:
    lines = text.splitlines()
    pages: list[Page] = []
    loci: list[Locus] = []
    comments: list[Comment] = []
    problems: list[str] = []
    cur_page: str | None = None
    page_vars: dict = {}
    last_locus = None
    for ln, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        lm = EVT_LOCUS_RE.match(line)
        if lm:
            txt = line[lm.end():]
            units = tokenize_evt_text(txt, problems)
            loci.append(Locus(
                page_id=lm["page"], locus_num=lm["num"], locator=None, locus_type=None,
                transcriber=lm["tr"], raw_line=line, text_raw=txt.strip(), file_line=ln,
                lsi_unit=lm["unit"], units=units, tags=dict(page_vars),
            ))
            last_locus = f"{lm['page']}.{lm['num']}"
            continue
        pm = EVT_PAGE_RE.match(line)
        if pm and "." not in line.split(">")[0]:
            cur_page = pm["page"]
            page_vars = _parse_vars(pm["vars"])
            pages.append(Page(cur_page, line, ln, page_vars))
            last_locus = None
            continue
        if line.startswith("#"):
            comments.append(Comment(cur_page, last_locus, ln, line.lstrip("#").strip()))
            continue
        if re.match(r"^(## )?<f[^>]*\.[A-Za-z0-9]+>", line):
            comments.append(Comment(cur_page, last_locus, ln, "[unit header] " + line))
            continue
        problems.append(f"line {ln}: unrecognised line {line[:60]!r}")
    return ParsedFile("", "Eva-", pages, loci, comments, problems)
