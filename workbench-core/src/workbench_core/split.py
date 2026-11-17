"""Bed splitting with alignment pins, and plate packing (print orientation, mm).

* Cut positions are planned per physical group (a letter, or the whole flat sign) from
  the union footprint of its parts, so stacked parts (body/face, plate/glyphs) get
  identical seams.
* A cut is chosen near the equal-division position where it crosses the least material
  and avoids thin (< 8 mm) cross-sections; ideally it runs through a gap (no seam).
* Pin holes (diameter 3.2, 10 mm deep each side, for 3 mm pins/filament) are subtracted
  along the cut normal before slicing, so both halves match exactly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import trimesh
from manifold3d import Manifold
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .geometry import BED_MM, Model, Part, cylinder, from_trimesh, mesh_footprint, to_trimesh

PIN_HOLE_D = 3.2
PIN_HOLE_DEPTH = 10.0
PIN_PIECE_D = 3.0
PIN_MIN_THICKNESS = 5.0  # parts thinner than this get glue-only seams
PIN_WALL = 1.2  # minimum material beside a pin hole
MIN_SUPPORT_MM = 8.0  # a cut segment shorter than this counts as a thin feature
CUT_WINDOW = 40.0


@dataclass
class SplitPiece:
    name: str
    part: Part
    group: str
    cell: tuple[int, int]
    mesh: trimesh.Trimesh  # print orientation, assembled position (mm)


@dataclass
class SplitResult:
    pieces: list[SplitPiece]
    cuts: dict[str, dict[str, list[float]]] = field(default_factory=dict)  # group -> {"x": [...], "y": [...]}
    pins: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Cut planning
# --------------------------------------------------------------------------- #
def _cut_score(footprint: BaseGeometry, axis: str, c: float) -> float:
    minx, miny, maxx, maxy = footprint.bounds
    line = LineString([(c, miny - 1), (c, maxy + 1)]) if axis == "x" else LineString([(minx - 1, c), (maxx + 1, c)])
    inter = footprint.intersection(line)
    segs = [g for g in getattr(inter, "geoms", [inter]) if not g.is_empty and g.length > 1e-6]
    total = sum(g.length for g in segs)
    thin = sum(1 for g in segs if g.length < MIN_SUPPORT_MM)
    return total + 1000.0 * thin


def plan_axis_cuts(footprint: BaseGeometry, axis: str, bed: float = BED_MM) -> list[float]:
    minx, miny, maxx, maxy = footprint.bounds
    lo, hi = (minx, maxx) if axis == "x" else (miny, maxy)
    extent = hi - lo
    n = math.ceil(extent / bed - 1e-9)
    cuts: list[float] = []
    prev = lo
    for k in range(1, n):
        ideal = lo + extent * k / n
        L = max(prev + 1.0, hi - (n - k) * bed)
        U = min(prev + bed, hi - 1.0)
        cl, cu = max(L, ideal - CUT_WINDOW), min(U, ideal + CUT_WINDOW)
        if cl > cu:
            cl, cu = L, U
        best, best_s = None, math.inf
        c = cl
        while c <= cu + 1e-9:
            sc = _cut_score(footprint, axis, c) + 0.05 * abs(c - ideal)
            if sc < best_s:
                best, best_s = c, sc
            c += 1.0
        cuts.append(round(best, 3))
        prev = cuts[-1]
    return cuts


# --------------------------------------------------------------------------- #
# Pins
# --------------------------------------------------------------------------- #
def _pin_spots(footprint: BaseGeometry, axis: str, c: float, other_cuts: list[float]):
    """(position along the cut line) values where a pin hole fits inside the footprint."""
    minx, miny, maxx, maxy = footprint.bounds
    line = LineString([(c, miny - 1), (c, maxy + 1)]) if axis == "x" else LineString([(minx - 1, c), (maxx + 1, c)])
    inter = footprint.intersection(line)
    segs = [g for g in getattr(inter, "geoms", [inter]) if not g.is_empty and g.length >= MIN_SUPPORT_MM]
    half = PIN_HOLE_D / 2 + PIN_WALL
    spots: list[float] = []
    for g in segs:
        a, b = sorted((g.coords[0][1], g.coords[-1][1])) if axis == "x" else sorted((g.coords[0][0], g.coords[-1][0]))
        n = max(1, round((b - a) / 50.0))
        for k in range(n):
            t = a + (b - a) * (k + 0.5) / n
            # search nearby for a position where the 20 mm x pin footprint fits and avoids other cuts
            for d in [0.0] + [s * i for i in range(1, 11) for s in (1.0, -1.0)]:
                tt = t + d * 1.0
                if not a + half <= tt <= b - half:
                    continue
                if any(abs(tt - oc) < 7.0 for oc in other_cuts):
                    continue
                if axis == "x":
                    region = box(c - PIN_HOLE_DEPTH, tt - half, c + PIN_HOLE_DEPTH, tt + half)
                else:
                    region = box(tt - half, c - PIN_HOLE_DEPTH, tt + half, c + PIN_HOLE_DEPTH)
                if footprint.buffer(1e-6).contains(region):
                    spots.append(tt)
                    break
    return spots


def split_model(model: Model, bed: float = BED_MM) -> SplitResult:
    """Cut every group whose print footprint exceeds ``bed`` x ``bed`` (XY) into pieces."""
    res = SplitResult(pieces=[])
    meshes = {id(p): p.mesh for p in model.parts}
    groups: dict[str, list[Part]] = {}
    for p in model.parts:
        groups.setdefault(p.group or p.name, []).append(p)
    shell = model.meta.get("construction") == "open_back_shell"
    for gname, parts in groups.items():
        foot = unary_union([mesh_footprint(meshes[id(p)]) for p in parts])
        xs = plan_axis_cuts(foot, "x", bed)
        ys = plan_axis_cuts(foot, "y", bed)
        if xs or ys:
            res.cuts[gname] = {"x": xs, "y": ys}
        for p in parts:
            mesh = meshes[id(p)]
            if not (xs or ys):
                res.pieces.append(SplitPiece(p.name, p, gname, (0, 0), mesh))
                continue
            man = from_trimesh(mesh)
            zmin, zmax = mesh.bounds[0][2], mesh.bounds[1][2]
            thick = zmax - zmin
            pfoot = mesh_footprint(mesh)
            pins_ok = thick >= PIN_MIN_THICKNESS and not shell
            if not pins_ok and p.role not in ("face", "letter_face"):
                reason = "open_back_shell walls" if shell else f"thickness {thick:.1f} mm"
                res.warnings.append(
                    f"No pin holes on '{p.name}' ({reason}); seams at the cut lines must be glued."
                )
            if pins_ok:
                for axis, cuts, others in (("x", xs, ys), ("y", ys, xs)):
                    for c in cuts:
                        spots = _pin_spots(pfoot, axis, c, others)
                        for t in spots:
                            center = (c, t, (zmin + zmax) / 2) if axis == "x" else (t, c, (zmin + zmax) / 2)
                            man = man - cylinder(PIN_HOLE_D / 2, 2 * PIN_HOLE_DEPTH, axis, center)
                            res.pins.append(
                                {
                                    "part": p.name, "group": gname, "axis": axis, "coord": c,
                                    "pos": round(t, 3), "z": round((zmin + zmax) / 2, 3),
                                    "hole_diameter": PIN_HOLE_D, "hole_depth": PIN_HOLE_DEPTH,
                                    "pin_diameter": PIN_PIECE_D,
                                }
                            )
            xb = [-1e4, *xs, 1e4]
            yb = [-1e4, *ys, 1e4]
            cells = []
            for ix in range(len(xb) - 1):
                for iy in range(len(yb) - 1):
                    cube = Manifold.cube(
                        (xb[ix + 1] - xb[ix], yb[iy + 1] - yb[iy], 1e4), False
                    ).translate((xb[ix], yb[iy], -5e3))
                    cell = man ^ cube
                    if cell.is_empty() or cell.volume() < 1e-3:
                        continue
                    cells.append(((ix, iy), to_trimesh(cell)))
            for k, (cell_ix, tm) in enumerate(cells, start=1):
                res.pieces.append(SplitPiece(f"{p.name}_p{k}of{len(cells)}", p, gname, cell_ix, tm))
    return res


# --------------------------------------------------------------------------- #
# Plate packing
# --------------------------------------------------------------------------- #
@dataclass
class Placement:
    unit: tuple[str, int, int]  # (group, ix, iy)
    plate: int
    x: float  # plate coordinates of the unit's min corner after rotation
    y: float
    rotated: bool
    width: float
    height: float


@dataclass
class Plate:
    index: int
    placements: list[Placement] = field(default_factory=list)


def _unit_boxes(pieces: list[SplitPiece]):
    units: dict[tuple[str, int, int], list[SplitPiece]] = {}
    for pc in pieces:
        units.setdefault((pc.group, *pc.cell), []).append(pc)
    boxes = {}
    for key, pcs in units.items():
        b = np.array([pc.mesh.bounds for pc in pcs])
        lo, hi = b[:, 0].min(axis=0), b[:, 1].max(axis=0)
        boxes[key] = (lo, hi)
    return units, boxes


def _clear_x(x: float, y: float, w: float, h: float, reserved, bed: float, gap: float) -> float | None:
    """Smallest x' >= x where the box (x', y, w, h) avoids every reserved rectangle (x, y, w, h)."""
    moved = True
    while moved:
        moved = False
        for rx, ry, rw, rh in reserved:
            if x < rx + rw and x + w > rx and y < ry + rh and y + h > ry:
                x = rx + rw + gap
                moved = True
    return x if x + w <= bed + 1e-6 else None


def pack_plates(
    pieces: list[SplitPiece], bed: float = BED_MM, gap: float = 5.0,
    reserved: list[tuple[float, float, float, float]] | None = None,
    mixed_reserved: list[tuple[float, float, float, float]] | None = None,
) -> list[Plate]:
    """Pack by colour: units using several extruders go on plates that also keep ``mixed_reserved``
    (the prime tower) free; single-extruder units get their own plates (one extruder per plate, so
    no tower and the full area). ``reserved`` applies to every plate."""
    units, _ = _unit_boxes(pieces)
    groups: dict[tuple[int, ...], list[SplitPiece]] = {}
    for pcs in units.values():
        ext = tuple(sorted({pc.part.extruder for pc in pcs}))
        groups.setdefault(ext, []).extend(pcs)
    order = sorted(groups, key=lambda e: (len(e) == 1, e))  # mixed first, then single extruders
    plates: list[Plate] = []
    for ext in order:
        res = list(reserved or []) + (list(mixed_reserved or []) if len(ext) > 1 else [])
        for pl in _pack(groups[ext], bed, gap, res):
            new = Plate(len(plates))
            for pm in pl.placements:
                pm.plate = new.index
                new.placements.append(pm)
            plates.append(new)
    return plates


def pack_plates_single(
    pieces: list[SplitPiece], bed: float = BED_MM, gap: float = 5.0,
    reserved: list[tuple[float, float, float, float]] | None = None,
) -> list[Plate]:
    """Plain shelf packing of all units together (see :func:`pack_plates` for the colour-aware wrapper)."""
    return _pack(pieces, bed, gap, reserved or [])


def _pack(
    pieces: list[SplitPiece], bed: float, gap: float,
    reserved: list[tuple[float, float, float, float]],
) -> list[Plate]:
    """Shelf-pack assembly units (pieces sharing group+cell stay together) onto plates.

    Uses bounding boxes (90 degree rotation allowed) with ``gap`` mm between units.
    ``reserved`` rectangles (x, y, w, h in plate coordinates) are kept free on every plate
    (prime tower, printer exclusion zone).
    """
    units, boxes = _unit_boxes(pieces)
    items = []
    for key, (lo, hi) in boxes.items():
        w, h = float(hi[0] - lo[0]), float(hi[1] - lo[1])
        if w > bed + 1e-6 or h > bed + 1e-6:
            if h > bed + 1e-6 and w <= bed + 1e-6:
                pass
            if min(w, h) > bed + 1e-6 or (w > bed and h > bed):
                raise ValueError(f"unit {key} ({w:.0f}x{h:.0f}) does not fit the bed")
        items.append((key, w, h))
    items.sort(key=lambda t: -max(t[1], t[2]))
    plates: list[Plate] = []
    shelves: list[list[dict]] = []  # per plate: shelves {y, h, x}
    cap = bed + gap  # trailing gap does not need to fit
    for key, w, h in items:
        placed = False
        for rotated in (False, True):
            iw, ih = (h, w) if rotated else (w, h)
            if iw > bed + 1e-6 or ih > bed + 1e-6:
                continue
            for pi, plate in enumerate(plates):
                for sh in shelves[pi]:
                    if ih <= sh["h"] + 1e-6:
                        x = _clear_x(sh["x"], sh["y"], iw, ih, reserved, bed, gap)
                        if x is not None:
                            plate.placements.append(Placement(key, pi, x, sh["y"], rotated, iw, ih))
                            sh["x"] = x + iw + gap
                            placed = True
                            break
                if placed:
                    break
                used = (shelves[pi][-1]["y"] + shelves[pi][-1]["h"] + gap) if shelves[pi] else 0.0
                if used + ih <= bed + 1e-6:
                    x = _clear_x(0.0, used, iw, ih, reserved, bed, gap)
                    if x is not None:
                        sh = {"y": used, "h": ih, "x": x + iw + gap}
                        shelves[pi].append(sh)
                        plate.placements.append(Placement(key, pi, x, used, rotated, iw, ih))
                        placed = True
                        break
            if placed:
                break
        if not placed:
            for rotated in (False, True):
                iw, ih = (h, w) if rotated else (w, h)
                x = _clear_x(0.0, 0.0, iw, ih, reserved, bed, gap)
                if x is not None and ih <= bed + 1e-6:
                    break
            else:
                raise ValueError(f"unit {key} ({w:.0f}x{h:.0f}) does not fit the bed with the reserved areas")
            plates.append(Plate(len(plates)))
            shelves.append([{"y": 0.0, "h": ih, "x": x + iw + gap}])
            plates[-1].placements.append(Placement(key, len(plates) - 1, x, 0.0, rotated, iw, ih))
    return plates


def place_piece(piece: SplitPiece, placement: Placement, boxes) -> trimesh.Trimesh:
    """Mesh of ``piece`` moved onto its plate position (z unchanged)."""
    lo, hi = boxes[placement.unit]
    m = piece.mesh.copy()
    if placement.rotated:
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        m.apply_translation([-cx, -cy, 0])
        rot = trimesh.transformations.rotation_matrix(math.pi / 2, [0, 0, 1])
        m.apply_transform(rot)
        w, h = hi[0] - lo[0], hi[1] - lo[1]
        m.apply_translation([h / 2, w / 2, 0])  # rotated unit now spans (h, w) from origin
    else:
        m.apply_translation([-lo[0], -lo[1], 0])
    m.apply_translation([placement.x, placement.y, 0])
    return m


def plate_meshes(result: SplitResult, plates: list[Plate]) -> list[list[tuple[SplitPiece, trimesh.Trimesh]]]:
    """For each plate, its pieces with meshes in plate coordinates."""
    units, boxes = _unit_boxes(result.pieces)
    out = []
    for plate in plates:
        items = []
        for pl in plate.placements:
            for pc in units[pl.unit]:
                items.append((pc, place_piece(pc, pl, boxes)))
        out.append(items)
    return out
