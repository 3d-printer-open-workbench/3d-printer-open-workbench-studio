import math

import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import Polygon

from maker import baking, core, flat
from maker.generators import GENERATORS
from maker.generators.roller import RES
from maker.job import build


def _section_area(mesh, z):
    s = mesh.section([0, 0, 1], [0, 0, z])
    p, _ = s.to_2D()
    return sum(q.area for q in p.polygons_full)


def test_t6_generators_ready():
    for k in ("cookie_cutter", "letter_stamp", "grid_cutter", "roller", "cake_topper"):
        assert GENERATORS[k].status == "ready"


def test_cutter_edge_and_stamp_fit():
    res, _ = build({"generator": "cookie_cutter", "params": {"shape": "circle", "width_mm": 60, "height_mm": 15}})
    cutter, stamp, handle = res.parts
    perim = math.pi * 60
    assert _section_area(cutter.mesh, 14.0) == pytest.approx(perim * baking.EDGE_MM, rel=0.08)  # thin cutting edge
    assert _section_area(cutter.mesh, 6.0) == pytest.approx(perim * 1.2, rel=0.08)  # 1.2 mm wall
    assert stamp.mesh.extents[0] == pytest.approx(60 - 2 * baking.STAMP_CLEAR, abs=0.05)  # slides inside the cutter
    assert handle.mesh.extents[2] > cutter.mesh.extents[2]  # ejector reaches through
    # peg vs socket: press fit with PEG_CLEAR per side
    peg = handle.mesh.section([0, 0, 1], [0, 0, handle.mesh.bounds[1][2] - 0.5]).to_2D()[0].polygons_full[0]
    sock = stamp.mesh.section([0, 0, 1], [0, 0, 1.0]).to_2D()[0].polygons_full[0].interiors[0]
    assert (peg.bounds[2] - peg.bounds[0]) == pytest.approx(baking.SOCKET_D - 2 * baking.PEG_CLEAR, abs=0.05)
    assert sock.bounds[2] - sock.bounds[0] == pytest.approx(baking.SOCKET_D + 2 * baking.PEG_CLEAR, abs=0.05)
    assert any("Gıda" in n for n in res.notes)


def test_name_cookie_stamp_is_mirrored_text():
    v = {"source": "text", "text": "Ali", "font": "Righteous", "stamp": "text", "stamp_text": ""}
    inside, _, own = baking.outline_from(v, 70)
    rel = baking.relief_from(v, inside.buffer(-baking.STAMP_CLEAR), [], own=own)
    assert rel.symmetric_difference(own).area < 0.1 * own.area  # the cutter's own letters (+ thickening only)
    assert inside.contains(rel)
    # print frame: cutter, plate and relief are all mirrored together, so the letters still sit in their bubble
    res, _ = build({"generator": "cookie_cutter", "params": v})
    cutter, stamp = res.parts[0].mesh, res.parts[1].mesh
    cut = cutter.section([0, 0, 1], [0, 0, 6.0]).to_2D(to_2D=np.eye(4))[0].polygons_full
    hole = max((q for q in cut), key=lambda q: q.area).interiors[0]
    assert affinity.scale(Polygon(hole), -1, 1, origin=(0, 0)).symmetric_difference(inside).area < 0.02 * inside.area


def test_letter_stamp_mirrored_relief():
    res, _ = build({"generator": "letter_stamp", "params": {"text": "Ece", "font": "Righteous", "letter_mm": 12}})
    stamp = res.parts[0].mesh
    top = stamp.section([0, 0, 1], [0, 0, stamp.bounds[1][2] - 0.3]).to_2D()[0]
    g = flat.text("Ece", "Righteous", [], height_mm=12)
    assert sum(q.area for q in top.polygons_full) == pytest.approx(g.area, rel=0.12)
    assert len(res.parts) == 2 and res.parts[1].name == "handle"


def test_grid_cutter_shared_walls():
    res, _ = build({"generator": "grid_cutter", "params": {"cell": "square", "size_mm": 30, "rows": 2, "cols": 3}})
    m = res.parts[0].mesh
    assert res.meta["cells"] == 6
    # 2 x 3 squares with shared walls: wall length = outer frame + 1 inner horizontal + 2 inner vertical
    frame = 2 * (3 * 31.2 + 2 * 31.2)
    inner = (3 * 31.2) + 2 * (2 * 31.2)
    assert _section_area(m, 6.0) == pytest.approx((frame + inner) * 1.2, rel=0.1)
    assert m.extents[2] == pytest.approx(15)


def test_roller_closed_seamless_sleeve():
    res, _ = build({"generator": "roller", "params": {"pattern": "dots", "bore_mm": 25, "wall_mm": 3, "relief_mm": 1.5, "length_mm": 80}})
    m = res.parts[0].mesh
    assert m.is_watertight and m.volume > 0
    r = np.hypot(m.vertices[:, 0], m.vertices[:, 1])
    assert r.min() == pytest.approx(12.7, abs=0.01)  # bore 25 + 0.4 clearance
    assert r.max() == pytest.approx(15.7 + 1.5, abs=0.05)
    assert res.meta["repeats"] >= 2 and m.extents[2] == pytest.approx(80)
    res, _ = build({"generator": "roller", "params": {"pattern": "text", "text": "Ece", "size_mm": 8, "length_mm": 60}})
    assert res.parts[0].mesh.is_watertight and any("aynalı" in n for n in res.notes)


def test_cake_topper_styles():
    res, _ = build({"generator": "cake_topper", "params": {}})
    base, txt = res.parts
    assert base.mesh.extents[1] > 50 + 20  # stakes below the lettering
    assert txt.mesh.bounds[0][2] == pytest.approx(base.mesh.bounds[1][2])
    res, _ = build({"generator": "cake_topper", "params": {"style": "script", "text": "Mutlu Yıllar", "accent": "stars"}})
    assert len(res.parts) == 1 and len(res.parts[0].mesh.split()) == 1  # one connected piece, stars and dots tied in
    assert not res.warnings


def test_food_notes_everywhere():
    for k in ("cookie_cutter", "letter_stamp", "grid_cutter", "roller"):
        res, _ = build({"generator": k, "params": {"length_mm": 60} if k == "roller" else {}})
        assert any("Gıda" in n for n in res.notes), k
