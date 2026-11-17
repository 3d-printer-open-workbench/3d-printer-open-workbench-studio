"""Container: pen holder, box with a slip-on lid, sticker / craft box with compartments. Any basic shape; optional
name wrapped around a round container (raised height field, 45 deg flanks), engraved or two-colour inlaid lid text."""
from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import Point, box
from shapely.ops import unary_union

from .. import core, flat
from ..shapes import SHAPES_TR, shape_polygon
from . import roller
from .base import BuildResult, Generator, Param, Part
from .. import estimate

LID_T = 2.0
LIP_W = 1.6
INLAY_MM = 0.6


def _part(name, label, solid, color, material, **meta) -> Part:
    mesh = core.to_trimesh(solid)
    e = estimate.part_estimate(mesh, material, "part")
    return Part(name, label, mesh, color, material, {"grams": e.grams, "minutes": e.minutes, "cost_try": e.try_, **meta})


def build(v: dict) -> BuildResult:
    w: list[str] = []
    W, H, wall, bot = v["width_mm"], v["height_mm"], v["wall_mm"], v["bottom_mm"]
    outline = shape_polygon(v["shape"], W)
    inner = outline.buffer(-wall, quad_segs=16)
    if inner.is_empty or inner.geom_type != "Polygon":
        raise ValueError("Duvar bu şekil için fazla kalın ya da şekil çok küçük.")
    c, mat = core.norm_hex(v["color"]), v["material"]
    side = v["side_text"].strip()
    if side and v["shape"] != "circle":
        w.append("Yan yazı yalnızca daire şeklinde yapılır; atlandı.")
        side = ""
    if side:
        R = W / 2
        C = 2 * math.pi * R
        g = flat.text(side, v["font"], w, height_mm=min(v["side_mm"], H * 0.6))
        if g.bounds[2] - g.bounds[0] > C * 0.9:
            g = flat.text(side, v["font"], w, width_mm=C * 0.9)
        x0, y0, x1, y1 = g.bounds
        g = affinity.translate(g, C * 0.75 - (x0 + x1) / 2, H * v["side_pos"] / 100 - (y0 + y1) / 2)  # u = 3/4 C faces -y (front)
        hf = roller.height_field(g, C, H, v["side_relief"])
        tube = roller.sleeve_mesh(hf, R, R - wall, H)
        body = core.from_trimesh(tube) + core.extrude(Point(0, 0).buffer(R - wall + 0.05, quad_segs=64), 0.0, bot)
    else:
        body = core.extrude(outline, 0.0, H) - core.extrude(inner, bot, H + 1)
    lid = v["lid"]
    lip_h = v["lip_mm"]
    div_top = H - (lip_h + 0.5 if lid else 0.0)
    rows, cols = v["rows"], v["cols"]
    if rows > 1 or cols > 1:
        ix0, iy0, ix1, iy1 = inner.bounds
        bars = [box(ix0 + (ix1 - ix0) * k / cols - v["divider_mm"] / 2, iy0 - 1, ix0 + (ix1 - ix0) * k / cols + v["divider_mm"] / 2, iy1 + 1)
                for k in range(1, cols)]
        bars += [box(ix0 - 1, iy0 + (iy1 - iy0) * k / rows - v["divider_mm"] / 2, ix1 + 1, iy0 + (iy1 - iy0) * k / rows + v["divider_mm"] / 2)
                 for k in range(1, rows)]
        body = body + core.extrude(unary_union(bars).intersection(inner.buffer(0.2)), bot - 0.01, div_top)
    parts = [_part("body", "Kap", body, c, mat, group="body", batch=c)]
    notes = []
    if lid:
        lc = core.norm_hex(v["lid_color"])
        ring = inner.buffer(-v["clear_mm"], quad_segs=16)
        lip = ring.difference(ring.buffer(-LIP_W, quad_segs=16))
        lid_s = core.extrude(outline, 0.0, LID_T) + core.extrude(lip, LID_T - 0.01, LID_T + lip_h)
        dx = outline.bounds[2] - outline.bounds[0] + 10
        lid_parts = []
        txt = v["lid_text"].strip()
        if txt:
            g, _ = flat.fit_text(txt, v["font"], outline.buffer(-3), (outline.bounds[2] - outline.bounds[0]) * 0.75, w, "Kapak yazısı")
            g = affinity.scale(g, -1, 1, origin=(0, 0))  # on the bed face: mirrored so it reads on the finished lid
            lid_s = lid_s - core.extrude(g, -0.01, INLAY_MM)
            if v["lid_text_style"] == "inlay":
                tc = core.norm_hex(v["text_color"])
                lid_parts.append(_part("lid_text", "Kapak yazısı", core.extrude(g, 0.0, INLAY_MM).translate((dx, 0, 0)), tc, mat,
                                       group="lid", batch="lid"))  # same object as the lid
                notes.append(f"Kapak yazısı iki renk, ilk {INLAY_MM:g} mm'de ({round(INLAY_MM / core.LAYER_H)} katman): CANVAS bu katmanlarda "
                             "renk değiştirir; tek renk için 'Kazıma' seçin.")
            else:
                notes.append("Kapak yazısı tablaya bakan yüze kazınır (aynalı): kapak üstünde doğru okunur.")
        lid_meta = {"group": "lid", "batch": "lid" if lid_parts else lc}
        parts.append(_part("lid", "Kapak", lid_s.translate((dx, 0, 0)), lc, mat, **lid_meta))
        parts += lid_parts
        notes.append(f"Kapak ağzı {v['clear_mm']:g} mm boşlukla içeri geçer; sıkı ya da gevşekse 'Kapak boşluğu' değerini değiştirin.")
    for p in parts:
        p.meta["count"] = v["count"]
    vol_ml = inner.area * (H - bot) / 1000
    grams = sum(p.meta["grams"] for p in parts)
    notes.insert(0, f"Kap {outline.bounds[2] - outline.bounds[0]:.0f} × {outline.bounds[3] - outline.bounds[1]:.0f} × {H:g} mm, "
                    f"iç hacim ~{vol_ml:.0f} ml, ~{grams:.0f} g ≈ {sum(p.meta['cost_try'] for p in parts):.0f} TL.")
    if side:
        notes.append("Yan yazı kabarık ve 45° kenarlı: dik baskıda destek gerekmez.")
    return BuildResult(parts, w, {"volume_ml": round(vol_ml)}, notes)


GENERATOR = Generator(
    key="container", label="Kap / kalemlik / kutu", group="Hediyelik",
    description="Kalemlik, kapaklı kutu, bölmeli sticker kutusu: hazır şekil, yuvarlakta çevresine isim, kapakta kazıma ya da iki renkli yazı.",
    params=[
        Param("shape", "Şekil", "choice", "circle", options=list(SHAPES_TR.items()), section="Kap"),
        Param("width_mm", "Genişlik", "number", 75, min=30, max=240, step=1, unit="mm", section="Kap"),
        Param("height_mm", "Yükseklik", "number", 100, min=15, max=240, step=1, unit="mm", section="Kap"),
        Param("wall_mm", "Duvar", "number", 1.2, min=0.8, max=5, step=0.2, unit="mm", section="Kap"),
        Param("bottom_mm", "Taban", "number", 1.6, min=0.8, max=6, step=0.2, unit="mm", section="Kap"),
        Param("rows", "Bölme satırı", "int", 1, min=1, max=6, section="Bölmeler"),
        Param("cols", "Bölme sütunu", "int", 1, min=1, max=6, section="Bölmeler"),
        Param("divider_mm", "Bölme duvarı", "number", 1.2, min=0.8, max=3, step=0.2, unit="mm", section="Bölmeler"),
        Param("side_text", "Yan yazı", "text", "", section="Yazı", help="Yalnızca daire: çevresine kabarık isim"),
        Param("font", "Yazı tipi", "font", "Righteous", section="Yazı"),
        Param("side_mm", "Yan yazı yüksekliği", "number", 18, min=6, max=60, step=1, unit="mm", section="Yazı"),
        Param("side_pos", "Yan yazı konumu", "int", 50, min=20, max=80, unit="%", section="Yazı", help="Yükseklik içinde"),
        Param("side_relief", "Yan yazı kabartması", "number", 1.2, min=0.6, max=3, step=0.2, unit="mm", section="Yazı"),
        Param("lid", "Kapak", "bool", False, section="Kapak"),
        Param("lip_mm", "Kapak ağzı", "number", 5, min=3, max=15, step=0.5, unit="mm", section="Kapak", show_if={"lid": True}),
        Param("clear_mm", "Kapak boşluğu", "number", 0.25, min=0.1, max=0.6, step=0.05, unit="mm", section="Kapak", show_if={"lid": True}),
        Param("lid_text", "Kapak yazısı", "text", "", section="Kapak", show_if={"lid": True}),
        Param("lid_text_style", "Kapak yazı türü", "choice", "engrave", options=[("engrave", "Kazıma (tek renk)"), ("inlay", "İki renk (gömme)")],
              section="Kapak", show_if={"lid": True}),
        Param("material", "Malzeme", "choice", "PLA", options=[("PLA", "PLA"), ("PETG", "PETG")], section="Baskı"),
        Param("color", "Renk", "color", "#3E7CB1", section="Baskı"),
        Param("lid_color", "Kapak rengi", "color", "#3E7CB1", section="Baskı", show_if={"lid": True}),
        Param("text_color", "Kapak yazı rengi", "color", "#FFFFFF", section="Baskı", show_if={"lid_text_style": "inlay"}),
        Param("count", "Adet", "int", 1, min=1, max=6, section="Baskı"),
    ],
    build=build,
)
