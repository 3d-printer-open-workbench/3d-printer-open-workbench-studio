import pytest
from shapely.geometry import box

from kaligraf.fonts import load_ttfont
from kaligraf.text2d import (
    build_text,
    contours_to_geometry,
    font_cap_height,
    thin_regions,
)

TR = "çğıİöşüÇĞÖŞÜ"


def test_flat_width_is_exact(montserrat):
    r = build_text("Portalin", montserrat, "flat", width_mm=400)
    assert r.width_mm == pytest.approx(400, abs=0.05)
    assert r.geometry.bounds[0] == pytest.approx(0, abs=1e-6)
    assert r.geometry.bounds[1] == pytest.approx(0, abs=1e-6)
    assert r.geometry.area > 0 and r.geometry.is_valid
    assert not r.warnings  # strokes well above 2 mm at 40 cm


def test_letters_cap_height(bebas):
    r = build_text("HEH", bebas, "letters", cap_height_mm=200)
    assert r.cap_height_mm == pytest.approx(200, abs=0.01)
    assert r.height_mm == pytest.approx(200, abs=0.5)  # flat-topped caps, no overshoot
    assert r.baseline_y == pytest.approx(0, abs=0.5)
    assert len(r.pieces) == 3


def test_cap_height_metric(bebas):
    assert font_cap_height(load_ttfont(bebas)) > 0


def test_turkish_characters_render(montserrat):
    r = build_text(TR, montserrat, "flat", width_mm=300)
    assert [g.char for g in r.glyphs] == list(TR)
    assert all(g.geometry.area > 0 for g in r.glyphs)
    assert not any("no glyph" in w for w in r.warnings)


def test_turkish_dotted_capital_has_dot(bebas):
    r_i = build_text("I", bebas, "letters", cap_height_mm=100)
    r_dot = build_text("İ", bebas, "letters", cap_height_mm=100)
    assert r_dot.height_mm > r_i.height_mm + 5  # dot above cap height
    assert len(r_dot.pieces) == 1  # dot stays with its letter


def test_sukru_pieces_and_cedilla(bebas):
    r = build_text("ŞÜKRÜ", bebas, "letters", cap_height_mm=200)
    assert len(r.pieces) == 5
    assert [p.text for p in r.pieces] == list("ŞÜKRÜ")
    assert r.baseline_y > 0  # cedilla goes below the baseline


def test_missing_glyph_warning(bebas):
    r = build_text("AB中", bebas, "letters", cap_height_mm=50)
    assert any("中" in w for w in r.warnings)
    assert [g.char for g in r.glyphs] == ["A", "B"]


def test_kerning_applied(montserrat):
    r = build_text("AV", montserrat, "letters", cap_height_mm=100)
    a, v = r.glyphs
    assert v.geometry.bounds[0] < a.geometry.bounds[2]  # kerned pair overlaps in x
    assert len(r.pieces) == 2


def test_tracking_widens(montserrat):
    base = build_text("ABCD", montserrat, "letters", cap_height_mm=100)
    wide = build_text("ABCD", montserrat, "letters", cap_height_mm=100, tracking=0.1)
    upem = load_ttfont(montserrat)["head"].unitsPerEm
    assert wide.width_mm - base.width_mm == pytest.approx(3 * 0.1 * upem * base.scale, rel=1e-3)


def test_touching_glyphs_union(montserrat):
    r = build_text("HH", montserrat, "letters", cap_height_mm=100, tracking=-0.4)
    assert len(r.pieces) == 1
    assert r.pieces[0].geometry.geom_type == "Polygon" or r.pieces[0].geometry.area > 0
    apart = build_text("HH", montserrat, "letters", cap_height_mm=100, tracking=0.2)
    assert len(apart.pieces) == 2


def test_two_lines_and_three_line_warning(montserrat):
    one = build_text("Portalin", montserrat, "flat", width_mm=200)
    two = build_text("Portalin\nStudio", montserrat, "flat", width_mm=200)
    assert two.height_mm > one.height_mm * 1.5
    assert len(two.lines) == 2 and not any("lines" in w for w in two.warnings)
    three = build_text("a\nb\nc", montserrat, "flat", width_mm=200)
    assert any("3 lines" in w for w in three.warnings)


def test_line_spacing(montserrat):
    a = build_text("Ab\nCd", montserrat, "flat", width_mm=100, line_spacing=1.0)
    b = build_text("Ab\nCd", montserrat, "flat", width_mm=100, line_spacing=1.5)
    assert b.height_mm / b.width_mm > a.height_mm / a.width_mm


def test_letters_limits(bebas):
    with pytest.raises(ValueError):
        build_text("A" * 31, bebas, "letters", cap_height_mm=50)
    r = build_text("AB\nCD", bebas, "letters", cap_height_mm=50)
    assert len(r.lines) == 1 and any("single line" in w for w in r.warnings)
    with pytest.raises(ValueError):
        build_text("  ", bebas, "letters", cap_height_mm=50)


def test_min_feature_warning_scales_with_size(montserrat):
    small = build_text("Portalin", montserrat, "flat", width_mm=40)
    assert any("thinner than 2.0 mm" in w for w in small.warnings)
    big = build_text("Portalin", montserrat, "letters", cap_height_mm=100)
    assert not any("thinner" in w for w in big.warnings)
    tiny_letters = build_text("Portalin", montserrat, "letters", cap_height_mm=20)
    assert any("thinner than 3.0 mm" in w for w in tiny_letters.warnings)


def test_thin_regions_unit():
    bar = box(0, 0, 50, 1.0)
    assert thin_regions(bar, 2.0)
    assert not thin_regions(box(0, 0, 50, 5.0), 2.0)


def test_nonzero_winding_overlap_and_hole():
    sq = lambda x0, y0, x1, y1: [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]  # clockwise
    ccw = lambda x0, y0, x1, y1: list(reversed(sq(x0, y0, x1, y1)))
    g = contours_to_geometry([sq(0, 0, 10, 10), sq(5, 0, 15, 10), ccw(2, 2, 4, 4)])
    assert g.area == pytest.approx(150 - 4)


def test_overlapping_contours_stay_filled(montserrat):
    """Variable-font glyphs overlap contours (P: stem + bowl); nonzero winding must not carve notches."""
    from kaligraf.text2d import build_text

    g = build_text("P", montserrat, "flat", width_mm=100).geometry
    polys = list(getattr(g, "geoms", [g]))
    assert len(polys) == 1 and len(polys[0].interiors) == 1  # only the real counter


def test_language_tr_selects_locl_dotted_i(fonts_dir):
    from kaligraf.fonts import FontNotFoundError, resolve_font

    try:
        cinzel = resolve_font("Cinzel", fonts_dir)
    except FontNotFoundError:
        pytest.skip("Cinzel missing")
    plain = build_text("i", cinzel, "letters", cap_height_mm=100)
    tr = build_text("i", cinzel, "letters", cap_height_mm=100, language="tr")
    assert tr.height_mm > plain.height_mm + 5  # Cinzel's TRK locl i.sc carries a dot
    assert len(tr.pieces) == 1  # dot stays with its letter


def test_job_language_field():
    from kaligraf.job import Job

    assert Job.from_dict({"mode": "letters", "text": "iz", "letter_height_cm": 10, "language": "tr"}).language == "tr"
