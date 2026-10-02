"""Archetype glyph polygons must land on ink in the Yale scans (verifies the y-axis flip)."""
import pytest
from conftest import scalar
from PIL import Image

from vud import paths


def test_polygons_inside_canvas(con):
    assert scalar(con, """select count(*) from annotations.glyph_annotations g join codicology.canvases c on c.seq = g.yale_seq
                          where x_min < 0 or y_min < 0 or x_max > c.width or y_max > c.height""") == 0


def test_registered_fraction(con):
    assert scalar(con, "select avg((canvas_id is not null)::int) from annotations.glyph_annotations") > 0.99


def test_boxes_land_on_ink_not_on_flipped_positions(con):
    """Median ink coverage inside converted boxes must clearly exceed that of y-flipped boxes.

    Per-box comparisons are noisy (a flipped box can land on other text), so compare medians.
    Measured at build time: ~0.08 converted vs ~0.01 flipped.
    """
    import numpy as np
    rows = con.sql("""select c.local_path, c.height, x_min, y_min, x_max, y_max
                      from annotations.glyph_annotations g join codicology.canvases c on c.seq = g.yale_seq
                      order by g.yale_seq""").fetchall()
    rows = [r for i, r in enumerate(rows) if i % 15 == 0]  # deterministic ~110-box sample
    if not rows or not (paths.ROOT / rows[0][0]).exists():
        pytest.skip("images not available")
    cache, conv, flip = {}, [], []
    for path, H, x0, y0, x1, y1 in rows:
        if path not in cache:
            L = np.asarray(Image.open(paths.ROOT / path).convert("L"), dtype=np.float32)
            cache = {path: (L, float(np.median(L[::8, ::8])))}
        L, med = cache[path]

        def ink(a, b):
            c = L[int(a):int(b), int(x0):int(x1)]
            return float((c < 0.7 * med).mean()) if c.size else 0.0
        conv.append(ink(y0, y1)); flip.append(ink(H - y1, H - y0))
    assert np.median(conv) > 0.05
    assert np.median(conv) > 3 * np.median(flip)
