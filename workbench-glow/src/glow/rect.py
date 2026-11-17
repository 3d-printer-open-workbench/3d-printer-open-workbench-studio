"""Design ``rect``: rectangular LED lightbox (name-light style). See lightbox.py for the construction."""
from __future__ import annotations

import math
from dataclasses import dataclass

from manifold3d import CrossSection, Manifold
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from workbench_core.fonts import resolve_font
from workbench_core.geometry import BED_MM

from .face import fit_logo, fit_text
from .hardware import Hardware, default_hardware
from .ledpath import serpentine
from .lightbox import (CLEAR, LIP_W, WALL, PLACEHOLDER, BoxSpec, LightBox, Plan, assemble, keyhole_cuts, rect_pocket, rrect)
from .parts import norm_color, solid

FOOT_H = 4.0
FOOT_W = 24.0
MIN_FRAME = WALL + CLEAR + LIP_W + 2.0


@dataclass
class RectSpec(BoxSpec):
    width_mm: float = 200.0
    height_mm: float | None = None  # None: from the content
    corner_radius_mm: float = 8.0
    frame_mm: float = 8.0
    tilt_deg: float = 0.0
    mount: str = "desk"  # desk | wall
    split_ok: bool = False  # widths above the bed are split into pieces (G5)

    def validate(self) -> None:
        self.validate_common()
        if self.width_mm > BED_MM and not self.split_ok:
            raise ValueError(f"width {self.width_mm / 10:g} cm exceeds the 25 cm bed")
        if self.width_mm < 100:
            raise ValueError("width must be at least 10 cm")
        if self.frame_mm < MIN_FRAME:
            raise ValueError(f"frame width must be >= {MIN_FRAME:.1f} mm (wall + lip)")
        if self.mount not in ("desk", "wall"):
            raise ValueError("mount must be desk or wall")
        if not (0 <= self.tilt_deg <= 15):
            raise ValueError("tilt_deg must be 0-15")
        if self.mount == "wall" and self.tilt_deg:
            raise ValueError("tilt applies to desk mode only")


def _foot(xc: float, w: float, z0: float, z1: float, y_top: float, y_bot0: float, tilt_deg: float) -> Manifold:
    """Foot under the box bottom; its sole is inclined so the box leans back by ``tilt_deg``."""
    t = math.tan(math.radians(tilt_deg))
    yb = lambda z: y_bot0 - t * (z - z0)  # noqa: E731  (front gets longer legs -> face tilts up)
    pts = [(-z0, y_top), (-z1, y_top), (-z1, yb(z1)), (-z0, yb(z0))]
    prism = Manifold.extrude(CrossSection([pts]), w)
    prism = prism.rotate((0.0, 90.0, 0.0))  # (px, py, pz) -> (pz, py, -px)
    return prism.translate((xc - w / 2, 0.0, 0.0))


def plan_rect(spec: RectSpec, hw: Hardware | None = None, allow_wide: bool = False) -> Plan:
    hw = hw or default_hardware()
    if not allow_wide:
        spec.validate()
    else:
        spec.validate_common()
    led = hw.led(spec.led)
    min_gap = hw.min_gap(spec.diffuser, spec.led)
    warnings: list[str] = []
    W = spec.width_mm
    fw = spec.frame_mm
    win_w = W - 2 * fw
    feats: list[tuple[str, BaseGeometry]] = []
    box_h = None if spec.height_mm is None else spec.height_mm - 2 * fw - 2 * spec.margin_mm
    if spec.logo:
        content, w1 = fit_logo(spec.logo, win_w - 2 * spec.margin_mm, box_h, n_colors=spec.logo_colors)
        feats += content
        bounds = unary_union([g for _, g in content]).bounds
    else:
        g, w1 = fit_text(spec.text, resolve_font(spec.font), win_w - 2 * spec.margin_mm, box_h)
        feats.append((PLACEHOLDER, g))  # colour assigned by lit mode
        bounds = g.bounds
    warnings += w1
    content_h = bounds[3] - bounds[1]
    win_h = content_h + 2 * spec.margin_mm if spec.height_mm is None else spec.height_mm - 2 * fw
    win_h = max(win_h, 30.0)
    H = win_h + 2 * fw
    r = min(spec.corner_radius_mm, H / 2 - 1, W / 2 - 1)
    outline = rrect(W, H, r)
    window = rrect(win_w, win_h, max(r - fw, 1.0))

    def boss_fn(geo, avoid):
        iw = geo.inner.bounds[2] - geo.inner.bounds[0]
        ih = geo.inner.bounds[3] - geo.inner.bounds[1]
        return [(sx * (iw / 2 - 5.0), sy * (ih / 2 - 5.0)) for sx in (-1, 1) for sy in (-1, 1)]

    def path_fn(geo, allowed, led_, pitch_target, margin, gap):
        return serpentine(allowed, led_, pitch_target_mm=pitch_target, max_pitch_mm=max(1.5 * gap, pitch_target))

    def body_add(ctx):
        if spec.mount != "desk":
            return []
        x_hi = W / 2 - r - 6.0
        return [_foot(s * (x_hi - FOOT_W / 2), FOOT_W, ctx.z0, ctx.z1, -H / 2 + 1.2, -H / 2 - FOOT_H, spec.tilt_deg) for s in (-1, 1)]

    def back_cut(ctx):
        if spec.mount != "wall":
            return []
        kx = min(W / 4, 60.0)
        ye = H / 2 - 3.0 - 4.75 - 10.0
        return keyhole_cuts([(-kx, ye), (kx, ye)])

    plan = Plan("rect", spec, outline, window, feats, W, H, boss_fn=boss_fn, pocket_fn=rect_pocket, path_fn=path_fn,
                body_add_fn=body_add, back_cut_fn=back_cut, warnings=warnings,
                meta={"tilt_deg": spec.tilt_deg, "frame_mm": fw, "window_mm": [win_w, win_h],
                      "keyholes": ([[-min(W / 4, 60.0), H / 2 - 17.75], [min(W / 4, 60.0), H / 2 - 17.75]] if spec.mount == "wall" else [])})
    return plan


def build_rect(spec: RectSpec, hw: Hardware | None = None) -> LightBox:
    hw = hw or default_hardware()
    plan = plan_rect(spec, hw)
    return assemble(plan, hw)
