"""E2 transliterations: lossless parsing, uncertainty preserved, loci resolvable."""
import re

from conftest import scalar

from vud import ivtff, paths
from vud.build_transcriptions import IVTFF_SOURCES


def kinds(text):
    return [(u.kind, u.value, u.options) for u in ivtff.tokenize_ivtff_text(text)]


def test_alternatives_are_kept_not_collapsed():
    u = ivtff.tokenize_ivtff_text("shory.[cth:oto]res")
    alt = [x for x in u if x.kind == "alt"][0]
    assert alt.options == ["cth", "oto"]


def test_alternatives_with_ligatures_and_rare_glyphs():
    u = ivtff.tokenize_ivtff_text("dai[{cto}:@194;]y")
    assert [x for x in u if x.kind == "alt"][0].options == ["{cto}", "@194;"]


def test_uncertain_space_drawing_break_and_paragraph_marks():
    k = [x[0] if x[0] != "sep" else x[1] for x in kinds("<%>ok,ch<->dy.qo<~>l<$>")]
    assert k == ["para_start", "char", "char", "uncertain_space", "char", "char", "drawing",
                 "char", "char", "space", "char", "char", "drawing_misaligned", "char", "para_end"]


def test_inline_comment_and_rare_glyph():
    k = kinds("sholdy<!@254;>.@221;taiin")
    assert ("comment", "@254;", None) in k and ("rare", "@221;", None) in k


def test_evt_fillers_and_breaks():
    u = ivtff.tokenize_evt_text("cth!res.y,kor{&252}*%-")
    ks = [(x.kind, x.value) for x in u]
    assert ("filler", "skip") in ks and ("filler", "nodata") in ks and ("rare", "@252;") in ks
    assert ("unread", None) in ks and ks[-1] == ("line_end", None)


def test_token_boundaries_record_separator_type():
    t = ivtff.tokens(ivtff.tokenize_ivtff_text("ar,y.kor"))
    assert [(x["text"], x["boundary_before"], x["boundary_after"]) for x in t] == [
        ("ar", "line_start", "uncertain_space"), ("y", "uncertain_space", "space"), ("kor", "space", "line_end")]


def test_units_reconstruct_raw_text_exactly(con):
    """Concatenated unit raws == source text with whitespace removed, for every locus of every witness."""
    bad = scalar(con, """
        with u as (select witness_id, locus_id, string_agg(raw, '' order by unit_idx) as r
                   from annotations.units group by 1, 2)
        select count(*) from annotations.loci l join u using (witness_id, locus_id)
        where regexp_replace(l.text_raw, '\\s', '', 'g') <> regexp_replace(u.r, '\\s', '', 'g')""")
    assert bad == 0


def test_no_parse_problems_and_counts_match_files(con):
    for sid, fname in IVTFF_SOURCES.items():
        text = (paths.evidence_dir(sid) / fname).read_text(encoding="latin-1")
        n_loci = sum(1 for line in text.splitlines() if re.match(r"^<f[^>]*\.\d+,", line))
        assert scalar(con, "select count(*) from annotations.loci where source_id = ?", [sid]) == n_loci
        n_alt = sum(line.count("[") for line in text.splitlines() if line.startswith("<f") and "." in line.split(">")[0])
        assert scalar(con, "select count(*) from annotations.units where source_id = ? and kind = 'alt'", [sid]) == n_alt


def test_every_ivtff_locus_page_exists(con):
    assert scalar(con, """select count(*) from annotations.loci l where source_id <> 'lsi_16e6'
                          and page_id not in (select page_id from codicology.pages)""") == 0


def test_lsi_lines_map_to_ivtff_loci(con):
    mapped = scalar(con, "select avg((ivtff_locus_id is not null)::int) from annotations.loci where witness_id = 'lsi_16e6:H'")
    assert mapped > 0.98
    # mapped ivtff ids must exist in it2a
    assert scalar(con, """select count(*) from annotations.lsi_locus_map m
                          where ivtff_locus_id not in (select locus_id from annotations.loci where source_id='it2a')""") == 0


def test_witness_alphabets_declared(con):
    assert scalar(con, "select count(*) from annotations.witnesses where alphabet is null") == 0
