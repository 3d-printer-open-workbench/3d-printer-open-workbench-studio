"""String art board: a plate with printed pegs (or nail holes) evenly spaced along a shape, a text outline or a
logo's outline; thread is wound peg to peg. Pegs start at the plate top (two colours = one filament change)."""
from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import Point, box
from shapely.ops import unary_union

from .. import baking, core, flat
from ..shapes import SHAPES_TR
from .base import BuildResult, Generator, Param

PEG_D, HEAD_D, HEAD_H = 3.0, 4.2, 1.2  # head = 0.6 mm lip that keeps the thread on (short overhang, prints fine)


def points_along(ring, pitch: float) -> list[tuple[float, float]]:
    n = max(3, int(round(ring.length / pitch)))
    return [ring.interpolate(i * ring.length / n).coords[0] for i in range(n)]


def build(v: dict) -> BuildResult:
    w: list[str] = []
    shape, w0, _ = baking.outline_from(v, v["width_mm"])
    w += w0
    rings = [shape.exterior] + list(shape.interiors)
    pts = [p for r in rings for p in points_along(r, v["pitch_mm"])]
    m = v["margin_mm"]
    x0, y0, x1, y1 = shape.bounds
    if v["board"] == "rect":
        board = box(x0 - m, y0 - m, x1 + m, y1 + m).buffer(-4, quad_segs=8).buffer(4, quad_segs=8)
    else:
        board = flat.bubble(shape, m)
    t = v["board_mm"]
    bc, pc = core.norm_hex(v["board_color"]), core.norm_hex(v["peg_color"])
    layers = [("board", "Pano", board, 0.0, t, bc)]
    cuts = None
    if v["pegs"] == "printed":
        H = v["peg_mm"]
        stems = unary_union([Point(p).buffer(PEG_D / 2, quad_segs=12) for p in pts])
        heads = unary_union([Point(p).buffer(HEAD_D / 2, quad_segs=12) for p in pts])
        layers += [("pegs", "Çiviler", stems, t, t + H - HEAD_H, pc), ("pegs", "Çiviler", heads, t + H - HEAD_H, t + H, pc)]
        if min(Point(a).distance(Point(b)) for a, b in zip(pts, pts[1:])) < HEAD_D + 0.8:
            w.append("Çiviler birbirine çok yakın; aralığı büyütün.")
    else:
        cuts = unary_union([Point(p).buffer(v["nail_mm"] / 2 - 0.1, quad_segs=10) for p in pts])  # snug for the nail
    if v["hanger"]:
        hx0, hy0, hx1, hy1 = board.bounds
        cuts = unary_union([c for c in (cuts, Point(0, hy1 - 6).buffer(2.5, quad_segs=16)) if c is not None])
    parts = flat.layer_parts(layers, "string_art", cuts=cuts)
    for p in parts:
        p.meta["count"] = v["count"]
    bx0, by0, bx1, by1 = board.bounds
    notes = [f"Pano {bx1 - bx0:.0f} × {by1 - by0:.0f} mm, {len(pts)} çivi ({v['pitch_mm']:g} mm arayla), "
             f"~{sum(p.meta['grams'] for p in parts):.0f} g ≈ {sum(p.meta['cost_try'] for p in parts):.0f} TL."]
    if v["pegs"] == "printed":
        notes.append("Çiviler panoyla birlikte basılır (başlık ipi tutar). İpi bir çiviye bağlayın, şeklin çevresinde dolaşıp "
                     "karşı çivilere çapraz geçirerek içi doldurun; sonunda düğümleyip bir damla yapıştırıcı sürün.")
    else:
        notes.append(f"Delikler Ø{v['nail_mm']:g} mm çivi için sıkı; çivileri çekiçle yarısına kadar çakın.")
    if v["board"] == "shape" and v["source"] == "shape":
        notes.append("İpli çerçeve: 'Dikdörtgen pano' seçerseniz iplerle dış alanı da doldurabilirsiniz.")
    return BuildResult(parts, w, {"pegs": len(pts)}, notes)


GENERATOR = Generator(
    key="string_art", label="İp sanatı panosu", group="Hediyelik",
    description="Kalp, yıldız, isim ya da logo çevresinde basılı çivili (ya da çivi delikli) ip sanatı panosu.",
    params=[
        Param("source", "Şekil kaynağı", "choice", "shape", options=[("shape", "Hazır şekil"), ("text", "Yazı silüeti"), ("logo", "Logo / görsel")], section="Şekil"),
        Param("shape", "Şekil", "choice", "heart", options=list(SHAPES_TR.items()), section="Şekil", show_if={"source": "shape"}),
        Param("text", "Yazı", "text", "Ece", section="Şekil", show_if={"source": "text"}),
        Param("font", "Yazı tipi", "font", "Righteous", section="Şekil", show_if={"source": "text"}),
        Param("logo", "Dosya", "file", "", section="Şekil", show_if={"source": "logo"}),
        Param("width_mm", "Şekil genişliği", "number", 140, min=50, max=230, step=5, unit="mm", section="Şekil"),
        Param("pitch_mm", "Çivi aralığı", "number", 8, min=5, max=25, step=0.5, unit="mm", section="Çiviler"),
        Param("pegs", "Çivi", "choice", "printed", options=[("printed", "Basılı çivi"), ("holes", "Gerçek çivi deliği")], section="Çiviler"),
        Param("peg_mm", "Çivi yüksekliği", "number", 10, min=6, max=20, step=0.5, unit="mm", section="Çiviler", show_if={"pegs": "printed"}),
        Param("nail_mm", "Çivi çapı", "number", 1.6, min=1, max=3, step=0.1, unit="mm", section="Çiviler", show_if={"pegs": "holes"}),
        Param("board", "Pano", "choice", "rect", options=[("rect", "Dikdörtgen"), ("shape", "Şekil çevresi")], section="Pano"),
        Param("margin_mm", "Kenar payı", "number", 12, min=5, max=40, step=1, unit="mm", section="Pano"),
        Param("board_mm", "Pano kalınlığı", "number", 2.4, min=2, max=8, step=0.2, unit="mm", section="Pano"),
        Param("hanger", "Asma deliği", "bool", True, section="Pano"),
        Param("board_color", "Pano rengi", "color", "#FFFFFF", section="Renk"),
        Param("peg_color", "Çivi rengi", "color", "#C9A27E", section="Renk"),
        Param("count", "Adet", "int", 1, min=1, max=4, section="Baskı"),
    ],
    build=build,
)
