import json
import re

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point

from maker import core, docs, estimate, plates, slicer
from maker.generators import Part, SheetLayout
from maker.generators.coupon import clearances
from maker.job import build, run_job


def _pdf_pages(path) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes()))


@pytest.fixture(scope="module")
def small():
    res, _ = build({"generator": "thermoform", "params": {"width_mm": 50, "cavities": 2}})
    return res


def test_pack_one_material_per_plate_and_copies(small):
    pls = plates.pack(small.parts)
    assert [p.material for p in pls][0] == "PETG"  # molds first
    names = [n for p in pls for n, _ in p.items]
    for p in small.parts:
        if not p.printable:
            assert not any(n.startswith(p.name) for n in names)
            continue
        k = int(p.meta.get("count", 1))
        assert sum(n == p.name or n.startswith(p.name + "_") for n in names) == k
    for pl in pls:
        for _, m in pl.items:
            lo, hi = m.bounds
            assert lo[2] == pytest.approx(0, abs=1e-6) and lo[0] >= -1e-6 and lo[1] >= -1e-6
            assert hi[0] <= core.BED_MM + 1e-6 and hi[1] <= core.BED_MM + 1e-6
            assert not (hi[0] > plates.EXCLUDE[0] and lo[1] < plates.EXCLUDE[1]), "part in the exclusion corner"
        boxes = [m.bounds[:, :2] for _, m in pl.items]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                assert a[1][0] <= b[0][0] + 1e-6 or b[1][0] <= a[0][0] + 1e-6 or a[1][1] <= b[0][1] + 1e-6 or b[1][1] <= a[0][1] + 1e-6


def test_pack_splits_full_plates():
    box = trimesh.creation.box((100, 100, 5))
    box.apply_translation(-box.bounds[0])
    pls = plates.pack([Part("b", "B", box, meta={"count": 7})])
    assert len(pls) == 2 and sum(len(p.items) for p in pls) == 7  # 4 per plate (2 x 2), the corner costs nothing here


def test_3mf_petg_slot_and_infill(small, tmp_path):
    f = tmp_path / "m.3mf"
    pls = plates.write_3mf(small.parts, f)
    info = core.inspect_3mf(f)
    proj = info["project"]
    assert proj["filament_type"] == ["PETG", "PLA"]
    assert proj["filament_settings_id"][0] == "Elegoo PETG @ECC" and proj["nozzle_temperature"][0] == "250"
    assert proj["curr_bed_type"] == "Textured PEI Plate"
    assert len(info["plates"]) == len(pls)
    import zipfile

    cfg = zipfile.ZipFile(f).read("Metadata/model_settings.config").decode()
    assert cfg.count('key="sparse_infill_density" value="10%"') == 2  # female + male only


def test_sheet_pdf_single_and_tiled(tmp_path):
    shape = Point(0, 0).buffer(20)
    small = SheetLayout((60, 60), [shape], [shape.buffer(5)], title="t", lines=["a", "b"])
    assert docs.write_sheet_pdf(small, tmp_path / "a.pdf")["pages"] == 1
    big = SheetLayout((230, 230), [shape], [shape.buffer(5)], title="t")
    r = docs.write_sheet_pdf(big, tmp_path / "b.pdf")
    assert r["pages"] == 2 and _pdf_pages(tmp_path / "b.pdf") == 2
    huge = SheetLayout((240, 400), [shape], [shape.buffer(5)], title="t")
    r = docs.write_sheet_pdf(huge, tmp_path / "c.pdf")
    assert r["pages"] == 3 and r["page"] == "A4 yatay"  # landscape needs fewer pages than portrait (4)
    assert docs._tiles(100, 100, 190, 250) == ([0.0], [0.0])
    xs, _ = docs._tiles(400, 10, 190, 250)
    assert xs[-1] + 190 >= 400 and len(xs) == 3


def test_thermoform_job_documents(tmp_path):
    res = run_job({"generator": "thermoform", "name": "k", "params": {"width_mm": 50}}, tmp_path)
    d = json.loads((res.out_dir / "job.json").read_text(encoding="utf-8"))
    for k in ("assembly_pdf", "sheet_pdf", "3mf", "render_product", "render_parts"):
        assert (res.out_dir / d["files"][k]).stat().st_size > 1000, k
    assert d["meta"]["sheet_template"]["pages"] == 1
    assert d["plates"] and all(p["objects"] for p in d["plates"])
    assert _pdf_pages(res.out_dir / "montaj.pdf") == 2
    assert any("levha_sablonu.pdf" in n for n in d["notes"])


def test_coupon_clearances_and_marks():
    res, v = build({"generator": "thermo_coupon", "params": {"count": 3, "clear_min": 0.1, "clear_step": 0.15}})
    assert clearances(v) == [0.1, 0.25, 0.4]
    males = [p for p in res.parts if p.name.startswith("male_")]
    assert [p.meta["clearance_mm"] for p in males] == [0.1, 0.25, 0.4]
    # half way up the plug (above the 4 mm base) its walls move in as the clearance grows
    widths = [np.ptp(p.mesh.section([0, 0, 1], [0, 0, 8.0]).vertices[:, 0]) for p in males]
    # on the 45 deg flank: inward normal offset d (x sqrt2) minus the male's lift by d -> 2 d (sqrt2 - 1) narrower
    assert np.allclose(np.diff(widths), -2 * 0.15 * (np.sqrt(2) - 1), atol=0.03), widths
    vols = [p.mesh.volume for p in males]
    assert vols[0] > vols[1] > vols[2]  # more marker holes and a lower plug
    assert [len(p.mesh.split()) for p in males] == [1, 1, 1]
    assert res.sheet.size_mm[0] < 80 and len(res.sheet.trims) == 1
    assert any("clearance_mm" in n for n in res.notes)
    assert all(p.material == "PETG" for p in res.parts)


def test_calibration_factors(tmp_path, monkeypatch):
    m = trimesh.creation.box((40, 40, 10))
    base = estimate.part_estimate(m, "PLA", "part")
    f = tmp_path / "c.yaml"
    f.write_text("calibration: {part: {grams: 0.5, minutes: 3}}\n", encoding="utf-8")
    monkeypatch.setattr(estimate, "USER_FILE", f)
    cal = estimate.part_estimate(m, "PLA", "part")
    assert cal.grams == pytest.approx(base.grams * 0.5 / 0.95, rel=0.02)
    assert cal.minutes == pytest.approx(base.minutes * 3 / 2.0, abs=1)


def test_slicer_stats_and_missing(tmp_path, monkeypatch):
    s = slicer.gcode_stats("; total filament used [g] = 57.22\n; estimated printing time (normal mode) = 4h 14m 24s\n")
    assert s == {"grams": 57.22, "time": "4h 14m 24s"}
    from maker.core import shared_slicer

    monkeypatch.setattr(shared_slicer, "ORCA", "olmayan-orca-xyz")  # the shared slicer (workbench_core) does the work
    res = run_job({"generator": "thermo_coupon", "name": "c", "slice": True, "params": {"count": 2}}, tmp_path)
    assert any("Dilimleme yapılamadı" in w for w in res.data["warnings"])
    assert (res.out_dir / "model.3mf").is_file()
