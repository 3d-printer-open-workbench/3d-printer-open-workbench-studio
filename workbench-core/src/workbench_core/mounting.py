"""Mounting features: keyhole, through holes, connector bar (all mm).

All coordinates here are *wall orientation* (x right, y up, back at z = 0).
Features are recorded in ``model.meta["mounting"]`` for the template (M6) and job.json.
Unsupported/unfitting features are skipped with a warning, never fatal.
"""
from __future__ import annotations

import copy
import math
from typing import Iterable

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from .geometry import (
    Model,
    Part,
    cylinder,
    extrude,
    from_trimesh,
    mesh_footprint,
    to_trimesh,
)
from .text2d import TextResult, _polys_only

MOUNTING_OPTIONS = ("tape", "keyhole", "holes", "connector_bar")

KEYHOLE_HEAD_D = 8.0
KEYHOLE_SHANK_D = 4.0
KEYHOLE_SLOT_LEN = 10.0
KEYHOLE_MIN_DEPTH = 8.0
KEYHOLE_CHAMBER_DEPTH = 5.0  # chamber floor measured from the back
KEYHOLE_LIP = 1.5  # back lip the screw head hooks behind
KEYHOLE_MARGIN = 2.0
HOLE_D = 3.0
HOLE_MARGIN = 2.0
BAR_W = 10.0
BAR_T = 4.0
BAR_CLEARANCE = 0.2
STRIP_H = 4.0
BRIDGE_W = 3.0
BRIDGE_T = 2.0
BRIDGE_MAX_LEN = 40.0


def normalize_mounting(mounting: Iterable[str] | None) -> list[str]:
    out = []
    for m in mounting or ["tape"]:
        if m not in MOUNTING_OPTIONS:
            raise ValueError(f"unknown mounting option {m!r}; choose from {MOUNTING_OPTIONS}")
        if m not in out:
            out.append(m)
    return out


# --------------------------------------------------------------------------- #
# Mode A baseline strip (2D, before extrusion)
# --------------------------------------------------------------------------- #
def connect_flat_layout(layout: TextResult) -> TextResult:
    """Return a layout whose geometry is joined by a 4 mm baseline strip per line."""
    strips = []
    for li, base in enumerate(layout.line_baselines):
        line_geoms = [g.geometry for g in layout.glyphs if g.line == li]
        if len(line_geoms) < 2:
            continue
        minx = min(g.bounds[0] for g in line_geoms)
        maxx = max(g.bounds[2] for g in line_geoms)
        strips.append(box(minx, base, maxx, base + STRIP_H))
    if not strips:
        return layout
    out = copy.copy(layout)
    out.geometry = _polys_only(unary_union([layout.geometry, *strips]))
    out.warnings = list(layout.warnings)
    if len(layout.lines) > 1:
        out.warnings.append(
            "connector_bar on a multi-line flat sign joins each line separately; lines are not connected."
        )
    return out


# --------------------------------------------------------------------------- #
# Placement helpers
# --------------------------------------------------------------------------- #
def keyhole_shape(cx: float, cy: float, r: float) -> BaseGeometry:
    """Stadium: circle radius r at (cx, cy) swept up by the slot length."""
    return LineString([(cx, cy), (cx, cy + KEYHOLE_SLOT_LEN)]).buffer(r, quad_segs=16)


def find_keyhole(geom: BaseGeometry, target: tuple[float, float] | None = None, step: float = 2.0):
    """Head-center (cx, cy) for a keyhole whose whole stadium (plus margin) lies inside geom."""
    reach = KEYHOLE_HEAD_D / 2 + KEYHOLE_MARGIN
    core = geom.buffer(-reach, join_style="round")
    if core.is_empty:
        return None
    minx, miny, maxx, maxy = geom.bounds
    if target is None:
        target = ((minx + maxx) / 2, miny + 0.65 * (maxy - miny) - KEYHOLE_SLOT_LEN / 2)
    best, best_d = None, math.inf
    x = minx
    while x <= maxx:
        y = miny
        while y <= maxy:
            seg = LineString([(x, y), (x, y + KEYHOLE_SLOT_LEN)])
            if core.contains(seg):
                d = math.hypot(x - target[0], y - target[1])
                if d < best_d:
                    best, best_d = (x, y), d
            y += step
        x += step
    return best


def find_hole_pair(geom: BaseGeometry):
    """Two through-hole centers near the left/right ends at mid height, inside geom."""
    core = geom.buffer(-(HOLE_D / 2 + HOLE_MARGIN), join_style="round")
    if core.is_empty:
        return []
    minx, miny, maxx, maxy = geom.bounds
    cy = (miny + maxy) / 2
    pts = []
    line = LineString([(minx - 1, cy), (maxx + 1, cy)])
    hit = core.intersection(line)
    if hit.is_empty:
        # fall back: nearest core points to the left/right ends of the mid line
        left = nearest_points(core, Point(minx, cy))[0]
        right = nearest_points(core, Point(maxx, cy))[0]
        pts = [(left.x, left.y), (right.x, right.y)]
    else:
        xs = [c[0] for g in getattr(hit, "geoms", [hit]) for c in g.coords]
        pts = [(min(xs), cy), (max(xs), cy)]
    if abs(pts[0][0] - pts[1][0]) < 20:
        pts = pts[:1]
    return pts


def _footprint(parts: list[Part]) -> BaseGeometry:
    return unary_union([mesh_footprint(p.mesh_wall) for p in parts])


def _part_footprint(part: Part) -> BaseGeometry:
    return mesh_footprint(part.mesh_wall)


def _cut(part: Part, tool) -> None:
    mesh = to_trimesh(from_trimesh(part.mesh_wall) - tool)
    part.mesh_wall = mesh


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
def apply_mounting(model: Model, mounting: Iterable[str] | None) -> Model:
    """Apply keyhole / holes / (Mode B) connector_bar. Mutates and returns ``model``.

    Mode A ``connector_bar`` (baseline strip) must be applied at layout level via
    :func:`connect_flat_layout` (done by ``make_flat``).
    """
    mounting = normalize_mounting(mounting)
    info = model.meta.setdefault("mounting", {"selected": mounting, "keyholes": [], "holes": [], "rail": None, "skipped": []})
    info["selected"] = mounting

    def skip(msg: str) -> None:
        model.warnings.append(msg)
        info["skipped"].append(msg)

    if "keyhole" in mounting:
        _apply_keyholes(model, info, skip)
    if "holes" in mounting:
        _apply_holes(model, info, skip)
    if "connector_bar" in mounting and model.mode == "letters":
        _apply_rail(model, info, skip)
    return model


def _keyhole_cut(cx: float, cy: float):
    entry = unary_union(
        [Point(cx, cy).buffer(KEYHOLE_HEAD_D / 2, quad_segs=16), keyhole_shape(cx, cy, KEYHOLE_SHANK_D / 2)]
    )
    chamber = keyhole_shape(cx, cy, KEYHOLE_HEAD_D / 2)
    return extrude(entry, -1.0, KEYHOLE_LIP) + extrude(chamber, KEYHOLE_LIP, KEYHOLE_CHAMBER_DEPTH)


def _apply_keyholes(model: Model, info: dict, skip) -> None:
    if model.mode == "flat":
        style = model.meta.get("style")
        if style == "backplate":
            if model.meta.get("keyhole_boss"):
                return _add_boss(model, info, skip)
            return skip("keyhole skipped: backplate is only 3 mm thick; enable keyhole_boss to add a round boss for it.")
        if model.meta.get("thickness", 0) < 10:
            return skip("keyhole skipped: Mode A needs 10 mm thickness (>= 8 mm depth).")
        body = max(model.parts, key=lambda q: q.mesh_wall.volume)  # largest body carries the keyhole
        geom = _part_footprint(body)
        minx, _, maxx, _ = geom.bounds
        targets = [None] if (maxx - minx) < 300 else [
            (minx + 0.25 * (maxx - minx), None),
            (minx + 0.75 * (maxx - minx), None),
        ]
        spots = []
        for t in targets:
            tgt = None
            if t is not None:
                _, miny, _, maxy = geom.bounds
                tgt = (t[0], miny + 0.65 * (maxy - miny) - KEYHOLE_SLOT_LEN / 2)
            s = find_keyhole(geom, tgt)
            if s is not None:
                spots.append(s)
        if not spots:
            return skip(
                "keyhole skipped: no solid area large enough (needs ~12 mm wide x 22 mm tall); "
                "use a thicker font or the backplate/holes option."
            )
        for cx, cy in spots:
            _cut(body, _keyhole_cut(cx, cy))
            info["keyholes"].append({"part": body.name, "x": cx, "y": cy, "angle_deg": 0})
        return
    # letters
    if model.depth_mm < KEYHOLE_MIN_DEPTH:
        return skip("keyhole skipped: depth < 8 mm.")
    if model.meta.get("construction") == "open_back_shell":
        return skip("keyhole skipped: not supported with open_back_shell (hollow back).")
    for part in model.parts:
        if part.role != "letter":
            continue
        geom = _part_footprint(part)
        spot = find_keyhole(geom)
        if spot is None:
            skip(f"keyhole skipped for '{part.name}': no solid area large enough (needs ~12 x 22 mm).")
            continue
        _cut(part, _keyhole_cut(*spot))
        info["keyholes"].append({"part": part.name, "x": spot[0], "y": spot[1], "angle_deg": 0})


BOSS_D = 30.0
BOSS_T = 6.0


def _add_boss(model: Model, info: dict, skip) -> None:
    """Round boss (30 mm, 6 mm thick) behind the backplate carrying the keyhole.

    It is a separate part glued to the plate back (a protruding boss cannot be printed
    unioned with a sign that lies back-down on the bed). Wall coordinates: z -6 .. 0."""
    plate = model.parts[0]
    foot = _part_footprint(plate)
    core = foot.buffer(-(BOSS_D / 2 + 0.3))
    if core.is_empty:
        return skip("keyhole_boss skipped: plate too small for a 30 mm boss.")
    minx, miny, maxx, maxy = foot.bounds
    target = Point((minx + maxx) / 2, miny + 0.6 * (maxy - miny))
    c = nearest_points(core, target)[0]
    cx, cy = c.x, c.y
    hx, hy = cx, cy - KEYHOLE_SLOT_LEN / 2  # head centre so the stadium is centred in the boss
    local = extrude(Point(cx, cy).buffer(BOSS_D / 2, quad_segs=32), 0.0, BOSS_T) - _keyhole_cut(hx, hy)
    mesh = to_trimesh(local.translate((0.0, 0.0, -BOSS_T)))
    flip = np.array([[1, 0, 0, 0], [0, -1, 0, 2 * cy], [0, 0, -1, 0], [0, 0, 0, 1]], dtype=float)
    boss = Part("keyhole_boss", "boss", mesh, plate.color, plate.extruder, flip, {"glue_to": plate.name}, "keyhole_boss")
    model.parts.append(boss)
    info["keyholes"].append({"part": "keyhole_boss", "x": hx, "y": hy, "angle_deg": 0, "boss": [cx, cy, BOSS_D]})
    model.warnings.append("keyhole_boss: print the boss separately and glue it to the plate back (Ø30 mm, centred on the marked position).")


def _apply_holes(model: Model, info: dict, skip) -> None:
    if model.mode != "flat":
        return skip("holes skipped: through holes are only for Mode A (flat signs).")
    foot = _footprint(model.parts)
    spots = find_hole_pair(foot)
    if not spots:
        return skip("holes skipped: no solid area large enough for a 3 mm hole with 2 mm margin.")
    if len(spots) == 1:
        model.warnings.append("holes: only one hole fits (sign too narrow or thin for two).")
    zmax = max(p.mesh_wall.bounds[1][2] for p in model.parts)
    for x, y in spots:
        tool = cylinder(HOLE_D / 2, zmax + 4.0, "z", (x, y, zmax / 2))
        for p in model.parts:
            _cut(p, tool)
        info["holes"].append({"x": x, "y": y, "diameter": HOLE_D})


def _apply_rail(model: Model, info: dict, skip) -> None:
    letters = [p for p in model.parts if p.role == "letter"]
    if len(letters) < 2:
        return skip("connector_bar skipped: needs at least two letter parts.")
    if model.depth_mm < BAR_T + 6:
        return skip("connector_bar skipped: depth too small for a 4 mm recess.")
    foots = {p.name: _part_footprint(p) for p in letters}
    allg = unary_union(list(foots.values()))
    minx, miny, maxx, maxy = allg.bounds
    cap = model.layout.cap_height_mm if model.layout else (maxy - miny)
    base = model.layout.baseline_y if model.layout else miny
    # choose the band centre where the thinnest-covered letter still has the most material
    best_y, best_score = None, -1.0
    for k in range(0, 41):
        yc = base + cap * (0.25 + 0.5 * k / 40)
        band = box(minx - 1, yc - BAR_W / 2, maxx + 1, yc + BAR_W / 2)
        score = min(f.intersection(band).area for f in foots.values())
        if score > best_score:
            best_y, best_score = yc, score
    if best_score <= 0:
        return skip("connector_bar skipped: no common height crosses all letters.")
    yc = best_y
    band = box(minx - 1, yc - BAR_W / 2 - BAR_CLEARANCE, maxx + 1, yc + BAR_W / 2 + BAR_CLEARANCE)
    # attach detached dots/accents to their letter with a tiny back bridge
    bridged = 0
    for p in letters:
        if "detached_pieces" not in p.meta:
            continue
        geom = foots[p.name]
        polys = sorted(getattr(geom, "geoms", [geom]), key=lambda g: -g.area)
        main = polys[0]
        for det in polys[1:]:
            a, b = nearest_points(main, det)
            if a.distance(b) > BRIDGE_MAX_LEN:
                skip(f"connector_bar: accent of '{p.name}' is too far to bridge ({a.distance(b):.0f} mm).")
                continue
            direction = np.array([b.x - a.x, b.y - a.y])
            norm = np.linalg.norm(direction)
            ext = direction / norm * 1.0 if norm > 0 else np.zeros(2)
            line = LineString([(a.x - ext[0], a.y - ext[1]), (b.x + ext[0], b.y + ext[1])])
            bridge = line.buffer(BRIDGE_W / 2, cap_style="flat")
            p.mesh_wall = to_trimesh(from_trimesh(p.mesh_wall) + extrude(bridge, 0.0, BRIDGE_T))
            p.meta.setdefault("bridges", []).append({"from": [a.x, a.y], "to": [b.x, b.y]})
            bridged += 1
    for p in letters:
        inter = foots[p.name].intersection(band)
        if inter.is_empty:
            skip(f"connector_bar: '{p.name}' does not reach the rail height.")
            continue
        fx0, _, fx1, _ = foots[p.name].bounds
        # cutting with the plain band box (not the footprint intersection) avoids sliver faces
        _cut(p, extrude(box(fx0 - 1, band.bounds[1], fx1 + 1, band.bounds[3]), -1.0, BAR_T + BAR_CLEARANCE))
        p.meta["rail_channel"] = True
    # rail segments (each <= 245 mm), cut inside letters so every segment is anchored
    length = maxx - minx
    max_seg = 245.0
    n = math.ceil(length / max_seg)
    cuts = []
    if n > 1:
        spans = [(foots[p.name].bounds[0], foots[p.name].bounds[2]) for p in letters]
        for k in range(1, n):
            ideal = minx + length * k / n
            lo = (cuts[-1] if cuts else minx) + 0.0
            # every segment <= max_seg: cut in [lo.., lo+max_seg] and not too early
            hi = lo + max_seg
            cand = [
                (abs((a + b) / 2 - ideal), (a + b) / 2)
                for a, b in spans
                if lo + 20 < (a + b) / 2 <= hi
            ]
            cuts.append(min(cand)[1] if cand else min(ideal, hi))
    edges = [minx, *cuts, maxx]
    letter_color, letter_ext = letters[0].color, letters[0].extruder
    for i, (x0, x1) in enumerate(zip(edges, edges[1:]), start=1):
        mesh = to_trimesh(extrude(box(x0, yc - BAR_W / 2, x1, yc + BAR_W / 2), 0.0, BAR_T))
        name = "rail" if n == 1 else f"rail_{i}"
        model.parts.append(Part(name, "rail", mesh, letter_color, letter_ext, group=name))
    info["rail"] = {
        "y_center": yc, "x_min": minx, "x_max": maxx, "width": BAR_W, "thickness": BAR_T,
        "segments": n, "cuts": cuts, "bridges": bridged,
    }
