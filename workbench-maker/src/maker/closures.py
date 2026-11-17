"""Finished ornament around the formed sheet: back plate, rim and the closure (glued rim, snap, magnet, screw cap).

Assembly frame (= ornament frame): back plate z 0..BACK_MM, the cut sheet lies on it, the rim's lip stands on the back
plate around the sheet and its ring presses the sheet's flange down. Parts are returned in print orientation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely
import trimesh
from shapely.geometry import Point, Polygon
from shapely.ops import polylabel

from . import core
from .sheets import Sheet
from .thermo import RX, Dome

BACK_MM, RING_MM, WALL_MM = 1.6, 1.6, 3.0  # thin: these are printed for every ornament
HANG_R, HOLE_R = 5.5, 1.75
CLOSURES_TR = {"rim": "Yapıştırma kenarı", "snap": "Geçmeli kenar (yapıştırmasız)", "magnet": "Mıknatıslı (buzdolabı süsü)",
               "screw": "Vidalı kapak (içi doldurulur)"}

SNAP_CLEAR, SNAP_WALL, SNAP_OVERLAP, SNAP_LIP_H = 0.2, 1.2, 0.5, 1.0
THREAD_D, THREAD_PITCH, THREAD_DEPTH, THREAD_CLEAR = 20.0, 2.5, 1.2, 0.35  # cap thread (mm); clearance is radial
COLLAR_H, COLLAR_WALL, CAP_HEAD = 5.0, 2.0, 1.6
MAGNET_SKIN, MAGNET_CLEAR = 0.6, 0.2


@dataclass
class Ornament:
    back: trimesh.Trimesh  # print orientation = assembly orientation
    rim: trimesh.Trimesh  # print orientation (flipped)
    shell: trimesh.Trimesh  # formed sheet sitting on the back plate (preview only)
    trim: Polygon  # where to cut the formed sheet
    extra: list = field(default_factory=list)  # (name, label, mesh) e.g. the screw cap
    notes: list[str] = field(default_factory=list)
    assembled_rim: trimesh.Trimesh | None = None  # rim in the assembly frame (tests / previews)
    accents: list = field(default_factory=list)  # (color, mesh): other-colour pieces of the back plate, same frame
    holes: int = 0  # light holes punched through the back plate


def perforation(o: Polygon, hole_d: float, pitch: float, keep_out=None) -> list[Polygon]:
    """Round light holes on a hexagonal grid inside the outline: clear of the edge (the cut sheet and the rim rest
    there) and of ``keep_out`` (magnet pockets, the screw collar)."""
    area = o.buffer(-(hole_d / 2 + WALL_MM + 1.0), quad_segs=16)
    if keep_out is not None and not keep_out.is_empty:
        area = area.difference(keep_out.buffer(hole_d / 2, quad_segs=16))  # the whole hole, not only its centre
    if area.is_empty:
        return []
    x0, y0, x1, y1 = o.bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    holes, row = [], 0
    dy = pitch * np.sqrt(3) / 2
    n_rows = int((y1 - y0) / dy) + 2
    for j in range(-n_rows, n_rows + 1):
        off = pitch / 2 if j % 2 else 0.0
        n_cols = int((x1 - x0) / pitch) + 2
        for i in range(-n_cols, n_cols + 1):
            p = Point(cx + i * pitch + off, cy + j * dy)
            if area.contains(p):
                holes.append(p.buffer(hole_d / 2, quad_segs=16))
    return holes


def _hanger(outer: Polygon, keep_clear: Polygon) -> tuple[Polygon, Polygon]:
    c = polylabel(outer, tolerance=0.5)
    _, _, _, y1 = outer.bounds
    line = shapely.LineString([(c.x, c.y), (c.x, y1 + 50)])
    hits = line.intersection(outer.exterior)
    top = max((p.y for p in getattr(hits, "geoms", [hits]) if hasattr(p, "y")), default=y1)
    y = top + 2.5
    while Point(c.x, y).buffer(HOLE_R + 1.2).intersects(keep_clear):
        y += 0.5
    return Point(c.x, y).buffer(HANG_R, quad_segs=16), Point(c.x, y).buffer(HOLE_R, quad_segs=16)


def thread_section(r_root: float, depth: float, n: int = 120) -> np.ndarray:
    """Cross-section of a single-start thread: radius rises and falls once per turn (twisting it makes the helix)."""
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    tri = 1 - np.abs(a - np.pi) / np.pi
    r = r_root + depth * tri
    return np.c_[r * np.cos(a), r * np.sin(a)]


def _helix(r_root: float, z0: float, z1: float) -> "core.Manifold":
    """Twisted extrusion with the phase fixed at z=0, so every helix of the same pitch meshes with every other."""
    lo, hi = np.floor(z0 / THREAD_PITCH) * THREAD_PITCH, np.ceil(z1 / THREAD_PITCH) * THREAD_PITCH
    turns = (hi - lo) / THREAD_PITCH
    sec = thread_section(r_root, THREAD_DEPTH)
    m = core.twist_extrude(sec, 0.0, hi - lo, 360.0 * turns, int(turns * 36))
    m = m.rotate((0.0, 0.0, 360.0 * lo / THREAD_PITCH)).translate((0.0, 0.0, lo))
    slab = core.extrude(Point(0, 0).buffer(r_root + THREAD_DEPTH + 2, quad_segs=32), z0, z1)
    return m ^ slab


def screw_parts(centre: tuple[float, float]):
    """(collar solid with threaded bore, bore void, cap) around ``centre``; assembly frame, cap fully screwed in."""
    r_root = THREAD_D / 2 - THREAD_DEPTH  # cap (male) thread root radius
    z_top = BACK_MM + COLLAR_H
    void = _helix(r_root + THREAD_CLEAR, -1.0, z_top + 1.0)
    collar = core.extrude(Point(0, 0).buffer(THREAD_D / 2 + THREAD_CLEAR + COLLAR_WALL, quad_segs=48), BACK_MM - 0.01, z_top)
    collar = collar - void
    thread = _helix(r_root, 0.0, z_top - 0.4)
    head = core.extrude(Point(0, 0).buffer(THREAD_D / 2 + 3.5, quad_segs=48), -CAP_HEAD, 0.0)
    slot = core.extrude(shapely.geometry.box(-THREAD_D * 0.35, -0.8, THREAD_D * 0.35, 0.8), -CAP_HEAD - 1, -CAP_HEAD + 0.8)
    cap = core.union_all([head, thread]) - slot  # coin slot on the outside
    move = lambda m: m.translate((centre[0], centre[1], 0.0))
    return move(collar), move(void), move(cap)


def _magnet_spots(o: Polygon, d: float) -> list[tuple[float, float]]:
    c = polylabel(o, tolerance=0.5)
    x0, y0, x1, y1 = o.bounds
    if max(x1 - x0, y1 - y0) < 70:
        return [(c.x, c.y)]
    horiz = (x1 - x0) >= (y1 - y0)
    span = 0.25 * ((x1 - x0) if horiz else (y1 - y0))
    pts = [(c.x - span, c.y), (c.x + span, c.y)] if horiz else [(c.x, c.y - span), (c.x, c.y + span)]
    inner = o.buffer(-(d / 2 + 4))
    return [p for p in pts if inner.contains(Point(p))] or [(c.x, c.y)]


def ornament_parts(dome: Dome, sheet: Sheet, flange_mm: float, hanger: bool, closure: str = "rim",
                   magnet: tuple[float, float] = (10.0, 2.0), holes: tuple[float, float] | None = None,
                   accents: list | None = None) -> Ornament:
    """``holes`` = (diameter, pitch) mm: light holes through the back plate. ``accents`` = [(colour, shapely geometry)]
    in the outline frame: those areas of the back plate are separate pieces in that colour (one multi-colour object)."""
    if closure not in CLOSURES_TR:
        raise ValueError(f"bilinmeyen kapanış: {closure}")
    o = dome.outline
    t = sheet.thickness_mm
    trim = o.buffer(flange_mm, quad_segs=16)
    outer = trim.buffer(WALL_MM, quad_segs=16)
    hole = None
    if hanger:
        tab, hole = _hanger(outer, trim)
        outer = outer.union(tab)
    back_g = outer.difference(hole) if hole else outer
    notes, extra = [], []
    keep = []
    if closure == "magnet":
        keep += [Point(p).buffer(magnet[0] / 2 + MAGNET_CLEAR + 1.6 + 1.5, quad_segs=16) for p in _magnet_spots(o, magnet[0])]
    elif closure == "screw":
        c0 = polylabel(o, tolerance=0.5)
        keep.append(Point(c0.x, c0.y).buffer(THREAD_D / 2 + THREAD_CLEAR + COLLAR_WALL + 2.0, quad_segs=32))
    hole_g = []
    if holes:
        hole_g = perforation(o, holes[0], holes[1], shapely.union_all(keep) if keep else None)
        if hole_g:
            back_g = back_g.difference(shapely.union_all(hole_g))
            notes.append(f"Işık delikleri: tabanda {len(hole_g)} delik (Ø{holes[0]:g} mm, {holes[1]:g} mm arayla); "
                         "arkadan gelen ışık şeffaf levhadan görünür.")
    accent_g = []
    for colour, g in accents or []:
        piece = back_g.intersection(g.intersection(o))
        if not piece.is_empty and piece.area > 1.0:
            accent_g.append((colour, piece))
            back_g = back_g.difference(piece.buffer(0.01))
    back = core.extrude(back_g, 0.0, BACK_MM)

    ring_g = back_g.difference(o.buffer(0.4, quad_segs=16))
    lip_g = back_g.difference(trim.buffer(0.3, quad_segs=16))  # rests on the back plate around the cut sheet
    rim = [core.extrude(lip_g, BACK_MM, BACK_MM + t + 0.01), core.extrude(ring_g, BACK_MM + t, BACK_MM + t + RING_MM)]
    if closure == "snap":
        # skirt around the back plate's edge, with an inward lip that clicks under it
        skirt = outer.buffer(SNAP_CLEAR + SNAP_WALL, quad_segs=16).difference(outer.buffer(SNAP_CLEAR, quad_segs=16))
        lip = outer.buffer(SNAP_CLEAR + SNAP_WALL, quad_segs=16).difference(outer.buffer(-SNAP_OVERLAP, quad_segs=16))
        if hole is not None:
            lip = lip.difference(hole.buffer(0.8))
        rim += [core.extrude(skirt, -SNAP_LIP_H, BACK_MM + t + RING_MM), core.extrude(lip, -SNAP_LIP_H, -0.05)]
        notes.append(f"Geçmeli kenar: tabanı kenarın içine bastırın, alttaki {SNAP_OVERLAP:g} mm'lik dil tabanı tutar; yapıştırıcı gerekmez.")
    elif closure == "magnet":
        md, mh = magnet
        pocket_d, pocket_h = md + MAGNET_CLEAR, mh + MAGNET_CLEAR
        boss_top = MAGNET_SKIN + pocket_h
        spots = _magnet_spots(o, md)
        if boss_top > BACK_MM:
            back = core.union_all([back, *[core.extrude(Point(p).buffer(pocket_d / 2 + 1.6, quad_segs=32), BACK_MM - 0.01, boss_top)
                                           for p in spots]])
        back = back - core.union_all([core.extrude(Point(p).buffer(pocket_d / 2, quad_segs=32), MAGNET_SKIN, boss_top + 1)
                                      for p in spots])
        notes.append(f"Mıknatıs: {len(spots)} adet Ø{md:g} × {mh:g} mm disk mıknatısı tabanın iç yüzündeki yuvalara yapıştırın "
                     f"(arkada {MAGNET_SKIN:g} mm duvar kalır, görünmez).")
    elif closure == "screw":
        c = polylabel(o, tolerance=0.5)
        r_out = THREAD_D / 2 + THREAD_CLEAR + COLLAR_WALL
        ring = np.array([(c.x + r_out * np.cos(a), c.y + r_out * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 24, endpoint=False)])
        room = float(dome.height(ring).min())  # inside of the shell above the collar rim (sheet inner face ~ dome height)
        if not o.buffer(-1.0).contains(Point(c.x, c.y).buffer(r_out)) or room < COLLAR_H + 0.5:
            raise ValueError(f"Vidalı kapak için şekil en az {2 * r_out + 2:.0f} mm genişlikte ve kubbe kapağın üstünde en az "
                             f"{COLLAR_H + 0.5:.1f} mm yüksek olmalı. Şekli büyütün ya da kubbeyi yükseltin.")
        collar, void, cap = screw_parts((c.x, c.y))
        back = core.union_all([back - void, collar])
        cap_m = core.to_trimesh(cap)
        cap_m.apply_translation([0, 0, CAP_HEAD])  # print head-down
        extra.append(("cap", "Vidalı kapak", cap_m))
        notes.append(f"Vidalı kapak: M{THREAD_D:g}×{THREAD_PITCH:g} tek ağızlı diş, {THREAD_CLEAR:g} mm boşluk; tabandaki delikten "
                     "konfeti / fotoğraf koyup kapağı bozuk parayla sıkın.")
    rim_m = core.to_trimesh(core.union_all(rim))
    assembled = rim_m.copy()
    rim_m.apply_transform(RX)
    rim_m.apply_translation([0, 0, -rim_m.bounds[0][2]])

    seg = max(0.9, dome.cell * 2.4)  # preview only: coarser

    def warp(v):
        v = np.array(v, dtype=np.float64)
        hi = dome.height(v[:, :2]) + t
        lo = np.maximum(hi - t * np.sqrt(1 + dome.slope2(v[:, :2])), 0.0)
        v[:, 2] = BACK_MM + lo + v[:, 2] * (hi - lo)
        return v

    shell = core.to_trimesh(core.extrude(trim, 0.0, 1.0).refine_to_length(seg).warp_batch(warp))
    acc = [(colour, core.to_trimesh(core.extrude(g, 0.0, BACK_MM))) for colour, g in accent_g]
    if acc:
        notes.append(f"Çok renkli taban: {len(acc) + 1} renk tek parça olarak basılır (CANVAS renk değiştirir).")
    return Ornament(core.to_trimesh(back), rim_m, shell, trim, extra, notes, assembled, acc, len(hole_g))

# ---------------------------------------------------------------------------------------------------------------
# Printed lattice ("delikli form"): a flat PLA mesh is printed, softened in hot water and pressed between the molds.
LATTICES_TR = {"voronoi": "Voronoi (organik)", "honeycomb": "Petek (altıgen)"}


def lattice_holes(o: Polygon, pattern: str, cell: float, strand: float, seed: int = 7) -> list[Polygon]:
    """Openings of the lattice inside the outline: cells of a hexagonal grid (jittered for Voronoi), each shrunk by
    half a strand and rounded, so the strands between them are ``strand`` mm wide."""
    if pattern not in LATTICES_TR:
        raise ValueError(f"bilinmeyen kafes deseni: {pattern}")
    inner = o.buffer(-strand, quad_segs=16)  # a strand of solid material runs along the outline
    if inner.is_empty:
        return []
    x0, y0, x1, y1 = o.bounds
    rng = np.random.default_rng(seed)
    dy = cell * np.sqrt(3) / 2
    pts = []
    for j in range(-2, int((y1 - y0) / dy) + 3):
        off = cell / 2 if j % 2 else 0.0
        for i in range(-2, int((x1 - x0) / cell) + 3):
            x, y = x0 + i * cell + off, y0 + j * dy
            if pattern == "voronoi":
                x, y = x + rng.uniform(-0.32, 0.32) * cell, y + rng.uniform(-0.32, 0.32) * cell
            pts.append((x, y))
    cells = shapely.voronoi_polygons(shapely.MultiPoint(pts), extend_to=shapely.box(x0 - 3 * cell, y0 - 3 * cell, x1 + 3 * cell, y1 + 3 * cell))
    r = min(0.9, cell * 0.15)
    holes = []
    for c in cells.geoms:
        h = c.buffer(-strand / 2, quad_segs=8).intersection(inner)
        h = h.buffer(-r, quad_segs=8).buffer(r, quad_segs=8)  # round the corners, drop slivers
        for g in getattr(h, "geoms", [h]):
            if not g.is_empty and g.area > max(2.0, 0.08 * cell * cell):
                holes.append(g)
    return holes


@dataclass
class Lattice:
    blank: trimesh.Trimesh  # flat printed mesh, print orientation
    formed: trimesh.Trimesh  # preview of the pressed piece (one shell, or two shells closed into a hollow piece)
    blank_g: Polygon  # 2D outline of the blank with its openings
    holes: int
    notes: list[str] = field(default_factory=list)


def lattice_parts(dome: Dome, thickness: float, flange_mm: float, hanger: bool, pattern: str, cell: float, strand: float,
                  halves: int = 2, z0: float = 0.0) -> Lattice:
    """Flat lattice blank for the outline (+ a solid flange the molds clamp, + a hanger tab) and what it looks like
    after forming: the blank lifted onto the dome, and for ``halves`` = 2 a mirrored second shell glued flange to
    flange (a hollow lattice piece). ``z0`` lifts a single shell onto a back plate."""
    o = dome.outline
    trim = o.buffer(flange_mm, quad_segs=16)
    solid = trim
    if hanger:
        tab, hole = _hanger(trim, o.buffer(0.5))
        solid = trim.union(tab).difference(hole)
    holes = lattice_holes(o, pattern, cell, strand)
    g = solid.difference(shapely.union_all(holes)) if holes else solid
    flat = core.extrude(g, 0.0, thickness)
    seg = max(0.8, min(1.4, cell / 5))

    def warp(v):
        v = np.array(v, dtype=np.float64)
        v[:, 2] = z0 + dome.height(v[:, :2]) + v[:, 2] * thickness
        return v

    top = core.to_trimesh(core.extrude(g, 0.0, 1.0).refine_to_length(seg).warp_batch(warp))
    if halves == 2:
        bottom = top.copy()
        bottom.apply_transform(np.diag([1.0, 1.0, -1.0, 1.0]))
        formed = trimesh.util.concatenate([top, bottom])
        formed.apply_translation([0, 0, -formed.bounds[0][2]])
    else:
        formed = top
    notes = [
        f"Kafes: {len(holes)} açıklık, {LATTICES_TR[pattern].split(' (')[0].lower()} desen, hücre {cell:g} mm, tel {strand:g} mm, "
        f"kalınlık {thickness:g} mm. Düz basılır (destek yok), sonra ısıtılıp kalıpta biçimlendirilir.",
        "Biçimlendirme (varsayım; ilk denemede süreyi ayarlayın): düz kafesi 70–80 °C suda 20–30 saniye yumuşatın, "
        "maşayla alıp dişi kalıba yerleştirin, erkek kalıbı bastırın ve soğuyana kadar (yaklaşık 30 saniye) tutun.",
    ]
    if halves == 2:
        notes.append("İçi boş parça: iki kafes basıp biçimlendirin, düz kenarlarından yapıştırın; askı delikleri üst üste gelir.")
    return Lattice(core.to_trimesh(flat), formed, g, len(holes), notes)
