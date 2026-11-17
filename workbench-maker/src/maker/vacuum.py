"""Vacuum forming: male buck(s) on a perforated plate + a box with a shop-vac hose port.

The heated sheet (held in a frame) is pulled down over the buck; its *inner* face touches the buck, so the buck is the
dome offset inwards by the sheet thickness (ball erosion, same as the press male) and the visible outer face never
touches the mold. Air leaves through a ring of holes around each buck foot and through holes in the buck's valleys.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from scipy import ndimage
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from . import core
from .sheets import Sheet
from .thermo import CLAMP_MM, EPS, Dome, _heightfield_solid, _moved, _rounded_rect

PLATE_MM = 3.0
HOLE_D = 1.2  # vent holes
RING_OFFSET = 1.2  # vent ring distance from the buck foot
RING_PITCH = 8.0  # max spacing of vent holes along the ring
POCKET_MM = 0.8  # a valley this deep (vs. its surroundings) traps air and gets its own hole
BOX_WALL, BOX_FLOOR = 2.4, 2.0
POST_PITCH, POST_D = 40.0, 6.0
FRAME_MM = 20.0  # extra sheet around the plate for the user's sheet frame


@dataclass
class VacuumSet:
    buck: trimesh.Trimesh  # perforated plate + buck(s), print orientation
    box: trimesh.Trimesh  # open box with posts and hose port
    plate_mm: tuple[float, float]
    sheet_size_mm: tuple[float, float]
    ring_holes: list[tuple[float, float]]
    valley_holes: list[tuple[float, float]]


def ring_points(outline: Polygon, offset: float = RING_OFFSET, pitch: float = RING_PITCH) -> list[tuple[float, float]]:
    """Evenly spaced points on the outline grown by ``offset`` (at most ``pitch`` apart)."""
    ring = outline.buffer(offset, quad_segs=16).exterior
    n = max(6, int(np.ceil(ring.length / pitch)))
    return [(p.x, p.y) for p in (ring.interpolate(i * ring.length / n) for i in range(n))]


def valley_points(dome: Dome, gap: float) -> list[tuple[float, float]]:
    """Deepest point of every pocket on the buck surface where trapped air would stop the sheet."""
    c = dome.cell
    X, Y = np.meshgrid(dome.xs, dome.ys)
    h = dome.offset_height(np.c_[X.ravel(), Y.ravel()], gap).reshape(X.shape)
    inside = h > 0.5
    size = max(3, int(round(12 / c)))
    depth = ndimage.grey_closing(h, size=(size, size)) - h
    lab, n = ndimage.label((depth > POCKET_MM) & inside)
    pts = []
    for k in range(1, n + 1):
        m = lab == k
        if m.sum() * c * c < 2.0:  # specks
            continue
        iy, ix = np.unravel_index(np.argmax(np.where(m, depth, -1)), m.shape)
        p = (float(dome.xs[ix]), float(dome.ys[iy]))
        if Point(p).distance(dome.outline.exterior) > 3 * RING_OFFSET:  # near the foot the ring holes already vent it
            pts.append(p)
    return pts


def _teardrop(r: float, cy: float) -> Polygon:
    """Circle with a 45 deg pointed roof (prints lying on its side without supports)."""
    k = r * np.sqrt(0.5)
    roof = Polygon([(-k, cy + k), (0, cy + r * np.sqrt(2)), (k, cy + k)])
    return unary_union([Point(0, cy).buffer(r, quad_segs=24), roof])


def _hose_port(d: float, wall_x: float, length: float = 25.0):
    """Horizontal spigot (outer diameter ``d``) on the +x wall, resting on the bed; returns (spigot, bore)."""
    r_out, r_in = d / 2, d / 2 - 2.0
    outer = core.to_trimesh(core.extrude(_teardrop(r_out, r_out), 0.0, length + BOX_WALL))
    inner = core.to_trimesh(core.extrude(_teardrop(r_in, r_out), -1.0, length + BOX_WALL + 1.0))
    rot = np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1.0]])  # extrusion z -> x, section (x, y) -> (y, z)
    for m in (outer, inner):
        m.apply_transform(rot)
        m.apply_translation([wall_x - BOX_WALL, 0, 0])
    return core.from_trimesh(outer), core.from_trimesh(inner)


def vacuum_molds(dome: Dome, sheet: Sheet, offsets=None, hose_d: float = 35.0) -> VacuumSet:
    offs = list(offsets or [(0.0, 0.0)])
    outlines = [affinity.translate(dome.outline, dx, dy) for dx, dy in offs]
    x0, y0, x1, y1 = unary_union(outlines).bounds
    pw, ph = x1 - x0 + 2 * CLAMP_MM, y1 - y0 + 2 * CLAMP_MM
    t = sheet.thickness_mm
    seg = max(0.6, dome.cell * 1.6)

    buck = _heightfield_solid(dome.outline, lambda xy: np.maximum(dome.offset_height(xy, t), -EPS / 2), -EPS, seg)
    buck.apply_translation([0, 0, PLATE_MM])
    plate = core.extrude(_rounded_rect(pw, ph, 4.0), 0.0, PLATE_MM)
    solid = core.union_all([plate, *[core.from_trimesh(m) for m in _moved(buck, offs)]])
    rings, valleys = [], []
    for dx, dy in offs:
        rings += [(x + dx, y + dy) for x, y in ring_points(dome.outline)]
        valleys += [(x + dx, y + dy) for x, y in valley_points(dome, t)]
    top = PLATE_MM + dome.max_height + 2
    holes = [core.cylinder(HOLE_D / 2, PLATE_MM + 2, "z", (x, y, PLATE_MM / 2)) for x, y in rings]
    holes += [core.cylinder(HOLE_D / 2, top + 2, "z", (x, y, top / 2)) for x, y in valleys]
    solid = solid - core.union_all(holes)

    # box: floor + walls (plate rests on them, seal with tape), posts under the plate, hose port on +x
    bh = max(hose_d + 6.0, 30.0)
    rect = _rounded_rect(pw, ph, 4.0)
    shell = core.extrude(rect, 0.0, bh) - core.extrude(rect.buffer(-BOX_WALL), BOX_FLOOR, bh + 1)
    posts = []
    nx, ny = max(0, int((pw - 30) // POST_PITCH)), max(0, int((ph - 30) // POST_PITCH))
    for i in range(nx + 1):
        for j in range(ny + 1):
            px, py = (i - nx / 2) * POST_PITCH, (j - ny / 2) * POST_PITCH
            if nx == 0 and ny == 0:
                continue
            posts.append(core.cylinder(POST_D / 2, bh - BOX_FLOOR + 0.1, "z", (px, py, (bh + BOX_FLOOR - 0.1) / 2)))
    port_o, port_i = _hose_port(hose_d, pw / 2)
    box_m = core.union_all([shell, *posts, port_o]) - port_i
    return VacuumSet(core.to_trimesh(solid), core.to_trimesh(box_m), (pw, ph), (pw + 2 * FRAME_MM, ph + 2 * FRAME_MM),
                     rings, valleys)
