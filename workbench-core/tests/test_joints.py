"""Script words cut into letters with jigsaw locks (workbench_core.joints)."""
import math

import pytest
from shapely import affinity

from workbench_core.fonts import resolve_font
from workbench_core.geometry import build_letters
from workbench_core.joints import CLEARANCE, split_joined
from workbench_core.text2d import build_text


@pytest.fixture(scope="module")
def ayse():
    lay = build_text("Ayşe", resolve_font("Pacifico"), "letters", cap_height_mm=120, language="tr")
    return lay, *split_joined(lay)


def _by_glyph(pieces):
    return {p.glyph_indices[0]: p.geometry for p in pieces}


def test_one_part_per_letter(ayse):
    lay, pieces, joints, warnings = ayse
    assert len(lay.pieces) < len(lay.glyphs)  # the font really joins letters
    assert [p.text for p in pieces] == ["A", "y", "ş", "e"]
    assert all(len(p.glyph_indices) == 1 for p in pieces)
    assert len(joints) == 2 and all(j.lock for j in joints) and not warnings


def test_parts_do_not_overlap_and_keep_the_word(ayse):
    lay, pieces, _, _ = ayse
    g = [p.geometry for p in pieces]
    for i in range(len(g)):
        assert g[i].is_valid
        for k in range(i + 1, len(g)):
            assert g[i].intersection(g[k]).area < 1e-3
    lost = 1 - sum(x.area for x in g) / lay.geometry.area
    assert 0 <= lost < 0.01  # only the socket clearance is removed


def test_lock_holds_in_every_direction(ayse):
    """A locked letter cannot slide 1 mm in any direction in the plane without hitting its neighbour."""
    _, pieces, joints, _ = ayse
    by = _by_glyph(pieces)
    for j in joints:
        a, b = by[j.left], by[j.right]
        for k in range(12):
            t = 2 * math.pi * k / 12
            moved = affinity.translate(a, math.cos(t), math.sin(t))
            assert moved.intersection(b).area > 0.05, (j.left, j.right, k)


def test_socket_clearance(ayse):
    _, pieces, joints, _ = ayse
    by = _by_glyph(pieces)
    for j in joints:
        a, b = by[j.left], by[j.right]
        mid = j.cut.interpolate(0.5, normalized=True).buffer(j.width * 0.8)
        # around the knob the parts are CLEARANCE apart, never touching except along the straight cut
        gap = a.intersection(mid).buffer(CLEARANCE * 0.5).intersection(b).area
        assert gap < j.width * CLEARANCE * 2.5


def test_thin_joins_are_glued_with_a_warning():
    lay = build_text("Selin", resolve_font("Dancing Script"), "letters", cap_height_mm=60, language="tr")
    pieces, joints, warnings = split_joined(lay)
    assert len(pieces) == 5
    thin = [j for j in joints if not j.lock]
    assert thin and len(warnings) >= len(thin) and all("yapıştırılmalı" in w for w in warnings[:len(thin)])


def test_print_font_unchanged():
    lay = build_text("ABC", resolve_font("Bebas Neue"), "letters", cap_height_mm=100)
    pieces, joints, warnings = split_joined(lay)
    assert [p.text for p in pieces] == ["A", "B", "C"] and not joints and not warnings


def test_build_letters_option(ayse):
    lay = ayse[0]
    one = build_letters(lay, depth=15)
    split = build_letters(lay, depth=15, joints="puzzle")
    assert len(one.parts) == len(lay.pieces) and len(split.parts) == 4
    assert len(split.meta["joints"]) == 2 and all(j["lock"] for j in split.meta["joints"])
    assert all(p.mesh.is_watertight for p in split.parts)
    with pytest.raises(ValueError):
        build_letters(lay, depth=15, joints="glue")
