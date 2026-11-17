import numpy as np
import pytest
import trimesh

from kaligraf.geometry import (
    BED_MM,
    back_contact_ratio,
    export_stl,
    fits_bed,
    is_part_valid,
    make_flat,
    make_letters,
)
from kaligraf.text2d import build_text

TOL = 0.5


def _check_parts(model, roundtrip_dir=None):
    for p in model.parts:
        assert is_part_valid(p.mesh_wall), p.name
        assert is_part_valid(p.mesh), p.name
        assert 1 <= p.extruder <= 4
    if roundtrip_dir is not None:
        for path in export_stl(model, roundtrip_dir):
            assert is_part_valid(trimesh.load(path)), path.name


@pytest.mark.parametrize("thickness", [5, 10])
def test_flat_single(montserrat, tmp_path, thickness):
    m = make_flat("Portalin", montserrat, 200, thickness=thickness)
    _check_parts(m, tmp_path)
    (p,) = m.parts
    ext = p.mesh.extents
    assert ext[0] == pytest.approx(200, abs=TOL)
    assert ext[2] == pytest.approx(thickness, abs=1e-6)
    assert all(fits_bed(q.mesh) for q in m.parts)
    assert p.mesh.volume == pytest.approx(m.layout.geometry.area * thickness, rel=0.01)
    assert not m.warnings


def test_flat_two_tone(montserrat, tmp_path):
    m = make_flat("Portalin", montserrat, 200, thickness=5, style="two_tone", colors=["#111111", "#EEEEEE"])
    _check_parts(m, tmp_path)
    body, face = m.parts
    assert (body.role, face.role) == ("body", "face")
    assert body.mesh.bounds[:, 2] == pytest.approx([0, 4.4], abs=1e-6)
    assert face.mesh.bounds[:, 2] == pytest.approx([4.4, 5.0], abs=1e-6)
    assert body.mesh.bounds[:, :2] == pytest.approx(face.mesh.bounds[:, :2], abs=1e-6)
    assert {body.extruder, face.extruder} == {1, 2}
    assert m.depth_mm == 5


def test_flat_backplate_overall_width(montserrat, tmp_path):
    m = make_flat("Portalin", montserrat, 200, thickness=10, style="backplate")
    _check_parts(m, tmp_path)
    plate, glyphs = m.parts
    assert plate.mesh.extents[0] == pytest.approx(200, abs=TOL)
    assert plate.mesh.bounds[:, 2] == pytest.approx([0, 3], abs=1e-6)
    assert glyphs.mesh.bounds[:, 2] == pytest.approx([3, 13], abs=1e-6)  # full T on top of plate
    assert m.depth_mm == 13
    # glyphs sit 6 mm inside the plate on every side
    assert glyphs.mesh.bounds[0, :2] - plate.mesh.bounds[0, :2] == pytest.approx([6, 6], abs=0.1)
    assert plate.mesh.bounds[1, :2] - glyphs.mesh.bounds[1, :2] == pytest.approx([6, 6], abs=0.1)
    assert plate.extruder != glyphs.extruder


def test_flat_validation(montserrat):
    # Custom thickness (e.g. 7 mm) and stroke_offset_mm work; out-of-range thickness raises ValueError
    m7 = make_flat("A", montserrat, 100, thickness=7, stroke_offset_mm=0.8)
    assert m7.depth_mm == 7
    with pytest.raises(ValueError):
        make_flat("A", montserrat, 100, thickness=0.5)
    with pytest.raises(ValueError):
        make_flat("A", montserrat, 100, thickness=260)
    with pytest.raises(ValueError):
        make_flat("A", montserrat, 10, style="backplate")
    with pytest.raises(ValueError):
        make_flat("A", montserrat, 100, style="two_tone", colors=["#000000"])


def test_flat_oversize_warns(montserrat):
    m = make_flat("Portalin", montserrat, 400, thickness=5)
    assert not fits_bed(m.parts[0].mesh)
    assert any(f"{BED_MM:.0f} mm bed" in w for w in m.warnings)
    assert is_part_valid(m.parts[0].mesh)


def test_flat_turkish(montserrat, tmp_path):
    m = make_flat("çğıİöşüÇĞÖŞÜ", montserrat, 240, thickness=5)
    _check_parts(m, tmp_path)
    assert m.parts[0].mesh.extents[0] == pytest.approx(240, abs=TOL)


def test_letters_solid_face_down(bebas, tmp_path):
    m = make_letters("ŞÜKRÜ", bebas, 200, depth=30)
    _check_parts(m, tmp_path)
    assert len(m.parts) == 5
    assert all(fits_bed(p.mesh) for p in m.parts)
    for part, piece in zip(m.parts, m.layout.pieces):
        mesh = part.mesh
        b = piece.geometry.bounds
        assert mesh.extents[0] == pytest.approx(b[2] - b[0], abs=TOL)
        assert mesh.extents[1] == pytest.approx(b[3] - b[1], abs=TOL)
        assert mesh.extents[2] == pytest.approx(30, abs=1e-6)
        # print orientation: smooth face on the plate (z=0) covers the full silhouette
        n, tri = mesh.face_normals, mesh.triangles
        flat0 = (n[:, 2] < -0.999) & (np.abs(tri[:, :, 2]).max(axis=1) < 1e-6)
        assert mesh.area_faces[flat0].sum() == pytest.approx(piece.geometry.area, rel=0.01)
    assert m.meta["recommended_infill"] == "10% gyroid"
    assert m.meta["print_orientation"] == "face_down"
    # assembled model bbox: width from layout, depth 30
    allv = np.vstack([p.mesh_wall.vertices for p in m.parts])
    assert allv[:, 0].max() - allv[:, 0].min() == pytest.approx(m.layout.width_mm, abs=TOL)
    assert allv[:, 2].max() == pytest.approx(30)


def test_letters_cap_height_bbox(bebas):
    m = make_letters("HEH", bebas, 150, depth=20)
    allv = np.vstack([p.mesh_wall.vertices for p in m.parts])
    assert allv[:, 1].max() - allv[:, 1].min() == pytest.approx(150, abs=TOL)
    assert m.depth_mm == 20


def test_letters_validation(bebas):
    # Custom depth (e.g. 25 mm) and stroke_offset_mm work; out-of-range depth raises ValueError
    m25 = make_letters("A", bebas, 100, depth=25, stroke_offset_mm=1.0)
    assert m25.depth_mm == 25
    with pytest.raises(ValueError):
        make_letters("A", bebas, 100, depth=1)
    with pytest.raises(ValueError):
        make_letters("A", bebas, 100, depth=260)
    with pytest.raises(ValueError):
        make_letters("A", bebas, 15)
    with pytest.raises(ValueError):
        make_letters("A", bebas, 450)
    # fewer colours than letters cycle in order (A, C = first colour; B = second)
    cyc = make_letters("ABC", bebas, 100, colors=["#111111", "#222222"])
    assert [p.color.upper() for p in cyc.parts if p.role == "letter"] == ["#111111", "#222222", "#111111"]
    with pytest.raises(ValueError):
        make_letters("ABCDE", bebas, 100, colors=["#111111", "#222222", "#333333", "#444444", "#555555"])


def test_letters_face_color_and_colors(bebas, tmp_path):
    m = make_letters("AB", bebas, 100, depth=15, colors=["#111111", "#222222"], face_color="#FFFFFF")
    _check_parts(m, tmp_path)
    assert len(m.parts) == 4
    bodies = [p for p in m.parts if p.role == "letter"]
    faces = [p for p in m.parts if p.role == "letter_face"]
    assert len(bodies) == len(faces) == 2
    for b, f in zip(bodies, faces):
        assert f.mesh_wall.bounds[:, 2] == pytest.approx([14.4, 15.0], abs=1e-6)
        assert b.mesh_wall.bounds[:, 2] == pytest.approx([0, 14.4], abs=1e-6)
    assert sorted({p.extruder for p in m.parts}) == [1, 2, 3]
    assert len(m.colors) == 3


def test_max_four_colors(bebas):
    with pytest.raises(ValueError):
        make_letters(
            "ABCD", bebas, 100,
            colors=["#111111", "#222222", "#333333", "#444444"], face_color="#FFFFFF",
        )
    m = make_letters("ABCD", bebas, 100, colors=["#111111", "#222222", "#333333", "#444444"])
    assert max(p.extruder for p in m.parts) == 4


@pytest.mark.parametrize("depth", [15, 30])
def test_open_back_shell(bebas, montserrat, tmp_path, depth):
    for font, txt in ((bebas, "ŞÜKRÜ"), (montserrat, "Hello")):
        solid = make_letters(txt, font, 150, depth=depth)
        shell = make_letters(txt, font, 150, depth=depth, open_back_shell=True)
        _check_parts(shell, tmp_path)
        assert shell.meta["construction"] == "open_back_shell"
        for s, h, piece in zip(shell.parts, solid.parts, shell.layout.pieces):
            assert s.mesh.volume < 0.8 * h.mesh.volume
            assert back_contact_ratio(s.mesh_wall, piece.geometry.area) >= 0.40
            assert s.mesh.extents == pytest.approx(h.mesh.extents, abs=1e-6)
        assert min(shell.meta["back_contact"].values()) >= 0.40


def test_open_back_shell_face_thickness(bebas):
    m = make_letters("H", bebas, 150, depth=30, open_back_shell=True, wall=2.4)
    mesh = m.parts[0].mesh_wall
    # faces below the 2.0 mm face slab: cavity ceiling at z = 28
    zs = np.unique(np.round(mesh.vertices[:, 2], 6))
    assert 28.0 in zs and 30.0 in zs and 0.0 in zs


def test_shell_mid_size_warns_but_builds(bebas):
    m = make_letters("A", bebas, 80, depth=15, open_back_shell=True)
    assert any("large letters" in w for w in m.warnings)
    assert m.meta["construction"] == "open_back_shell"


def test_shell_falls_back_to_solid_below_60(bebas):
    m = make_letters("A", bebas, 55, depth=15, open_back_shell=True)
    assert any("building solid" in w for w in m.warnings)
    assert m.meta["construction"] == "solid"
    assert "back_contact" not in m.meta
    assert all(is_part_valid(p.mesh) for p in m.parts)


def test_detached_pieces_recorded(bebas):
    m = make_letters("ÜIİ", bebas, 150, depth=15)
    u, i, idot = m.parts
    assert len(u.meta["detached_pieces"]) == 2
    assert "detached_pieces" not in i.meta
    assert len(idot.meta["detached_pieces"]) == 1
    d = idot.meta["detached_pieces"][0]
    assert d["bounds"][1] > 150 * 0.95  # dot sits above cap height (wall coords)
    f = make_letters("İ", bebas, 150, depth=15, face_color="#FFFFFF")
    assert all("detached_pieces" in p.meta for p in f.parts)


def test_stl_export_origin_and_names(bebas, tmp_path):
    m = make_letters("ŞÜK", bebas, 100, depth=15)
    paths = export_stl(m, tmp_path / "parts")
    assert [p.name for p in paths] == ["letter_01_S.stl", "letter_02_U.stl", "letter_03_K.stl"]
    for path in paths:
        mesh = trimesh.load(path)
        assert mesh.bounds[0] == pytest.approx([0, 0, 0], abs=1e-6)


def test_layout_reuse(montserrat):
    layout = build_text("Ab", montserrat, "flat", width_mm=100)
    from kaligraf.geometry import build_flat

    m = build_flat(layout, thickness=5)
    assert m.parts[0].mesh.extents[0] == pytest.approx(100, abs=TOL)
