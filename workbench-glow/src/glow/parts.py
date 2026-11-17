"""Small helpers shared by the design builders: part assembly, print transforms, extruders."""
from __future__ import annotations

import numpy as np
import trimesh
from manifold3d import Manifold
from shapely.geometry.base import BaseGeometry

from workbench_core.geometry import MAX_COLORS, Part, extrude, to_trimesh, union_all

BLOCK_COLOR = "#111111"


def norm_color(c: str) -> str:
    c = str(c).strip()
    if len(c) != 7 or not c.startswith("#"):
        raise ValueError(f"colour must be #RRGGBB, got {c!r}")
    int(c[1:], 16)
    return c.upper()


def luminance(color: str) -> float:
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def slug(color: str) -> str:
    return color.lstrip("#").upper()


def solid(geom: BaseGeometry, z0: float, z1: float) -> Manifold:
    return extrude(geom, z0, z1)


def union(items: list[Manifold]) -> Manifold:
    items = [m for m in items if not m.is_empty()]
    return union_all(items) if items else Manifold()


def to_mesh(m: Manifold) -> trimesh.Trimesh:
    return to_trimesh(m)


def tf_to_bed(mesh: trimesh.Trimesh, flip: bool) -> np.ndarray:
    """Print transform: optionally rotate 180 deg about X (face-down), then lift so min z = 0."""
    m = mesh.copy()
    rot = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]) if flip else np.eye(4)
    m.apply_transform(rot)
    t = np.eye(4)
    t[2, 3] = -float(m.bounds[0][2])
    return t @ rot


def assign_extruders(parts: list[Part]) -> list[str]:
    """Extruders 1..N by first appearance of each colour; > 4 colours is an error."""
    order: list[str] = []
    for p in parts:
        if p.color not in order:
            order.append(p.color)
    if len(order) > MAX_COLORS:
        raise ValueError(f"{len(order)} filament colours needed ({', '.join(order)}); the printer supports {MAX_COLORS}. "
                         "Reduce the number of colours (e.g. use the frame colour for another region).")
    for p in parts:
        p.extruder = order.index(p.color) + 1
    return order
