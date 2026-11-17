"""Rattan letters: wall / shelf letters whose inside is a woven cane (hexagon) lattice inside a solid rim, one part
per letter so a long name spreads over plates. The rim can be taller and a second colour."""
from __future__ import annotations

import math

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from .. import core, flat
from .base import BuildResult, Generator, Param


def cane_lattice(bounds, cell: float, strand: float):
    """Three families of parallel strands at 0/60/120 deg: the open hexagon-and-star pattern of woven rattan cane."""
    x0, y0, x1, y1 = bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    R = math.hypot(x1 - x0, y1 - y0)
    lines = []
    for ang in (0, 60, 120):
        a = math.radians(ang)
        d = np.array([math.cos(a), math.sin(a)])
        n = np.array([-d[1], d[0]])
        for k in np.arange(-R, R, cell):
            p = np.array([cx, cy]) + n * k
            lines.append(LineString([p - d * R, p + d * R]))
    return unary_union(lines).buffer(strand / 2, cap_style=2)


def letters(g) -> list:
    """Split text geometry into letters: small pieces (dots, accents) join the letter they sit over."""
    polys = sorted(getattr(g, "geoms", [g]), key=lambda q: -q.area)
    big = [q for q in polys if q.area > 0.12 * polys[0].area]
    groups = [[q] for q in big]
    for q in polys:
        if q in big:
            continue
        cx = q.centroid.x
        best = min(range(len(big)), key=lambda i: abs((big[i].bounds[0] + big[i].bounds[2]) / 2 - cx))
        groups[best].append(q)
    out = [unary_union(gr) for gr in groups]
    return sorted(out, key=lambda q: q.bounds[0])


def build(v: dict) -> BuildResult:
    w: list[str] = []
    txt = v["text"].strip()
    if not txt:
        raise ValueError("Harfler için bir yazı girin.")
    g = flat.text(txt, v["font"], w, height_mm=v["height_mm"])
    rim_w, cell, strand = v["rim_mm"], v["cell_mm"], v["strand_mm"]
    t, rim_h = v["thick_mm"], v["rim_h_mm"]
    rc, lc = core.norm_hex(v["rim_color"]), core.norm_hex(v["lattice_color"])
    parts = []
    for i, L in enumerate(letters(g), 1):
        inner = L.buffer(-rim_w, quad_segs=8)
        rim = L.difference(inner)
        lattice = cane_lattice(L.bounds, cell, strand).intersection(inner.buffer(0.3))
        x0, y0, x1, y1 = L.bounds
        if inner.is_empty or (x1 - x0) > core.BED_MM or (y1 - y0) > core.BED_MM:
            w.append(f"{i}. harf tablaya sığmıyor ya da çok ince; yüksekliği değiştirin.")
        layers = [(f"rim_{i}", f"Harf {i}", rim, 0.0, rim_h, rc), (f"cane_{i}", f"Harf {i}", lattice, 0.0, t, lc)]
        lp = flat.layer_parts(layers, f"letter_{i}")
        for p in lp:
            p.meta["count"] = v["count"]
        parts += lp
    if rc != lc:
        w.append("Kenar ve örgü farklı renk: aynı katmanlarda yan yana iki renk var, CANVAS her katmanda renk değiştirir (yavaş, atık). "
                 "En ucuzu tek renk.")
    grams = sum(p.meta["grams"] for p in parts)
    notes = [f"{len(letters(g))} harf, yükseklik {v['height_mm']:g} mm, ~{grams:.0f} g ≈ {sum(p.meta['cost_try'] for p in parts):.0f} TL "
             f"({v['count']} takım). Her harf ayrı nesne: tablalara dağıtılır.",
             "Örgü hasır (rattan) görünümü: düz basılır, destek gerekmez. Duvara çift taraflı bantla ya da raf üstüne koyun."]
    return BuildResult(parts, w, {"letters": len(letters(g))}, notes)


GENERATOR = Generator(
    key="rattan_letters", label="Rattan harf", group="Hediyelik",
    description="Hasır örgü (rattan) desenli dekor harfler: kalın kenar, içi altıgen örgü; her harf ayrı basılır.",
    params=[
        Param("text", "Yazı", "text", "EVİM", section="Harfler"),
        Param("font", "Yazı tipi", "font", "Montserrat", section="Harfler", help="Kalın yazı tipleri örgüye daha çok yer bırakır"),
        Param("height_mm", "Harf yüksekliği", "number", 120, min=40, max=240, step=5, unit="mm", section="Harfler"),
        Param("rim_mm", "Kenar genişliği", "number", 4, min=2, max=10, step=0.5, unit="mm", section="Örgü"),
        Param("cell_mm", "Örgü aralığı", "number", 7, min=4, max=15, step=0.5, unit="mm", section="Örgü"),
        Param("strand_mm", "Örgü teli", "number", 1.4, min=0.8, max=3, step=0.1, unit="mm", section="Örgü"),
        Param("thick_mm", "Örgü kalınlığı", "number", 2.4, min=1.2, max=5, step=0.2, unit="mm", section="Örgü"),
        Param("rim_h_mm", "Kenar kalınlığı", "number", 4, min=1.2, max=10, step=0.2, unit="mm", section="Örgü"),
        Param("rim_color", "Kenar rengi", "color", "#C9A27E", section="Renk"),
        Param("lattice_color", "Örgü rengi", "color", "#C9A27E", section="Renk"),
        Param("count", "Takım", "int", 1, min=1, max=3, section="Baskı"),
    ],
    build=build,
)
