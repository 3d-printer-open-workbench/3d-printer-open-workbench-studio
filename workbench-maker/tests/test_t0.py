import ast
import json
import time
from pathlib import Path

import pytest
import trimesh

from maker import core, tools
from maker.generators import GENERATORS, Generator, get_generator
from maker.job import load_job, run_job
from maker.sheets import get_sheet, load_sheets
from maker.shapes import SHAPES, shape_polygon

SRC = Path(__file__).parents[1] / "src" / "maker"


def test_only_core_imports_the_engine():
    for f in SRC.rglob("*.py"):
        if f.name == "core.py":
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(m.startswith(("kaligraf", "workbench_core")) for m in mods), f"{f.name} imports the engine directly"


def test_registry():
    assert {"thermoform", "plate", "keychain", "qr_plaque"} <= set(GENERATORS)
    assert get_generator("plate").status == "ready"
    th = Generator("later", "Sonra", "Deneme", "", [], status="planned", milestone="S1")  # every catalogue item is ready since T7
    with pytest.raises(ValueError, match="henüz hazır değil"):
        th.run({})
    with pytest.raises(ValueError, match="bilinmeyen"):
        get_generator("yok")
    for g in GENERATORS.values():
        s = g.schema()
        json.dumps(s)  # serialisable for the UI / MCP
        assert len({p["key"] for p in s["params"]}) == len(s["params"])


def test_param_validation():
    g = get_generator("plate")
    v = g.values({"width_mm": "100"})
    assert v["width_mm"] == 100.0 and v["shape"] == "heart"
    with pytest.raises(ValueError, match="aralığında"):
        g.values({"width_mm": 999})
    with pytest.raises(ValueError, match="geçersiz seçim"):
        g.values({"shape": "kare-degil"})
    with pytest.raises(ValueError, match="bilinmeyen parametre"):
        g.values({"renk": "#fff"})


def test_sheets_petg_default():
    default, sheets = load_sheets()
    assert default == "petg_05" and all(s.material == "PETG" for s in sheets.values())
    s = get_sheet()
    assert s.thickness_mm == 0.5 and s.mold_gap_mm == pytest.approx(0.7)


@pytest.mark.parametrize("kind", SHAPES)
def test_shapes(kind):
    g = shape_polygon(kind, 80)
    x0, y0, x1, y1 = g.bounds
    assert g.is_valid and x1 - x0 == pytest.approx(80, abs=0.01)
    assert abs(x0 + x1) < 0.01 and abs(y0 + y1) < 0.01


def test_plate_job(tmp_path):
    try:
        core.resolve_font("Righteous")
    except Exception:
        pytest.skip("Montserrat font missing")
    res = run_job(load_job(Path(__file__).parents[1] / "examples" / "kalp_plaka.yaml"), tmp_path)
    d = json.loads((res.out_dir / "job.json").read_text(encoding="utf-8"))
    assert [p["name"] for p in d["parts"]] == ["plate", "text"]
    assert d["overall_mm"][0] == pytest.approx(80, abs=0.5)
    for p in d["parts"]:
        m = trimesh.load(res.out_dir / "parts" / p["stl"])
        assert m.is_watertight and m.volume > 0 and m.bounds[0] == pytest.approx([0, 0, 0], abs=1e-6)
    assert (res.out_dir / "preview.glb").stat().st_size > 1000


def test_plate_no_text(tmp_path):
    res = run_job({"generator": "plate", "name": "yıldız ş", "params": {"shape": "star", "text": " "}}, tmp_path)
    assert res.out_dir.name == "yildiz_s" and len(res.data["parts"]) == 1


def test_turkish_warnings():
    assert core.tr_warning("3 feature(s) thinner than 2.0 mm at this size (e.g. near x=14 mm, y=3 mm); they may print poorly or break.").startswith("3 yerde çizgi 2.0 mm")
    assert core.tr_warning("SVG has 7 distinct colors; merged to 4.") == "SVG'de 7 farklı renk var; 4 renge indirildi."
    assert core.tr_warning("başka bir mesaj") == "başka bir mesaj"


def test_plate_defaults_clean_and_render():
    from maker.job import build
    from maker.render import render_parts

    try:
        core.resolve_font("Righteous")
    except Exception:
        pytest.skip("Righteous font missing")
    res, _ = build({"generator": "plate", "params": {}})
    assert res.warnings == []
    im = render_parts(res.parts, width_px=300)
    assert im.mode == "RGBA" and im.getbbox() is not None


def test_plate_text_autofits():
    from maker.job import build

    res, _ = build({"generator": "plate", "params": {"shape": "star", "text": "Ayşe"}})
    plate, text = res.parts
    assert any("küçültüldü" in w for w in res.warnings)
    assert text.mesh.extents[0] < 0.6 * plate.mesh.extents[0]


def test_cut_paths_written(tmp_path):
    from maker.core import gcode_stats  # the shared slicer, re-exported

    res = run_job({"generator": "plate", "name": "kesim", "params": {"shape": "heart", "text": " "}}, tmp_path)
    assert res.files["cut_svg"].is_file() and res.files["cut_dxf"].is_file()
    assert gcode_stats("; total filament used [g] = 1.5\n")["grams"] == 1.5


def test_default_sheet():
    assert tools.list_sheets()["default"] == "petg_05"
