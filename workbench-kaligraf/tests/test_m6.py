import json
import re

import numpy as np
import pytest
from PIL import Image

from kaligraf.job import Job, build_model, run_job
from kaligraf.prompt import build_prompts, color_names, default_user_fields, load_template
from kaligraf.render import render_dims, render_model
from kaligraf.template_pdf import template_geometry, write_template_pdf


def _flat(**kw):
    d = dict(mode="flat", text="Portalin", font="Montserrat", width_cm=40, color_style="two_tone", colors=["siyah", "beyaz"])
    d.update(kw)
    return Job.from_dict(d)


def _letters(**kw):
    d = dict(mode="letters", text="ŞÜK", font="Bebas Neue", letter_height_cm=10, depth_mm=15,
             face_color="beyaz", letter_colors=["siyah"])
    d.update(kw)
    return Job.from_dict(d)


def test_render_transparent_and_true_colours(fonts_dir):
    m = build_model(_letters(), fonts_dir)
    img = np.asarray(render_model(m, "front", 800))
    assert img[0, 0, 3] == 0 and img[-1, -1, 3] == 0  # transparent background
    solid = img[img[..., 3] == 255][:, :3]
    assert len(solid) > 1000
    # front faces are the white face colour #F5F5F5, lit close to true colour
    white = solid[(solid > 200).all(axis=1)]
    assert len(white) > 0.5 * len(solid) and white.mean() > 225
    m34 = np.asarray(render_model(m, "34", 800))
    dark = m34[(m34[..., 3] == 255) & (m34[..., :3] < 90).all(axis=2)]
    assert len(dark) > 100  # the black letter sides show in the 3/4 view


def test_render_matches_footprint_area(fonts_dir):
    m = build_model(_flat(color_style="single", colors=["siyah"]), fonts_dir)
    img = np.asarray(render_model(m, "front", 1600, margin=0.0))
    covered = (img[..., 3] > 127).sum()
    lo = np.min([p.mesh_wall.bounds[0] for p in m.parts], axis=0)
    hi = np.max([p.mesh_wall.bounds[1] for p in m.parts], axis=0)
    px_mm = img.shape[1] / (hi[0] - lo[0])
    from kaligraf.geometry import mesh_footprint

    area = sum(mesh_footprint(p.mesh_wall).area for p in m.parts[:1])
    assert covered / px_mm**2 == pytest.approx(area, rel=0.03)


def test_dims_image(fonts_dir, tmp_path):
    m = build_model(_flat(), fonts_dir)
    out = render_dims(m, tmp_path / "dims.png", {"width_mm": 400, "height_mm": 80, "depth_mm": 5})
    im = Image.open(out)
    assert im.width > 500 and im.height > 100


def test_template_marks_and_tiles(fonts_dir, tmp_path):
    job = _letters(letter_height_cm=20, text="ŞÜKRÜ", mounting=["keyhole", "connector_bar"], depth_mm=30)
    res = run_job(job, tmp_path, extras=False)
    marks = template_geometry(res.model, res.split.cuts)
    n_detached = sum(len(p.meta.get("detached_pieces", [])) for p in res.model.parts)
    assert len(marks["keyholes"]) == len(res.data["mounting"]["keyholes"]) > 0
    assert len(marks["detached"]) == n_detached > 0  # accents / cedilla
    assert marks["rail"] is not None
    info = write_template_pdf(res.model, tmp_path / "t.pdf", res.split.cuts, "x")
    W, H = marks["size"]
    assert info["tiles"][0] * info["tiles"][1] >= 2 and info["pages"] == info["tiles"][0] * info["tiles"][1] + 1
    assert (tmp_path / "t.pdf").read_bytes().startswith(b"%PDF")
    pages = re.findall(rb"/Type\s*/Page[^s]", (tmp_path / "t.pdf").read_bytes())
    assert len(pages) == info["pages"]


def test_template_marks_split_cuts_and_holes(fonts_dir, tmp_path):
    job = _flat(width_cm=40, mounting=["holes"])
    res = run_job(job, tmp_path, extras=False)
    marks = template_geometry(res.model, res.split.cuts)
    assert res.split.cuts and marks["cuts"]  # 400 mm sign is cut for the 250 mm bed
    assert len(marks["holes"]) == 2


def test_prompt_auto_and_user_fields(fonts_dir, tmp_path):
    job = _letters(text="ŞÜK", letter_height_cm=20)
    res = run_job(job, tmp_path, extras=False)
    p = build_prompts(job, res.data, res.model)
    ov = res.data["overall_mm"]
    for lang in ("tr", "en"):
        assert "ŞÜK" in p[lang] and "Bebas Neue" in p[lang] and f"{ov['width_mm'] / 10:.1f}" in p[lang]
    assert "mat PLA" in p["tr"] and "matte PLA" in p["en"]
    assert "beyaz" in p["tr"] and "siyah" in p["tr"] and "white" in p["en"] and "black" in p["en"]
    q = build_prompts(job, res.data, res.model, {"scene": "kafe", "wall": "tugla", "extra": "bir fincan kahve"})
    assert "kafe" in q["tr"] and "café" in q["en"] and "tuğla" in q["tr"] and "brick" in q["en"]
    assert "bir fincan kahve" in q["tr"] and "bir fincan kahve" in q["en"]
    d = default_user_fields()
    assert set(d) == {"scene", "wall", "lighting", "camera", "scale_ref", "extra"}
    assert "salon" in load_template()["user_fields"]["scene"]["choices"]


def test_color_names():
    assert color_names("#222222") == ("siyah", "black")
    assert color_names("#F0F0F0") == ("beyaz", "white")


def test_run_job_writes_all_outputs(fonts_dir, tmp_path):
    res = run_job(_flat(mounting=["holes"]), tmp_path)
    for k in ("render_front", "render_34", "dims", "template", "prompt_tr", "prompt_en"):
        assert res.files[k].exists() and res.files[k].stat().st_size > 500, k
    data = json.loads((res.out_dir / "job.json").read_text(encoding="utf-8"))
    assert data["template"]["pages"] >= 2 and set(data["prompts"]) == {"tr", "en"}
    im = Image.open(res.files["render_front"])
    assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0
