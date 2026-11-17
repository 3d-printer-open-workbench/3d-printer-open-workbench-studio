"""Joined (cursive) text -> one part per letter, cut where the letters join, with a jigsaw lock at every cut.

Script fonts draw a word as one connected shape. For big letters that is one huge part (or a part split by the bed
with straight cuts). Here every letter becomes its own part: between consecutive letters the connecting stroke is cut
at its narrowest place near the letters' contact, and a jigsaw knob (round head on a narrower neck) on one side fits a
matching socket on the other. The knob locks the letters in the plane; parts are pressed together from above (they
are flat extrusions) and may be glued. Strokes too thin for a knob get a plain glued seam and a warning.

All dimensions mm, in layout coordinates (``TextResult``)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import split as shp_split
from shapely.ops import unary_union

from .text2d import Piece, TextResult, _polys_only

CLEARANCE = 0.15   # gap per side between knob and socket (snug PLA fit on a 0.4 mm nozzle)
MIN_NECK = 2.4     # narrowest printable neck (6 lines of 0.4 mm)
WALL = 1.2         # material kept around a socket
ANGLES = range(-50, 51, 10)  # cut directions tried, degrees from perpendicular to the letters' contact direction


@dataclass
class Joint:
    left: int            # glyph index that keeps the knob
    right: int           # glyph index that gets the socket
    cut: LineString      # the cut segment (mm)
    width: float         # stroke width at the cut
    lock: bool           # False: glued seam only

    def info(self) -> dict:
        (x0, y0), (x1, y1) = self.cut.coords[0], self.cut.coords[-1]
        return {"between": [self.left, self.right], "cut": [[round(x0, 2), round(y0, 2)], [round(x1, 2), round(y1, 2)]],
                "width_mm": round(self.width, 2), "lock": self.lock}


def _polys(g) -> list[Polygon]:
    g = _polys_only(g)
    if g.is_empty:
        return []
    return [g] if isinstance(g, Polygon) else list(g.geoms)


def knob(mid: Point, normal: tuple[float, float], width: float, scale: float = 1.0) -> Polygon:
    """Jigsaw knob starting on the cut line at ``mid`` and pointing along ``normal``; sized from the stroke width."""
    w = width * scale
    neck_w, neck_d, r = 0.34 * w, 0.22 * w, 0.24 * w
    nx, ny = normal
    a = math.degrees(math.atan2(ny, nx))
    shape = unary_union([box(-0.05 * w, -neck_w / 2, neck_d + r * 0.6, neck_w / 2),
                         Point(neck_d + r, 0).buffer(r, quad_segs=16)])
    shape = shape.buffer(0.3, quad_segs=6).buffer(-0.3, quad_segs=6)  # soften the neck corners (printable, no stress point)
    return affinity.translate(affinity.rotate(shape, a, origin=(0, 0)), mid.x, mid.y)


def _share(g: BaseGeometry, region: BaseGeometry) -> float:
    return g.intersection(region).area if not g.is_empty else 0.0


def _best_cut(P: Polygon, A: BaseGeometry, B: BaseGeometry, reach: float):
    """Shortest straight cut through P near the contact of glyph regions A and B that leaves A's own ink on one side
    and B's on the other. Returns (cut LineString, side_A Polygon, side_B Polygon) or None."""
    only_a, only_b = A.difference(B), B.difference(A)
    if only_a.area <= 0 or only_b.area <= 0:
        return None
    contact = A.buffer(0.05).intersection(B.buffer(0.05)).intersection(P)
    if contact.is_empty:
        return None
    c = contact.centroid
    ca, cb = only_a.centroid, only_b.centroid
    base = math.atan2(cb.y - ca.y, cb.x - ca.x) + math.pi / 2  # perpendicular to "from A to B"
    best = None
    step = max(reach / 6, 0.5)
    offsets = [(dx * step, dy * step) for dx in range(-3, 4) for dy in range(-3, 4)]
    far = 4 * reach + 50
    for ang in ANGLES:
        t = base + math.radians(ang)
        ux, uy = math.cos(t), math.sin(t)
        for ox, oy in offsets:
            px, py = c.x + ox, c.y + oy
            if not P.contains(Point(px, py)):
                continue
            line = LineString([(px - ux * far, py - uy * far), (px + ux * far, py + uy * far)])
            seg = None
            for s in getattr(line.intersection(P), "geoms", [line.intersection(P)]):
                if s.geom_type == "LineString" and s.distance(Point(px, py)) < 1e-6:
                    seg = s
                    break
            if seg is None or seg.length <= 0 or (best and seg.length >= best[0]):
                continue
            ext = affinity.scale(seg, 1.02, 1.02)  # reach just past the outline so split() cuts cleanly
            parts = [q for q in getattr(shp_split(P, ext), "geoms", []) if q.area > 1e-6]
            if len(parts) != 2:
                continue
            sa = [(_share(q, only_a), _share(q, only_b)) for q in parts]
            ia = 0 if sa[0][0] - sa[0][1] >= sa[1][0] - sa[1][1] else 1
            qa, qb = parts[ia], parts[1 - ia]
            if _share(qa, only_a) < 0.85 * _share(P, only_a) or _share(qb, only_b) < 0.85 * _share(P, only_b):
                continue
            best = (seg.length, seg, qa, qb)
    return best[1:] if best else None


def _lock(cut: LineString, qa: Polygon, qb: Polygon, width: float):
    """Knob on one side, socket on the other: returns (qa', qb', lock?) trying knob A->B, then B->A, then smaller."""
    (x0, y0), (x1, y1) = cut.coords[0], cut.coords[-1]
    mid = cut.interpolate(0.5, normalized=True)
    nx, ny = (y1 - y0) / cut.length, -(x1 - x0) / cut.length
    if Point(mid.x + nx, mid.y + ny).distance(qb) > Point(mid.x - nx, mid.y - ny).distance(qb):
        nx, ny = -nx, -ny  # (nx, ny) now points from A into B
    smallest = MIN_NECK / (0.34 * width)  # the smallest printable knob (neck = MIN_NECK)
    for scale in sorted({s for s in (1.0, 0.8, 0.65, smallest) if smallest <= s <= 1.0}, reverse=True) or [smallest]:
        for owner, host, sgn in ((qa, qb, 1), (qb, qa, -1)):
            k = knob(mid, (sgn * nx, sgn * ny), width, scale)
            tab = k.intersection(host.buffer(0.01))  # the part of the knob beyond the cut
            if tab.area < 0.3 * k.area:
                continue
            whole = unary_union([owner, host]).buffer(0.01)
            if tab.buffer(CLEARANCE + WALL).difference(whole).area > 0.05:  # socket would break through the outline
                continue
            new_owner = unary_union([owner, tab])
            new_host = host.difference(tab.buffer(CLEARANCE, join_style="mitre"))
            if len(_polys(new_owner)) != 1 or len(_polys(new_host)) != 1:
                continue
            return (new_owner, new_host, True) if sgn == 1 else (new_host, new_owner, True)
    return qa, qb, False


def split_joined(layout: TextResult, *, lock: bool = True) -> tuple[list[Piece], list[Joint], list[str]]:
    """Re-split ``layout.pieces`` so every drawn letter is its own part (see module doc)."""
    glyphs = layout.glyphs
    out: list[Piece] = []
    joints: list[Joint] = []
    warnings: list[str] = []
    for piece in layout.pieces:
        idx = list(piece.glyph_indices)
        if len(idx) == 1:
            out.append(piece)
            continue
        regions = [list(_polys(piece.geometry))]  # working polygons
        for a, b in zip(idx[:-1], idx[1:]):
            A, B = glyphs[a].geometry, glyphs[b].geometry
            for P in [p for p in regions[-1]]:
                if P.intersection(A).area < 1e-3 or P.intersection(B).area < 1e-3:
                    continue
                reach = max(1.0, min(math.sqrt(A.area), math.sqrt(B.area)) * 0.35)
                found = _best_cut(P, A, B, reach)
                if found is None:
                    continue
                cut, qa, qb = found
                w = cut.length
                has_lock = False
                if lock:
                    qa, qb, has_lock = _lock(cut, qa, qb, w)
                    if not has_lock:
                        warnings.append(f"'{glyphs[a].char}{glyphs[b].char}' birleşimi kilit için çok ince ({w:.1f} mm): "
                                        f"bu ek yeri yapıştırılmalı.")
                regions[-1] = [q for q in regions[-1] if q is not P] + _polys(qa) + _polys(qb)
                joints.append(Joint(a, b, cut, w, has_lock))
        # label every final polygon by the letter whose ink it holds most of
        by_glyph: dict[int, list[Polygon]] = {i: [] for i in idx}
        for q in regions[-1]:
            owner = max(idx, key=lambda i: q.intersection(glyphs[i].geometry).area)
            by_glyph[owner].append(q)
        for i in idx:
            if by_glyph[i]:
                g = unary_union(by_glyph[i])
                out.append(Piece(glyphs[i].char, g if isinstance(g, (Polygon, MultiPolygon)) else _polys_only(g), (i,)))
        missing = [glyphs[i].char for i in idx if not by_glyph[i]]
        if missing:
            warnings.append(f"'{piece.text}': {''.join(missing)} ayrı parça yapılamadı (komşu harfle birlikte kaldı).")
    return out, joints, warnings
