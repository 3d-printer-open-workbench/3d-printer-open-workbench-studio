"""Pack printable parts (with their copy counts) onto 250 x 250 plates, one material per plate, and write the
OrcaSlicer 3MF (via core). One material per plate means no filament change between materials.

Parts sharing ``meta['group']`` are one print object (they keep their relative position), and each colour of such a
group gets its own filament slot: a multi-colour keychain prints in one go on the CANVAS. Plates with multi-colour
objects keep the prime tower corner free. ``meta['orca']`` = per-object Orca settings (e.g. lithophane infill). ``meta['pause_z']`` on a group part adds a pause (e.g. NFC tag insert).
Parts with their own ``meta['batch']`` go on separate plates: a single-colour stand next to a two-colour plaque would
force a filament change on every layer."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from . import core
from .generators import Part

GAP = 6.0  # between parts on a plate
EXCLUDE = (240.0, 20.0)  # Centauri Carbon's front-right exclusion corner, in packing coordinates (x >=, y <=)
MAX_FILAMENTS = 4


def _tower() -> tuple[tuple[float, float, float, float], tuple[float, float]]:
    """(rectangle kept free in packing coordinates, tower position in bed coordinates) for multi-colour plates."""
    _, mixed, xy = core.plate_reserved(True)
    return mixed[0], xy


@dataclass
class Unit:
    """One print object: its pieces (name, mesh, slot key) share one transform on the plate."""
    name: str
    pieces: list[tuple[str, trimesh.Trimesh, tuple]]
    pause_z: list[float] = field(default_factory=list)

    @property
    def multicolour(self) -> bool:
        return len({k for _, _, k in self.pieces}) > 1

    @property
    def bounds(self) -> np.ndarray:
        return np.array([np.min([m.bounds[0] for _, m, _ in self.pieces], axis=0),
                         np.max([m.bounds[1] for _, m, _ in self.pieces], axis=0)])

    def transformed(self, tf: np.ndarray) -> "Unit":
        out = []
        for n, m, k in self.pieces:
            c = m.copy()
            c.apply_transform(tf)
            out.append((n, c, k))
        return Unit(self.name, out, self.pause_z)


@dataclass
class Plate:
    material: str
    units: list[Unit] = field(default_factory=list)

    @property
    def items(self) -> list[tuple[str, trimesh.Trimesh]]:
        """(object name, combined mesh in plate coordinates)."""
        return [(u.name, trimesh.util.concatenate([m for _, m, _ in u.pieces])) for u in self.units]

    @property
    def multicolour(self) -> bool:
        return any(u.multicolour for u in self.units)


def _footprint(u: Unit) -> tuple[float, float]:
    lo, hi = u.bounds
    return float(hi[0] - lo[0]), float(hi[1] - lo[1])


def _overlap(x, y, w, d, r) -> bool:
    rx, ry, rw, rh = r
    return x < rx + rw and rx < x + w and y < ry + rh and ry < y + d


def _shelf(units: list[Unit], bed: float, blocked: list[tuple]) -> list[list[Unit]]:
    """Shelf packing, tallest first; each object may turn 90 deg so its long side runs along x. ``blocked``:
    rectangles (x, y, w, h) that must stay free (exclusion corner, prime tower)."""
    prepared = []
    for u in units:
        w, d = _footprint(u)
        if d > w and d <= bed:
            u = u.transformed(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
        prepared.append(u)
    prepared.sort(key=lambda u: -_footprint(u)[1])
    plates: list[list[Unit]] = []
    cur: list[Unit] = []
    x = y = row_d = 0.0
    for u in prepared:
        w, d = _footprint(u)
        if w > bed or d > bed:
            continue  # job.build already warned that this part does not fit
        while True:
            hit = next((r for r in blocked if _overlap(x, y, w, d, r)), None)
            if hit is None and x + w <= bed + 1e-6 and y + d <= bed + 1e-6:
                lo = u.bounds[0]
                cur.append(u.transformed(trimesh.transformations.translation_matrix([x - lo[0], y - lo[1], -lo[2]])))
                x += w + GAP
                row_d = max(row_d, d)
                break
            if hit is not None and hit[0] + hit[2] + w <= bed + 1e-6:
                x = hit[0] + hit[2]  # jump past the blocked rectangle on this shelf
                continue
            ny = y + row_d + GAP if row_d > 0 else (hit[1] + hit[3] + GAP if hit is not None else bed + 1)
            if ny + d <= bed + 1e-6:
                x, y, row_d = 0.0, ny, 0.0
                continue
            if not cur:
                break  # cannot be placed at all
            plates.append(cur)
            cur, x, y, row_d = [], 0.0, 0.0, 0.0
    if cur:
        plates.append(cur)
    return plates


def slot_key(p: Part) -> tuple:
    """Grouped (multi-colour) parts get a slot per colour; single parts share one slot per material."""
    return (p.material, p.color.upper() if p.meta.get("group") else None)


def units(parts: list[Part]) -> dict[tuple[str, str], list[Unit]]:
    """Print objects per (material, batch) (``meta['count']`` copies each)."""
    by_mat: dict[tuple[str, str], list[Unit]] = {}
    groups: dict[str, list[Part]] = {}
    for p in parts:
        if p.printable:
            groups.setdefault(p.meta.get("group") or f"\0{p.name}", []).append(p)
    for g, ps in groups.items():
        name = ps[0].name if g.startswith("\0") else g
        n = max(int(p.meta.get("count", 1) or 1) for p in ps)
        pause = sorted({float(p.meta["pause_z"]) for p in ps if p.meta.get("pause_z")})
        for k in range(n):
            u = Unit(name if n == 1 else f"{name}_{k + 1}", [(p.name, p.mesh, slot_key(p)) for p in ps], pause)
            by_mat.setdefault((ps[0].material, str(ps[0].meta.get("batch", ""))), []).append(u)
    return by_mat


def pack(parts: list[Part], bed: float = core.BED_MM) -> list[Plate]:
    """Plates for every printable part, grouped by material, molds (PETG) first."""
    by_mat = units(parts)
    corner = (EXCLUDE[0], 0.0, bed - EXCLUDE[0] + 1.0, EXCLUDE[1])
    out = []
    for key in sorted(by_mat, key=lambda k: (k[0] != "PETG", k)):
        blocked = [corner] + ([_tower()[0]] if any(u.multicolour for u in by_mat[key]) else [])
        out += [Plate(key[0], us) for us in _shelf(by_mat[key], bed, blocked)]
    return out


def write_3mf(parts: list[Part], path, title: str = "Workbench Maker") -> list[Plate]:
    plates = pack(parts)
    colors: dict[tuple, str] = {}
    for p in parts:
        if p.printable:
            colors.setdefault(slot_key(p), p.color)
    keys = list(dict.fromkeys(k for pl in plates for u in pl.units for _, _, k in u.pieces))
    if len(keys) > MAX_FILAMENTS:
        raise ValueError(f"Bu iş {len(keys)} filament istiyor; CANVAS en çok {MAX_FILAMENTS} filament alır. Renk sayısını azaltın.")
    molds = {u.name for pl in plates for u in pl.units
             for p in parts if p.meta.get("role") == "mold" and (u.name == p.name or u.name.startswith(p.name + "_"))}
    pauses = {i: [z for u in pl.units for z in u.pause_z] for i, pl in enumerate(plates) if any(u.pause_z for u in pl.units)}
    orca = {u.name: p.meta["orca"] for pl in plates for u in pl.units for p in parts
            if p.meta.get("orca") and (u.name == (p.meta.get("group") or p.name) or u.name.startswith((p.meta.get("group") or p.name) + "_"))}
    core.write_plates_3mf(
        path, [[(u.name, [(pn, m, keys.index(k) + 1) for pn, m, k in u.pieces]) for u in pl.units] for pl in plates],
        [(colors[k], k[0]) for k in keys], title=title, mold_names=molds,
        tower_xy=_tower()[1] if any(pl.multicolour for pl in plates) else None, pauses=pauses or None, object_settings=orca or None)
    return plates
