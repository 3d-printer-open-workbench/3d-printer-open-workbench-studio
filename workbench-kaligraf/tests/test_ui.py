import json

import pytest

from kaligraf import form as ui

FLAT = dict(mode="Düz tabela", text="Portalin", font="Montserrat", width_cm=40, thickness_mm=5, color_style="two_tone",
            colors=["siyah", "beyaz"], mounting=["holes"], oversize_policy="split")
LETTERS = dict(mode="3D harfler", text="ŞÜK", font="Bebas Neue", letter_height_cm=10, depth_mm=15, face_color="beyaz",
               letter_colors=["siyah"], mounting=["tape"], oversize_policy="limit")


def test_font_choices_numbered_like_catalog(fonts_dir):
    ch = ui.font_choices(fonts_dir)
    assert len(ch) == 36 and ch[0][0].startswith("1. Tinos") and ch[19][0].startswith("20. Syncopate")


def test_font_info_shows_min_sizes_and_warns(fonts_dir):
    from kaligraf.fontinfo import load_metrics

    m = load_metrics(fonts_dir)["abril-fatface"]
    md = ui.font_info_md("Abril Fatface", "flat", 20, fonts_dir, "Portalin")
    assert f"{m['min_cap_flat_cm']:g} cm" in md and "⚠️" in md and "büyük harf yüksekliği" in md
    assert "⚠️" not in ui.font_info_md("Abril Fatface", "flat", 400, fonts_dir, "Portalin")
    assert "⚠️" in ui.font_info_md("Montserrat", "letters", 1, fonts_dir)
    # a shorter text at the same width has taller letters, so it needs less width to pass
    short = ui.font_info_md("Montserrat", "flat", 15, fonts_dir, "AB")
    long = ui.font_info_md("Montserrat", "flat", 15, fonts_dir, "Portalin Your Brand Wall Sign")
    assert "⚠️" not in short and "⚠️" in long


def test_inputs_to_job_and_validation():
    j = ui.inputs_to_job(FLAT)
    assert j.mode == "flat" and j.colors == ["siyah", "beyaz"] and j.mounting == ["holes"]
    j = ui.inputs_to_job({**LETTERS, "infill": 12})
    assert j.mode == "letters" and j.oversize_policy == "limit" and j.infill_percent == 12
    with pytest.raises(ValueError):
        ui.inputs_to_job({**LETTERS, "letter_height_cm": 1})


def test_generate_returns_everything(fonts_dir, tmp_path):
    out = ui.generate(LETTERS, tmp_path, None, fonts_dir)
    assert out["glb"].exists() and out["zip"].exists() and len(out["files"]) == 10
    assert "Filament" in out["estimate"] and "Bölmeden basılabilecek" in out["estimate"]
    assert "ŞÜK" in out["prompt_tr"] and "ŞÜK" in out["prompt_en"]
    import trimesh

    scene = trimesh.load(str(out["glb"]))
    assert len(scene.geometry) >= 2


def test_prompt_update_from_saved_job(fonts_dir, tmp_path):
    out = ui.generate(FLAT, tmp_path, None, fonts_dir)
    data = json.loads((out["result"].out_dir / "job.json").read_text(encoding="utf-8"))
    job = ui.Job.from_dict(data["inputs"])
    p = ui._prompts_from_data(job, data, {"scene": "kafe", "lighting": "sicak"})
    assert "kafe" in p["tr"] and "warm evening" in p["en"] and "Portalin" in p["en"]


def test_open_folder_missing(tmp_path):
    assert "Önce" in ui.open_folder(tmp_path / "nope")


def test_color_picker_helpers(tmp_path):
    import numpy as np

    assert "siyah" in ui.color_choices()
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    img[...] = (210, 105, 30)
    img[20, 20] = (255, 255, 255)  # one bright pixel: the 7x7 median ignores it
    img[5, 5] = (0, 0, 255)
    assert ui.sample_color(img, 20, 20) == "#D2691E"
    assert ui.sample_color(img, 999, -3) == "#D2691E"  # clamped to the image
    md = ui.capture_report("#D2691E")
    assert "#D2691E" in md and "RAL" in md and "ΔE2000" in md and "background:#D2691E" in md
    assert "RAL" in ui.colors_info_md(["siyah", "#D2691E"])
    assert "geçersiz" in ui.colors_info_md(["nope"])


def test_inputs_to_job_finishes():
    j = ui.inputs_to_job(dict(mode="flat", text="A", width_cm=20, color_style="two_tone", colors=["siyah", "beyaz"],
                              finish1="mat", finish2="ipek"))
    assert j.finishes == {"beyaz": "ipek"}
    j = ui.inputs_to_job(dict(mode="3D harfler", text="A", letter_height_cm=10, face_color="beyaz", letter_colors=["siyah"],
                              finish_face="parlak", finish_body="mat"))
    assert j.finishes == {"beyaz": "parlak"}


def test_letters_three_axis_mm():
    """UI sliders: letter width (X), height (Y) and depth (Z) in mm, each up to 250 mm."""
    j = ui.inputs_to_job({**LETTERS, "letter_height_mm": 250, "letter_width_mm": 180, "depth_mm": 250})
    assert j.letter_height_cm == 25 and j.letter_width_mm == 180 and j.depth_mm == 250
    with pytest.raises(ValueError):
        ui.inputs_to_job({**LETTERS, "depth_mm": 260})
    with pytest.raises(ValueError):
        ui.inputs_to_job({**LETTERS, "letter_width_mm": 300})
