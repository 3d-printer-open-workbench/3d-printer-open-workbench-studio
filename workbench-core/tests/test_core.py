import importlib
from pathlib import Path

import pytest

import workbench_core
from workbench_core import colorlib, estimate, export3mf, fonts, prompt, text2d

ROOT = Path(workbench_core.__file__).resolve().parents[2]
MODULES = ["fonts", "fontinfo", "text2d", "geometry", "logo2d", "split", "export3mf", "estimate", "render", "template_pdf",
           "colorlib", "mounting", "prompt"]


@pytest.mark.parametrize("name", MODULES)
def test_modules_import(name):
    importlib.import_module(f"workbench_core.{name}")


def test_data_at_repo_root():
    assert fonts.REPO_ROOT == ROOT
    assert export3mf.TEMPLATE.is_file() and colorlib.RAL_FILE.is_file() and estimate.DEFAULT_PRINTER_FILE.is_file()
    assert (ROOT / "fonts" / "fonts.yaml").is_file()


def test_text_from_bundled_font():
    f = fonts.resolve_font("Montserrat")
    res = text2d.build_text("Portalin", f, "flat", width_mm=100)
    assert res.geometry.bounds[2] == pytest.approx(100, abs=0.01)


def test_prompt_helpers(tmp_path):
    tpl = {"user_fields": {"scene": {"label": "Mekan", "default": "salon",
                                     "choices": {"salon": {"tr": "salon", "en": "a living room"}}}}}
    assert prompt.default_user_fields(tpl) == {"scene": "salon"}
    assert prompt.user_text(tpl, {}, "scene", "en") == "a living room"
    assert prompt.user_text(tpl, {"scene": "mutfak"}, "scene", "tr") == "mutfak"  # free text kept
    assert prompt.join(["a", "b", "c"], "tr") == "a, b ve c" and prompt.join(["a", "b"], "en") == "a and b"
    tr, en = prompt.color_names("#FFFFFF")
    assert tr and en
    out = prompt.write_prompts({"tr": "x", "en": "y"}, tmp_path)
    assert out["tr"].name == "prompt_tr.txt" and out["en"].read_text() == "y\n"


def test_raster_coverage_and_depth():
    import numpy as np

    from workbench_core.render import _raster

    # a 40 x 40 px square (two triangles) in front of a 60 x 60 px one: exact coverage, nearest wins
    sq = lambda x0, y0, s: [[[x0, y0], [x0 + s, y0], [x0 + s, y0 + s]], [[x0, y0], [x0 + s, y0 + s], [x0, y0 + s]]]
    tris = np.array(sq(10, 10, 60) + sq(20, 20, 40), dtype=float)
    z = np.array([[5.0] * 3, [5.0] * 3, [1.0] * 3, [1.0] * 3])
    cols = np.array([[1, 0, 0], [1, 0, 0], [0, 0, 1], [0, 0, 1]], dtype=np.float32)
    rgb, depth, _ = _raster(tris, z, cols, 100, 100)
    covered = np.isfinite(depth)
    assert covered.sum() == 60 * 60
    blue = (rgb[..., 2] > 0.5) & covered
    assert blue.sum() == 40 * 40 and blue[20:60, 20:60].all()
    # a long thin sliver costs its area, not its bounding box, and is still drawn
    thin = np.array([[[0, 0], [99, 98], [99, 99.5]]], dtype=float)
    _, d2, _ = _raster(thin, np.zeros((1, 3)), np.ones((1, 3), np.float32), 100, 100)
    assert 0 < np.isfinite(d2).sum() < 200


def test_render_meshes_and_glb(tmp_path):
    import numpy as np
    import trimesh

    from workbench_core.render import Z_UP, render_meshes, view_rotation, write_glb

    box = trimesh.creation.box((20, 10, 5))
    img = render_meshes([(box, "#E0453A"), (box.copy().apply_translation([0, 0, 5]), "#1F6FB2", {"gloss": 0.5})],
                        view_rotation(-30, 30) @ Z_UP, width_px=200)
    a = np.asarray(img)
    assert img.mode == "RGBA" and a[..., 3].max() == 255 and a[0, 0, 3] == 0  # transparent around the model
    seen = a[a[..., 3] == 255][:, :3]
    assert (seen[:, 0] > 150).any() and (seen[:, 2] > 120).any()  # both colours visible
    on_grey = render_meshes([(box, "#111111")], np.eye(3), width_px=100, bg=(238, 240, 243))
    assert on_grey.mode == "RGB" and on_grey.getpixel((0, 0)) == (238, 240, 243)
    f = write_glb([(box, "#C8664A", "kutu")], tmp_path / "p.glb", z_up=True)
    sc = trimesh.load(f)
    assert list(sc.geometry) == ["kutu"]
    mat = next(iter(sc.geometry.values())).visual.material
    assert np.allclose(np.asarray(mat.baseColorFactor)[:3] / (255 if np.asarray(mat.baseColorFactor).max() > 1 else 1),
                       [0xC8 / 255, 0x66 / 255, 0x4A / 255], atol=0.01)
