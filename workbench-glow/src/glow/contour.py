"""Design ``contour``: lightbox whose housing follows the logo/text silhouette offset by ``rim_mm``.

* housing outline = silhouette (holes filled, close parts bridged) offset by the rim; the offset outline is the box wall
* window (lit area) = the filled silhouette; logo colours listed in ``light_colors`` (or all, ``lit: text``) glow,
  the rest is opaque; relief raised | flush | recessed (+-0.5-2.5 mm)
* slot-in desk stand: a stub under the flattest part of the outline plugs into a separate base; or wall keyholes
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

import trimesh
from workbench_core.fonts import resolve_font
from workbench_core.geometry import BED_MM, Part
from workbench_core.shapes import shape_polygon  # noqa: F401  (shared shapes, re-exported)

from .face import fit_logo, fit_text
from .hardware import Hardware, default_hardware
from .ledpath import contour_path
from .lightbox import (BOSS_R, PLACEHOLDER, BoxSpec, LightBox, Plan, assemble, auto_pocket, keyhole_cuts)
from .parts import solid, to_mesh

STUB_W = 44.0
STUB_DROP = 12.0  # stub reaches this far below the lowest outline point
MIN_RIM = 3.0

SHAPES = ("auto", "heart", "star", "star4", "circle", "square", "triangle", "hexagon")
# share of the shape width the content may use at first (then shrunk until it fits) and its vertical offset (x height)
SHAPE_FIT = {"heart": (0.62, 0.10), "star": (0.40, -0.02), "star4": (0.40, 0.0), "circle": (0.74, 0.0), "square": (0.86, 0.0),
             "triangle": (0.52, -0.20), "hexagon": (0.78, 0.0)}





def fit_into(feats: list, window: BaseGeometry, margin: float, start_w: float, dy: float) -> tuple[list, list[str]]:
    """Scale/centre content (already centred on the origin, ``start_w`` wide) until it lies inside window - margin."""
    inner = window.buffer(-margin)

    def place(k):
        return [(c, affinity.translate(affinity.scale(g, k, k, origin=(0, 0)), 0, dy)) for c, g in feats]

    def ok(k):
        return inner.contains(unary_union([g for _, g in place(k)]))

    lo, hi = 0.0, 1.8  # largest scale that fits (binary search); content may grow beyond the start width
    if ok(hi):
        return place(hi), []
    for _ in range(22):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    if lo < 0.05:
        return place(0.3), ["İçerik şeklin içine sığmadı: metni kısaltın ya da şekli büyütün."]
    return place(lo * 0.97), []


@dataclass
class ContourSpec(BoxSpec):
    width_mm: float = 220.0  # overall housing width
    depth_mm: float = 30.0
    rim_mm: float = 6.0
    relief: str = "raised"
    relief_mm: float = 1.5
    mount: str = "stand"  # stand | wall
    led: str = "ws2812b_5mm"
    logo_colors: int = 3
    drop_thin_mm: float = 1.8  # logo parts thinner than this (e.g. a tagline) are dropped
    drop_area_mm2: float = 25.0  # ... and parts smaller than this
    split_ok: bool = False
    shape: str = "auto"  # auto: silhouette of the text/logo | heart | star | star4 | circle | square | triangle | hexagon

    def validate(self) -> None:
        self.validate_common()
        if self.shape not in SHAPES:
            raise ValueError(f"shape must be one of {', '.join(SHAPES)}")
        if self.mount == "desk":
            self.mount = "stand"
        if self.mount not in ("stand", "wall"):
            raise ValueError("mount must be stand or wall")
        if self.rim_mm < MIN_RIM:
            raise ValueError(f"rim must be >= {MIN_RIM:g} mm")
        if self.width_mm < 80:
            raise ValueError("width must be at least 8 cm")
        if self.width_mm > BED_MM and not self.split_ok:
            raise ValueError(f"width {self.width_mm / 10:g} cm exceeds the 25 cm bed")


def fill_holes(g: BaseGeometry) -> BaseGeometry:
    polys = list(getattr(g, "geoms", [g]))
    return unary_union([Polygon(p.exterior) for p in polys if not p.is_empty])


def drop_thin(g: BaseGeometry, min_w: float, min_area: float = 0.0) -> BaseGeometry:
    keep = [p for p in getattr(g, "geoms", [g]) if not p.is_empty and p.area >= min_area and not p.buffer(-min_w / 2).is_empty]
    return unary_union(keep) if keep else Polygon()


def housing_outline(sil: BaseGeometry, rim: float) -> tuple[BaseGeometry, list[str]]:
    """Silhouette offset by the rim, notches closed, separate parts bridged into one housing."""
    warns: list[str] = []
    out = sil.buffer(rim, quad_segs=16)
    out = out.buffer(4.0, quad_segs=16).buffer(-4.0, quad_segs=16)
    n = 0
    while len(getattr(out, "geoms", [out])) > 1 and n < 20:
        comps = list(out.geoms)
        a, rest = comps[0], unary_union(comps[1:])
        p, q = nearest_points(a, rest)
        out = unary_union([out, LineString([(p.x, p.y), (q.x, q.y)]).buffer(max(rim, 4.0), cap_style="flat")])
        n += 1
    if n:
        warns.append(f"Logo parts too far apart: {n} connecting bar(s) added to the housing.")
    return out, warns


def _ylow(outline: BaseGeometry, x: float) -> float | None:
    inter = outline.intersection(LineString([(x, outline.bounds[1] - 1), (x, outline.bounds[3] + 1)]))
    return None if inter.is_empty else inter.bounds[1]


def stub_span(outline: BaseGeometry) -> tuple[float, float, float, float]:
    """(x centre, y reference (highest low point in the span), y lowest, flatness) of the flattest bottom stretch."""
    minx, miny, maxx, maxy = outline.bounds
    cx0 = outline.centroid.x
    best = None
    xc = minx + STUB_W / 2
    while xc <= maxx - STUB_W / 2:
        ys = [_ylow(outline, x) for x in np.arange(xc - STUB_W / 2, xc + STUB_W / 2 + 0.01, 2.0)]
        if all(y is not None for y in ys):
            rng = max(ys) - min(ys)
            key = (round(rng / 2.0), abs(xc - cx0))  # flatness in 2 mm buckets, then closest to the centre
            if best is None or key < best[0]:
                best = (key, xc, max(ys))
        xc += 2.0
    if best is None:
        raise ValueError("no stretch of the outline is wide enough for the stand stub; use mount=wall")
    return best[1], best[2], miny, best[0][0] * 2.0


def contour_bosses(geo, avoid: BaseGeometry, n: int = 4) -> list[tuple[float, float]]:
    """Screw boss centres near the housing wall (4 well spread points, clear of ``avoid``)."""
    region = geo.inner.buffer(-(BOSS_R + 1.8)).difference(avoid)
    if region.is_empty:
        return []
    minx, miny, maxx, maxy = region.bounds
    pts = []
    y = miny
    while y <= maxy:
        x = minx
        while x <= maxx:
            p = Point(x, y)
            if region.contains(p) and 5.3 <= geo.inner.boundary.distance(p) <= 9.0:
                pts.append((x, y))
            x += 3.0
        y += 3.0
    if not pts:
        return []
    c0 = geo.inner.centroid
    chosen = [max(pts, key=lambda p: math.hypot(p[0] - c0.x, p[1] - c0.y))]
    while len(chosen) < n:
        cand = max(pts, key=lambda p: min(math.hypot(p[0] - q[0], p[1] - q[1]) for q in chosen))
        if min(math.hypot(cand[0] - q[0], cand[1] - q[1]) for q in chosen) < 25.0:
            break
        chosen.append(cand)
    return chosen


def place_keyholes(outline: BaseGeometry) -> list[tuple[float, float]]:
    """Up to two keyholes (entry, slot up) as high as the plate allows, at least 40 mm apart."""
    plate = outline.buffer(-1.5)
    minx, miny, maxx, maxy = outline.bounds

    def shape(x, y):
        return unary_union([Point(x, y).buffer(4.75), box(x - 4.75, y, x + 4.75, y + 10.0), Point(x, y + 10.0).buffer(4.75)])

    found = []
    y = maxy - 20.0
    while y > miny + 20 and len(found) < 2:
        x = minx + 6
        row = []
        while x < maxx - 6:
            if plate.contains(shape(x, y)):
                row.append(x)
            x += 3.0
        if row:
            if not found:
                cx = outline.centroid.x
                x0 = min(row, key=lambda v: abs(v - (cx - 25)))
                found.append((x0, y))
            else:
                far = [v for v in row if abs(v - found[0][0]) >= 40.0]
                if far:
                    found.append((min(far, key=lambda v: abs(abs(v - found[0][0]) - 50)), found[0][1]))
        y -= 2.0
    return found


def stand_part(xc: float, y_low: float, z0: float, z1: float) -> Part:
    ext = 35.0
    bw = 60.0
    y_top, y_slot, y_base = y_low - 2.0, y_low - STUB_DROP - 0.3, y_low - STUB_DROP - 8.3
    base = solid(box(xc - bw, y_base, xc + bw, y_top), z0 - ext, z1 + ext)
    slot = solid(box(xc - STUB_W / 2 - 0.3, y_slot, xc + STUB_W / 2 + 0.3, y_top + 1), z0 - 0.3, z1 + 0.3)
    part = Part("stand", "stand", to_mesh(base - slot), "#1F4D3A", 1, group="stand")
    part.meta["print_rot"] = trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0])
    return part


def plan_contour(spec: ContourSpec, hw: Hardware | None = None) -> Plan:
    hw = hw or default_hardware()
    spec.validate()
    rim = spec.rim_mm
    warnings: list[str] = []
    inner_w = spec.width_mm - 2 * rim
    if spec.shape != "auto":
        return _plan_shape(spec, hw, rim, inner_w)
    if spec.logo:
        content, w1 = fit_logo(spec.logo, inner_w, None, n_colors=spec.logo_colors)
        warnings += [w for w in w1 if "thin" not in w]
        kept = []
        dropped = 0
        for c, g in content:
            g2 = drop_thin(g, spec.drop_thin_mm, spec.drop_area_mm2)
            dropped += len(getattr(g, "geoms", [g])) - (0 if g2.is_empty else len(getattr(g2, "geoms", [g2])))
            if not g2.is_empty:
                kept.append((c, g2))
        if dropped:
            warnings.append(f"{dropped} logo part(s) thinner than {spec.drop_thin_mm:g} mm or smaller than {spec.drop_area_mm2:g} mm2 were left out (tagline, hairlines, specks).")
        feats = kept
    else:
        g, w1 = fit_text(spec.text, resolve_font(spec.font), inner_w, None)
        warnings += w1
        feats = [(PLACEHOLDER, g)]
    allg = unary_union([g for _, g in feats])
    cx, cy = (allg.bounds[0] + allg.bounds[2]) / 2, (allg.bounds[1] + allg.bounds[3]) / 2
    feats = [(c, affinity.translate(g, -cx, -cy)) for c, g in feats]
    sil = fill_holes(unary_union([g for _, g in feats]))
    outline, w2 = housing_outline(sil, rim)
    warnings += w2
    return _finish_plan(spec, hw, rim, feats, sil, outline, warnings)


def _plan_shape(spec: ContourSpec, hw: Hardware, rim: float, inner_w: float) -> Plan:
    """Shape mode: the housing is a basic shape (heart, star, ...) and the text/logo sits inside its lit window."""
    warnings: list[str] = []
    sil = shape_polygon(spec.shape, inner_w)
    frac, dyk = SHAPE_FIT[spec.shape]
    H0 = sil.bounds[3] - sil.bounds[1]
    if spec.logo:
        feats, w1 = fit_logo(spec.logo, inner_w * frac, None, n_colors=spec.logo_colors)
        warnings += [w for w in w1 if "thin" not in w]
    else:
        g, w1 = fit_text(spec.text, resolve_font(spec.font), inner_w * frac, None)
        warnings += w1
        feats = [(PLACEHOLDER, g)]
    feats, w2 = fit_into(feats, sil, spec.margin_mm * 0.6, inner_w * frac, dyk * H0)
    warnings += w2
    outline = sil.buffer(rim, quad_segs=16).buffer(4.0, quad_segs=16).buffer(-4.0, quad_segs=16)
    return _finish_plan(spec, hw, rim, feats, sil, outline, warnings)


def _finish_plan(spec: ContourSpec, hw: Hardware, rim: float, feats: list, sil: BaseGeometry, outline: BaseGeometry,
                 warnings: list[str]) -> Plan:
    wall, lip_w = (2.4, 1.2) if rim >= 5.0 else (1.6, 0.8)
    if rim < 5.0:
        warnings.append(f"Rim {rim:g} mm < 5 mm: thin 1.6 mm walls and a 0.8 mm lip.")
    window = sil.intersection(outline)
    ob = outline.bounds
    W, H = ob[2] - ob[0], ob[3] - ob[1]
    if (W > BED_MM or H > BED_MM) and not spec.split_ok:
        raise ValueError(f"housing {W:.0f} x {H:.0f} mm exceeds the 25 cm bed")

    def pocket_fn(geo, boss_zone, ctrl):
        return auto_pocket(geo, boss_zone, ctrl)

    def path_fn(geo, allowed, led_, pitch_target, margin, gap):
        return contour_path(allowed, led_, pitch_target_mm=pitch_target)

    stub = {}
    if spec.mount == "stand":
        xc, y_ref, y_low, flat = stub_span(outline)
        stub = {"xc": xc, "y_ref": y_ref, "y_low": y_low}
        if flat > 6.0:
            warnings.append(f"Bottom of the outline is not flat under the stub ({flat:.0f} mm): the stub is longer there.")

    def body_add(ctx):
        if spec.mount != "stand":
            return []
        s = box(stub["xc"] - STUB_W / 2, stub["y_low"] - STUB_DROP, stub["xc"] + STUB_W / 2, stub["y_ref"] + 3.0)
        return [solid(s.difference(ctx.inner), ctx.z0, ctx.z1)]

    def extra(ctx):
        return [stand_part(stub["xc"], stub["y_low"], ctx.z0, ctx.z1)] if spec.mount == "stand" else []

    kh = place_keyholes(outline) if spec.mount == "wall" else []
    if spec.mount == "wall" and len(kh) < 2:
        warnings.append(f"Only {len(kh)} keyhole(s) fit the plate.")

    def back_cut(ctx):
        return keyhole_cuts(kh) if spec.mount == "wall" else []

    return Plan("contour", spec, outline, window, feats, W, H, wall=wall, lip_w=lip_w, boss_fn=contour_bosses,
                bosses_after_pocket=True, pocket_fn=pocket_fn, path_fn=path_fn, body_add_fn=body_add, back_cut_fn=back_cut,
                extra_parts_fn=extra, warnings=warnings,
                meta={"rim_mm": rim, "width_mm": W, "height_mm": H, "stub": stub, "keyholes": kh, "shape": spec.shape})


def build_contour(spec: ContourSpec, hw: Hardware | None = None) -> LightBox:
    hw = hw or default_hardware()
    return assemble(plan_contour(spec, hw), hw)
