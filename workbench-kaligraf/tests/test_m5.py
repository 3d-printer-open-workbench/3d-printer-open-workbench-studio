import json
import math
import zipfile

import numpy as np
import pytest
import trimesh
import yaml

from kaligraf.cli import main as cli_main
from kaligraf.estimate import ASSUMPTIONS, estimate, part_grams, plate_time
from kaligraf.export3mf import build_objects, inspect_3mf, plate_origin, write_3mf
from kaligraf.geometry import is_part_valid, make_flat, make_letters
from kaligraf.job import Job, resolve_color, run_job
from kaligraf.split import pack_plates, plate_meshes, split_model


def _pipeline(model):
    res = split_model(model)
    plates = pack_plates(res.pieces)
    return res, plates


# ------------------------------- 3MF ------------------------------------- #
def test_3mf_structure_and_reopen(bebas, tmp_path):
    m = make_letters("ŞÜKRÜ", bebas, 200, depth=30, face_color="#FFFFFF", colors=["#222222"])
    res, plates = _pipeline(m)
    objs = build_objects(res, plates, {p.group: "10% gyroid" for p in res.pieces})
    path = write_3mf(tmp_path / "model.3mf", objs, len(plates), m.colors)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    for need in ("[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model",
                 "Metadata/model_settings.config", "Metadata/project_settings.config"):
        assert need in names
    info = inspect_3mf(path)
    parts = [p for o in info["objects"] for p in o["parts"]]
    assert len(parts) == len(res.pieces) == 10  # part count matches
    assert len(info["objects"]) == 5  # one object per letter (body + face stacked)
    exts = {p["extruder"] for p in parts}
    assert exts == {1, 2} and len(exts) <= 4
    by_name = {pc.name: pc for pc in res.pieces}
    for p in parts:
        assert p["extruder"] == by_name[p["name"]].part.extruder
        assert is_part_valid(p["mesh"])
        assert p["mesh"].volume == pytest.approx(by_name[p["name"]].mesh.volume, rel=1e-4)
    for o in info["objects"]:
        assert o["components"] == [p["id"] for p in o["parts"]]
        assert o["meta"]["sparse_infill_pattern"] == "gyroid" and o["meta"]["sparse_infill_density"] == "10%"
    assert info["project"]["filament_colour"] == ["#222222", "#FFFFFF"]
    assert len(info["project"]["filament_settings_id"]) == 2
    assert sorted(i for pl in info["plates"] for i in pl["objects"]) == sorted(o["id"] for o in info["objects"])
    assert len(info["plates"]) == len(plates)
    # third-party loader agrees
    scene = trimesh.load(path)
    assert len(scene.geometry) == 10 and all(g.is_watertight for g in scene.geometry.values())


def test_3mf_objects_inside_their_plate(bebas, tmp_path):
    m = make_letters("ŞÜKRÜ", bebas, 200, depth=30)
    res, plates = _pipeline(m)
    path = write_3mf(tmp_path / "m.3mf", build_objects(res, plates), len(plates), m.colors)
    info = inspect_3mf(path)
    plate_of = {oid: pl["id"] - 1 for pl in info["plates"] for oid in pl["objects"]}
    for o in info["objects"]:
        t = [float(v) for v in o["transform"].split()][9:12]
        verts = np.vstack([p["mesh"].vertices for p in o["parts"]]) + t
        ox, oy = plate_origin(plate_of[o["id"]], len(plates))
        assert verts[:, 0].min() >= ox - 1e-3 and verts[:, 0].max() <= ox + 256 + 1e-3
        assert verts[:, 1].min() >= oy - 1e-3 and verts[:, 1].max() <= oy + 256 + 1e-3
        assert verts[:, 2].min() == pytest.approx(0, abs=1e-4)


def test_plate_origin_grid():
    assert plate_origin(0, 1) == (0.0, 0.0)
    assert plate_origin(1, 2) == pytest.approx((256 * 1.2, 0.0))
    assert plate_origin(2, 3) == pytest.approx((0.0, -256 * 1.2))  # 2 columns: third plate wraps down


def test_3mf_four_colors_max(bebas, tmp_path):
    m = make_letters("ABCD", bebas, 100, colors=["#111111", "#222222", "#333333", "#444444"])
    res, plates = _pipeline(m)
    info = inspect_3mf(write_3mf(tmp_path / "m.3mf", build_objects(res, plates), len(plates), m.colors))
    assert max(p["extruder"] for o in info["objects"] for p in o["parts"]) == 4
    assert len(info["project"]["filament_colour"]) == 4


def test_3mf_split_pieces_named(bebas, tmp_path):
    m = make_letters("A", bebas, 400, depth=30)
    res, plates = _pipeline(m)
    info = inspect_3mf(write_3mf(tmp_path / "m.3mf", build_objects(res, plates), len(plates), m.colors))
    assert sorted(o["name"] for o in info["objects"]) == ["letter_01_A_p1of2", "letter_01_A_p2of2"]


# ------------------------------ estimate --------------------------------- #
def test_grams_solid_cube_known_value():
    cube = trimesh.creation.box((20, 20, 20))
    shell = 2 * 400 * 1.0 + 4 * 400 * 1.26
    expected = (shell + (8000 - shell) * 0.10) / 1000 * 1.24
    assert part_grams(cube, 0.10) == pytest.approx(expected, rel=1e-6)
    assert 3.5 < part_grams(cube, 0.10) < 5.0
    assert part_grams(cube, 1.0) == pytest.approx(8 * 1.24, rel=1e-6)


def test_grams_thin_part_is_solid():
    plate = trimesh.creation.box((100, 50, 1.0))
    assert part_grams(plate, 0.1) == pytest.approx(plate.volume / 1000 * 1.24, rel=1e-6)


def test_estimate_letters_sane(bebas):
    m = make_letters("ŞÜKRÜ", bebas, 200, depth=30, face_color="#FFFFFF")
    res, plates = _pipeline(m)
    e = estimate(res, plates, 0.10)
    solid_g = sum(p.mesh.volume for p in m.parts) / 1000 * 1.24
    assert 0.15 * solid_g < e.grams_total < 0.6 * solid_g
    assert set(e.grams_by_color) == {"#222222", "#FFFFFF"}
    assert e.grams_by_color["#FFFFFF"] < e.grams_by_color["#222222"] * 0.2
    assert e.grams_total == pytest.approx(sum(e.grams_by_color.values()), abs=0.2)
    assert len(e.time_by_plate_s) == len(plates) and 3600 < e.time_s < 200 * 3600
    assert e.assumptions == ASSUMPTIONS
    # more infill -> more filament
    assert estimate(res, plates, 0.25).grams_total > e.grams_total


def test_estimate_flat_two_tone_changes(montserrat):
    m = make_flat("Hi", montserrat, 200, thickness=5, style="two_tone")
    res, plates = _pipeline(m)
    e = estimate(res, plates, 0.15)
    assert e.colour_changes == 1  # body layers, then one swap for the 0.6 mm face
    assert 0 < e.grams_total < sum(p.mesh.volume for p in m.parts) / 1000 * 1.24


def test_time_grows_with_colour_changes(bebas):
    one = make_letters("AB", bebas, 100, depth=15, colors=["#111111"])
    two = make_letters("AB", bebas, 100, depth=15, colors=["#111111"], face_color="#FFFFFF")
    r1, p1 = _pipeline(one)
    r2, p2 = _pipeline(two)
    assert estimate(r2, p2, 0.1).time_s > estimate(r1, p1, 0.1).time_s


# -------------------------------- jobs ----------------------------------- #
def test_resolve_color():
    assert resolve_color("siyah") == "#222222"
    assert resolve_color("#abcdef") == "#ABCDEF"
    with pytest.raises(ValueError):
        resolve_color("turkuaz-ish")


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "cube"},
        {"mode": "flat", "text": "A"},  # no width
        {"mode": "flat", "text": "A", "width_cm": 10, "thickness_mm": 0.5},
        {"mode": "flat", "text": "A", "width_cm": 10, "thickness_mm": 260},
        {"mode": "flat", "text": "A", "logo": "x.png", "width_cm": 10, "logo_layout": "up"},
        {"mode": "letters", "text": "A", "letter_height_cm": 1.5},
        {"mode": "letters", "text": "A", "letter_height_cm": 10, "depth_mm": 1},
        {"mode": "letters", "text": "A", "letter_height_cm": 10, "depth_mm": 260},
        {"mode": "letters", "text": "A", "letter_height_cm": 10, "stroke_offset_mm": 15},
        {"mode": "letters", "text": "A", "letter_height_cm": 10, "mounting": ["glue"]},
        {"mode": "letters", "text": "A", "letter_height_cm": 10, "oversize_policy": "shrink"},
        {"mode": "letters", "text": "A", "letter_height_cm": 10, "bogus": 1},
    ],
)
def test_job_validation(bad):
    with pytest.raises(ValueError):
        Job.from_dict(bad)


def test_run_job_letters_outputs(tmp_path):
    job = Job.from_dict(
        dict(mode="letters", text="ŞÜK", font="Bebas Neue", letter_height_cm=10, depth_mm=15,
             letter_colors=["siyah"], face_color="beyaz")
    )
    res = run_job(job, tmp_path)
    out = tmp_path / "suk_letters_10cm"
    assert res.out_dir == out
    for f in ("model.3mf", "job.json", "warnings.txt"):
        assert (out / f).exists()
    stls = sorted((out / "parts").glob("*.stl"))
    assert len(stls) == 6  # 3 letters x (body, face)
    for s in stls:
        assert is_part_valid(trimesh.load(s))
        assert trimesh.load(s).bounds[0] == pytest.approx([0, 0, 0], abs=1e-6)
    d = json.loads((out / "job.json").read_text())
    assert d["mode"] == "letters" and d["plates"] >= 1
    assert d["overall_mm"]["depth_mm"] == 15 and d["overall_mm"]["cap_height_mm"] == 100
    assert len(d["parts"]) == len(d["pieces"]) == 6
    assert d["filament_grams"]["total"] == pytest.approx(sum(d["filament_grams"]["by_color"].values()), abs=0.2)
    assert d["estimated_print_time"]["seconds"] > 0 and "assumptions" in d["estimated_print_time"]
    assert d["recommended_infill"] == "10% gyroid"
    assert d["oversize"]["policy"] == "split" and d["oversize"]["max_no_split_size_mm"] > 100
    assert [c["extruder"] for c in d["colors"]] == [1, 2]
    info = inspect_3mf(out / "model.3mf")
    assert sum(len(o["parts"]) for o in info["objects"]) == 6
    assert (out / "warnings.txt").read_text() == "\n".join(d["warnings"]) + ("\n" if d["warnings"] else "")


def test_run_job_flat_split_and_pins(tmp_path):
    job = Job.from_dict(dict(mode="flat", text="HELLO", font="Bebas Neue", width_cm=40, thickness_mm=10,
                             tracking=-0.1, job_id="split_demo"))
    res = run_job(job, tmp_path)
    d = res.data
    assert d["oversize"]["split"] and d["oversize"]["max_no_split_size_mm"] == pytest.approx(250, abs=1)
    assert any(p["name"].endswith("_p1of2") for p in d["pieces"])
    assert d["splitting"]["pin_pieces"]["count"] == len(d["splitting"]["pins"]) > 0
    assert (tmp_path / "split_demo" / "parts" / "body_p1of2.stl").exists()


def test_run_job_limit_policy(tmp_path):
    job = Job.from_dict(dict(mode="letters", text="AB", font="Bebas Neue", letter_height_cm=40,
                             oversize_policy="limit"))
    d = run_job(job, tmp_path).data
    assert d["oversize"]["split"] is False
    assert d["oversize"]["size_applied_mm"] == pytest.approx(250, abs=1)
    assert d["oversize"]["size_requested_mm"] == 400
    assert any("requested letter height 40.0 cm" in w for w in d["warnings"])
    assert d["plates"] >= 1 and all(p["size_mm"][0] <= 250 and p["size_mm"][1] <= 250 for p in d["pieces"])


def test_run_job_logo(tmp_path):
    svg = tmp_path / "l.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">'
                   '<rect width="60" height="60" fill="#f00"/><circle cx="75" cy="30" r="20" fill="#00f"/></svg>')
    y = tmp_path / "job.yaml"
    y.write_text(yaml.safe_dump(dict(mode="flat", logo="l.svg", width_cm=15, thickness_mm=5)))
    res = run_job(Job.from_yaml(y), tmp_path / "out")
    assert len(res.data["colors"]) == 2 and len(res.data["parts"]) == 2


def test_cli_make_and_errors(tmp_path, capsys):
    y = tmp_path / "j.yaml"
    y.write_text(yaml.safe_dump(dict(mode="letters", text="AB", font="Bebas Neue", letter_height_cm=8, depth_mm=15)))
    assert cli_main(["make", str(y), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "Hazır" in out and "Filament" in out and "baskı süresi" in out
    y.write_text(yaml.safe_dump(dict(mode="letters", text="AB", letter_height_cm=1)))
    assert cli_main(["make", str(y), "--out", str(tmp_path / "o")]) == 2
    assert "Hata" in capsys.readouterr().err
    assert cli_main(["make", str(tmp_path / "missing.yaml")]) == 2


def test_example_yamls_load():
    from pathlib import Path

    for p in Path(__file__).resolve().parents[1].glob("examples/*.yaml"):
        Job.from_yaml(p)
