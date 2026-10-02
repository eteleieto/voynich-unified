from conftest import scalar


def test_every_page_has_an_image(con):
    assert scalar(con, "select count(*) from codicology.pages where page_id not in (select page_id from codicology.canvas_pages)") == 0


def test_every_canvas_is_accounted_for(con):
    assert scalar(con, """select count(*) from codicology.canvases where seq not in (select seq from codicology.canvas_pages)
                          and seq not in (select seq from codicology.binding_canvases)""") == 0


def test_panel_regions_inside_canvas(con):
    assert scalar(con, """select count(*) from codicology.canvas_pages m join codicology.canvases c using (seq)
                          where region_xywh is not null and (region_xywh[1] < 0 or region_xywh[2] < 0
                            or region_xywh[1] + region_xywh[3] > c.width or region_xywh[2] + region_xywh[4] > c.height)""") == 0


def test_canvas_files_hashed(con):
    assert scalar(con, "select count(*) from codicology.canvases where sha256 is null or local_path is null") == 0


def test_page_order_and_quires(con):
    assert scalar(con, "select count(*) from codicology.pages") == 227
    assert scalar(con, "select count(*) from codicology.folios where not present") == 14  # 12, 59-64, 74, 91-92, 97-98, 109-110
    assert scalar(con, "select count(distinct quire_num) from codicology.pages") == 18


def test_material_samples_reference_real_pages(con):
    assert scalar(con, "select count(*) from codicology.material_samples") == 20
    assert scalar(con, """select count(*) from codicology.material_samples where page_id is not null
                          and page_id not in (select page_id from codicology.pages)""") == 0
    assert scalar(con, "select cal95_from_ad || '-' || cal95_to_ad from codicology.radiocarbon where kind='combined'") == "1404-1438"
