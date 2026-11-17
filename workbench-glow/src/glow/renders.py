"""Renders: unlit (daylight) and lit (emissive glow in a dark room) views, plus the dimensions image."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from workbench_core.geometry import Model
from workbench_core.render import render_dims

from . import zrender
from .parts import norm_color, solid, to_mesh

UNLIT_BG = (233, 236, 240, 255)
DARK_BG = (9, 11, 15, 255)
DARK_FACTOR = 0.30  # unlit surfaces in the dark room keep this share of their colour
VIEWS = {"front": (0.0, 0.0), "34": (-28.0, 14.0)}


def _rgb(c: str) -> np.ndarray:
    return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], dtype=float) / 255.0


def _hex(v: np.ndarray) -> str:
    v = np.clip(v, 0, 1)
    return "#" + "".join(f"{int(round(x * 255)):02X}" for x in v)


def glow_color(region_color: str, led_color: str) -> str:
    """Colour of the light leaving a region: LED colour filtered by the filament colour, normalised to full brightness."""
    g = _rgb(norm_color(region_color)) * _rgb(norm_color(led_color))
    m = g.max()
    return _hex(g / m) if m > 1e-6 else "#000000"


def _light_items(box) -> list[tuple]:
    """Emissive meshes of the light-passing face layers (pushed 0.05 mm proud of the face to win the depth test)."""
    D = box.model.depth_mm
    out = []
    for l in box.layers:
        if l.role != "light":
            continue
        m = to_mesh(solid(l.geometry, D - l.z1, D - l.z0 + 0.05))
        out.append((m, glow_color(l.color, box.spec.led_color), 1.0))
    return out


def _visible(box) -> list:
    """Parts as (mesh, colour); the back cover loses its inside faces (rails, cradle: hidden behind the body)."""
    tb = box.model.meta["tb_mm"]
    out = []
    for p in box.model.parts:
        m = p.mesh_wall
        if p.group == "back":
            keep = m.triangles_center[:, 2] < tb - 0.05
            m = m.submesh([np.nonzero(keep)[0]], append=True) if keep.any() else m
        out.append((m, p.color))
    return out


def render_unlit(box, view: str = "34", width_px: int = 1200) -> Image.Image:
    az, el = VIEWS[view]
    items = _visible(box)
    return zrender.render_scene(items, azim=az, elev=el, width_px=width_px, bg=UNLIT_BG)


def render_lit(box, view: str = "34", width_px: int = 1200) -> Image.Image:
    """Dark-room render: housing barely visible, light regions glow in the LED colour (with bloom)."""
    az, el = VIEWS[view]
    light = _light_items(box)
    dark = [(m, _hex(_rgb(c) * DARK_FACTOR)) for m, c in _visible(box)]
    base = zrender.render_scene(dark + light, azim=az, elev=el, width_px=width_px, bg=DARK_BG).convert("RGB")
    black = [(m, "#000000", 1.0) for m, _ in _visible(box)]
    emit = zrender.render_scene(black + light, azim=az, elev=el, width_px=width_px, bg=(0, 0, 0, 255)).convert("RGB")
    b = np.asarray(base, dtype=float) / 255.0
    e = np.asarray(emit, dtype=float) / 255.0
    w = base.size[0]
    bloom = np.zeros_like(e)
    for sigma, gain in ((0.004, 0.55), (0.014, 0.45), (0.04, 0.40)):
        blur = np.asarray(emit.filter(ImageFilter.GaussianBlur(sigma * w)), dtype=float) / 255.0
        bloom += gain * blur
    out = 1 - (1 - b) * (1 - np.clip(bloom, 0, 1))
    out = np.maximum(out, e)  # the emitting surface itself stays at full colour
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def render_dims_png(box, out_path: str | Path) -> Path:
    model = box.model
    body = [p for p in model.parts if p.group != "stand"]
    m2 = Model(model.mode, body, model.width_mm, model.height_mm, model.depth_mm, [], {})
    has_stand = len(body) != len(model.parts)
    lo = min(float(p.mesh_wall.bounds[0][1]) for p in model.parts)
    hi = max(float(p.mesh_wall.bounds[1][1]) for p in model.parts)
    title = f"Workbench - Glow  {model.meta['design']}  ({model.width_mm / 10:.1f} x {model.height_mm / 10:.1f} x {model.depth_mm / 10:.1f} cm)"
    if has_stand:
        title += f" — ayakla toplam yükseklik {(hi - lo) / 10:.1f} cm"
    overall = {"width_mm": model.width_mm, "height_mm": model.height_mm, "depth_mm": model.depth_mm}
    return render_dims(m2, out_path, overall=overall, title=title)


def write_renders(box, out: Path) -> dict[str, Path]:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for view in ("34", "front"):
        suffix = "" if view == "34" else "_front"
        p = out / f"render_unlit{suffix}.png"
        render_unlit(box, view).save(p)
        files[f"unlit{suffix}"] = p
        p = out / f"render_lit{suffix}.png"
        render_lit(box, view).save(p)
        files[f"lit{suffix}"] = p
    files["dims"] = render_dims_png(box, out / "dims.png")
    return files
