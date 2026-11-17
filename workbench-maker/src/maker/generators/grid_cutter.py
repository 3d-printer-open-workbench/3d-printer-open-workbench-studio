"""Grid cutter: rows x columns of square, hexagonal or round cells in one cutter (crackers, ravioli-style fondant
squares, petit fours); shared walls between square / hex cells, thin cutting edge up, flange around the outside."""
from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from .. import baking, core
from .base import BuildResult, Generator, Param


def cells(kind: str, size: float, rows: int, cols: int, wall: float) -> list[Polygon]:
    """Cell openings (cut lines), centred on the origin; neighbours are one wall apart."""
    out = []
    if kind == "hex":
        r = size / math.sqrt(3)  # flat-to-flat = size
        hexa = Polygon([(r * math.cos(math.radians(30 + 60 * k)), r * math.sin(math.radians(30 + 60 * k))) for k in range(6)])
        hexa = affinity.rotate(hexa, 30, origin=(0, 0))  # flat top
        px, py = 1.5 * r + wall * math.sqrt(3) / 2, size + wall
        for c in range(cols):
            for rr in range(rows):
                out.append(affinity.translate(hexa, c * px, rr * py + (py / 2 if c % 2 else 0)))
    else:
        p = size + wall
        cell = box(-size / 2, -size / 2, size / 2, size / 2).buffer(-1.0).buffer(1.0, quad_segs=8) if kind == "square" \
            else Point(0, 0).buffer(size / 2, quad_segs=32)
        out = [affinity.translate(cell, c * p, r * p) for r in range(rows) for c in range(cols)]
    u = unary_union(out)
    x0, y0, x1, y1 = u.bounds
    return [affinity.translate(q, -(x0 + x1) / 2, -(y0 + y1) / 2) for q in out]


def build(v: dict) -> BuildResult:
    w: list[str] = []
    wall, H = v["wall_mm"], v["height_mm"]
    cs = cells(v["cell"], v["size_mm"], v["rows"], v["cols"], wall)
    holes = unary_union(cs)
    outer = unary_union([c.buffer(wall, quad_segs=8) for c in cs])
    outer = Polygon(outer.exterior) if outer.geom_type == "Polygon" else outer.convex_hull

    def walls(t):
        """All walls of thickness ``t`` (dividers between cells + outer ring)."""
        return unary_union([c.buffer(t / 2 if v["cell"] != "round" else t, quad_segs=8, join_style=1) for c in cs]
                           + [outer]).difference(holes).intersection(unary_union([c.buffer(t, quad_segs=8) for c in cs]))

    x0, y0, x1, y1 = outer.bounds
    if max(x1 - x0, y1 - y0) + 2 * v["flange_mm"] > core.BED_MM:
        w.append("Kesici tablaya sığmıyor: hücre sayısını ya da boyutunu azaltın.")
    flange = outer.buffer(v["flange_mm"], quad_segs=8).difference(holes)
    mat = v["material"]
    solid = core.union_all([core.extrude(flange, 0.0, 1.2), core.extrude(walls(wall), 0.0, H - baking.EDGE_H),
                            core.extrude(walls(baking.EDGE_MM), H - baking.EDGE_H - 0.01, H)])
    part = baking.part("grid", "Izgara kesici", solid, core.norm_hex(v["color"]), mat)
    part.meta["count"] = v["count"]
    notes = [f"{v['rows']} × {v['cols']} = {len(cs)} hücre, kesici {x1 - x0 + 2 * v['flange_mm']:.0f} × {y1 - y0 + 2 * v['flange_mm']:.0f} mm, "
             f"~{part.meta['grams']:.0f} g ≈ {part.meta['cost_try']:.0f} TL.",
             "Geniş kenar tablada, kesme ağızları yukarıda basılır. Hamuru açın, kesiciyi bastırın, sallayarak kaldırın."] + baking.FOOD_NOTES
    return BuildResult([part], w, {"cells": len(cs), "size_mm": [round(x1 - x0, 1), round(y1 - y0, 1)]}, notes)


GENERATOR = Generator(
    key="grid_cutter", label="Izgara kesici", group="Mutfak",
    description="Tek basışta çok kurabiye / kraker / şeker hamuru: kare, altıgen ya da yuvarlak hücreli kesici.",
    params=[
        Param("cell", "Hücre", "choice", "square", options=[("square", "Kare"), ("hex", "Altıgen"), ("round", "Yuvarlak")], section="Izgara"),
        Param("size_mm", "Hücre boyu", "number", 30, min=10, max=80, step=1, unit="mm", section="Izgara"),
        Param("rows", "Satır", "int", 3, min=1, max=8, section="Izgara"),
        Param("cols", "Sütun", "int", 4, min=1, max=8, section="Izgara"),
        Param("height_mm", "Yükseklik", "number", 15, min=8, max=30, step=1, unit="mm", section="Kesici"),
        Param("wall_mm", "Duvar", "number", 1.2, min=0.8, max=2.4, step=0.2, unit="mm", section="Kesici", help="Kesme ağzı her zaman 0.8 mm"),
        Param("flange_mm", "Tutma kenarı", "number", 4, min=0, max=10, step=0.5, unit="mm", section="Kesici"),
        Param("material", "Malzeme", "choice", "PLA", options=[("PLA", "PLA"), ("PETG", "PETG")], section="Baskı"),
        Param("color", "Renk", "color", "#3E7CB1", section="Baskı"),
        Param("count", "Adet", "int", 1, min=1, max=4, section="Baskı"),
    ],
    build=build,
)
