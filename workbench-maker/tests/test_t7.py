import zipfile

import numpy as np
import pytest
from PIL import Image, ImageDraw
from shapely import affinity

from maker import plates
from maker.generators import GENERATORS
from maker.generators.ornament import snowflake
from maker.generators.photo_stand import BACK_T, POCKET_T, SIZES
from maker.job import build


def test_t7_generators_ready():
    for k in ("container", "photo_stand", "ornament", "string_art", "rattan_letters", "coloring_plaque"):
        assert GENERATORS[k].status == "ready"
    assert all(g.status == "ready" for g in GENERATORS.values())


def test_container_lid_fit_dividers_and_side_text():
    res, _ = build({"generator": "container", "params": {"shape": "square", "width_mm": 80, "height_mm": 40, "lid": True,
                                                         "rows": 2, "cols": 2, "clear_mm": 0.25, "wall_mm": 1.2}})
    body, lid = res.parts
    assert body.mesh.is_watertight and lid.mesh.is_watertight
    lip = lid.mesh.section([0, 0, 1], [0, 0, 4.0]).to_2D(to_2D=np.eye(4))[0].polygons_full
    lip_w = max(q.bounds[2] - q.bounds[0] for q in lip)
    assert lip_w == pytest.approx(80 - 2 * 1.2 - 2 * 0.25, abs=0.05)  # slides into the body with 0.25 mm per side
    sec = body.mesh.section([0, 0, 1], [0, 0, 20.0]).to_2D(to_2D=np.eye(4))[0].polygons_full
    assert sum(len(q.interiors) for q in sec) == 4  # 2 x 2 compartments
    res, _ = build({"generator": "container", "params": {"side_text": "Ece", "side_relief": 1.2, "width_mm": 70}})
    m = res.parts[0].mesh
    r = np.hypot(m.vertices[:, 0], m.vertices[:, 1])
    assert m.is_watertight and r.max() == pytest.approx(35 + 1.2, abs=0.05)
    assert m.bounds[0][2] == pytest.approx(0) and m.contains([[0, 0, 0.8]])[0]  # closed bottom


def test_photo_frame_pocket_open_at_top():
    res, _ = build({"generator": "photo_stand", "params": {"size": "10x15", "caption": ""}})
    frame = next(p for p in res.parts if p.name != "stand").mesh
    W, H = frame.extents[:2]
    cx, cy = (frame.bounds[0][:2] + frame.bounds[1][:2]) / 2
    zp = BACK_T + POCKET_T / 2
    assert not frame.contains([[cx, cy, zp]])[0]  # photo pocket
    assert not frame.contains([[cx, frame.bounds[1][1] - 0.3, zp]])[0]  # open at the top edge: the photo slides in
    assert frame.contains([[cx, cy, BACK_T / 2]])[0]  # closed back by default
    pw, ph = SIZES["10x15"]
    assert W == pytest.approx(pw + 20) and H == pytest.approx(ph + 20)
    assert any(p.name == "stand" and p.meta["batch"] == "stand" for p in res.parts)
    res, _ = build({"generator": "photo_stand", "params": {"back": "open", "caption": ""}})
    f2 = next(p for p in res.parts if p.name != "stand").mesh
    assert f2.volume < frame.volume * 0.7


def test_snowflake_symmetry_and_seeds():
    g = snowflake(80, 7, 3.0)
    assert g.symmetric_difference(affinity.rotate(g, 60, origin=(0, 0))).area < 0.02 * g.area
    assert g.symmetric_difference(affinity.scale(g, -1, 1, origin=(0, 0))).area < 0.02 * g.area
    assert snowflake(80, 8, 3.0).symmetric_difference(g).area > 0.05 * g.area  # another seed, another flake
    res, _ = build({"generator": "ornament", "params": {"seed": 3, "text": "2026"}})
    assert len(res.parts) == 2 and res.parts[0].mesh.is_watertight


def test_lithophane_thickness_and_orca_settings(tmp_path):
    im = Image.new("L", (200, 200), 255)
    ImageDraw.Draw(im).rectangle((0, 0, 99, 199), fill=0)  # left half black
    f = tmp_path / "p.png"
    im.save(f)
    res, _ = build({"generator": "ornament", "params": {"kind": "photo", "photo": str(f), "shape": "rect", "size_mm": 60,
                                                        "t_min": 0.8, "t_max": 3.0}})
    m = res.parts[0].mesh
    assert m.is_watertight
    ray = lambda x: m.ray.intersects_location([[x, 0, 10]], [[0, 0, -1]])[0][:, 2].max()
    assert ray(-12) == pytest.approx(3.0, abs=0.05) and ray(12) == pytest.approx(0.8, abs=0.05)  # dark = thick
    plates.write_3mf(res.parts, tmp_path / "l.3mf")
    cfg = zipfile.ZipFile(tmp_path / "l.3mf").read("Metadata/model_settings.config").decode()
    assert 'key="sparse_infill_density" value="100%"' in cfg and 'key="layer_height" value="0.12"' in cfg


def test_string_art_pegs():
    res, _ = build({"generator": "string_art", "params": {"shape": "circle", "width_mm": 100, "pitch_mm": 10}})
    assert res.meta["pegs"] == round(np.pi * 100 / 10)
    board, pegs = res.parts
    assert pegs.mesh.bounds[0][2] == pytest.approx(board.mesh.bounds[1][2])
    assert len(pegs.mesh.split()) == res.meta["pegs"]
    res, _ = build({"generator": "string_art", "params": {"pegs": "holes"}})
    assert len(res.parts) == 1


def test_rattan_one_object_per_letter():
    res, _ = build({"generator": "rattan_letters", "params": {"text": "Aİ", "height_mm": 80}})
    groups = {p.meta["group"] for p in res.parts}
    assert groups == {"letter_1", "letter_2"}  # the dot of İ stays with its letter
    m = res.parts[0].mesh
    full = m.extents[0] * m.extents[1] * m.extents[2]
    assert m.volume < 0.35 * full  # open cane lattice


def test_coloring_plaque_raised_lines():
    res, _ = build({"generator": "coloring_plaque", "params": {}})
    (p,) = res.parts
    assert p.mesh.is_watertight and p.mesh.extents[2] == pytest.approx(2.4 + 1.6)
    top = p.mesh.section([0, 0, 1], [0, 0, 3.2]).to_2D(to_2D=np.eye(4))[0]
    assert sum(q.area for q in top.polygons_full) < 0.25 * p.mesh.extents[0] * p.mesh.extents[1]  # thin lines only
