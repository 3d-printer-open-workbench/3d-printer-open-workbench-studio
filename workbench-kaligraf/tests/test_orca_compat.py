import zipfile

import numpy as np
import trimesh

from kaligraf.export3mf import project_settings, plate_reserved, TEMPLATE
import json

from kaligraf.split import SplitPiece, pack_plates_single


def test_project_settings_vectors_consistent():
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for n in (1, 2, 4):
        p = project_settings(["#222222", "#F5F5F5", "#C0392B", "#2980B9"][:n], (210, 228), n_plates=3)
        for k in raw["per_filament"]:
            assert len(p[k]) == n, k
        assert p["wipe_tower_x"] == ["210"] * 3 and p["skirt_loops"] == "0"
        assert len(p["flush_volumes_matrix"]) == n * n


def test_3mf_application_tag_is_orca_compatible(tmp_path):
    from kaligraf.job import Job, run_job

    res = run_job(Job(mode="letters", text="AB", font="Montserrat", letter_height_cm=6, depth_mm=15,
                      face_color="beyaz", letter_colors=["siyah"]), tmp_path)
    with zipfile.ZipFile(res.files["3mf"]) as z:
        model = z.read("3D/3dmodel.model").decode()
        proj = json.loads(z.read("Metadata/project_settings.config"))
    # Orca's own identification; "OrcaSlicer-x.y.z" crashes the loader, and without any tag the CLI re-arranges
    assert 'name="Application">BambuStudio-' in model and 'OrcaSlicer-' not in model
    assert len(proj["filament_colour"]) == len(proj["filament_type"]) == len(proj["filament_map"])


class _P:  # minimal piece stand-in
    pass


def _piece(name, w, h):
    from kaligraf.geometry import Part

    m = trimesh.creation.box((w, h, 5))
    m.apply_translation(-m.bounds[0])
    part = Part.__new__(Part)
    part.name = name
    return SplitPiece(name=name, part=part, group=name, cell=(0, 0), mesh=m)


def test_packer_keeps_reserved_rectangles_free():
    pieces = [_piece(f"p{i}", 90, 120) for i in range(6)]
    reserved, mixed, tower = plate_reserved(True)
    assert tower is not None
    plates = pack_plates_single(pieces, reserved=reserved + mixed)
    reserved = reserved + mixed
    for pl in plates:
        for p in pl.placements:
            for rx, ry, rw, rh in reserved:
                assert not (p.x < rx + rw and p.x + p.width > rx and p.y < ry + rh and p.y + p.height > ry)


def _plate_extruders(res):
    from kaligraf.split import plate_meshes

    return [{pc.part.extruder for pc, _ in items} for items in plate_meshes(res.split, _plates(res))]


def _plates(res):
    from kaligraf.export3mf import plate_reserved
    from kaligraf.split import pack_plates

    reserved, mixed, _ = plate_reserved(len({p.extruder for p in res.model.parts}) > 1)
    return pack_plates(res.split.pieces, reserved=reserved, mixed_reserved=mixed)


def test_single_colour_plates_have_one_extruder_and_full_area(tmp_path):
    from kaligraf.job import Job, run_job

    single = run_job(Job(mode="letters", text="ŞÜKRÜ", font="Bebas Neue", letter_height_cm=20, depth_mm=30,
                         letter_colors=["siyah"]), tmp_path / "a", extras=False)
    assert all(len(e) == 1 for e in _plate_extruders(single))
    proj = json.loads(zipfile.ZipFile(single.files["3mf"]).read("Metadata/project_settings.config"))
    assert len(proj["filament_colour"]) == 1  # one colour: no tower needed anywhere
    mixed = run_job(Job(mode="letters", text="ŞÜKRÜ", font="Bebas Neue", letter_height_cm=20, depth_mm=30,
                        letter_colors=["siyah"], face_color="beyaz"), tmp_path / "b", extras=False)
    assert all(len(e) == 2 for e in _plate_extruders(mixed))
    # without the tower strip the single-colour job packs onto no more plates than the mixed one
    assert single.data["plates"] <= mixed.data["plates"]


def test_colour_aware_packing_separates_extruders():
    from kaligraf.geometry import Part
    from kaligraf.split import pack_plates, plate_meshes  # noqa: F401

    def piece(name, ext, w=60, h=60):
        m = trimesh.creation.box((w, h, 5))
        m.apply_translation(-m.bounds[0])
        part = Part.__new__(Part)
        part.name, part.extruder = name, ext
        return SplitPiece(name=name, part=part, group=name, cell=(0, 0), mesh=m)

    pcs = [piece("a1", 1), piece("a2", 1), piece("b1", 2), piece("m", 1), piece("m", 2)]
    pcs[3].group = pcs[4].group = "m"  # one assembly unit holding two colours
    plates = pack_plates(pcs, reserved=[], mixed_reserved=[(190.0, 190.0, 60.0, 60.0)])
    by_plate = {pl.index: {pc.part.extruder for u in pl.placements for pc in pcs if (pc.group, *pc.cell) == u.unit} for pl in plates}
    assert sorted(len(v) for v in by_plate.values()) == [1, 1, 2]
    mixed_plate = next(pl for pl in plates if len(by_plate[pl.index]) == 2)
    for pm in mixed_plate.placements:
        assert not (pm.x + pm.width > 190 and pm.y + pm.height > 190)
