"""M8: colour maths, surface finishes, MCP tool functions, opencode files."""
import json
from pathlib import Path

import numpy as np
import pytest

from kaligraf import colorlib as cl
from kaligraf import tools
from kaligraf.job import Job, run_job

ROOT = Path(__file__).resolve().parents[1]


def test_delta_e2000_sharma_pairs():
    # Sharma, Wu, Dalal (2005) reference pairs
    pairs = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
             ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
             ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
             ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492)]
    for a, b, want in pairs:
        assert float(cl.delta_e2000(np.array(a), np.array(b))) == pytest.approx(want, abs=1e-3)


def test_hex_lab_and_ral():
    assert cl.norm_hex("d2691e") == "#D2691E" and cl.norm_hex("#abc") == "#AABBCC"
    with pytest.raises(ValueError):
        cl.norm_hex("zzz")
    assert cl.hex_to_lab("#FFFFFF")[0] == pytest.approx(100, abs=0.1)
    pal = cl.ral_palette()
    assert len(pal.hexes) > 200
    exact = cl.nearest_ral(pal.hexes[0])
    assert exact["delta_e"] == pytest.approx(0, abs=1e-6) and exact["code"].startswith("RAL ")
    assert cl.nearest_ral("#FF0000")["code"].startswith("RAL 3")


def test_names_and_descriptor():
    assert cl.english_name("#000000").lower() in {"black", "very dark", "off black"} or "black" in cl.english_name("#000000").lower()
    assert cl.canonical_tr("#222222") == "siyah"
    d = cl.descriptor("#D2691E", "ipek")
    assert d["finish"] == "silk" and "silk" in d["text_en"] and "ipek" in d["text_tr"] and "RAL" in d["text_en"]
    assert cl.descriptor("#D2691E")["finish"] == "matte"
    for tr, en in [("mat", "matte"), ("parlak", "glossy"), ("ipek", "silk"), ("ahşap", "wood"), ("mermer", "marble"), ("simli", "sparkle")]:
        assert cl.norm_finish(tr) == en == cl.norm_finish(en)
    with pytest.raises(ValueError):
        cl.norm_finish("kadife")


def test_finish_in_job_json_and_render(fonts_dir, tmp_path):
    j = Job.from_dict(dict(mode="flat", text="Portalin", width_cm=20, color_style="two_tone",
                           colors=["siyah", "beyaz"], finishes={"beyaz": "ipek"}))
    res = run_job(j, tmp_path, fonts_dir)
    data = json.loads((res.out_dir / "job.json").read_text(encoding="utf-8"))
    fin = {c["hex"]: c["finish"] for c in data["colors"]}
    assert fin["#F5F5F5"] == "silk" and fin["#222222"] == "matte"
    assert all("ral" in c and "name_en" in c for c in data["colors"])
    with pytest.raises(ValueError):
        Job.from_dict(dict(mode="flat", text="A", width_cm=10, finishes={"beyaz": "kadife"}))


def test_tools_direct(fonts_dir, tmp_path):
    t = tools.color_info("#D2691E")
    assert "#D2691E" in t and "RAL" in t and "dE2000" in t
    out = tools.make_model({"mode": "letters", "text": "AB", "letter_height_cm": 10, "depth_mm": 15,
                            "face_color": "beyaz", "letter_colors": ["siyah"], "finishes": {"beyaz": "parlak"}}, str(tmp_path))
    assert Path(out["job_dir"]).is_dir() and any(f.endswith(".3mf") for f in out["files"])
    s = tools.job_summary(out["job_dir"])
    assert "Text: AB" in s and "3D letters" in s and "finish glossy" in s and "RAL" in s and "cm wide" in s and "render_front.png" in s
    paths = tools.save_prompt(out["job_dir"], "tr metin", "en text")
    assert (Path(out["job_dir"]) / "prompt_ai_tr.txt").read_text(encoding="utf-8").strip() == "tr metin"
    assert "prompt_ai_en.txt" in paths
    with pytest.raises(FileNotFoundError):
        tools.job_summary(str(tmp_path / "nope"))


