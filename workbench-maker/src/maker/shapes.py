"""The basic shapes Maker offers (the drawing itself is workbench_core.shapes, shared with Glow and Topo)."""
from __future__ import annotations

from .core import shape_polygon  # noqa: F401  (re-exported for the generators)

SHAPES_TR = {"heart": "Kalp", "star": "Yıldız", "star4": "4 köşe yıldız", "circle": "Daire", "square": "Yuvarlak kare",
             "triangle": "Üçgen", "hexagon": "Altıgen", "oval": "Oval"}
SHAPES = tuple(SHAPES_TR)
