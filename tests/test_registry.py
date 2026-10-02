from conftest import scalar

from vud import registry

REQUIRED = ["source_id", "name", "creator", "version", "layer", "kind", "acquisition", "canonical_location", "license"]


def test_registry_entries_complete():
    for s in registry.load_sources():
        for k in REQUIRED:
            assert s.get(k), f"{s.get('source_id')}: missing {k}"
        assert s["layer"] in {"E0", "E2", "H", "LIT", "CMP"}
        assert s["acquisition"] in {"auto", "iiif", "manual", "registered", "deferred"}


def test_every_row_cites_a_registered_source(con):
    ids = {r[0] for r in con.sql("select source_id from registry.sources").fetchall()}
    for table in ["annotations.loci", "annotations.tokens", "annotations.units", "annotations.page_variables",
                  "annotations.source_comments", "annotations.glyph_annotations", "codicology.canvases",
                  "codicology.material_samples", "codicology.radiocarbon", "literature.pages"]:
        used = {r[0] for r in con.sql(f"select distinct source_id from {table}").fetchall()}
        assert used <= ids, f"{table}: unregistered {used - ids}"


def test_hypothesis_layer_sources_not_used_as_evidence(con):
    h = {r[0] for r in con.sql("select source_id from registry.sources where layer = 'H'").fetchall()}
    used = {r[0] for r in con.sql("select distinct source_id from annotations.loci").fetchall()}
    assert not (h & used)
