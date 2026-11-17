"""Design ``round``: circular LED lightbox with an opaque rim, concentric LED rings and a slot-in stand (or keyholes)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh
from manifold3d import Manifold
from shapely import affinity
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from workbench_core.fonts import resolve_font
from workbench_core.geometry import Part

from .face import fit_logo, fit_text
from .hardware import Hardware, default_hardware
from .ledpath import concentric
from .lightbox import CLEAR, LIP_W, PLACEHOLDER, WALL, BoxSpec, LightBox, Plan, assemble, auto_pocket, keyhole_cuts
from .parts import norm_color, solid, to_mesh

STAND_MIN_FRAME = WALL + CLEAR + LIP_W + 2.0
STAND_TOP = 16.0  # stand top above the lowest point of the box
STAND_BELOW = 6.0
STAND_CLEAR = 0.3


@dataclass
class RoundSpec(BoxSpec):
    diameter_mm: float = 200.0
    depth_mm: float = 45.0
    rim_mm: float = 10.0
    mount: str = "stand"  # stand | wall
    split_ok: bool = False  # G5: diameters above the bed are split

    def validate(self) -> None:
        self.validate_common()
        if self.mount == "desk":
            self.mount = "stand"
        if self.mount not in ("stand", "wall"):
            raise ValueError("mount must be stand or wall")
        if self.diameter_mm < 120:
            raise ValueError("diameter must be at least 12 cm")
        if self.diameter_mm > 250 and not self.split_ok:
            raise ValueError(f"diameter {self.diameter_mm / 10:g} cm exceeds the 25 cm bed")
        if self.rim_mm < STAND_MIN_FRAME:
            raise ValueError(f"rim width must be >= {STAND_MIN_FRAME:.1f} mm (wall + lip)")


def fit_in_circle(geoms: list[tuple[str, BaseGeometry]], radius: float) -> list[tuple[str, BaseGeometry]]:
    """Scale content (about the origin) so its farthest point lies within ``radius``."""
    allg = unary_union([g for _, g in geoms])
    far = max(math.hypot(x, y) for p in getattr(allg, "geoms", [allg]) for x, y in p.exterior.coords)
    k = min(1.0, radius / far) if far > 0 else 1.0
    return [(c, affinity.scale(g, k, k, origin=(0, 0))) for c, g in geoms]


def stand_part(R: float, D: float, tb: float, cable_x: float | None) -> Part:
    """Slot-in stand: block with a circular groove (R + 0.3) over the box thickness, front/back walls hold the box."""
    ext = 35.0
    bw = max(55.0, 0.6 * R)
    y0, y1 = -R - STAND_BELOW, -R + STAND_TOP
    block = box(-bw, y0, bw, y1)
    z_lo, z_hi = -ext, D + ext
    base = solid(block, z_lo, z_hi)
    groove = solid(Point(0, 0).buffer(R + STAND_CLEAR, quad_segs=64), -STAND_CLEAR, D + STAND_CLEAR)
    m = base - groove
    if cable_x is not None:  # cable channel through the back wall of the stand
        notch = solid(box(cable_x - 6, y0 + 4, cable_x + 6, y1 + 1), z_lo - 1, -STAND_CLEAR - 0.01)
        m = m - notch
    part = Part("stand", "stand", to_mesh(m), "#1F4D3A", 1, group="stand")
    part.meta["print_rot"] = trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0])  # y -> z: base on the bed
    return part


def plan_round(spec: RoundSpec, hw: Hardware | None = None) -> Plan:
    hw = hw or default_hardware()
    spec.validate()
    min_gap = hw.min_gap(spec.diffuser, spec.led)
    R = spec.diameter_mm / 2
    Rw = R - spec.rim_mm
    warnings: list[str] = []
    outline = Point(0, 0).buffer(R, quad_segs=64)
    window = Point(0, 0).buffer(Rw, quad_segs=64)
    lim = Rw - spec.margin_mm
    if spec.logo:
        content, w1 = fit_logo(spec.logo, 2 * lim * 0.95, 2 * lim * 0.95, n_colors=spec.logo_colors)
        feats = content
    else:
        g, w1 = fit_text(spec.text, resolve_font(spec.font), 2 * lim * 0.95, None)
        feats = [(PLACEHOLDER, g)]
    warnings += w1
    feats = fit_in_circle(feats, lim)

    def boss_fn(geo, avoid):
        ri = R - geo.wall
        return [((ri - 5.5) * math.cos(math.radians(a)), (ri - 5.5) * math.sin(math.radians(a))) for a in (45, 135, 225, 315)]

    def pocket_fn(geo, boss_zone, ctrl):
        return auto_pocket(geo, boss_zone, ctrl)

    def path_fn(geo, allowed, led_, pitch_target, margin, gap):
        minx, miny, maxx, maxy = allowed.bounds
        r_outer = (maxx - minx) / 2
        return concentric(allowed, led_, r_outer=r_outer, pitch_target_mm=pitch_target)

    def back_cut(ctx):
        if spec.mount != "wall":
            return []
        return keyhole_cuts([(-30.0, R * 0.45), (30.0, R * 0.45)])

    def extra(ctx):
        if spec.mount != "stand":
            return []
        return [stand_part(R, ctx.D, ctx.tb, ctx.cable_x)]

    plan = Plan("round", spec, outline, window, feats, 2 * R, 2 * R, boss_fn=boss_fn, pocket_fn=pocket_fn, path_fn=path_fn,
                back_cut_fn=back_cut, extra_parts_fn=extra, warnings=warnings,
                meta={"diameter_mm": spec.diameter_mm, "rim_mm": spec.rim_mm,
                      "keyholes": ([[-30.0, R * 0.45], [30.0, R * 0.45]] if spec.mount == "wall" else [])})
    return plan


def build_round(spec: RoundSpec, hw: Hardware | None = None) -> LightBox:
    hw = hw or default_hardware()
    return assemble(plan_round(spec, hw), hw)
