"""voynich.duckdb: one schema per layer, a view per Parquet table, plus convenience views.

Schemas:  registry · codicology · annotations (E2) · observations (E1) · derived (E3) · hypotheses (H) · literature
The database holds only views; Parquet files remain the canonical storage. Rebuild with `vud db`.
"""
from __future__ import annotations

import duckdb

from . import paths

LAYER_DIRS = {
    "registry": paths.REGISTRY_DATA,
    "codicology": paths.CODICOLOGY,
    "annotations": paths.ANNOTATIONS,
    "observations": paths.OBSERVATIONS,
    "derived": paths.DERIVED,
    "hypotheses": paths.DATA / "hypotheses",
    "literature": paths.DATA / "literature",
    "comparative": paths.DATA / "comparative",
}

CONVENIENCE = r"""
-- Tokens with page-level context (section/language/hand are ZL3b page variables: one authority, not truth)
create or replace view main.tokens as
select t.*, p.quire_num, p.illustration as section, p.currier_language, p.davis_hand, p.currier_hand,
       p.ivtff_order as page_order
from annotations.tokens t left join codicology.pages p using (page_id);

-- One row per IVTFF locus with the reading of each main witness side by side
create or replace view main.locus_readings as
select coalesce(l.ivtff_locus_id, l.locus_id) as locus_id, any_value(l.page_id) as page_id,
       max(case when witness_id='zl3b' then locus_type end) as locus_type,
       max(case when witness_id='zl3b' then text end) as zl3b,
       max(case when witness_id='it2a' then text end) as it2a,
       max(case when witness_id='gc2a' then text end) as gc2a_v101,
       max(case when witness_id='cd2a' then text end) as cd2a_currier,
       max(case when witness_id='fg2a' then text end) as fg2a_fsg,
       max(case when witness_id='rf1b_er' then text end) as rf1b_er,
       max(case when witness_id='lsi_16e6:U' then text end) as lsi_stolfi,
       max(case when witness_id='lsi_16e6:V' then text end) as lsi_grove
from annotations.loci l where coalesce(l.ivtff_locus_id, l.locus_id) is not null
group by 1;

-- Every alternative reading as its own row (rank 1 = transcriber's preferred)
create or replace view main.alternatives as
select witness_id, locus_id, unit_idx, token_idx, raw, unnest(options) as option,
       generate_subscripts(options, 1) as rank
from annotations.units where kind = 'alt';

-- Separators (word-boundary observations) with their kind, for boundary studies
create or replace view main.boundaries as
select witness_id, locus_id, unit_idx, value as boundary_kind, raw
from annotations.units where kind = 'sep';

-- Where to look: page -> canvas image file (+ approximate panel box for foldouts)
create or replace view main.page_images as
select m.page_id, m.seq, c.label as yale_label, c.local_path, c.width, c.height, m.role,
       m.region_xywh, m.region_method, m.method as map_method, m.confidence, m.note, c.image_service
from codicology.canvas_pages m join codicology.canvases c using (seq);

-- Machine locus->row alignments with the most recent review verdict (if any) from observations
create or replace view main.alignment_reviewed as
with rv as (
  select target_id as locus_id, value_text as verdict, value_json, region_xywh, author, created_at,
         row_number() over (partition by target_id order by created_at desc) as rn
  from observations.observations where property = 'machine_review' and target_type = 'locus')
select a.*, rv.verdict as review_verdict, rv.author as reviewed_by, rv.created_at as reviewed_at,
       rv.region_xywh as corrected_xywh, rv.value_json as correction
from observations.spatial_locus_alignment a left join rv on rv.locus_id = a.locus_id and rv.rn = 1;

-- Glyph annotations with page names
create or replace view main.glyphs_located as
select g.*, list(m.page_id) as candidate_pages
from annotations.glyph_annotations g left join codicology.canvas_pages m on m.seq = g.yale_seq
  and (m.region_xywh is null or ((g.x_min + g.x_max) / 2 >= m.region_xywh[1]
                                  and (g.x_min + g.x_max) / 2 < m.region_xywh[1] + m.region_xywh[3]))
group by all;
"""


def build() -> list[str]:
    """Build into a temp file and atomically swap it in, so concurrent readers never see a missing DB."""
    import os
    tmp = paths.DB_PATH.with_name(paths.DB_PATH.name + f".tmp{os.getpid()}")
    if tmp.exists():
        tmp.unlink()
    con = duckdb.connect(str(tmp))
    made = []
    for schema, d in LAYER_DIRS.items():
        con.sql(f"create schema if not exists {schema}")
        if not d.exists():
            continue
        for f in sorted(d.glob("*.parquet")):
            name = f.stem.lstrip("_")
            con.sql(f"create or replace view {schema}.{name} as select * from read_parquet('{f}')")
            made.append(f"{schema}.{name}")
    con.sql(CONVENIENCE)
    made += ["main.tokens", "main.locus_readings", "main.alternatives", "main.boundaries",
             "main.page_images", "main.glyphs_located", "main.alignment_reviewed"]
    con.close()
    os.replace(tmp, paths.DB_PATH)
    return made


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(paths.DB_PATH), read_only=read_only)
