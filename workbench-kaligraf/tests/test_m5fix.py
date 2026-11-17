import numpy as np
import pytest
import yaml

from kaligraf.estimate import PrinterProfile, estimate, load_printer
from kaligraf.geometry import is_part_valid, make_flat, make_logo_flat
from kaligraf.job import Job, run_job
from kaligraf.split import pack_plates, split_model

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">'
       '<rect width="60" height="60" fill="#ff0000"/><circle cx="75" cy="30" r="20" fill="#0000ff"/></svg>')
SVG4 = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 20">'
        '<rect x="0" width="20" height="20" fill="#ff0000"/><rect x="20" width="20" height="20" fill="#00ff00"/>'
        '<rect x="40" width="20" height="20" fill="#0000ff"/><rect x="60" width="20" height="20" fill="#ffff00"/></svg>')


@pytest.fixture()
def svg(tmp_path):
    p = tmp_path / "l.svg"
    p.write_text(SVG)
    return p


def _bounds(parts):
    return {p.name: p.mesh_wall.bounds for p in parts}


def test_logo_above_text(svg, bebas):
    m = make_logo_flat(svg, 200, thickness=5, text="HELLO", font=bebas, layout="logo_above", gap_mm=12, logo_share=0.5)
    b = _bounds(m.parts)
    text = b["text"]
    logos = [v for k, v in b.items() if k != "text"]
    assert len(logos) == 2 and len(m.parts) == 3
    allv = np.vstack([p.mesh_wall.vertices for p in m.parts])
    assert allv[:, 0].max() - allv[:, 0].min() == pytest.approx(200, abs=0.5)  # combined width
    assert text[1][0] - text[0][0] == pytest.approx(200, abs=0.5)
    assert min(v[0][1] for v in logos) == pytest.approx(text[1][1] + 12, abs=0.2)  # gap above the text
    lw = max(v[1][0] for v in logos) - min(v[0][0] for v in logos)
    assert lw == pytest.approx(100, abs=0.5)  # logo_share 0.5
    assert min(v[0][0] for v in logos) == pytest.approx(50, abs=0.5)  # centred
    assert all(is_part_valid(p.mesh_wall) for p in m.parts)
    assert m.meta["style"] == "logo_text"


def test_logo_left_text(svg, bebas):
    m = make_logo_flat(svg, 300, thickness=5, text="HELLO", font=bebas, layout="logo_left", gap_mm=10)
    b = _bounds(m.parts)
    text = b["text"]
    logos = [v for k, v in b.items() if k != "text"]
    allv = np.vstack([p.mesh_wall.vertices for p in m.parts])
    assert allv[:, 0].max() - allv[:, 0].min() == pytest.approx(300, abs=0.5)
    assert text[0][0] - max(v[1][0] for v in logos) == pytest.approx(10, abs=0.2)
    th = text[1][1] - text[0][1]
    lh = max(v[1][1] for v in logos) - min(v[0][1] for v in logos)
    assert lh == pytest.approx(th, abs=0.3)  # logo as high as the text


def test_colors_total_max_four(tmp_path, bebas, svg):
    svg_two = svg
    p = tmp_path / "four.svg"
    p.write_text(SVG4)
    m = make_logo_flat(p, 200, text="AB", font=bebas, text_color="#000000", n_colors=4)
    assert any("reduced to 3 colors" in w for w in m.warnings)
    assert max(q.extruder for q in m.parts) <= 4
    # text colour equal to a logo colour shares the extruder
    m2 = make_logo_flat(svg_two, 200, text="AB", font=bebas, text_color="#FF0000")
    assert len({q.extruder for q in m2.parts}) == 2 and len(m2.parts) == 3


def test_logo_text_validation_and_policy(svg, bebas):
    with pytest.raises(ValueError):
        make_logo_flat(svg, 200, text="A")  # no font
    with pytest.raises(ValueError):
        make_logo_flat(svg, 200, text="A", font=bebas, layout="diagonal")
    m = make_logo_flat(svg, 500, text="HELLO", font=bebas, oversize_policy="limit")
    assert all(max(p.mesh.extents[:2]) <= 250 for p in m.parts)
    assert "requested width 50.0 cm" in m.warnings[0]


def test_job_logo_plus_text(svg, tmp_path):
    y = tmp_path / "j.yaml"
    y.write_text(yaml.safe_dump(dict(mode="flat", text="HELLO", font="Bebas Neue", logo="l.svg", width_cm=20,
                                     logo_layout="logo_left", logo_gap_mm=8, colors=["#111111"])))
    job = Job.from_yaml(y)
    res = run_job(job, tmp_path / "o")
    assert {p["name"] for p in res.data["parts"]} >= {"text"}
    assert res.data["overall_mm"]["width_mm"] == pytest.approx(200, abs=0.5)
    with pytest.raises(ValueError):
        Job.from_dict(dict(mode="flat", text="A", logo="x.svg", width_cm=10, logo_layout="up"))


# ----------------------------- keyhole boss ------------------------------ #
def test_keyhole_boss_backplate(montserrat, tmp_path):
    from kaligraf.geometry import export_stl
    import trimesh

    m = make_flat("Hi", montserrat, 200, thickness=5, style="backplate", mounting=["keyhole"], keyhole_boss=True)
    plate, glyphs, boss = m.parts
    assert boss.role == "boss" and boss.mesh_wall.bounds[:, 2] == pytest.approx([-6, 0], abs=1e-6)
    assert boss.mesh_wall.extents[:2] == pytest.approx([30, 30], abs=0.1)
    kh = m.meta["mounting"]["keyholes"][0]
    assert kh["part"] == "keyhole_boss" and kh["boss"][2] == 30
    # boss sits inside the plate footprint, plate/glyphs untouched
    from kaligraf.geometry import mesh_footprint
    assert mesh_footprint(plate.mesh_wall).buffer(1e-6).contains(mesh_footprint(boss.mesh_wall))
    assert is_part_valid(boss.mesh) and boss.mesh.bounds[0][2] == pytest.approx(0, abs=1e-6)  # prints flat
    base = make_flat("Hi", montserrat, 200, thickness=5, style="backplate")
    assert plate.mesh_wall.volume == pytest.approx(base.parts[0].mesh_wall.volume, rel=1e-9)
    from math import pi
    assert boss.mesh.volume < pi * 15**2 * 6 - 400  # keyhole removed material
    for path in export_stl(m, tmp_path):
        assert is_part_valid(trimesh.load(path))


def test_keyhole_boss_not_requested_and_too_small(montserrat):
    m = make_flat("Hi", montserrat, 200, thickness=5, style="backplate", mounting=["keyhole"])
    assert any("keyhole_boss" in w for w in m.warnings) and len(m.parts) == 2
    small = make_flat("Hi", montserrat, 30, thickness=5, style="backplate", mounting=["keyhole"], keyhole_boss=True)
    assert any("too small" in w for w in small.warnings)


def test_job_keyhole_boss_validation():
    with pytest.raises(ValueError):
        Job.from_dict(dict(mode="flat", text="A", width_cm=10, keyhole_boss=True))
    Job.from_dict(dict(mode="flat", text="A", width_cm=10, color_style="backplate", keyhole_boss=True))


# ------------------------------- printer.yaml ---------------------------- #
def test_printer_profile_changes_time(bebas, tmp_path):
    from kaligraf.geometry import make_letters

    m = make_letters("AB", bebas, 100, depth=15, face_color="#FFFFFF")
    res = split_model(m)
    plates = pack_plates(res.pieces)
    base = estimate(res, plates, 0.1, PrinterProfile())
    slow = estimate(res, plates, 0.1, PrinterProfile(flow_mm3_s=4.5, colour_change_s=80))
    assert slow.time_s > base.time_s * 1.3
    assert slow.assumptions["effective_flow_mm3_s"] == 4.5 and slow.assumptions["colour_change_s"] == 80
    assert slow.grams_total == base.grams_total


def test_load_printer(tmp_path):
    d = load_printer()
    assert d.flow_mm3_s == 9 and d.colour_change_s == 40  # repo printer.yaml defaults
    p = tmp_path / "p.yaml"
    p.write_text("flow_mm3_s: 12\ncolour_change_s: 25\n")
    prof = load_printer(p)
    assert (prof.flow_mm3_s, prof.colour_change_s, prof.layer_overhead_s) == (12, 25, 2.5)
    p.write_text("speed: 3\n")
    with pytest.raises(ValueError):
        load_printer(p)
    p.write_text("flow_mm3_s: 0\n")
    with pytest.raises(ValueError):
        load_printer(p)
    with pytest.raises(FileNotFoundError):
        load_printer(tmp_path / "nope.yaml")


def test_job_uses_printer_profile(tmp_path):
    p = tmp_path / "slow.yaml"
    p.write_text("flow_mm3_s: 3\n")
    base = dict(mode="letters", text="AB", font="Bebas Neue", letter_height_cm=8, depth_mm=15)
    a = run_job(Job.from_dict(base), tmp_path / "a").data["estimated_print_time"]
    b = run_job(Job.from_dict({**base, "printer_profile": str(p)}), tmp_path / "b").data["estimated_print_time"]
    assert b["seconds"] > a["seconds"] and b["assumptions"]["effective_flow_mm3_s"] == 3
