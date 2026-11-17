"""Generic lightbox assembler used by the designs (rect, round, contour).

Wall coordinates (mm): origin at the box centre, x right, y up, z toward the viewer; back outer plane z = 0,
front surface z = depth.

Parts
* **face**   multi-colour plate (frame ring + lit window + features) + a lip that plugs into the body
             (0.25 mm clearance, stops light leaking at the joint). Press-fit/loose lip: add a drop of glue.
             Printed face-down (face-up when relief != flush).
* **body**   wall tube (2.4 mm), M3 screw bosses (pilot 2.5 mm), design-specific extras (feet, stub).
* **back**   plate + lip, LED guide rails, controller cradle, USB cable slot + zip-tie slots, screw holes
             (4 x M3 self-tapping into the bosses), keyholes in wall mode. Printed back-down; with a dark body
             colour the last 0.6 mm (the inner surface) is white (``interior_white``).
Each design supplies a ``Plan`` (outline, window, features and placement hooks); ``assemble`` builds everything.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from types import SimpleNamespace
from typing import Callable

import numpy as np
import trimesh
from manifold3d import Manifold
from shapely import affinity
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from workbench_core.geometry import Model, Part, from_trimesh, to_trimesh

from .checks import assembly_report
from .face import DARK_LUM, FaceLayer, build_face_regions, build_layers, face_depth, layers_to_parts, light_back_z
from .power import power_report
from .hardware import Hardware, default_hardware, strip_power_w
from .ledpath import LedPath, coverage
from .parts import BLOCK_COLOR, assign_extruders, luminance, norm_color, solid, tf_to_bed, to_mesh, union

WALL = 2.4
CLEAR = 0.25  # lip-to-wall clearance
LIP_W = 1.6
LIP_H = 3.0
BOSS_R = 3.5
BOSS_H = 8.0
PILOT_D = 2.5
SCREW_HOLE_D = 3.4
RAIL_W = 0.8
CRADLE_WALL = 1.2
CRADLE_H = 4.0
TB_DESK, TB_WALL = 3.0, 6.0
TB_KEYHOLE_MIN = 4.5  # keyhole chamber needs 4.5 mm of back plate
# LED channel (led_mount="channel"): U-channel walls on the back plate that hold the strip
CH_WALL = 1.2
CH_CLEAR = 0.3  # strip-to-wall clearance per side
CH_ABOVE = 1.0  # channel walls stand this far above the strip
# snap-on channel cover (channel_cover=True): diffuser-colour cap over the channel walls, legs outside the walls
COVER_T = 0.8
COVER_LEG = 1.0
COVER_CLEAR = 0.15
COVER_LEG_H = 2.0
COVER_LIFT = 0.1  # cover top floats 0.1 mm above the wall tops (no coplanar contact in the interference check)
HOLE_TYPES = ("rect", "circle", "key")
WHITE = "#F5F5F5"
PLACEHOLDER = "#000000"  # text feature colour, assigned from the lit mode
INTERIOR_WHITE_T = 0.6


@dataclass
class BoxSpec:
    depth_range = (20.0, 100.0)  # allowed depth (class attribute, not a field); Lightbox Maker range
    text: str = ""
    logo: str | None = None
    font: str = "Montserrat"
    depth_mm: float = 35.0
    margin_mm: float = 10.0  # content margin inside the lit window
    frame_color: str = "#1F4D3A"  # frame / body colour
    lit: str = "text"  # text: letters/logo glow on an opaque background | background: the background glows
    text_color: str | None = None  # lit=text: filament colour of the glowing letters (default diffuser); lit=background: opaque letter colour (default frame)
    background_color: str | None = None  # lit=text: opaque background colour (default frame colour)
    face_color: str | None = None  # lit=background: light colour (default diffuser)
    accent_color: str | None = None  # optional thin border line inside the window
    back_color: str | None = None  # default: frame colour
    relief: str = "flush"
    relief_mm: float = 1.0
    block: str = "layer"
    led: str = "ws2812b_10mm"
    controller: str = "bt_rgb_mini"
    diffuser: str = "pla_white"
    mount: str = "desk"
    interior_white: str = "auto"  # auto | on | off
    led_color: str = "#FFF1D8"  # colour of the LED light in the lit renders only (RGB strips can be any colour)
    led_fill: str = "normal"  # normal | dense (finer pitch: extra inner loops/rows, more jumpers)
    light_colors: list | None = None  # logo colours that glow (others opaque); overrides `lit` per colour
    recolor: dict | None = None  # logo colour -> filament colour, e.g. a translucent green for a dark logo green
    logo_colors: int = 4  # raster/SVG logos are reduced to this many colours (2-4)
    # --- Lightbox Maker style options -------------------------------------------------------------
    front_mm: float | None = None  # light-region thickness override (default: diffuser table), 0.6-2.4
    back_mm: float | None = None  # back plate thickness override (default 3 desk / 6 wall), 2-8
    diffusion_mm: float = 0.0  # 0 = off; 0.1-1.0 mm diffuser-colour layer behind every light region
    stroke_mm: float = 0.0  # 0 = off; outline ring around the text/logo (0.5-6 mm)
    stroke_color: str | None = None  # default white
    stroke_glow: bool = False  # True: the ring lets light through (light region), else opaque
    stand_color: str | None = None  # separate stand / base part colour (default frame colour)
    holes: list | None = None  # extra back holes: [{type: rect|circle|key, w, h, x, y}] (mm, box centre origin)
    # --- LED mounting -----------------------------------------------------------------------------------
    led_mount: str = "rails"  # rails: thin guide rails | channel: U-channel that holds the strip
    channel_cover: bool = False  # channel only: snap-on diffuser cover strips over the channels
    job_id: str | None = None

    @classmethod
    def from_dict(cls, raw: dict):
        names = {f.name for f in fields(cls)}
        bad = set(raw) - names - {"design"}
        if bad:
            raise ValueError(f"unknown option(s): {', '.join(sorted(bad))}")
        return cls(**{k: v for k, v in raw.items() if k in names})

    def validate_common(self) -> None:
        if not (self.text.strip() or self.logo):
            raise ValueError("give text or logo")
        lo, hi = self.depth_range
        if not (lo <= self.depth_mm <= hi):
            raise ValueError(f"depth must be {lo:g}-{hi:g} mm")
        if self.lit not in ("text", "background"):
            raise ValueError("lit must be text or background")
        norm_color(self.led_color)
        if self.led_fill not in ("normal", "dense"):
            raise ValueError("led_fill must be normal or dense")
        if self.interior_white not in ("auto", "on", "off"):
            raise ValueError("interior_white must be auto, on or off")
        if self.front_mm is not None and not (0.6 <= self.front_mm <= 2.4):
            raise ValueError("front_mm must be 0.6-2.4 mm")
        if self.back_mm is not None and not (2.0 <= self.back_mm <= 8.0):
            raise ValueError("back_mm must be 2-8 mm")
        if self.diffusion_mm and not (0.1 <= self.diffusion_mm <= 1.0):
            raise ValueError("diffusion_mm must be 0 (off) or 0.1-1.0 mm")
        if self.stroke_mm and not (0.5 <= self.stroke_mm <= 6.0):
            raise ValueError("stroke_mm must be 0 (off) or 0.5-6 mm")
        if self.stroke_color:
            norm_color(self.stroke_color)
        if self.stand_color:
            norm_color(self.stand_color)
        if not (2 <= int(self.logo_colors) <= 4):
            raise ValueError("logo_colors must be 2-4")
        if self.led_mount not in ("rails", "channel"):
            raise ValueError("led_mount must be rails or channel")
        if self.channel_cover and self.led_mount != "channel":
            raise ValueError("channel_cover needs led_mount: channel")
        for h in self.holes or []:
            if h.get("type") not in HOLE_TYPES:
                raise ValueError(f"hole type must be one of {', '.join(HOLE_TYPES)}")
            if h["type"] != "key" and not (2.0 <= float(h.get("w", 0)) <= 60.0 and 2.0 <= float(h.get("h", h.get("w", 0))) <= 60.0):
                raise ValueError("hole size must be 2-60 mm")


@dataclass
class Geo:
    outline: BaseGeometry
    inner: BaseGeometry
    lip_out: BaseGeometry
    lip_in: BaseGeometry
    wall: float
    lip_w: float


@dataclass
class Pocket:
    cx: float
    cy: float
    side: int  # -1: cable leaves to the left, +1 right (in the pocket's own frame)
    vertical: bool = False  # rotated 90 deg (cable then leaves downwards for side -1)


@dataclass
class Plan:
    kind: str
    spec: BoxSpec
    outline: BaseGeometry
    window: BaseGeometry
    features: list  # [(colour, geometry)]
    W: float
    H: float
    wall: float = WALL
    lip_w: float = LIP_W
    boss_fn: Callable | None = None  # (geo, avoid) -> [(x, y)]
    bosses_after_pocket: bool = False  # place bosses around the pocket instead of the pocket around the bosses
    pocket_fn: Callable | None = None  # (geo, boss_zone, ctrl) -> Pocket
    path_fn: Callable | None = None  # (geo, allowed, led, pitch_target, margin, gap) -> LedPath
    body_add_fn: Callable | None = None  # (ctx) -> [Manifold]
    back_cut_fn: Callable | None = None  # (ctx) -> [Manifold]
    extra_parts_fn: Callable | None = None  # (ctx) -> [Part]
    warnings: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class LightBox:
    model: Model
    spec: BoxSpec
    path: LedPath
    regions: object
    solids: dict
    report: dict = field(default_factory=dict)
    layers: list = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return self.model.warnings


def rrect(w: float, h: float, r: float, cx: float = 0.0, cy: float = 0.0) -> BaseGeometry:
    r = max(0.0, min(r, w / 2 - 1e-3, h / 2 - 1e-3))
    if r <= 0:
        return box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return box(cx - w / 2 + r, cy - h / 2 + r, cx + w / 2 - r, cy + h / 2 - r).buffer(r, quad_segs=16)


def boss_shape(c: tuple[float, float], geo: Geo) -> BaseGeometry:
    """Boss cylinder + web to the nearest wall (overlapping the wall so the union is robust)."""
    p = Point(c)
    q = nearest_points(geo.inner.exterior, p)[0]
    d = np.array([q.x - c[0], q.y - c[1]])
    n = np.linalg.norm(d)
    tip = (q.x, q.y) if n < 1e-9 else (q.x + d[0] / n * geo.wall * 0.5, q.y + d[1] / n * geo.wall * 0.5)
    web = LineString([c, tip]).buffer(BOSS_R * 0.85, cap_style="flat")
    return unary_union([p.buffer(BOSS_R, quad_segs=16), web]).intersection(geo.outline.buffer(-geo.wall / 2, quad_segs=16))


def pocket_shapes(ctrl, side: int = -1) -> dict:
    """Pocket geometry in its own frame (cradle centre at the origin, cable on the ``side`` x side)."""
    cL, cW, _ = ctrl.pocket_mm
    cl_ = ctrl.clearance_mm
    pk_w, pk_h = cL + 2 * cl_, cW + 2 * cl_
    pocket_in = box(-pk_w / 2, -pk_h / 2, pk_w / 2, pk_h / 2)
    cradle_out = pocket_in.buffer(CRADLE_WALL, join_style="mitre")
    nx0, nx1 = sorted((side * (pk_w / 2 - 0.5), side * (pk_w / 2 + CRADLE_WALL + 0.5)))
    notch = box(nx0 - 1.0, -5.0, nx1 + 1.0, 5.0)
    cable_x = side * (pk_w / 2 + CRADLE_WALL + 7.0)
    return {
        "pocket_in": pocket_in, "cradle_out": cradle_out, "cradle": cradle_out.difference(pocket_in).difference(notch),
        "controller": box(-cL / 2, -cW / 2, cL / 2, cW / 2), "cable_slot": rrect(5.0, 11.0, 2.4, cable_x, 0.0),
        "zip": [box(cable_x + dx - 0.8, -1.6, cable_x + dx + 0.8, 1.6) for dx in (-6.5, 6.5)],
        "cable_xy": (cable_x, 0.0),
        "footprint": unary_union([cradle_out, box(cable_x - 3.5, -6.0, side * (pk_w / 2), 6.0)]),
    }


def place_pocket(shapes: dict, pk: "Pocket") -> dict:
    """Rotate/translate the pocket shapes into the box frame."""
    def tf(g):
        if pk.vertical:
            g = affinity.rotate(g, 90, origin=(0, 0))
        return affinity.translate(g, pk.cx, pk.cy)

    out = {k: ([tf(g) for g in v] if isinstance(v, list) else tf(v)) for k, v in shapes.items() if k != "cable_xy"}
    c = Point(shapes["cable_xy"])
    out["cable_xy"] = (tf(c).x, tf(c).y)
    return out


def auto_pocket(geo: Geo, boss_zone: BaseGeometry, ctrl, *, prefer: str = "bottom", inset: float = 1.0, step: float = 3.0) -> Pocket:
    """Lowest free spot for the cradle plus its cable slot (tries horizontal, then rotated by 90 degrees)."""
    ok = geo.lip_in.buffer(-inset).difference(boss_zone.buffer(min(1.0, inset)))
    shapes = pocket_shapes(ctrl, -1)
    minx, miny, maxx, maxy = ok.bounds
    best = None
    for vertical in (False, True):
        foot0 = affinity.rotate(shapes["footprint"], 90, origin=(0, 0)) if vertical else shapes["footprint"]
        fb = foot0.bounds
        y = miny - fb[1]
        while y <= maxy - fb[3] + 1e-6:
            x = minx - fb[0]
            while x <= maxx - fb[2] + 1e-6:
                foot = affinity.translate(foot0, x, y)
                if ok.contains(foot):
                    key = (round(foot.bounds[1] / 3.0), vertical, abs(x))  # lowest, then horizontal, then centred
                    if best is None or key < best[0]:
                        best = (key, x, y, vertical)
                x += step
            y += step
    if best is None:
        cL, cW, _ = ctrl.pocket_mm
        raise ValueError(f"controller {ctrl.id} ({cL:.0f} x {cW:.0f} mm) does not fit inside the box; use a smaller controller or a bigger box")
    _, cx, cy, vertical = best
    return Pocket(cx, cy, -1, vertical)


EXTERNAL_CTRL_ID = "external"


def resolve_pocket(plan: "Plan", geo: Geo, boss_zone: BaseGeometry, ctrl, hw: Hardware, led_id: str) -> tuple[Pocket, object, str, list[str]]:
    """Never hard-fails: plan search -> finer/relaxed search -> smaller controllers -> external (inline) controller.

    Returns (pocket, controller actually housed, mode, warnings); mode is ``normal | relaxed | smaller | external``.
    """
    from dataclasses import replace

    def attempts(c):
        yield "normal", lambda: plan.pocket_fn(geo, boss_zone, c)
        yield "relaxed", lambda: auto_pocket(geo, boss_zone, c, inset=0.3, step=1.5)

    smaller = sorted((c for c in hw.controllers.values() if led_id in c.supports and c.id != ctrl.id
                      and c.pocket_mm[0] * c.pocket_mm[1] < ctrl.pocket_mm[0] * ctrl.pocket_mm[1]),
                     key=lambda c: -c.pocket_mm[0] * c.pocket_mm[1])
    for c in [ctrl, *smaller]:
        for mode, fn in attempts(c):
            try:
                pk = fn()
            except ValueError:
                continue
            if c is ctrl:
                w = ["Controller pocket needed a tighter search (closer to the lip)."] if mode == "relaxed" else []
                return pk, c, mode, w
            return pk, c, "smaller", [f"Kontrolcü {ctrl.id} kutuya sığmadı; daha küçük {c.id} ({c.pocket_mm[0]:g} x {c.pocket_mm[1]:g} mm) kullanıldı."]
    ext = replace(ctrl, id=EXTERNAL_CTRL_ID, label="harici kontrolcü", pocket_mm=(4.0, 4.0, 2.0), clearance_mm=1.0, supports=(), price_try=0.0)
    for mode, fn in attempts(ext):
        try:
            return fn(), ext, "external", [
                f"Kontrolcü {ctrl.id} kutuya sığmıyor: HARİCİ KONTROLCÜ kullanılacak. Kontrolcü kablo üzerinde kutunun dışında durur, "
                "kutuda yalnızca kablo çıkış deliği vardır; LED şeridi kablo ile dışarı verilir."]
        except ValueError:
            continue
    raise ValueError("no room for even a cable exit hole: the box is too small")


def rect_pocket(geo: Geo, boss_zone: BaseGeometry, ctrl) -> Pocket:
    """Bottom-left pocket, clear of the corner bosses and the cable slot (mirrored for right-hand cable sides)."""
    iw = geo.inner.bounds[2] - geo.inner.bounds[0]
    ih = geo.inner.bounds[3] - geo.inner.bounds[1]
    cL, cW, _ = ctrl.pocket_mm
    cl_ = ctrl.clearance_mm
    pk_w, pk_h = cL + 2 * cl_, cW + 2 * cl_
    side = -1 if ctrl.cable_side in ("left", "bottom", "top") else 1
    x_edge = side * (iw / 2 - 30.0)
    pk_cx = x_edge - side * (pk_w / 2 + CRADLE_WALL)
    pk_cy = -ih / 2 + geo.lip_w + CLEAR + 3.0 + CRADLE_WALL + pk_h / 2
    return Pocket(pk_cx, pk_cy, side, False)


def keyhole_cuts(positions: list[tuple[float, float]]) -> list[Manifold]:
    """Keyholes (entry circle/slot up): neck 4.5 mm in a 1.5 mm back lip over a 9.5 mm wide, 3 mm deep chamber."""
    cuts = []
    for xc, ye in positions:
        neck = unary_union([Point(xc, ye).buffer(4.75, quad_segs=16), box(xc - 2.25, ye, xc + 2.25, ye + 10.0),
                            Point(xc, ye + 10.0).buffer(2.25, quad_segs=16)])
        chamber = unary_union([Point(xc, ye).buffer(4.75, quad_segs=16), box(xc - 4.75, ye, xc + 4.75, ye + 10.0),
                               Point(xc, ye + 10.0).buffer(4.75, quad_segs=16)])
        cuts += [solid(neck, -0.1, 1.5), solid(chamber, 1.5, 4.5)]
    return cuts


def _tint(color: str, diff) -> str:
    return diff.color if luminance(color) > 0.92 else color  # near-white light regions use the diffuser filament


def build_regions(plan: Plan, hw: Hardware):
    spec = plan.spec
    diff = hw.diffuser(spec.diffuser)
    lc = {norm_color(c) for c in (spec.light_colors or [])}
    feats = []
    for f in plan.features:
        c, g = f[0], f[1]
        if len(f) > 2:  # explicit kind (stroke ring, accent line set by the assembler)
            kind = f[2]
            c = norm_color(c)
            feats.append((_tint(c, diff) if kind == "light" else c, g, kind))
            continue
        if c == PLACEHOLDER:  # the text
            c = (spec.text_color or diff.color) if spec.lit == "text" else (spec.text_color or spec.frame_color)
            kind = "light" if spec.lit == "text" else "opaque"
        else:
            kind = "light" if (norm_color(c) in lc or (not lc and spec.lit == "text")) else "opaque"
        if spec.recolor and c != PLACEHOLDER:
            c = {norm_color(k): norm_color(v) for k, v in spec.recolor.items()}.get(norm_color(c), c)
        if kind == "light":
            c = _tint(norm_color(c), diff)
        feats.append((c, g, kind))
    if spec.lit == "text" or lc:
        ground_color = spec.background_color or spec.frame_color
        return build_face_regions(plan.outline, plan.window, feats, light="features", ground_color=ground_color,
                                  frame_color=spec.frame_color, light_color=diff.color)
    return build_face_regions(plan.outline, plan.window, feats, light="ground", light_color=spec.face_color or diff.color,
                              frame_color=spec.frame_color)


def assemble(plan: Plan, hw: Hardware | None = None) -> LightBox:
    hw = hw or default_hardware()
    spec = plan.spec
    spec.validate_common()
    led = hw.led(spec.led)
    ctrl = hw.controller(spec.controller)
    if spec.led not in ctrl.supports:
        raise ValueError(f"controller {spec.controller} does not support {spec.led} (supports: {', '.join(ctrl.supports)})")
    t_light = spec.front_mm or hw.diffuser_thickness(spec.diffuser, spec.led)
    min_gap = hw.min_gap(spec.diffuser, spec.led)
    warnings: list[str] = list(plan.warnings)
    meta_notes: list[str] = []
    D, W, H = spec.depth_mm, plan.W, plan.H
    outline, window = plan.outline, plan.window

    # ---- face --------------------------------------------------------------
    feats = list(plan.features)
    if spec.stroke_mm:
        content = unary_union([f[1] for f in feats])
        ring = content.buffer(spec.stroke_mm, quad_segs=12).difference(content).intersection(window)
        if ring.is_empty or ring.area < 1.0:
            warnings.append("Kontur çizgisi pencereye sığmadı (içerik pencere kenarına çok yakın).")
        else:
            sc = norm_color(spec.stroke_color or hw.diffuser(spec.diffuser).color)
            if luminance(sc) > 0.92:
                sc = norm_color(hw.diffuser(spec.diffuser).color)  # near-white: the white diffuser filament, no extra spool
            feats.append((sc, ring, "light" if spec.stroke_glow else "opaque"))
            if content.buffer(spec.stroke_mm).difference(window).area > 1.0:
                warnings.append("Kontur çizgisi pencere kenarında kırpıldı: kenar boşluğunu (margin) kontur kalınlığından büyük yapın.")
    if spec.accent_color:
        ring = window.buffer(-2.0).difference(window.buffer(-3.5))
        feats.append((norm_color(spec.accent_color), ring))
    plan.features = feats
    fr = build_regions(plan, hw)
    warnings += fr.warnings
    layers, w2 = build_layers(fr, t_light=t_light, relief=spec.relief, relief_mm=spec.relief_mm, block=spec.block)
    warnings += w2
    if spec.diffusion_mm:
        diff_c = norm_color(hw.diffuser(spec.diffuser).color)
        for l in [l for l in layers if l.role == "light"]:
            layers.append(FaceLayer(f"{l.name}_diffusion", diff_c, "light", l.region, l.geometry, l.z1, l.z1 + spec.diffusion_mm))
    frame_back = max(l.z1 for l in layers if l.region == "frame")
    fdepth = face_depth(layers)
    light_back = light_back_z(layers)

    # ---- geometry ------------------------------------------------------------
    wall = plan.wall
    has_key = any(h.get("type") == "key" for h in (spec.holes or []))
    tb = spec.back_mm or (TB_WALL if (spec.mount == "wall" or has_key) else TB_DESK)
    if (spec.mount == "wall" or has_key) and tb < TB_KEYHOLE_MIN:
        raise ValueError(f"Anahtar deliği için arka kapak en az {TB_KEYHOLE_MIN:g} mm olmalı (şu an {tb:g} mm).")
    inner = outline.buffer(-wall, quad_segs=16)
    z0, z1 = tb, D - frame_back
    lip_out = inner.buffer(-CLEAR, quad_segs=16)
    lip_in = lip_out.buffer(-plan.lip_w, quad_segs=16)
    lip_ring = lip_out.difference(lip_in)
    geo = Geo(outline, inner, lip_out, lip_in, wall, plan.lip_w)
    empty = Point(0, 0).buffer(0)
    if plan.bosses_after_pocket:
        boss_c, boss_shapes, boss_zone = [], [], empty
        pk, ctrl, pocket_mode, pocket_w = resolve_pocket(plan, geo, empty, ctrl, hw, spec.led)
        avoid = place_pocket(pocket_shapes(ctrl, pk.side), pk)["footprint"].buffer(2.0)
        boss_c = plan.boss_fn(geo, avoid) if plan.boss_fn else []
        boss_shapes = [boss_shape(c, geo) for c in boss_c]
        boss_zone = unary_union(boss_shapes) if boss_shapes else empty
    else:
        boss_c = plan.boss_fn(geo, empty) if plan.boss_fn else []
        boss_shapes = [boss_shape(c, geo) for c in boss_c]
        boss_zone = unary_union(boss_shapes) if boss_shapes else empty
        pk, ctrl, pocket_mode, pocket_w = resolve_pocket(plan, geo, boss_zone, ctrl, hw, spec.led)
    warnings += pocket_w
    if len(boss_c) < 3:
        warnings.append(f"Only {len(boss_c)} screw boss(es) fit: close the back cover with glue/tape as well.")
    cL, cW, cH = ctrl.pocket_mm
    ps = place_pocket(pocket_shapes(ctrl, pk.side), pk)
    pk_w, pk_h = ps["pocket_in"].bounds[2] - ps["pocket_in"].bounds[0], ps["pocket_in"].bounds[3] - ps["pocket_in"].bounds[1]
    pocket_in, cradle_out, cradle = ps["pocket_in"], ps["cradle_out"], ps["cradle"]
    controller_box, cable_slot, zip_slots = ps["controller"], ps["cable_slot"], ps["zip"]
    pk_cx, pk_cy = pocket_in.centroid.x, pocket_in.centroid.y
    cable_x, cable_y = ps["cable_xy"]

    # ---- LED path ----------------------------------------------------------------
    sw = led.width_mm
    keep_out = unary_union([boss_zone.buffer(1.0), cradle_out.buffer(1.0), cable_slot.buffer(1.0)])
    free = lip_in.difference(keep_out)
    channel = spec.led_mount == "channel"
    ch_in = sw / 2 + CH_CLEAR
    ch_out = ch_in + CH_WALL
    ch_h = led.thickness_mm + CH_ABOVE
    cov_out = ch_out + COVER_CLEAR + COVER_LEG
    if channel:
        margin = (cov_out if spec.channel_cover else ch_out) + 1.0
    else:
        margin = sw / 2 + 0.3 + RAIL_W + 1.0
    allowed = free.buffer(-margin, quad_segs=8)
    pitch_target = min(1.5 * min_gap, 30.0)
    gap_actual = (D - light_back) - (tb + led.thickness_mm)
    reach = max(gap_actual, min_gap) * 0.8
    if spec.led_fill == "dense":
        cands = []
        for f in (1.0, 0.7, 0.5, 0.4):
            try:
                cands.append(plan.path_fn(geo, allowed, led, pitch_target * f, margin, gap_actual))
            except ValueError:
                continue
        if not cands:
            raise ValueError("LED strip does not fit")
        path = max(cands, key=lambda c: (round(coverage(c, window, reach), 2), -c.total_length_mm))
    else:
        path = plan.path_fn(geo, allowed, led, pitch_target, margin, gap_actual)
    warnings += path.warnings
    if channel:
        rails = unary_union([ln.buffer(ch_out, cap_style="flat").difference(ln.buffer(ch_in, cap_style="flat")) for ln in path.rail_lines()])
        rail_h = ch_h
    else:
        rails = unary_union([ln.buffer(sw / 2 + 0.3 + RAIL_W, cap_style="flat").difference(ln.buffer(sw / 2 + 0.3, cap_style="flat"))
                             for ln in path.rail_lines()])
        rail_h = 1.5
    cover_on = channel and spec.channel_cover
    cover_lines: list = []
    if cover_on:
        # a cover piece is kept when its footprint stays clear of every other channel, strip, cover, the cradle and bosses
        segs = sorted(path.rail_lines(), key=lambda l: -l.length)
        other_bends = [ln.buffer(sw / 2 + 0.5, cap_style="flat") for ln in path.strip_lines() if not any(ln.equals(x) for x in segs)]
        kept_fp = []
        for i, ln in enumerate(segs):
            fp = ln.buffer(cov_out, cap_style="flat")
            others = [l.buffer(ch_out + 0.2, cap_style="flat") for j, l in enumerate(segs) if j != i]
            blockers = unary_union(others + other_bends + kept_fp + [cradle_out.buffer(0.3), boss_zone.buffer(0.3)])
            if not fp.intersects(blockers):
                cover_lines.append(ln)
                kept_fp.append(fp.buffer(0.2))
        skipped = len(segs) - len(cover_lines)
        if not cover_lines:
            cover_on = False
            warnings.append("LED kanal kapağı eklenemedi: şerit parçaları birbirine çok yakın. Normal dolgu ya da daha ince LED seçin.")
        elif skipped:
            warnings.append(f"{skipped} LED kanal parçasına kapak sığmadı (komşu kanala çok yakın); o parçalar açık kalır.")
    strips = [ln.buffer(sw / 2, cap_style="flat") for ln in path.strip_lines()]
    cov = coverage(path, window, reach)
    if 0.6 <= cov < 0.75:
        meta_notes.append(f"LED coverage of the lit area is {cov * 100:.0f} % (normal fill); led_fill: dense raises it with more jumpers.")
    elif cov < 0.75:
        warnings.append(f"LED coverage of the lit area is only {cov * 100:.0f} %: some parts will look dim (raise depth or use more rows/narrower window).")

    # ---- face parts ----------------------------------------------------------------
    parts: list[Part] = []
    face_parts = layers_to_parts(layers, D, group="face", name="face")
    lip_color = BLOCK_COLOR if (spec.block == "layer" and luminance(spec.frame_color) > DARK_LUM) else norm_color(spec.frame_color)
    lip_m = solid(lip_ring, D - frame_back - LIP_H, D - frame_back)
    for p in face_parts:
        if p.color == lip_color:
            p.mesh_wall = to_trimesh(from_trimesh(p.mesh_wall) + lip_m)
            lip_color = None
            break
    if lip_color is not None:
        parts.append(Part("face_lip", "face", to_mesh(lip_m), lip_color, 1, group="face"))
    parts = face_parts + parts
    flip = spec.relief == "flush"

    # ---- body ----------------------------------------------------------------------
    ctx = SimpleNamespace(tb=tb, D=D, z0=z0, z1=z1, outline=outline, inner=inner, W=W, H=H, wall=wall, spec=spec, geo=geo,
                          frame_back=frame_back, cable_x=cable_x, cable_y=cable_y)
    body_items = [solid(outline.difference(inner), z0, z1)]
    for shp, c in zip(boss_shapes, boss_c):
        body_items.append(solid(shp.difference(Point(c).buffer(PILOT_D / 2, quad_segs=12)), z0, z0 + BOSS_H - 1.0))
        body_items.append(solid(shp, z0 + BOSS_H - 1.0, z0 + BOSS_H))
    if plan.body_add_fn:
        body_items += plan.body_add_fn(ctx)
    body_m = union(body_items)
    parts.append(Part("body", "body", to_mesh(body_m), norm_color(spec.frame_color), 1, group="body"))

    # ---- back cover ------------------------------------------------------------------
    back_color = norm_color(spec.back_color or spec.frame_color)
    holes = [Point(c).buffer(SCREW_HOLE_D / 2, quad_segs=12) for c in boss_c]
    cb_depth = min(2.5 if spec.mount == "wall" else 2.0, tb - 1.0)
    cut_items = [solid(Point(c).buffer(3.2, quad_segs=12), -0.1, cb_depth) for c in boss_c]
    if plan.back_cut_fn:
        cut_items += plan.back_cut_fn(ctx)
    user_holes, user_keys, hole_meta = [], [], []
    busy = unary_union([boss_zone, cradle_out, cable_slot.buffer(1.0)] + strips)
    for i, h in enumerate(spec.holes or [], start=1):
        x, y = float(h.get("x", 0.0)), float(h.get("y", 0.0))
        if h["type"] == "key":
            shp = unary_union([Point(x, y).buffer(4.75), box(x - 4.75, y, x + 4.75, y + 10.0), Point(x, y + 10.0).buffer(4.75)])
            user_keys.append((x, y))
        elif h["type"] == "circle":
            shp = Point(x, y).buffer(float(h["w"]) / 2, quad_segs=24)
            user_holes.append(shp)
        else:
            w_, h_ = float(h["w"]), float(h.get("h", h["w"]))
            shp = rrect(w_, h_, min(1.5, w_ / 2 - 0.1, h_ / 2 - 0.1), x, y)
            user_holes.append(shp)
        if not lip_in.buffer(-0.5).contains(shp):
            raise ValueError(f"Delik {i} ({h['type']}, x={x:g}, y={y:g}) arka kapağın iç alanına sığmıyor; konumu merkeze yaklaştırın.")
        if shp.intersects(busy):
            warnings.append(f"Delik {i} ({h['type']}, x={x:g}, y={y:g}) LED şeridi, vida yuvası ya da kontrolcü yuvasıyla çakışıyor: konumunu değiştirin.")
        hole_meta.append({"type": h["type"], "x": x, "y": y, "polygon": [list(c) for c in shp.exterior.coords]})
    if user_keys:
        cut_items += keyhole_cuts(user_keys)
    plate_m = solid(outline.difference(unary_union(holes + user_holes + [cable_slot] + zip_slots)), 0, tb)
    if cut_items:
        plate_m = plate_m - union(cut_items)
    back_lip = lip_ring.difference(boss_zone.buffer(CLEAR + 0.05)) if boss_shapes else lip_ring
    back_m = union([plate_m, solid(back_lip, tb, tb + LIP_H), solid(rails, tb, tb + rail_h), solid(cradle, tb, tb + CRADLE_H)])
    used = {p.color for p in parts} | {norm_color(spec.frame_color), back_color}
    room = WHITE in used or len(used) < 4  # white must not become a 5th filament in auto mode
    want_white = spec.interior_white == "on" or (spec.interior_white == "auto" and luminance(back_color) < 0.35
                                                 and back_color != WHITE and room)
    if want_white:
        slab = solid(lip_in.buffer(-0.2), tb - INTERIOR_WHITE_T, tb)  # just inside the lip (0.2 mm green border): the lip stands on solid plate, no coincident edges
        white_m = back_m ^ slab
        green_m = back_m - slab
        parts.append(Part("back", "back", to_mesh(green_m), back_color, 1, group="back"))
        parts.append(Part("back_white", "back", to_mesh(white_m), WHITE, 1, group="back"))
    else:
        parts.append(Part("back", "back", to_mesh(back_m), back_color, 1, group="back"))
    if plan.extra_parts_fn:
        for ep in plan.extra_parts_fn(ctx):
            ep.color = norm_color(spec.stand_color or spec.frame_color)
            parts.append(ep)
    cover_top = tb + ch_h + COVER_LIFT + COVER_T
    if cover_on:
        z_top0 = tb + ch_h + COVER_LIFT
        items = []
        for ln in cover_lines:
            items.append(solid(ln.buffer(cov_out, cap_style="flat"), z_top0, z_top0 + COVER_T))
            legs = ln.buffer(cov_out, cap_style="flat").difference(ln.buffer(ch_out + COVER_CLEAR, cap_style="flat"))
            items.append(solid(legs, z_top0 - COVER_LEG_H, z_top0 + 0.01))
        cov_part = Part("led_cover", "cover", to_mesh(union(items)), norm_color(hw.diffuser(spec.diffuser).color), 1, group="cover")
        cov_part.meta["print_rot"] = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])
        parts.append(cov_part)

    # ---- print orientation + extruders ---------------------------------------------------
    order = assign_extruders(parts)
    rot = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]) if flip else np.eye(4)
    face_ps = [p for p in parts if p.group == "face"]
    zmin = min(float((p.mesh_wall.vertices @ rot[:3, :3].T)[:, 2].min()) for p in face_ps)
    tz = np.eye(4)
    tz[2, 3] = -zmin
    groups: dict[str, list[Part]] = {}
    for p in parts:
        groups.setdefault(p.group, []).append(p)
    for g, ps in groups.items():
        if g == "face":
            for p in ps:
                p.print_transform = tz @ rot
            continue
        r = ps[0].meta.get("print_rot", np.eye(4))
        zm = min(float((p.mesh_wall.vertices @ r[:3, :3].T)[:, 2].min()) for p in ps)
        t = np.eye(4)
        t[2, 3] = -zm
        for p in ps:
            p.print_transform = t @ r

    # ---- virtual parts for checks ----------------------------------------------------------
    led_t = led.thickness_mm
    solids = {p.name: from_trimesh(p.mesh_wall) for p in parts}
    solids["_led_strips"] = union([solid(s, tb, tb + led_t) for s in strips])
    solids["_controller"] = solid(controller_box, tb, tb + cH)
    z_light = D - light_back
    gap = z_light - (tb + led_t)
    if gap < min_gap - 1e-6:
        warnings.append(f"LED-to-face gap {gap:.1f} mm is below the {min_gap:.0f} mm needed for {spec.led} behind {spec.diffuser}: "
                        f"hot spots visible; increase the depth to >= {D + (min_gap - gap):.0f} mm.")
    if channel and z_light - (cover_top if cover_on else tb + ch_h) < 2.0:
        warnings.append("LED kanalı/kapağı ön yüze 2 mm'den fazla yaklaşıyor: derinliği artırın.")
    if cover_on:
        meta_notes.append("LED kanal kapakları difüzör renginde basılır, kanal duvarlarına üstten geçer; sıcak noktaları azaltır, ışığı biraz kısar.")
    if (D - fdepth) - (tb + cH) < 1.0:
        warnings.append("Controller is taller than the free depth; increase depth.")
    if not want_white and luminance(back_color) < 0.35:
        warnings.append("Interior is dark (interior_white=off): less light output.")
    if luminance(spec.frame_color) < 0.35 and spec.interior_white != "off":
        meta_notes.append("body walls stay in the frame colour (a white inner wall layer would need a colour change on every layer); "
                          "only the back cover interior is white")
    power, power_warn = power_report(hw, spec.led, path.total_length_mm)
    power["n_leds"] = path.n_leds
    warnings.extend(power_warn)
    meta = {
        "design": plan.kind, "mount": spec.mount, "led": spec.led, "controller": spec.controller, "diffuser": spec.diffuser,
        "lit": spec.lit, "diffuser_thickness_mm": t_light, "min_gap_mm": min_gap, "gap_mm": round(gap, 2),
        "tb_mm": tb, "wall_mm": wall, "clearance_mm": CLEAR, "lip_h_mm": LIP_H, "lip_w_mm": plan.lip_w,
        "colors": order, "extruders": len(order), "relief": spec.relief, "face_down": flip, "power": power,
        "n_bosses": len(boss_c), "led_mount": spec.led_mount, "channel_cover": bool(cover_on), "covered_pieces": len(cover_lines), "diffusion_mm": spec.diffusion_mm,
        "channel": ({"inner_w_mm": round(2 * ch_in, 2), "wall_mm": CH_WALL, "height_mm": round(ch_h, 2)} if channel else None),
        "holes": hole_meta, "controller_mode": pocket_mode, "controller_used": ctrl.id, "controller_bom": spec.controller if pocket_mode == "external" else ctrl.id, "interior_white": bool(want_white), "notes": meta_notes, "led_coverage": round(cov, 3),
        "led_path": {"kind": path.kind, "joint": path.joint, "row_pitch_mm": round(path.row_pitch_mm, 2), "cut_list": path.cut_list,
                     "jumper_wire_total_mm": round(path.wire_total_mm, 1),
                     "segments": [[list(c[:2]) for c in s.line.coords] for s in path.segments]},
        "controller_pocket": {"center": [pk_cx, pk_cy], "size": [pk_w, pk_h], "controller": [cL, cW, cH], "vertical": pk.vertical,
                              "controller_polygon": [list(c) for c in controller_box.exterior.coords]},
        "cable_slot": [cable_x, cable_y],
        "polys": {"outline": outline, "window": window, "inner": inner, "lip_out": lip_out, "lip_in": lip_in,
                  "boss_zone": boss_zone, "cradle": cradle_out, "pocket_in": pocket_in},
        **plan.meta,
    }
    model = Model(plan.kind, parts, W, H, D, warnings, meta)
    box_ = LightBox(model, spec, path, fr, solids, layers=layers)
    box_.report = assembly_report(box_)
    warnings += box_.report["problems"]
    warnings[:] = list(dict.fromkeys(warnings))
    return box_
