"""Basic outline shapes shared by every program (Maker, Glow contour boxes, Topo map footprints)."""
from __future__ import annotations

import math

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon, box

SHAPES_TR = {"heart": "Kalp", "star": "Yıldız", "star4": "4 köşe yıldız", "circle": "Daire", "oval": "Oval",
             "square": "Kare", "rect": "Dikdörtgen", "triangle": "Üçgen", "hexagon": "Altıgen", "octagon": "Sekizgen"}


def unit_shape(kind: str, *, rounded: bool = True, segments: int | None = None) -> Polygon:
    """The shape at an arbitrary size, centred later. ``rounded``: soften the corners (prints and forms better);
    ``segments``: finer curves (hearts, circles)."""
    if kind == "heart":
        t = np.linspace(0, 2 * np.pi, segments or 240, endpoint=False)
        return Polygon(np.c_[16 * np.sin(t) ** 3, 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)]).buffer(0)
    if kind in ("star", "star4"):
        n, ri = (5, 0.45) if kind == "star" else (4, 0.42)
        a = np.pi / 2 + np.arange(2 * n) * np.pi / n
        r = np.where(np.arange(2 * n) % 2 == 0, 1.0, ri)
        g = Polygon(np.c_[r * np.cos(a), r * np.sin(a)])
        return g.buffer(0.04, quad_segs=12).buffer(-0.08, quad_segs=12).buffer(0.04, quad_segs=12) if rounded else g
    if kind == "circle":
        return Point(0, 0).buffer(1.0, quad_segs=segments or 48)
    if kind == "oval":
        return affinity.scale(Point(0, 0).buffer(1.0, quad_segs=segments or 48), 1.0, 0.72)
    if kind in ("square", "rect"):
        g = box(-1, -1, 1, 1)
        return g.buffer(-0.12).buffer(0.12, quad_segs=12) if rounded else g
    if kind == "triangle":
        a = np.pi / 2 + np.arange(3) * 2 * np.pi / 3
        g = Polygon(np.c_[np.cos(a), np.sin(a)])
        return g.buffer(-0.1).buffer(0.1, quad_segs=12) if rounded else g
    if kind in ("hexagon", "octagon"):
        n = 6 if kind == "hexagon" else 8
        off = 0.0 if kind == "hexagon" else math.pi / n
        a = off + np.arange(n) * 2 * np.pi / n
        g = Polygon(np.c_[np.cos(a), np.sin(a)])
        return g.buffer(-0.06).buffer(0.06, quad_segs=12) if rounded else g
    raise ValueError(f"bilinmeyen şekil: {kind} (seçenekler: {', '.join(SHAPES_TR)})")


def shape_polygon(kind: str, width: float, height: float | None = None, *, rounded: bool = True,
                  segments: int | None = None) -> Polygon:
    """Shape centred on the origin, ``width`` mm wide; with ``height`` it is stretched to width x height."""
    g = unit_shape(kind, rounded=rounded, segments=segments)
    x0, y0, x1, y1 = g.bounds
    g = affinity.translate(g, -(x0 + x1) / 2, -(y0 + y1) / 2)
    kx = width / (x1 - x0)
    ky = kx if height is None else height / (y1 - y0)
    return affinity.scale(g, kx, ky, origin=(0, 0))
