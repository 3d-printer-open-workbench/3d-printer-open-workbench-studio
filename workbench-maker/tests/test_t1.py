"""T1: thermoform press molds. Acceptance: parts watertight, fit 250x250, male-female gap = sheet + clearance."""
import time

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon, box

from maker import closures, core, thermo
from maker.generators import get_generator
from maker.job import build, run_job
from maker.shapes import shape_polygon
from maker.sheets import get_sheet


def _molds(kind="heart", width=80, depth=12, sheet="petg_05"):
    s = get_sheet(sheet)
    o, _ = thermo.clean_outline(shape_polygon(kind, width), s, depth)
    d = thermo.Dome(thermo.centred(o), depth)
    return s, d, thermo.press_molds(d, s)


def test_thermoform_ready_and_schema():
    g = get_generator("thermoform")
    assert g.status == "ready"
    keys = {p.key: p for p in g.params}
    assert keys["text"].show_if == {"source": "text"} and keys["logo"].type == "file"


@pytest.mark.parametrize("kind", ["heart", "star"])
@pytest.mark.parametrize("sheet", ["petg_05", "petg_10"])
def test_gap_equals_sheet_plus_clearance(kind, sheet):
    s, d, m = _molds(kind, sheet=sheet)
    assert m.gap_mm == pytest.approx(s.thickness_mm + s.clearance_mm)
    female = core.from_trimesh(m.female)
    male = thermo.male_in_use(m)
    # boolean: fully pressed molds never collide ...
    assert core.to_trimesh(female ^ core.from_trimesh(male)).volume == pytest.approx(0, abs=1e-3)
    # ... and the plug surface stays one gap away from the cavity (normal distance, not a scaled copy)
    base_z = m.female_top_z + m.gap_mm
    c, n = male.triangles_center, male.face_normals
    pts = c[(n[:, 2] < -0.3) & (c[:, 2] < base_z - 0.3)]  # whole plug, rim included
    assert len(pts) > 1000
    _, dist, _ = trimesh.proximity.closest_point(m.female, pts)
    assert np.median(dist) == pytest.approx(m.gap_mm, abs=0.02)
    assert np.mean(np.abs(dist - m.gap_mm) < 0.1) > 0.99  # 0.1 mm = print resolution
    # deep enough: the plug reaches into the cavity by (nearly) the dome depth
    assert base_z - pts[:, 2].min() == pytest.approx(d.depth, abs=0.5)


def test_moved_male_collides():
    """Sanity check of the boolean test above: pressing 1 mm further makes the molds intersect."""
    _, _, m = _molds()
    male = thermo.male_in_use(m)
    male.apply_translation([0, 0, -1.0])
    assert core.to_trimesh(core.from_trimesh(m.female) ^ core.from_trimesh(male)).volume > 100


def test_female_is_mirrored_ornament():
    """An asymmetric shape reads correctly after the formed sheet is flipped: the cavity is the mirror image."""
    s = get_sheet()
    o = Polygon([(0, 0), (60, 0), (60, 20), (20, 20), (20, 50), (0, 50)])  # L shape
    o, _ = thermo.clean_outline(o, s, 8)
    o = thermo.centred(o)
    d = thermo.Dome(o, 8)
    m = thermo.press_molds(d, s, economy=False)
    x0, y0, x1, y1 = o.bounds
    arm = (x1 - 8, y0 + 8)  # tip of the horizontal arm, ornament frame
    top = m.female_top_z
    ray = lambda x, y: m.female.ray.intersects_location([[x, y, top + 5]], [[0, 0, -1]])[0][:, 2].max()
    assert ray(arm[0], -arm[1]) < top - 4  # cavity under the mirrored arm
    assert ray(arm[0], arm[1]) == pytest.approx(top, abs=0.01)  # flat top where the arm is not


def test_clean_outline_rounds_corners_and_warns():
    s = get_sheet()
    sq, w = thermo.clean_outline(box(0, 0, 60, 60), s, 10)
    corner = np.hypot(*(np.array(sq.exterior.coords) - [60, 60]).T).min()
    assert corner > s.min_radius_mm * 0.4  # sharp corner gone
    _, w = thermo.clean_outline(box(0, 0, 60, 60).union(box(60, 27, 70, 33)).union(box(70, 0, 130, 60)), s, 10)
    assert any("dar bir boynu" in x for x in w)
    _, w = thermo.clean_outline(box(0, 0, 40, 40), s, 30)
    assert any("derin" in x for x in w)
    _, w = thermo.clean_outline(box(0, 0, 40, 40), s, 8)
    assert not w


def test_thermoform_job_files(tmp_path):
    res = run_job({"generator": "thermoform", "name": "kalp süs", "params": {}}, tmp_path)
    stls = sorted(p.name for p in (res.out_dir / "parts").glob("*.stl"))
    assert stls == ["kalp_sus_back.stl", "kalp_sus_female.stl", "kalp_sus_male.stl", "kalp_sus_rim.stl"]  # shell = preview only
    for f in stls:
        m = trimesh.load(res.out_dir / "parts" / f)
        assert m.is_watertight and max(m.extents[:2]) <= core.BED_MM
    d = res.data
    assert d["warnings"] == [] and d["meta"]["gap_mm"] == pytest.approx(0.7)
    assert any("Levha kesim ölçüsü" in n for n in d["notes"]) and (res.out_dir / "notes.txt").is_file()
    assert {p["material"] for p in d["parts"]} == {"PETG", "PLA"}


@pytest.mark.parametrize("params", [
    {"source": "text", "text": "Noel", "width_mm": 120},
    {"shape": "triangle", "width_mm": 200, "depth_mm": 25},
    {"shape": "star", "sheet": "petg_03", "hanger": False, "depth_mm": 8},
])
def test_thermoform_variants_valid_and_fit(params):
    res, _ = build({"generator": "thermoform", "params": params})
    for p in res.parts:
        assert core.is_part_valid(p.mesh), p.label
        if p.printable:
            assert max(p.mesh.extents[:2]) <= core.BED_MM, p.label
    assert not any("tablaya sığmıyor" in w for w in res.warnings)


def test_rim_and_back_trap_the_flange():
    s = get_sheet()
    _, d, _ = _molds()
    orn = closures.ornament_parts(d, s, 5.0, True)
    assert orn.trim.contains(d.outline) and orn.trim.area > d.outline.area
    # rim: ring + lip; the lip is exactly one sheet thick so the ring presses the flange onto the back plate
    assert orn.rim.extents[2] == pytest.approx(closures.RING_MM + s.thickness_mm, abs=0.02)
    assert orn.back.extents[2] == pytest.approx(closures.BACK_MM)
    assert len(orn.back.split()) == 1 and orn.back.euler_number == 0  # one piece with one (hanger) hole


def test_logo_source(tmp_path):
    svg = tmp_path / "bulut.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">'
                   '<circle cx="30" cy="35" r="22" fill="#3366cc"/><circle cx="62" cy="28" r="26" fill="#3366cc"/>'
                   '<circle cx="85" cy="40" r="14" fill="#cc3333"/></svg>')
    res, _ = build({"generator": "thermoform", "params": {"source": "logo", "logo": str(svg), "width_mm": 90}})
    assert res.meta["outline_mm"][0] == pytest.approx(90, abs=1.0)
    with pytest.raises(ValueError, match="dosyası seçin"):
        build({"generator": "thermoform", "params": {"source": "logo", "logo": ""}})


