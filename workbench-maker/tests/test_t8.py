"""T8: thermoform back plate colours, light holes and multi-colour backs; vessel (bowl / vase) generator."""
import numpy as np
import pytest
import shapely
from shapely.geometry import Point

from maker import closures, thermo
from maker.generators.vessel import DEFAULT_SIZE, FORMS_TR
from maker.job import build
from maker.shapes import shape_polygon
from maker.sheets import get_sheet

TWO_COLOUR_TREE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 112">'
                   '<path d="M50 4 L70 36 L60 36 L80 66 L66 66 L92 96 L8 96 L34 66 L20 66 L40 36 L30 36 Z" fill="#1E8A4C"/>'
                   '<rect x="40" y="94" width="20" height="14" fill="#6B4423"/></svg>')


def _parts(res):
    return {p.name: p for p in res.parts}


def test_colours_follow_params():
    res, _ = build({"generator": "thermoform", "params": {"back_color": "#B3261E", "rim_color": "#E0B84C"}})
    p = _parts(res)
    assert p["back"].color.upper() == "#B3261E" and p["rim"].color.upper() == "#E0B84C"
    assert "group" not in p["back"].meta  # single colour: an ordinary part


def test_light_holes():
    plain, _ = build({"generator": "thermoform", "params": {"shape": "circle", "width_mm": 90}})
    holed, _ = build({"generator": "thermoform", "params": {"shape": "circle", "width_mm": 90, "back_holes": True,
                                                            "hole_d": 5, "hole_pitch": 9}})
    b0, b1 = _parts(plain)["back"].mesh, _parts(holed)["back"].mesh
    n = holed.meta["back_holes"]
    assert n > 30 and b1.is_watertight
    hole_vol = n * np.pi * 2.5 ** 2 * closures.BACK_MM
    assert b0.volume - b1.volume == pytest.approx(hole_vol, rel=0.03)
    assert any("Işık delikleri" in s for s in holed.notes)


def test_holes_keep_clear_of_magnets_and_edge():
    s = get_sheet()
    o, _ = thermo.clean_outline(shape_polygon("hexagon", 75), s, 10)
    o = thermo.centred(o)
    spots = closures._magnet_spots(o, 10.0)
    keep = Point(spots[0]).buffer(10)
    holes = closures.perforation(o, 4, 8, keep)
    assert holes and not any(h.intersects(keep) for h in holes)
    edge = o.buffer(-closures.WALL_MM)
    assert all(edge.contains(h) for h in holes)


def test_pitch_must_leave_a_bridge():
    with pytest.raises(ValueError, match="aralığı"):
        build({"generator": "thermoform", "params": {"back_holes": True, "hole_d": 6, "hole_pitch": 7}})


def test_two_colour_back_from_svg(tmp_path):
    svg = tmp_path / "agac.svg"
    svg.write_text(TWO_COLOUR_TREE)
    one, _ = build({"generator": "thermoform", "params": {"source": "logo", "logo": str(svg), "width_mm": 85}})
    two, _ = build({"generator": "thermoform", "params": {"source": "logo", "logo": str(svg), "width_mm": 85,
                                                          "back_colors": "logo"}})
    p = _parts(two)
    assert p["back"].color.upper() == "#1E8A4C" and p["back_1"].color.upper() == "#6B4423"
    assert p["back"].meta["group"] == p["back_1"].meta["group"] == "back"  # one multi-colour print object
    assert two.meta["back_colors"] == 2
    total = p["back"].mesh.volume + p["back_1"].mesh.volume
    assert total == pytest.approx(_parts(one)["back"].mesh.volume, rel=0.01)  # same plate, only split by colour


def test_logo_colours_need_a_logo():
    res, _ = build({"generator": "thermoform", "params": {"back_colors": "logo"}})
    assert any("logo / görsel" in w for w in res.warnings) and res.meta["back_colors"] == 1


@pytest.mark.parametrize("form", list(FORMS_TR))
def test_vessel_forms_print_without_supports(form):
    d, h = DEFAULT_SIZE[form]
    res, _ = build({"generator": "vessel", "params": {"form": form, "diameter_mm": d, "height_mm": h, "surface": "shinogi"}})
    m = res.parts[0].mesh
    assert m.is_watertight and m.volume > 0
    assert res.meta["max_overhang_deg"] <= 55 and not res.warnings
    assert m.extents[0] == pytest.approx(d, abs=1.0) and m.extents[2] == pytest.approx(h, abs=0.1)
    assert m.bounds[0][2] == pytest.approx(0, abs=1e-6)


def _inner_radius(mesh, z):
    """Distance from the axis to the first wall a ray meets at height z (the inside surface)."""
    hits = []
    for a in np.linspace(0, 2 * np.pi, 36, endpoint=False):
        loc, _, _ = mesh.ray.intersects_location([[0, 0, z]], [[np.cos(a), np.sin(a), 0]])
        hits.append(np.min(np.hypot(loc[:, 0], loc[:, 1])))
    return np.array(hits)


def test_pattern_only_outside():
    base = {"form": "chawan", "diameter_mm": 120, "height_mm": 75}
    smooth, _ = build({"generator": "vessel", "params": base})
    ribbed, _ = build({"generator": "vessel", "params": base | {"surface": "shinogi", "ribs": 24, "rib_mm": 1.2}})
    r0, r1 = _inner_radius(smooth.parts[0].mesh, 50), _inner_radius(ribbed.parts[0].mesh, 50)
    assert np.allclose(r0, r1, atol=0.05) and np.ptp(r1) < 0.2  # the inside stays round and unchanged
    assert ribbed.parts[0].mesh.volume < smooth.parts[0].mesh.volume  # grooves are cut into the outside


def test_vessel_wall_too_thin_for_pattern():
    with pytest.raises(ValueError, match="Duvar"):
        build({"generator": "vessel", "params": {"wall_mm": 1.6, "surface": "shinogi", "rib_mm": 1.0}})


def test_vessel_food_note():
    res, _ = build({"generator": "vessel", "params": {}})
    assert any("Gıda" in n for n in res.notes)


# ---------- printed lattice ("delikli form")
def test_lattice_hollow_piece():
    res, _ = build({"generator": "thermoform", "params": {"formed": "mesh", "shape": "heart", "width_mm": 90, "depth_mm": 14}})
    p = _parts(res)
    assert set(p) == {"female", "male", "blank", "shell"}  # no back plate, no rim, no sheet
    blank, shell = p["blank"], p["shell"]
    assert blank.printable and blank.material == "PLA" and blank.meta["count"] == 2  # two halves
    assert blank.mesh.is_watertight and blank.mesh.extents[2] == pytest.approx(0.8, abs=1e-6)
    assert not shell.printable and shell.mesh.extents[2] == pytest.approx(2 * (14 + 0.8), abs=0.3)
    assert res.meta["mesh_openings"] > 60 and res.sheet is None
    assert any("70–80 °C" in n for n in res.notes) and not any("Levha" in n for n in res.notes)


def test_lattice_is_mostly_open_and_strands_printable():
    s = get_sheet()
    o, _ = thermo.clean_outline(shape_polygon("circle", 90), s, 12)
    o = thermo.centred(o)
    for pattern in closures.LATTICES_TR:
        holes = closures.lattice_holes(o, pattern, 7, 1.2)
        open_area = sum(h.area for h in holes)
        assert 0.45 < open_area / o.area < 0.8
        solid = o.difference(shapely.union_all(holes))
        assert solid.buffer(-0.45).buffer(0.45).area > 0.9 * solid.area  # strands are at least ~0.9 mm wide


def test_lattice_molds_gap_matches_mesh_thickness():
    res, _ = build({"generator": "thermoform", "params": {"formed": "mesh", "mesh_t": 1.0}})
    assert res.meta["gap_mm"] == pytest.approx(1.2, abs=1e-6)  # mesh 1.0 + clearance 0.2


def test_lattice_on_back_plate():
    res, _ = build({"generator": "thermoform", "params": {"formed": "mesh", "mesh_halves": "one", "mesh_pattern": "honeycomb"}})
    p = _parts(res)
    assert {"back", "rim", "blank", "shell"} <= set(p) and "count" not in p["blank"].meta
    assert p["shell"].mesh.bounds[0][2] >= p["back"].mesh.bounds[1][2] - 0.05  # the lattice sits on the plate


def test_lattice_rejects_vacuum_and_tiny_cells():
    with pytest.raises(ValueError, match="pres"):
        build({"generator": "thermoform", "params": {"formed": "mesh", "method": "vacuum"}})
    with pytest.raises(ValueError, match="Hücre"):
        build({"generator": "thermoform", "params": {"formed": "mesh", "mesh_cell": 3, "mesh_strand": 1.2}})
