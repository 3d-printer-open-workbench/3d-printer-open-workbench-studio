"""T9: desk name plate generator."""
import pytest
from shapely.geometry import box

from maker import flat
from maker.generators import GENERATORS
from maker.generators.nameplate import RIM_IN, SLOT_KEEP, STAND_CLEAR
from maker.job import build


def _parts(res):
    return {p.name: p for p in res.parts}


def _make(**params):
    res, _ = build({"generator": "nameplate", "params": params})
    return res


def test_registered_and_default_builds_two_colours_with_stand():
    assert GENERATORS["nameplate"].group == "Hediyelik"
    res = _make()
    p = _parts(res)
    assert set(p) == {"base", "rim", "stand"} and all(q.mesh.is_watertight for q in res.parts)
    assert p["base"].color != p["rim"].color and res.meta["colors"] == [p["base"].color, p["rim"].color]
    assert list(p["base"].mesh.extents.round(1)) == [200.0, 60.0, 3.0]
    assert p["rim"].mesh.bounds[0][2] == pytest.approx(3.0) and p["rim"].mesh.bounds[1][2] == pytest.approx(4.2)
    assert res.warnings == [] and res.meta["size_mm"] == [200, 60, 4.2]
    assert p["base"].meta["group"] == "nameplate" and p["stand"].meta["group"] == "stand"


def test_raised_layer_stays_on_the_plate_and_out_of_the_slot():
    for params in ({}, {"title": "Avukat", "height_mm": 70}, {"text": "Öğr. Gör. Çağla Öztürk", "title": "Matematik Öğretmeni", "height_mm": 75}):
        res = _make(**params)
        (x0, y0, _), (x1, y1, _) = _parts(res)["rim"].mesh.bounds
        W, H = res.meta["size_mm"][:2]
        assert x0 >= -W / 2 + RIM_IN - 0.01 and x1 <= W / 2 - RIM_IN + 0.01, params
        assert y1 <= H / 2 - RIM_IN + 0.01 and y0 >= -H / 2 + RIM_IN + SLOT_KEEP - 0.01, params  # bottom strip is plain


def test_title_line_is_smaller_and_below_the_name():
    one, two = _make(height_mm=70), _make(height_mm=70, title="Avukat", rim=False)
    assert set(_parts(two)) == {"base", "text", "stand"} and two.meta["title"] == "Avukat"
    assert _parts(two)["text"].mesh.volume > 0 and one.warnings == []
    # the name alone uses the whole text area; with a title it gets the upper part only
    assert _parts(_make(height_mm=70, rim=False))["text"].mesh.bounds[0][1] < _parts(two)["text"].mesh.bounds[0][1] + 15


def test_stand_slot_matches_the_plate_and_can_be_switched_off():
    res = _make(base_mm=4, width_mm=180)
    stand = _parts(res)["stand"].mesh
    ref, length = flat.slot_stand(180, 4, 75.0, STAND_CLEAR)
    assert length == 90 and stand.volume == pytest.approx(ref.volume, rel=1e-6)
    assert any("4.6 mm" in n for n in res.notes)
    # on the bed the stand lies in front of the plate, not under it
    assert stand.bounds[1][1] < _parts(res)["base"].mesh.bounds[0][1]
    flat_only = _make(stand=False)
    assert "stand" not in _parts(flat_only) and flat_only.meta["stand"] is False
    assert _parts(flat_only)["rim"].mesh.bounds[0][1] < _parts(_make())["rim"].mesh.bounds[0][1]  # frame uses the full height


def test_single_colour_merges_into_one_part():
    res = _make(text_color="#1F2A44", stand=False)
    assert [p.name for p in res.parts] == ["base"] and res.meta["colors"] == ["#1F2A44"]
    assert any("tek renk" in n for n in res.notes)


def test_errors_and_limits():
    with pytest.raises(ValueError, match="isim yazın"):
        _make(text="  ")
    with pytest.raises(ValueError, match="çok alçak"):
        _make(height_mm=35)
    with pytest.raises(ValueError):
        _make(width_mm=400)
    tiny = _make(text="Prof. Dr. Abdülkadir Müftüoğlu Karahasanoğlu", title="Kardiyoloji Anabilim Dalı Başkanı", width_mm=100, height_mm=50)
    assert any("ince" in w for w in tiny.warnings)  # too much text for the plate: the user is told
