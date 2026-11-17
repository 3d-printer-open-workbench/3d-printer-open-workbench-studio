"""T3: closures (screw cap thread tolerance, snap, magnet), multi-cavity molds, vacuum mode (vent hole distribution)."""
import numpy as np
import pytest
import trimesh
from shapely import affinity
from shapely.geometry import Point

from maker import closures, core, thermo, vacuum
from maker.job import build, run_job
from maker.shapes import shape_polygon
from maker.sheets import get_sheet


def _dome(kind="heart", width=80, depth=12, **kw):
    s = get_sheet()
    o, _ = thermo.clean_outline(shape_polygon(kind, width), s, depth)
    return s, thermo.Dome(thermo.centred(o), depth, **kw)


# ---------- screw cap
def test_thread_tolerance():
    collar, _, cap = closures.screw_parts((0.0, 0.0))
    assert (collar ^ cap).volume() == pytest.approx(0, abs=1e-3)  # screwed in: no collision
    cm, km = core.to_trimesh(collar), core.to_trimesh(cap)
    assert core.is_part_valid(cm) and core.is_part_valid(km)
    r_root = closures.THREAD_D / 2 - closures.THREAD_DEPTH
    c = km.triangles_center
    sel = (np.hypot(c[:, 0], c[:, 1]) > r_root + 0.2) & (c[:, 2] > closures.BACK_MM + 0.5) & (c[:, 2] < closures.BACK_MM + closures.COLLAR_H - 1)
    _, dist, _ = trimesh.proximity.closest_point(cm, c[sel])
    # radial clearance 0.35 on 44 deg flanks -> ~0.25 mm normal gap everywhere on the engaged flanks
    expect = closures.THREAD_CLEAR * np.cos(np.arctan(closures.THREAD_DEPTH / (closures.THREAD_PITCH / 2)))
    assert np.percentile(dist, 1) > expect - 0.03 and np.percentile(dist, 99) < expect + 0.03


def test_thread_engages():
    """The thread really holds: pulling the cap out by 1 mm (without turning) collides; turning with the pitch does not."""
    collar, _, cap = closures.screw_parts((0.0, 0.0))
    assert (collar ^ cap.translate((0, 0, -1.0))).volume() > 1.0
    turned = cap.rotate((0, 0, 360 * 1.0 / closures.THREAD_PITCH)).translate((0, 0, 1.0))
    assert (collar ^ turned).volume() < 0.05


def test_screw_closure_parts_and_room():
    s, d = _dome(depth=12)
    orn = closures.ornament_parts(d, s, 5, True, "screw")
    (name, label, cap), = orn.extra
    assert name == "cap" and core.is_part_valid(cap) and core.is_part_valid(orn.back)
    assert orn.back.euler_number == -2  # hanger hole + threaded fill hole
    s, low = _dome(depth=4)
    with pytest.raises(ValueError, match="Vidalı kapak için"):
        closures.ornament_parts(low, s, 5, True, "screw")


# ---------- snap / magnet
def test_snap_lip_overlaps_back_without_collision():
    s, d = _dome()
    orn = closures.ornament_parts(d, s, 5, True, "snap")
    rim, back = orn.assembled_rim, orn.back
    assert core.to_trimesh(core.from_trimesh(rim) ^ core.from_trimesh(back)).volume == pytest.approx(0, abs=1e-3)
    # the lip reaches under the back plate's edge by SNAP_OVERLAP (it clicks under it)
    v = back.vertices[np.argmax(back.vertices[:, 0])]
    under = lambda dx: rim.contains([[v[0] - dx, v[1], -closures.SNAP_LIP_H / 2]])[0]
    assert under(closures.SNAP_OVERLAP * 0.6) and not under(closures.SNAP_OVERLAP + 0.3)
    assert rim.contains([[v[0] + closures.SNAP_CLEAR + closures.SNAP_WALL / 2, v[1], closures.BACK_MM / 2]])[0]  # skirt beside the plate


def test_magnet_pockets():
    s, d = _dome(width=90)
    orn = closures.ornament_parts(d, s, 5, False, "magnet", (10.0, 2.0))
    assert core.is_part_valid(orn.back)
    spots = closures._magnet_spots(d.outline, 10.0)
    assert len(spots) == 2
    for x, y in spots:
        assert orn.back.contains([[x, y, closures.MAGNET_SKIN / 2]])[0]  # thin skin behind the magnet
        assert not orn.back.contains([[x + 4.9, y, closures.MAGNET_SKIN + 1.0]])[0]  # pocket fits a 10 mm magnet
        assert orn.back.contains([[x + 5.1 + 1.2, y, closures.MAGNET_SKIN + 1.0]])[0]  # boss wall around it


# ---------- multi-cavity
@pytest.mark.parametrize("n", [2, 4, 6])
def test_multi_cavity(n):
    s, d = _dome(width=60, depth=10)
    offs, k = thermo.cavity_layout(d.outline, n, 5)
    assert k == n
    trims = [affinity.translate(d.outline.buffer(5), dx, dy) for dx, dy in offs]
    assert all(not a.intersects(b) for i, a in enumerate(trims) for b in trims[i + 1:])  # cut lines never touch
    m = thermo.press_molds(d, s, offsets=offs)
    assert max(m.block_mm) <= core.BED_MM and len(m.vents) == n
    male = thermo.male_in_use(m)
    assert core.to_trimesh(core.from_trimesh(m.female) ^ core.from_trimesh(male)).volume == pytest.approx(0, abs=1e-3)
    assert thermo.cavity_draft(m, d)[1] == 0


def test_cavities_capped_with_warning():
    res, _ = build({"generator": "thermoform", "params": {"width_mm": 120, "cavities": 6}})
    assert res.meta["cavities"] < 6 and any("en çok" in w for w in res.warnings)
    assert all(max(p.mesh.extents[:2]) <= core.BED_MM for p in res.parts if p.printable)


# ---------- vacuum
def test_vacuum_vent_distribution():
    s, d = _dome("star")
    v = vacuum.vacuum_molds(d, s)
    assert core.is_part_valid(v.buck) and core.is_part_valid(v.box)
    ring = np.array(v.ring_holes)
    gaps = np.hypot(*(ring - np.roll(ring, 1, axis=0)).T)
    assert gaps.max() <= vacuum.RING_PITCH + 1e-6 and gaps.min() > 2 * vacuum.HOLE_D  # evenly around the foot
    dist = [d.outline.exterior.distance(Point(p)) for p in v.ring_holes]
    assert all(abs(x - vacuum.RING_OFFSET) < 0.2 for x in dist) and all(not d.outline.contains(Point(p)) for p in v.ring_holes)
    assert v.valley_holes == []  # a star with a flat-ish dome traps no air
    # holes are really open: a vertical ray through each ring hole passes the plate
    hits = v.buck.ray.intersects_any(np.c_[ring, np.full(len(ring), 50.0)], np.tile([0, 0, -1.0], (len(ring), 1)))
    assert not hits.any()


def test_vacuum_valleys_get_holes():
    g, _ = core.text_geometry("O", "Righteous", width_mm=30)
    x0, y0, x1, y1 = g.bounds
    g = affinity.translate(g, -(x0 + x1) / 2, -(y0 + y1) / 2)
    s, d = _dome("circle", width=90, profile="flat", relief=thermo.Relief(g, 2.0, raised=False))
    pts = vacuum.valley_points(d, s.thickness_mm)
    assert pts and all(g.buffer(1.0).contains(Point(p)) for p in pts)  # vents sit in the sunk letter


def test_vacuum_job_and_buck_offset(tmp_path):
    res = run_job({"generator": "thermoform", "name": "vak", "params": {"method": "vacuum", "cavities": 2}}, tmp_path)
    names = sorted(p["name"] for p in res.data["parts"])
    assert names == ["back", "box", "buck", "rim"]
    assert res.data["meta"]["ring_holes"] > 20 and any("hortum" in n for n in res.data["notes"])
    s, d = _dome()
    # the buck is the dome offset inwards by the sheet thickness (inner face of the sheet touches it)
    xy = np.array([[0.0, 0.0]])
    assert d.offset_height(xy, s.thickness_mm)[0] == pytest.approx(d.height(xy)[0], abs=0.05)  # flat-ish top: same height
    assert max(p["size_mm"][0] for p in res.data["parts"]) <= core.BED_MM


@pytest.mark.parametrize("closure", list(closures.CLOSURES_TR))
def test_generator_closures(closure):
    res, _ = build({"generator": "thermoform", "params": {"closure": closure, "cavities": 2}})
    for p in res.parts:
        assert core.is_part_valid(p.mesh), p.label
    printed = {p.name: p for p in res.parts if p.printable}
    assert ("cap" in printed) == (closure == "screw")
    assert printed["back"].meta["count"] == 2
