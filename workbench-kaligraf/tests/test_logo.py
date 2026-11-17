import math

import cv2
import numpy as np
import pytest

from kaligraf.geometry import is_part_valid, make_logo_flat
from kaligraf.logo2d import load_logo

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">
<rect width="200" height="100" fill="#ffffff"/>
<g transform="translate(10,10)">
  <rect x="0" y="0" width="100" height="80" fill="#ff0000"/>
  <circle cx="50" cy="40" r="25" fill="#0000ff"/>
</g>
<path d="M120 20 L180 20 L180 80 L120 80 Z M135 35 L165 35 L165 65 L135 65 Z" fill="#00aa00" fill-rule="evenodd"/>
<path d="M0 0 L5 5" stroke="#000" fill="none"/>
</svg>"""


def _by_color(logo):
    return {r.color: r.geometry for r in logo.regions}


@pytest.fixture()
def svg_file(tmp_path):
    p = tmp_path / "logo.svg"
    p.write_text(SVG)
    return p


def test_svg_regions_colors_and_scale(svg_file):
    logo = load_logo(svg_file, 300)
    assert logo.source == "svg"
    assert logo.width_mm == pytest.approx(300, abs=1e-6)
    cols = _by_color(logo)
    assert set(cols) == {"#FF0000", "#0000FF", "#00AA00"}
    k = (300 / 170) ** 2  # content is 170 units wide
    assert cols["#0000FF"].area == pytest.approx(math.pi * 25**2 * k, rel=0.01)
    assert cols["#FF0000"].area == pytest.approx((100 * 80 - math.pi * 25**2) * k, rel=0.01)  # blue covers red
    assert cols["#00AA00"].area == pytest.approx((60 * 60 - 30 * 30) * k, rel=1e-3)  # even-odd hole
    assert any("stroke-only" in w for w in logo.warnings)
    assert any("background" in w for w in logo.warnings)
    # y is up: the bbox starts at the origin
    b = np.array([g.bounds for g in cols.values()])
    assert b[:, 0].min() == pytest.approx(0, abs=1e-6) and b[:, 1].min() == pytest.approx(0, abs=1e-6)


def test_svg_many_colors_merged_to_four(tmp_path):
    rects = "".join(
        f'<rect x="{i * 20}" y="0" width="18" height="50" fill="rgb({i * 40},{255 - i * 40},{(i * 90) % 256})"/>'
        for i in range(6)
    )
    p = tmp_path / "m.svg"
    p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 50">{rects}</svg>')
    logo = load_logo(p, 120, n_colors=4)
    assert len(logo.regions) <= 4
    assert any("merged to 4" in w for w in logo.warnings)


def _raster(tmp_path, name="a.png", bg=(255, 255, 255), size=(900, 1200), noise=False):
    img = np.full((size[0], size[1], 3), bg, np.uint8)
    cv2.circle(img, (400, 450), 300, (30, 30, 200), -1)  # red (BGR)
    cv2.rectangle(img, (700, 200), (1100, 700), (200, 60, 30), -1)  # blue
    cv2.circle(img, (400, 450), 120, (0, 0, 0), -1)  # black disc inside red
    cv2.circle(img, (1150, 80), 1, (0, 0, 0), -1)  # speck (dust)
    if noise:
        img = np.clip(img.astype(int) + np.random.default_rng(1).normal(0, 6, img.shape), 0, 255).astype(np.uint8)
    p = tmp_path / name
    cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 80] if name.endswith("jpg") else [])
    return p


def test_raster_png_quantize_and_trace(tmp_path):
    logo = load_logo(_raster(tmp_path), 200, n_colors=4)
    assert logo.source == "raster" and logo.source_px == (1200, 900)
    assert logo.width_mm == pytest.approx(200, abs=0.05)  # speck removed => bbox = circle..rect
    assert len(logo.regions) == 3  # red, blue, black; white background removed
    mm = 200 / 1000.0
    by_area = sorted(logo.regions, key=lambda r: r.geometry.area)
    areas = [r.geometry.area for r in by_area]
    black, blue, red = areas
    assert black == pytest.approx(math.pi * 120**2 * mm**2, rel=0.05)
    assert blue == pytest.approx(400 * 500 * mm**2, rel=0.04)
    assert red == pytest.approx((math.pi * 300**2 - math.pi * 120**2) * mm**2, rel=0.05)
    assert not any("Low resolution" in w for w in logo.warnings)
    assert all(r.geometry.is_valid for r in logo.regions)


def test_raster_jpg_noise_and_colored_background(tmp_path):
    logo = load_logo(_raster(tmp_path, "b.jpg", bg=(40, 200, 220), noise=True), 200, n_colors=3)
    assert 3 <= len(logo.regions) <= 3
    assert logo.width_mm == pytest.approx(200, abs=0.1)
    # jpeg artefacts must not create many tiny regions
    assert sum(len(getattr(r.geometry, "geoms", [r.geometry])) for r in logo.regions) <= 8


def test_raster_transparent_png(tmp_path):
    rgba = np.zeros((900, 1200, 4), np.uint8)
    cv2.circle(rgba, (600, 450), 300, (30, 30, 200, 255), -1)
    p = tmp_path / "t.png"
    cv2.imwrite(str(p), rgba)
    logo = load_logo(p, 100)
    assert len(logo.regions) == 1
    assert logo.height_mm == pytest.approx(100, rel=0.01)  # circle: height == width
    assert logo.regions[0].geometry.area == pytest.approx(math.pi * 50**2, rel=0.02)


def test_raster_low_resolution_and_tiny_region_warnings(tmp_path):
    img = np.full((300, 400, 3), 255, np.uint8)
    cv2.rectangle(img, (50, 50), (350, 250), (200, 60, 30), -1)
    cv2.rectangle(img, (100, 100), (104, 104 + 60), (0, 0, 0), -1)  # thin 4 px line
    p = tmp_path / "low.png"
    cv2.imwrite(str(p), img)
    logo = load_logo(p, 40)  # 40 mm wide: that line becomes ~0.5 mm
    assert any("Low resolution" in w for w in logo.warnings)


def test_n_colors_clamped_and_validation(tmp_path):
    logo = load_logo(_raster(tmp_path), 100, n_colors=9)
    assert any("reduced from 9 to 4" in w for w in logo.warnings)
    with pytest.raises(ValueError):
        load_logo(tmp_path / "x.gif", 100)
    with pytest.raises(ValueError):
        load_logo(tmp_path / "missing.png", 100)


def test_logo_to_model(svg_file, tmp_path):
    from kaligraf.geometry import export_stl
    import trimesh

    m = make_logo_flat(svg_file, 200, thickness=5)
    assert len(m.parts) == 3
    assert sorted(p.extruder for p in m.parts) == [1, 2, 3]
    for p in m.parts:
        assert is_part_valid(p.mesh)
        assert p.mesh.extents[2] == pytest.approx(5)
    allv = np.vstack([p.mesh.vertices for p in m.parts])
    assert allv[:, 0].max() - allv[:, 0].min() == pytest.approx(200, abs=0.5)
    for path in export_stl(m, tmp_path / "o"):
        assert is_part_valid(trimesh.load(path))


def test_logo_raster_model_with_mounting(tmp_path):
    m = make_logo_flat(_raster(tmp_path), 200, thickness=10, mounting=["keyhole", "holes", "connector_bar"])
    assert len(m.parts) == 3 and all(is_part_valid(p.mesh_wall) for p in m.parts)
    assert m.meta["mounting"]["keyholes"] and len(m.meta["mounting"]["holes"]) == 2
    assert any("not applicable to logos" in w for w in m.warnings)


def test_logo_oversize_limit(svg_file):
    m = make_logo_flat(svg_file, 400, oversize_policy="limit")
    assert all(max(p.mesh.extents[:2]) <= 250 for p in m.parts)
    assert "requested width 40.0 cm" in m.warnings[0]
