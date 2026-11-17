import math

import numpy as np
import pytest
import trimesh

from kaligraf.geometry import is_part_valid, make_flat, make_letters
from kaligraf.mounting import (
    KEYHOLE_CHAMBER_DEPTH,
    KEYHOLE_LIP,
    normalize_mounting,
)


def _inside(mesh, pt):
    return bool(mesh.contains([pt])[0])


def test_normalize_mounting():
    assert normalize_mounting(None) == ["tape"]
    assert normalize_mounting(["keyhole", "keyhole"]) == ["keyhole"]
    with pytest.raises(ValueError):
        normalize_mounting(["glue"])


def test_keyhole_letters(bebas):
    base = make_letters("HK", bebas, 150, depth=30)
    m = make_letters("HK", bebas, 150, depth=30, mounting=["keyhole"])
    assert len(m.meta["mounting"]["keyholes"]) == 2
    for p, b, kh in zip(m.parts, base.parts, m.meta["mounting"]["keyholes"]):
        assert is_part_valid(p.mesh_wall)
        assert p.mesh_wall.volume < b.mesh_wall.volume
        cx, cy = kh["x"], kh["y"]
        mesh = p.mesh_wall
        # entry hole open at the back, chamber behind the lip, solid lip beside the slot
        assert not _inside(mesh, (cx, cy, 0.5))
        assert not _inside(mesh, (cx, cy + 10, 0.5))
        assert not _inside(mesh, (cx + 3.5, cy, (KEYHOLE_LIP + KEYHOLE_CHAMBER_DEPTH) / 2))
        assert _inside(mesh, (cx + 3.0, cy + 5, 0.5))  # lip beside the 4 mm slot
        assert _inside(mesh, (cx, cy, KEYHOLE_CHAMBER_DEPTH + 1.0))  # solid above the chamber
        # volume removed ~ entry + chamber
        removed = b.mesh_wall.volume - mesh.volume
        assert removed == pytest.approx(590, rel=0.1)


def test_keyhole_skipped_cases(bebas, montserrat):
    m = make_flat("Hi", bebas, 120, thickness=5, mounting=["keyhole"])
    assert any("10 mm" in w for w in m.warnings) and not m.meta["mounting"]["keyholes"]
    m = make_flat("Hi", montserrat, 200, thickness=10, style="backplate", mounting=["keyhole"])
    assert any("backplate" in w for w in m.warnings)
    m = make_flat("Portalin", montserrat, 100, thickness=10, mounting=["keyhole"])  # strokes too thin
    assert any("no solid area" in w for w in m.warnings)
    m = make_letters("I", bebas, 60, depth=15, mounting=["keyhole"])  # too narrow
    assert any("no solid area" in w for w in m.warnings)
    m = make_letters("HK", bebas, 150, depth=15, open_back_shell=True, mounting=["keyhole"])
    assert any("open_back_shell" in w for w in m.warnings)


def test_keyhole_mode_a_10mm(bebas):
    m = make_flat("Hi", bebas, 200, thickness=10, mounting=["keyhole"])
    assert len(m.meta["mounting"]["keyholes"]) == 1
    assert is_part_valid(m.parts[0].mesh_wall)


def test_holes_mode_a_backplate(montserrat):
    base = make_flat("Hi", montserrat, 200, thickness=5, style="backplate")
    m = make_flat("Hi", montserrat, 200, thickness=5, style="backplate", mounting=["holes"])
    holes = m.meta["mounting"]["holes"]
    assert len(holes) == 2 and all(h["diameter"] == 3.0 for h in holes)
    plate, glyphs = m.parts
    assert all(is_part_valid(p.mesh_wall) for p in m.parts)
    removed = base.parts[0].mesh_wall.volume - plate.mesh_wall.volume
    assert removed == pytest.approx(2 * math.pi * 1.5**2 * 3.0, rel=0.05)  # through the 3 mm plate
    for h in holes:
        assert not _inside(plate.mesh_wall, (h["x"], h["y"], 1.5))
        assert _inside(plate.mesh_wall, (h["x"] + 2.0, h["y"], 1.5))


def test_holes_through_two_tone_and_skip_for_letters(bebas):
    m = make_flat("HI", bebas, 160, thickness=10, style="two_tone", mounting=["holes"])
    h = m.meta["mounting"]["holes"][0]
    for p in m.parts:
        assert not _inside(p.mesh_wall, (h["x"], h["y"], p.mesh_wall.bounds.mean(axis=0)[2]))
    mb = make_letters("HI", bebas, 100, mounting=["holes"])
    assert any("only for Mode A" in w for w in mb.warnings)


def test_holes_no_room_warns(montserrat):
    m = make_flat("Portalin", montserrat, 100, thickness=5, mounting=["holes"])
    assert not m.meta["mounting"]["holes"]
    assert any("holes skipped" in w for w in m.warnings)


def test_connector_bar_letters(bebas):
    m = make_letters("ŞÜKRÜ", bebas, 200, depth=30, mounting=["connector_bar"])
    rails = [p for p in m.parts if p.role == "rail"]
    letters = [p for p in m.parts if p.role == "letter"]
    info = m.meta["mounting"]["rail"]
    assert len(letters) == 5 and len(rails) == info["segments"] == 3
    total = 0.0
    for r in rails:
        e = r.mesh.extents
        assert e[1] == pytest.approx(10.0, abs=1e-6) and e[2] == pytest.approx(4.0, abs=1e-6)
        assert e[0] <= 245.0 + 1e-6
        assert is_part_valid(r.mesh)
        total += e[0]
    assert total == pytest.approx(info["x_max"] - info["x_min"], abs=1e-3)
    # recessed into every letter back, and accents bridged to their letters
    assert all(p.meta.get("rail_channel") for p in letters)
    assert info["bridges"] == 4  # two U-diaereses (2 dots each... bridged) + S cedilla etc.
    for p in letters:
        assert is_part_valid(p.mesh_wall)
        assert len(p.mesh_wall.split(only_watertight=False)) == 1  # one solid after bridging


def test_connector_bar_short_word_single_rail(bebas):
    m = make_letters("HIH", bebas, 100, depth=20, mounting=["connector_bar"])
    assert [p.name for p in m.parts if p.role == "rail"] == ["rail"]
    assert m.meta["mounting"]["rail"]["y_center"] > 0


def test_connector_bar_single_letter_skips(bebas):
    m = make_letters("H", bebas, 100, mounting=["connector_bar"])
    assert any("at least two" in w for w in m.warnings)


def test_connector_bar_flat_baseline_strip(bebas):
    sep = make_flat("AB", bebas, 160, thickness=5)
    joined = make_flat("AB", bebas, 160, thickness=5, mounting=["connector_bar"])
    # tracking default leaves A and B apart in a flat sign only if not touching; force with tracking
    sep = make_flat("AB", bebas, 160, thickness=5, tracking=0.4)
    joined = make_flat("AB", bebas, 160, thickness=5, tracking=0.4, mounting=["connector_bar"])
    n_sep = len(sep.parts[0].mesh_wall.split(only_watertight=False))
    n_join = len(joined.parts[0].mesh_wall.split(only_watertight=False))
    assert n_sep == 2 and n_join == 1
    assert is_part_valid(joined.parts[0].mesh_wall)
