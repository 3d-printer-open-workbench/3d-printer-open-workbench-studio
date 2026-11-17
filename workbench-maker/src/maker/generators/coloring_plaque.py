"""Coloring plaque: a plate with raised outline walls for children to paint inside (acrylic / markers): a built-in
shape and / or the outline of a name, or the colour regions of an uploaded drawing / logo. Single colour, cheap."""
from __future__ import annotations

from pathlib import Path

from shapely import affinity
from shapely.geometry import box
from shapely.ops import unary_union

from .. import core, flat
from ..shapes import SHAPES_TR, shape_polygon
from .base import BuildResult, Generator, Param


def outline_walls(g, line: float):
    """Raised walls along every boundary of ``g`` (outer and holes), ``line`` mm wide."""
    return unary_union([g.boundary.buffer(line / 2, quad_segs=6)])


def build(v: dict) -> BuildResult:
    w: list[str] = []
    W, line = v["width_mm"], v["line_mm"]
    art = []
    if v["picture"] == "shape":
        art.append(shape_polygon(v["shape"], W * 0.62))
    elif v["picture"] == "image":
        if not v["image"] or not Path(v["image"]).is_file():
            raise ValueError("Çizim / logo dosyası seçin (SVG, PNG ya da JPG).")
        logo = core.load_logo(v["image"], W * 0.75, v["regions"])
        w += logo.warnings
        art += [affinity.translate(r.geometry, -logo.width_mm / 2, -logo.height_mm / 2) for r in logo.regions]
    pic = unary_union(art) if art else None
    name = v["name"].strip()
    tg = None
    if name:
        tg = flat.text(name, v["font"], w, width_mm=W * 0.8)
        tg = affinity.translate(tg, -(tg.bounds[0] + tg.bounds[2]) / 2, 0)
        if pic is not None:
            tg = affinity.translate(tg, 0, pic.bounds[1] - 6 - tg.bounds[3])
        else:
            tg = affinity.translate(tg, 0, -(tg.bounds[1] + tg.bounds[3]) / 2)
    content = unary_union([g for g in (pic, tg) if g is not None])
    if content.is_empty:
        raise ValueError("Bir şekil, çizim ya da isim seçin.")
    x0, y0, x1, y1 = content.bounds
    m = v["margin_mm"]
    plate = box(x0 - m, y0 - m, x1 + m, y1 + m).buffer(-5, quad_segs=8).buffer(5, quad_segs=8)
    plate = affinity.translate(plate, 0, 0)
    t, wall_h = v["plate_mm"], v["wall_mm"]
    walls = outline_walls(content, line).union(plate.difference(plate.buffer(-line, quad_segs=8)))  # frame
    small = [q for q in getattr(content, "geoms", [content]) for r in [q.buffer(-1.5)] if r.is_empty]
    if small:
        w.append(f"{len(small)} bölge boyamak için çok dar (< 3 mm); çizimi büyütün ya da daha az renk bölgesi seçin.")
    c = core.norm_hex(v["color"])
    layers = [("plate", "Plaket", plate, 0.0, t, c), ("lines", "Kabarık çizgiler", walls, t, t + wall_h, c)]
    if v["hanger"]:
        px0, py0, px1, py1 = plate.bounds
        plate_cut = unary_union([box(-1, -1, 1, 1).buffer(1.5).buffer(1.0)]).buffer(0)
        cuts = affinity.translate(plate_cut, 0, py1 - 7)
    else:
        cuts = None
    parts = flat.layer_parts(layers, "coloring", cuts=cuts)
    for p in parts:
        p.meta["count"] = v["count"]
    bx0, by0, bx1, by1 = plate.bounds
    notes = [f"Plaket {bx1 - bx0:.0f} × {by1 - by0:.0f} mm, ~{sum(p.meta['grams'] for p in parts):.0f} g ≈ "
             f"{sum(p.meta['cost_try'] for p in parts):.0f} TL / adet.",
             f"Kabarık çizgiler {wall_h:g} mm: boya taşmaz. Akrilik boya ya da kalın keçeli kalemle boyanır; beyaz PLA en iyi sonucu verir.",
             "Çocuk etkinlikleri ve doğum günü hediyesi için toplu basın (Adet)."]
    return BuildResult(parts, w, {"size_mm": [round(bx1 - bx0, 1), round(by1 - by0, 1)]}, notes)


GENERATOR = Generator(
    key="coloring_plaque", label="Boyama plaketi", group="Hediyelik",
    description="Çocuklar için boyanacak plaket: kabarık çizgili şekil, isim harfleri ya da yüklenen çizimin bölgeleri.",
    params=[
        Param("picture", "Resim", "choice", "shape", options=[("shape", "Hazır şekil"), ("image", "Çizim / logo"), ("none", "Yok (yalnız isim)")], section="Resim"),
        Param("shape", "Şekil", "choice", "star", options=list(SHAPES_TR.items()), section="Resim", show_if={"picture": "shape"}),
        Param("image", "Dosya", "file", "", section="Resim", show_if={"picture": "image"}, help="Az renkli çizim en iyisi"),
        Param("regions", "Bölge sayısı", "int", 3, min=1, max=4, section="Resim", show_if={"picture": "image"}),
        Param("name", "İsim", "text", "Ece", section="İsim"),
        Param("font", "Yazı tipi", "font", "Righteous", section="İsim", help="Kalın harfler daha kolay boyanır"),
        Param("width_mm", "Genişlik", "number", 120, min=60, max=230, step=5, unit="mm", section="Plaket"),
        Param("margin_mm", "Kenar payı", "number", 8, min=4, max=20, step=1, unit="mm", section="Plaket"),
        Param("line_mm", "Çizgi kalınlığı", "number", 1.2, min=0.8, max=3, step=0.2, unit="mm", section="Plaket"),
        Param("wall_mm", "Çizgi yüksekliği", "number", 1.6, min=0.8, max=4, step=0.2, unit="mm", section="Plaket"),
        Param("plate_mm", "Plaket kalınlığı", "number", 2.4, min=1.6, max=5, step=0.2, unit="mm", section="Plaket"),
        Param("hanger", "Asma deliği", "bool", True, section="Plaket"),
        Param("color", "Renk", "color", "#FFFFFF", section="Baskı"),
        Param("count", "Adet", "int", 1, min=1, max=20, section="Baskı"),
    ],
    build=build,
)
