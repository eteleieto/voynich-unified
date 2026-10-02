"""Version history, common alphabet, spatial registration, visual objects, reading orders."""
from conftest import scalar


def test_legacy_releases_parsed_and_diffed(con):
    assert scalar(con, "select count(distinct release) from annotations.legacy_loci") == 9
    assert scalar(con, "select count(*) from derived.version_diffs where lineage='ZL' and from_release='ZL 3a' and change='edited'") > 0


def test_sta_witnesses_use_two_char_glyphs(con):
    # every STA glyph unit is a 2-character code (family letter + member)
    assert scalar(con, """select count(*) from annotations.units where witness_id like 'sta1:%' and kind = 'char'
                          and not regexp_full_match(value, '[A-Z][0-9a-z]')""") == 0


def test_common_alphabet_covers_all_traditions(con):
    w = {r[0] for r in con.sql("select distinct witness_id from derived.common_eva_loci").fetchall()}
    assert {"beva:ZL3b", "beva:IT2a", "beva:CD2a_0", "beva:FG2a", "beva:GC2a_0"} <= w
    # Currier and FSG, converted by the author's own rules, must broadly agree with ZL in basic Eva
    sim = scalar(con, """select avg(glyph_similarity) from derived.witness_agreement
                         where comparison_space='common_basic_eva' and witness_a='beva:CD2a_0' and witness_b='beva:ZL3b'""")
    assert sim > 0.9


def test_spatial_alignment_coverage_and_sanity(con):
    aligned = scalar(con, "select sum(n_aligned)::double / sum(n_p_loci) from observations.spatial_page_qa")
    assert aligned > 0.9
    # every aligned row id exists, and rows lie inside their canvas
    assert scalar(con, """select count(*) from observations.spatial_locus_alignment a
                          anti join observations.spatial_text_rows r using (row_id)""") == 0
    assert scalar(con, """select count(*) from observations.spatial_text_rows r join codicology.canvases c using (seq)
                          where r.x0 < 0 or r.y0 < 0 or r.x1 > c.width or r.y1 > c.height""") == 0


def test_measured_gaps_order_sensibly(con):
    """Transcribed certain spaces sit on wider physical gaps than uncertain ones, which exceed in-word gaps."""
    q = """select median(gap_norm) from observations.spatial_boundary_gaps
           where witness_id='zl3b' and boundary_kind=? and alignment_confidence > 0.6"""
    space, unc = scalar(con, q, ["space"]), scalar(con, q, ["uncertain_space"])
    inword = scalar(con, """select median(gap_norm) from observations.spatial_row_gaps g anti join
                            (select row_id, gap_idx from observations.spatial_boundary_gaps where witness_id='zl3b') using (row_id, gap_idx)""")
    assert space > unc > inword


def test_machine_observations_are_labelled(con):
    for t in ["spatial_text_rows", "spatial_locus_alignment", "spatial_boundary_gaps", "visual_objects"]:
        assert scalar(con, f"select count(*) from observations.{t} where review_status is null or review_status <> 'unreviewed'") == 0


def test_reading_orders_are_plural(con):
    assert scalar(con, "select count(*) from derived.reading_order_schemes where scope='loci'") >= 6
    # a scheme never invents loci
    assert scalar(con, """select count(*) from derived.reading_order_items i join derived.reading_order_schemes s using (scheme_id)
                          where s.scope='loci' and i.item_id not in (select locus_id from annotations.loci where source_id <> 'lsi_16e6')""") == 0


def test_bifolios(con):
    assert scalar(con, "select count(*) from codicology.bifolios where is_reconstruction") == 2


def test_token_spans_inside_their_rows(con):
    assert scalar(con, "select count(*) from observations.spatial_token_spans") > 50_000
    assert scalar(con, """select count(*) from observations.spatial_token_spans t join observations.spatial_text_rows r using (row_id)
                          where t.x0 < r.x0 - 1 or t.x1 > r.x1 + 1""") == 0
