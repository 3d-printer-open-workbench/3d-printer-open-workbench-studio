"""LED strip path generation: serpentine rows (rect), concentric rings (round), offset rings + rows (contour).

A path is a list of ``Segment`` (one cut strip piece or one continuous bent piece) plus ``Joint``s between
them: ``bend`` (strip bends in-plane with radius >= min bend radius, only used when the layout allows it)
or ``jumper`` (short wire between cut strips).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from .hardware import Led

WIRE_SLACK_MM = 30.0  # extra wire per jumper (strip tails + soldering)


@dataclass
class Segment:
    row: int
    line: LineString
    length_mm: float
    n_cuts: int
    kind: str = "row"  # row | ring | center | fill

    @property
    def p0(self) -> tuple[float, float]:
        return tuple(self.line.coords[0][:2])

    @property
    def p1(self) -> tuple[float, float]:
        return tuple(self.line.coords[-1][:2])


@dataclass
class Joint:
    type: str  # bend | jumper
    a: int
    b: int
    line: LineString
    wire_mm: float = 0.0


@dataclass
class LedPath:
    segments: list[Segment]
    joints: list[Joint]
    row_pitch_mm: float
    total_length_mm: float
    n_leds: int
    cut_list: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    kind: str = "rows"

    @property
    def joint(self) -> str:
        t = {j.type for j in self.joints}
        return "none" if not t else (t.pop() if len(t) == 1 else "mixed")

    def strip_lines(self) -> list[LineString]:
        """Everything the strip occupies: pieces plus bent joints."""
        return [s.line for s in self.segments] + [j.line for j in self.joints if j.type == "bend"]

    def rail_lines(self) -> list[LineString]:
        return [s.line for s in self.segments]

    def polyline(self) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        for s in self.segments:
            pts += [s.p0, s.p1]
        return pts

    @property
    def wire_total_mm(self) -> float:
        return sum(j.wire_mm for j in self.joints if j.type == "jumper")


def _floor_units(length: float, led: Led) -> int:
    return int(math.floor(length / led.cut_pitch_mm + 1e-9))


def _trim_centered(line: LineString, length: float) -> LineString:
    if length >= line.length - 1e-6:
        return line
    s = (line.length - length) / 2
    return substring(line, s, s + length)


def _pieces(geom: BaseGeometry) -> list[LineString]:
    if geom.is_empty:
        return []
    gs = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    out: list[LineString] = []
    for g in gs:
        if isinstance(g, LineString) and g.length > 1e-6:
            out.append(g)
        elif hasattr(g, "geoms"):
            out += _pieces(g)
    return out


def _finish(segs: list[Segment], joints: list[Joint], led: Led, pitch: float, warnings: list[str], kind: str) -> LedPath:
    if not segs:
        raise ValueError("LED strip does not fit (no piece reaches one cut unit)")
    arcs = sum(j.line.length for j in joints if j.type == "bend")
    total = sum(s.length_mm for s in segs) + arcs
    n_leds = int(round(total / 1000.0 * led.leds_per_m)) if led.addressable else 0
    cut_list = [{"piece": i + 1, "kind": s.kind, "row": s.row, "length_mm": round(s.length_mm, 2), "cuts": s.n_cuts,
                 "from_mm": [round(s.p0[0], 1), round(s.p0[1], 1)], "to_mm": [round(s.p1[0], 1), round(s.p1[1], 1)]}
                for i, s in enumerate(segs)]
    joint_list = [{"from_piece": j.a + 1, "to_piece": j.b + 1, "type": j.type,
                   "wire_mm": round(j.wire_mm, 1)} for j in joints]
    path = LedPath(segs, joints, pitch, total, n_leds, cut_list, warnings, kind)
    path.cut_list.append({"joints": joint_list, "jumper_wire_total_mm": round(path.wire_total_mm, 1)})
    return path


def _chain_jumpers(segs: list[Segment]) -> list[Joint]:
    out = []
    for i in range(len(segs) - 1):
        a, b = segs[i].p1, segs[i + 1].p0
        d = math.dist(a, b)
        out.append(Joint("jumper", i, i + 1, LineString([a, b]), d + WIRE_SLACK_MM))
    return out


# --------------------------------------------------------------------------- #
# rect: serpentine rows
# --------------------------------------------------------------------------- #
def _row_ys(allowed: BaseGeometry, n_rows: int) -> tuple[list[float], float]:
    minx, miny, maxx, maxy = allowed.bounds
    span = maxy - miny
    if n_rows == 1 or span < 1e-6:
        return [(miny + maxy) / 2], 0.0
    eps = min(0.2, span / 4)  # a row exactly on the region boundary would intersect it in a point only
    pitch = (span - 2 * eps) / (n_rows - 1)
    return [miny + eps + i * pitch for i in range(n_rows)], pitch


def _jumper_rows(allowed: BaseGeometry, led: Led, ys: list[float], pitch: float) -> tuple[list[Segment], list[Joint]]:
    minx, _, maxx, _ = allowed.bounds
    segs: list[Segment] = []
    for i, y in enumerate(ys):
        row = LineString([(minx - 1, y), (maxx + 1, y)])
        for g in sorted(_pieces(row.intersection(allowed)), key=lambda g: g.bounds[0]):
            n = _floor_units(g.length, led)
            if n < 1:
                continue
            length = n * led.cut_pitch_mm
            mid = (g.bounds[0] + g.bounds[2]) / 2
            x0, x1 = mid - length / 2, mid + length / 2
            if i % 2 == 1:
                x0, x1 = x1, x0
            segs.append(Segment(i, LineString([(x0, y), (x1, y)]), length, n))
    return segs, _chain_jumpers(segs)


def _bend_rows(allowed: BaseGeometry, led: Led, ys: list[float], pitch: float) -> tuple[list[Segment], list[Joint]] | None:
    """One continuous strip: rows joined by half circles (radius pitch/2 >= min bend radius)."""
    n = len(ys)
    minx, _, maxx, _ = allowed.bounds
    ext = []
    for y in ys:
        ps = _pieces(LineString([(minx - 1, y), (maxx + 1, y)]).intersection(allowed))
        if len(ps) != 1:
            return None
        ext.append((ps[0].bounds[0], ps[0].bounds[2]))
    R = pitch / 2
    xt = []
    for i in range(n - 1):
        xt.append(min(ext[i][1], ext[i + 1][1]) - R if i % 2 == 0 else max(ext[i][0], ext[i + 1][0]) + R)
    rows_x = []
    for i in range(n):
        start = ext[0][0] if i == 0 else xt[i - 1]
        end = xt[i] if i < n - 1 else (ext[i][1] if i % 2 == 0 else ext[i][0])
        if i % 2 == 1 and i == n - 1:
            pass
        rows_x.append((start, end))
    # row direction: even -> +x, odd -> -x
    for i, (a, b) in enumerate(rows_x):
        if (i % 2 == 0 and b - a < 1.0) or (i % 2 == 1 and a - b < 1.0):
            return None
    arcs: list[Joint] = []
    ok = allowed.buffer(1e-6)
    for i in range(n - 1):
        yc = (ys[i] + ys[i + 1]) / 2
        th = np.linspace(-math.pi / 2, math.pi / 2, 24) if i % 2 == 0 else np.linspace(-math.pi / 2, -3 * math.pi / 2, 24)
        pts = [(xt[i] + R * math.cos(t), yc + R * math.sin(t)) for t in th]
        arc = LineString(pts)
        if not ok.contains(arc):
            return None
        arcs.append(Joint("bend", i, i + 1, arc, 0.0))
    total = sum(abs(b - a) for a, b in rows_x) + sum(j.line.length for j in arcs)
    over = total - math.floor(total / led.cut_pitch_mm + 1e-9) * led.cut_pitch_mm
    a, b = rows_x[-1]
    rows_x[-1] = (a, b - over if b > a else b + over)  # trim the free end to a whole number of cut units
    if abs(rows_x[-1][1] - rows_x[-1][0]) < 1.0:
        return None
    segs = []
    for i, ((a, b), y) in enumerate(zip(rows_x, ys)):
        ln = LineString([(a, y), (b, y)])
        segs.append(Segment(i, ln, ln.length, 0))
    cuts = int(round(total / led.cut_pitch_mm))
    segs[0].n_cuts = cuts  # whole piece counted on the first row
    return segs, arcs


def serpentine(allowed: BaseGeometry, led: Led, *, pitch_target_mm: float, max_pitch_mm: float | None = None,
               prefer_bend: bool = True) -> LedPath:
    """Horizontal rows over ``allowed`` (region of the strip centre line).

    Prefers a layout without jumper wires (rows joined by U-turns of radius >= min bend radius) when the height
    allows it and the rows are free; otherwise rows are cut strips joined by wire jumpers (warned).
    """
    if allowed.is_empty:
        raise ValueError("no room for the LED strip inside the box")
    span = allowed.bounds[3] - allowed.bounds[1]
    n0 = 1 if span < 1e-6 else max(2, math.ceil(span / pitch_target_mm) + 1)
    max_pitch = max_pitch_mm or 2.0 * pitch_target_mm
    cands = [n0]
    if prefer_bend and n0 > 1:
        for n in range(n0, 1, -1):
            p = (span - 0.4) / (n - 1)
            if p >= 2 * led.min_bend_radius_mm and p <= max_pitch and n not in cands:
                cands.append(n)
        cands = sorted(set(cands), reverse=True)
    for n in cands:
        ys, pitch = _row_ys(allowed, n)
        if n > 1 and pitch >= 2 * led.min_bend_radius_mm and prefer_bend and pitch <= max_pitch:
            res = _bend_rows(allowed, led, ys, pitch)
            if res:
                return _finish(res[0], res[1], led, pitch, [], "rows")
    ys, pitch = _row_ys(allowed, n0)
    segs, joints = _jumper_rows(allowed, led, ys, pitch)
    warnings: list[str] = []
    if len(segs) > 1:
        why = (f"row pitch {pitch:.0f} mm < 2 x min bend radius ({2 * led.min_bend_radius_mm:.0f} mm)"
               if n0 > 1 and pitch < 2 * led.min_bend_radius_mm else "rows are interrupted by walls/controller")
        warnings.append(f"LED rows joined with {len(joints)} wire jumpers ({why}): cut the strip into {len(segs)} pieces "
                        "and solder 5V/GND (+DIN) between them.")
    return _finish(segs, joints, led, pitch, warnings, "rows")


# --------------------------------------------------------------------------- #
# round: concentric rings
# --------------------------------------------------------------------------- #
def concentric(allowed: BaseGeometry, led: Led, *, r_outer: float, pitch_target_mm: float,
               center: tuple[float, float] = (0.0, 0.0)) -> LedPath:
    """Concentric ring pieces (radius >= min bend radius) clipped to ``allowed``; centre filled by a straight piece."""
    r_min = max(led.min_bend_radius_mm, 1.0)
    if r_outer < r_min:
        return serpentine(allowed, led, pitch_target_mm=pitch_target_mm)
    span = r_outer - r_min
    n = 1 if span < 1e-6 else math.ceil(span / pitch_target_mm) + 1
    pitch = 0.0 if n == 1 else span / (n - 1)
    radii = [r_outer - i * pitch for i in range(n)]
    cx, cy = center
    segs: list[Segment] = []
    ok = allowed.buffer(1e-6)
    gap_deg = 6.0  # every ring is open at the bottom (270 deg), where the controller and the cable are
    for k, r in enumerate(radii):
        d = math.degrees(math.asin(min(1.0, 6.0 / max(r, 6.0))))  # ~12 mm wide opening
        a0, a1 = math.radians(270 + max(d, gap_deg / 2)), math.radians(270 + 360 - max(d, gap_deg / 2))
        th = np.linspace(a0, a1, 400)
        ring = LineString([(cx + r * math.cos(t), cy + r * math.sin(t)) for t in th])
        if k % 2 == 1:  # alternate direction so that a ring ends next to the start of the next one
            ring = LineString(list(ring.coords)[::-1])
        pieces = [ring] if ok.contains(ring) else sorted(_pieces(ring.intersection(allowed)), key=lambda g: ring.project(g.interpolate(0)))
        for g in pieces:
            nu = _floor_units(g.length - 0.3, led)
            if nu < 1:
                continue
            ln = substring(g, 0, nu * led.cut_pitch_mm)  # keep the start (chain continuity), trim the tail
            segs.append(Segment(k, ln, ln.length, nu, "ring"))
    # centre: a straight piece across the middle when the innermost ring leaves room
    c_len = _floor_units(2 * (radii[-1] - led.width_mm / 2 - 2.0), led) * led.cut_pitch_mm
    if c_len >= led.cut_pitch_mm:
        ln = LineString([(cx - c_len / 2, cy), (cx + c_len / 2, cy)])
        if ok.contains(ln):
            segs.append(Segment(n, ln, c_len, int(round(c_len / led.cut_pitch_mm)), "center"))
    warnings = []
    if len(segs) > 1:
        warnings.append(f"LED rings are cut strips joined with {len(segs) - 1} wire jumpers (solder 5V/GND (+DIN)).")
    return _finish(segs, _chain_jumpers(segs), led, pitch, warnings, "rings")


# --------------------------------------------------------------------------- #
# contour: inward offset rings (smoothed to the bend radius) + straight fill rows in the thin parts
# --------------------------------------------------------------------------- #
def contour_path(allowed: BaseGeometry, led: Led, *, pitch_target_mm: float) -> LedPath:
    r = led.min_bend_radius_mm
    segs: list[Segment] = []
    covered: list[BaseGeometry] = []
    k = 0
    region = allowed
    while k < 8 and not region.is_empty:
        sm = region.buffer(-r * 0.5, join_style="round").buffer(r * 0.5, join_style="round")  # remove sharp convex corners
        sm = sm.buffer(r * 0.5, join_style="round").buffer(-r * 0.5, join_style="round")  # and sharp concave ones
        sm = sm.intersection(region)
        polys = [p for p in (sm.geoms if hasattr(sm, "geoms") else [sm]) if p.area > 1.0 and p.minimum_rotated_rectangle.length > 0]
        for p in polys:
            for ring in [p.exterior, *p.interiors]:
                nu = _floor_units(ring.length - 0.5, led)
                if nu < 1:
                    continue
                ln = substring(LineString(ring.coords), 0, nu * led.cut_pitch_mm)
                segs.append(Segment(k, ln, ln.length, nu, "ring"))
                covered.append(ring.buffer(0.1))
        k += 1
        region = allowed.buffer(-k * pitch_target_mm)
    cov = unary_union(covered).buffer(pitch_target_mm * 0.6) if covered else Polygon_empty()
    left = allowed.difference(cov)
    fill = 0
    if not left.is_empty:
        minx, miny, maxx, maxy = left.bounds
        y = miny + 0.3
        while y <= maxy:
            row = LineString([(minx - 1, y), (maxx + 1, y)])
            for g in sorted(_pieces(row.intersection(left.buffer(-0.01))), key=lambda g: g.bounds[0]):
                nu = _floor_units(g.length, led)
                if nu >= 1:
                    ln = _trim_centered(g, nu * led.cut_pitch_mm)
                    segs.append(Segment(100 + fill, ln, ln.length, nu, "fill"))
            y += pitch_target_mm
            fill += 1
    segs = _nn_order(segs)
    warnings = []
    if len(segs) > 1:
        warnings.append(f"Contour LED path: {len(segs)} strip pieces joined with wire jumpers (solder 5V/GND (+DIN)).")
    return _finish(segs, _chain_jumpers(segs), led, pitch_target_mm, warnings, "contour")


def Polygon_empty():
    from shapely.geometry import Polygon

    return Polygon()


def _nn_order(segs: list[Segment]) -> list[Segment]:
    if len(segs) < 3:
        return segs
    rest = segs[:]
    cur = rest.pop(0)
    out = [cur]
    while rest:
        j = min(range(len(rest)), key=lambda i: min(math.dist(cur.p1, rest[i].p0), math.dist(cur.p1, rest[i].p1)))
        nxt = rest.pop(j)
        if math.dist(cur.p1, nxt.p1) < math.dist(cur.p1, nxt.p0):
            nxt = Segment(nxt.row, LineString(list(nxt.line.coords)[::-1]), nxt.length_mm, nxt.n_cuts, nxt.kind)
        out.append(nxt)
        cur = nxt
    return out


def coverage(path: LedPath, window: BaseGeometry, reach_mm: float) -> float:
    """Share of the lit window within ``reach_mm`` of a strip."""
    if window.is_empty:
        return 1.0
    strips = unary_union([s.line for s in path.segments]).buffer(reach_mm)
    return float(window.intersection(strips).area / window.area)
