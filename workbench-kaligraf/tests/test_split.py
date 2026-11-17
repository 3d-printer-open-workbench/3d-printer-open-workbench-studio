import math

import numpy as np
import pytest

from kaligraf.geometry import BED_MM, is_part_valid, make_flat, make_letters
from kaligraf.split import (
    PIN_HOLE_D,
    PIN_HOLE_DEPTH,
    pack_plates,
    plate_meshes,
    split_model,
)


def _fp(mesh):
    return mesh.extents[:2]


def test_no_split_when_it_fits(bebas):
    m = make_letters("ŞÜKRÜ", bebas, 200, depth=30)  # Ş is 245 mm tall: must NOT split
    r = split_model(m)
    assert r.cuts == {} and r.pins == []
    assert [p.name for p in r.pieces] == [p.name for p in m.parts]


def test_flat_two_tone_split_glue_seam(montserrat):
    m = make_flat("Portalin", montserrat, 400, thickness=5, style="two_tone")
    r = split_model(m)
    assert list(r.cuts) == ["sign"] and len(r.cuts["sign"]["x"]) == 1 and not r.cuts["sign"]["y"]
    assert sorted(p.name for p in r.pieces) == ["body_p1of2", "body_p2of2", "face_p1of2", "face_p2of2"]
    for pc in r.pieces:
        assert is_part_valid(pc.mesh), pc.name
        assert all(_fp(pc.mesh) <= BED_MM)
    for src in m.parts:  # pieces tile the part exactly
        vol = sum(pc.mesh.volume for pc in r.pieces if pc.part is src)
        assert vol == pytest.approx(src.mesh.volume, rel=1e-3)
    assert any("glue" in w for w in r.warnings)  # 4.4 mm body: no room for pins
    # body and face share identical seams
    bx = sorted(pc.mesh.bounds[1][0] for pc in r.pieces if pc.part.name == "body")
    fx = sorted(pc.mesh.bounds[1][0] for pc in r.pieces if pc.part.name == "face")
    assert bx == pytest.approx(fx, abs=1e-3)


def test_pin_holes_match_across_the_seam(bebas):
    m = make_flat("HELLO", bebas, 400, thickness=10, tracking=-0.1)  # touching letters: no gap to cut through
    r = split_model(m)
    assert r.pins, "10 mm sign must get pin holes"
    body = m.parts[0]
    expected_hole_volume = len(r.pins) * math.pi * (PIN_HOLE_D / 2) ** 2 * 2 * PIN_HOLE_DEPTH
    removed = body.mesh.volume - sum(pc.mesh.volume for pc in r.pieces)
    assert removed == pytest.approx(expected_hole_volume, rel=0.03)
    cx = r.cuts["sign"]["x"][0]
    for pin in r.pins:
        assert pin["axis"] == "x" and pin["coord"] == pytest.approx(cx)
        assert pin["hole_diameter"] == 3.2 and pin["hole_depth"] == 10.0 and pin["pin_diameter"] == 3.0
        y, z = pin["pos"], pin["z"]
        # holes extend 8 mm into both pieces (empty), while 2.5 mm beside the axis is solid
        for dx in (-8.0, 8.0):
            assert not any(pc.mesh.contains([(cx + dx, y, z)])[0] for pc in r.pieces)
            assert any(pc.mesh.contains([(cx + dx, y + 2.5, z)])[0] for pc in r.pieces)
    for pc in r.pieces:
        assert is_part_valid(pc.mesh)


def test_cut_prefers_gaps(bebas):
    m = make_flat("AB", bebas, 480, thickness=10, tracking=1.2)  # wide gap between letters
    r = split_model(m)
    cx = r.cuts["sign"]["x"][0]
    a, b = sorted(m.layout.pieces, key=lambda p: p.geometry.bounds[0])
    assert a.geometry.bounds[2] < cx < b.geometry.bounds[0]
    assert r.pins == []  # cut through the gap: no seam, no pins


def test_letters_40cm_split_with_pins_and_names(bebas):
    m = make_letters("AB", bebas, 400, depth=30)
    r = split_model(m)
    assert set(r.cuts) == {"letter_01_A", "letter_02_B"}
    names = sorted(pc.name for pc in r.pieces)
    assert names == ["letter_01_A_p1of2", "letter_01_A_p2of2", "letter_02_B_p1of2", "letter_02_B_p2of2"]
    assert r.pins and all(p["axis"] == "y" for p in r.pins)
    for pc in r.pieces:
        assert is_part_valid(pc.mesh), pc.name
        assert all(_fp(pc.mesh) <= BED_MM + 1e-6), pc.name


def test_stacked_parts_split_in_same_cells(bebas):
    m = make_letters("A", bebas, 400, depth=30, face_color="#FFFFFF")
    r = split_model(m)
    assert sorted(pc.name for pc in r.pieces) == [
        "letter_01_A_body_p1of2", "letter_01_A_body_p2of2",
        "letter_01_A_face_p1of2", "letter_01_A_face_p2of2",
    ]
    assert sum("pin" in w for w in r.warnings) == 0  # face role never warns
    assert {p["part"] for p in r.pins} == {"letter_01_A_body"}


def test_shell_split_no_pins_warns(bebas):
    m = make_letters("A", bebas, 400, depth=30, open_back_shell=True)
    r = split_model(m)
    assert r.pins == [] and any("open_back_shell" in w for w in r.warnings)


def test_plate_packing(bebas):
    m = make_letters("ŞÜKRÜ", bebas, 200, depth=30, face_color="#FFFFFF")
    r = split_model(m)
    plates = pack_plates(r.pieces)
    assert len(plates) >= 2
    seen = 0
    for items in plate_meshes(r, plates):
        boxes = []
        for pc, mesh in items:
            lo, hi = mesh.bounds
            assert lo[0] >= -1e-6 and lo[1] >= -1e-6
            assert hi[0] <= BED_MM + 1e-6 and hi[1] <= BED_MM + 1e-6
            boxes.append((lo, hi, pc))
            seen += 1
        # body+face of one letter share XY; different letters never overlap
        for i, (l1, h1, p1) in enumerate(boxes):
            for l2, h2, p2 in boxes[i + 1:]:
                if p1.group == p2.group:
                    continue
                assert h1[0] <= l2[0] + 1e-6 or h2[0] <= l1[0] + 1e-6 or h1[1] <= l2[1] + 1e-6 or h2[1] <= l1[1] + 1e-6
    assert seen == len(r.pieces)


def test_plate_packing_split_pieces(bebas):
    m = make_letters("AB", bebas, 400, depth=30)
    r = split_model(m)
    plates = pack_plates(r.pieces)
    assert sum(len(p.placements) for p in plates) == 4
    for items in plate_meshes(r, plates):
        for _, mesh in items:
            assert mesh.bounds[0][2] == pytest.approx(0, abs=1e-6)
            assert np.all(mesh.bounds[1][:2] <= BED_MM + 1e-6)
