"""Shared 2.5D helpers for flat products (keychains, QR plaques, pet tags): fitting text into a region, ring tabs,
NFC pockets and colour layers stacked in z.

Colours are stacked, never side by side in the same layer: the base is one colour, everything raised on it starts at
the base top. A multi-colour piece therefore needs one filament change per extra colour, not one per layer
(minimum purge waste and time on the CANVAS)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polylabel, unary_union

from . import core, estimate
from .generators.base import Part

MIN_STROKE = 0.8  # raised text on a flat part: two 0.4 mm lines (Kaligraf's 2 mm is for free-standing letters)
RING_WALL = 2.5  # around the key ring hole
NFC_FLOOR = 1.0  # plastic under the NFC pocket
NFC_ROOF = 0.8  # plastic over it


def fit_geometry(g, region, warnings: list[str], what: str = "Yazı", centre=None):
    """Place ``g`` inside ``region`` as large as possible (scale <= 1, 5 % steps down to 30 %): centred on the visual
    centre, also tried a little higher / lower (hearts, shields are wider up top). Returns (geometry, scale)."""
    poly = region if region.geom_type == "Polygon" else max(region.geoms, key=lambda q: q.area)
    gx0, gy0, gx1, gy1 = g.bounds
    h = region.bounds[3] - region.bounds[1]
    best = None
    if centre:
        tries = [centre]
    else:  # polylabel is arbitrary along long thin regions: also try the centroid
        cs = [polylabel(poly, tolerance=0.3)] + ([poly.centroid] if poly.contains(poly.centroid) else [])
        tries = [Point(c.x, c.y + dy * h) for c in cs for dy in (0.0, 0.08, -0.08, 0.16, -0.16, 0.24, -0.24)]
    for cc in tries:
        q = affinity.translate(g, cc.x - (gx0 + gx1) / 2, cc.y - (gy0 + gy1) / 2)
        k = 1.0
        while not region.contains(q) and k > 0.3:
            q = affinity.scale(q, 0.95, 0.95, origin=cc)
            k *= 0.95
        ok = region.contains(q)
        if best is None or (ok, k) > (best[2], best[1]):
            best = (q, k, ok)
        if ok and k > 0.999:
            break
    g, k, ok = best
    if not ok:
        warnings.append(f"{what} bu alana sığmıyor; daha kısa bir yazı ya da daha büyük bir boyut seçin.")
    elif k < 0.999:
        warnings.append(f"{what} alana sığsın diye %{round(k * 100)} oranında küçültüldü.")
    return g, k


def text(s: str, font: str, warnings: list[str], width_mm: float | None = None, height_mm: float | None = None):
    """Text outline ``width_mm`` wide or with capitals ``height_mm`` tall."""
    g, w = core.text_geometry(s, font, width_mm=width_mm, cap_height_mm=height_mm, min_feature_mm=MIN_STROKE)
    warnings += [x for x in w if x not in warnings]
    return g


def fit_text(s: str, font: str, region, width_mm: float, warnings: list[str], what: str = "Yazı", centre=None):
    """Text ``width_mm`` wide placed in ``region`` (shrunk if needed); the stroke check runs at the final size."""
    probe: list[str] = []
    g, k = fit_geometry(text(s, font, probe, width_mm=width_mm), region, probe, what, centre)
    if k < 0.999:
        g2, k2 = fit_geometry(text(s, font, [], width_mm=width_mm * k), region, [], what, centre)
        if k2 > 0.999:
            g = g2
        own: list[str] = []
        text(s, font, own, width_mm=width_mm * k)
        probe = [x for x in probe if "ince" not in x] + own
    g = thicken(g, probe, what, region)
    warnings += [x for x in probe if x not in warnings]
    return g, k


def thicken(g, warnings: list[str], what: str = "Yazı", region=None):
    """Small text: thicken strokes thinner than MIN_STROKE by up to 0.3 mm per side (staying inside ``region``);
    on success the thin-stroke warnings in ``warnings`` are replaced by an info line."""
    if not core.thin_regions(g, MIN_STROKE):
        return g
    for d in (0.1, 0.2, 0.3):
        gb = g.buffer(d, quad_segs=6)
        if region is not None and not region.contains(gb):
            break
        if not core.thin_regions(gb, MIN_STROKE):
            warnings[:] = [x for x in warnings if "ince" not in x] + [f"{what}: ince çizgiler {2 * d:.1f} mm kalınlaştırıldı (basılabilsin diye)."]
            return gb
    return g


def bubble(g, border: float):
    """Single outline ``border`` mm around the geometry; pieces further apart are bridged by a wider closing."""
    for extra in (0.0, 1.5, 3.0, 5.0, 8.0):
        b = g.buffer(border + extra, quad_segs=16)
        if extra:
            b = b.buffer(-extra, quad_segs=16)
        if b.geom_type == "Polygon":
            return Polygon(b.exterior)
    return Polygon(max(b.geoms, key=lambda q: q.area).exterior)


def band(region, y0: float, y1: float):
    """Part of ``region`` between two heights."""
    x0, _, x1, _ = region.bounds
    return region.intersection(box(x0 - 1, y0, x1 + 1, y1))


def _edge_point(outline, side: str, at: float | None = None) -> tuple[Point, tuple[float, float]]:
    """Point where a line through the outline's middle (or through x / y = ``at``) leaves it on ``side`` and the
    outward direction."""
    x0, y0, x1, y1 = outline.bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if at is not None:
        cx = cy = at
    if side == "top":
        line, d = LineString([(cx, y0 - 1), (cx, y1 + 1)]), (0.0, 1.0)
    else:
        line, d = LineString([(x0 - 1, cy), (x1 + 1, cy)]), (-1.0, 0.0)
    pts = outline.boundary.intersection(line)
    pts = [pts] if pts.geom_type == "Point" else [q for q in getattr(pts, "geoms", []) if q.geom_type == "Point"]
    if not pts:  # thin outlines: fall back to the extreme vertex
        coords = list(outline.exterior.coords)
        p = max(coords, key=lambda q: q[1]) if side == "top" else min(coords, key=lambda q: q[0])
        return Point(p), d
    return (max(pts, key=lambda q: q.y) if side == "top" else min(pts, key=lambda q: q.x)), d


def ring_tab(outline, side: str = "left", hole_d: float = 5.0, wall: float = RING_WALL, at: float | None = None):
    """Outline with a key ring eye on ``side`` ("left" / "top") and the hole polygon (cut through every layer).
    ``at``: x (top) or y (left) of the eye instead of the outline's middle."""
    p, (dx, dy) = _edge_point(outline, side, at)
    r = hole_d / 2
    c = Point(p.x + dx * (r + 1.0), p.y + dy * (r + 1.0))
    eye = c.buffer(r + wall, quad_segs=24)
    neck = unary_union([eye, Point(p.x, p.y).buffer(r + wall * 0.6, quad_segs=16)]).convex_hull
    shape = unary_union([outline, eye, neck]).buffer(1.5, quad_segs=12).buffer(-1.5, quad_segs=12)
    if shape.geom_type != "Polygon":
        shape = max(shape.geoms, key=lambda q: q.area)
    return Polygon(shape.exterior), c.buffer(r, quad_segs=24)


@dataclass
class Pocket:
    shape: Polygon
    z0: float
    z1: float
    pause_z: float  # Orca pauses before printing the layer at this height


def nfc_pocket(outline, diameter: float, thickness: float, warnings: list[str], keep_out=None) -> Pocket | None:
    """Closed pocket for an NFC sticker/coin inside the base, at the outline's visual centre; ``None`` if it does not fit."""
    pocket = Point(0, 0).buffer(diameter / 2 + 0.25, quad_segs=32)
    room = outline.buffer(-1.5)
    if keep_out is not None:
        room = room.difference(keep_out.buffer(1.5))
    if room.is_empty:
        warnings.append("NFC yuvası bu boyuta sığmıyor; anahtarlığı büyütün ya da daha küçük etiket seçin.")
        return None
    c = polylabel(room if room.geom_type == "Polygon" else max(room.geoms, key=lambda q: q.area), tolerance=0.2)
    pocket = affinity.translate(pocket, c.x, c.y)
    if not room.contains(pocket):
        warnings.append(f"Ø{diameter:g} mm NFC etiketi bu şekle sığmıyor (en az 1.5 mm duvar gerekir); yuva eklenmedi.")
        return None
    lh = core.LAYER_H
    depth = math.ceil((thickness + 0.2) / lh - 1e-6) * lh
    z1 = NFC_FLOOR + depth
    return Pocket(pocket, NFC_FLOOR, z1, round(z1 + lh, 2))


def slab(g, z0: float, z1: float):
    return core.to_trimesh(core.extrude(g, z0, z1))


def layer_parts(layers: list[tuple[str, str, object, float, float, str]], group: str, *, material: str = "PLA",
                cuts=None, pocket: Pocket | None = None) -> list[Part]:
    """Parts from colour layers (name, Turkish label, polygon, z0, z1, colour) as one print object ``group``.

    Layers of the same colour are merged into one part (fewer objects, no internal walls). ``cuts`` (polygon) is removed
    from every layer (key ring hole); ``pocket`` is a closed void in the first layer (NFC tag)."""
    by_color: dict[str, list] = {}
    for name, label, g, z0, z1, color in layers:
        if g is None or g.is_empty or z1 <= z0:
            continue
        if cuts is not None:
            g = g.difference(cuts)
        by_color.setdefault(color.upper(), []).append((name, label, core.extrude(g, z0, z1)))
    parts = []
    for i, (color, items) in enumerate(by_color.items()):
        name, label = items[0][0], items[0][1]
        solid = core.union_all([m for _, _, m in items])
        if i == 0 and pocket is not None:
            solid = solid - core.extrude(pocket.shape, pocket.z0, pocket.z1)
        mesh = core.to_trimesh(solid)
        e = estimate.part_estimate(mesh, material, "flat")
        meta = {"group": group, "grams": e.grams, "minutes": e.minutes, "cost_try": e.try_}
        if i == 0 and pocket is not None:
            meta["pause_z"] = pocket.pause_z
        if len(items) > 1:
            label = " + ".join(dict.fromkeys(lb for _, lb, _ in items))
        parts.append(Part(name, label, mesh, color, material, meta))
    return parts


def waves(centre, size: float, stroke: float, angle_deg: float = 0.0, n: int = 3, dot: bool = True):
    """WiFi-style icon (dot + ``n`` arcs opening upwards), ``size`` mm tall; rotated -90 deg it is the NFC sign."""
    import numpy as np

    pieces = []
    r0 = size / (n + 1.2)
    if dot:
        pieces.append(Point(0, 0).buffer(stroke * 0.9, quad_segs=12))
    a = np.radians(np.linspace(45, 135, 24))
    for i in range(1, n + 1):
        r = r0 * (i + 0.2)
        pieces.append(LineString(np.c_[r * np.cos(a), r * np.sin(a)]).buffer(stroke / 2, cap_style=1, quad_segs=8))
    g = unary_union(pieces)
    g = affinity.translate(g, 0, -(g.bounds[1] + g.bounds[3]) / 2)
    g = affinity.rotate(g, angle_deg, origin=(0, 0))
    return affinity.translate(g, centre[0], centre[1])


def slot_stand(width: float, thick: float, angle: float = 75.0, clear: float = 0.3, depth: float = 26.0, height: float = 11.0):
    """Desk stand block (``width`` / 2 long) with a slot leaning back ``angle`` deg from horizontal for a plate
    ``thick`` mm (+ ``clear`` per side); prints flat on its base, no support. Returns (mesh, length)."""
    import numpy as np

    L = width * 0.5
    blk = core.extrude(box(-L / 2, -depth / 2, L / 2, depth / 2).buffer(-2, quad_segs=8).buffer(2, quad_segs=8), 0.0, height)
    s = thick + 2 * clear
    slot = core.to_trimesh(core.extrude(box(-L, -s / 2, L, s / 2), 0.0, 60.0))
    a = -np.radians(90 - angle)
    c, sn = np.cos(a), np.sin(a)
    slot.apply_transform(np.array([[1, 0, 0, 0], [0, c, -sn, 0], [0, sn, c, 0], [0, 0, 0, 1]]))
    slot.apply_translation([0, 2.0, 3.0])  # slot floor 3 mm above the bed, a little behind the middle
    return core.to_trimesh(blk - core.from_trimesh(slot)), L


def stand_preview_parts(group_parts: list[Part], stand_mesh, stand_color: str, y_bottom: float, thick: float,
                        angle: float = 75.0, slot_offset: tuple[float, float, float] = (0.0, 2.0, 3.0)) -> list[Part]:
    """Build non-printable assembled preview parts (plaque/frame tilted inside the stand slot) for ``urun.png`` and ``preview.glb``."""
    import numpy as np

    tf = np.eye(4)
    a = np.radians(angle)
    c, s = np.cos(a), np.sin(a)
    rot = np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]])
    pre = np.eye(4)
    pre[1, 3] = -y_bottom
    pre[2, 3] = -thick / 2.0
    post = np.eye(4)
    post[:3, 3] = list(slot_offset)
    tf = post @ rot @ pre

    preview: list[Part] = [
        Part("stand_preview", "Masa standı (montajlı)", stand_mesh.copy(), stand_color, "PLA",
             {"product": True}, printable=False),
    ]
    for p in group_parts:
        m = p.mesh.copy()
        m.apply_transform(tf)
        preview.append(Part(f"{p.name}_preview", p.label, m, p.color, p.material,
                            {"product": True, "gloss": p.meta.get("gloss", 0)}, printable=False))
    return preview


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
