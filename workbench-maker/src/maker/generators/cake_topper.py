"""Cake topper: 1-2 lines of (script) text, either on a bubble outline in a second colour (sturdy, letters always
connected) or as bare connected lettering, optional heart / star accents, with pointed stakes for the cake."""
from __future__ import annotations

from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import nearest_points, unary_union

from .. import core, flat
from ..shapes import shape_polygon
from .base import BuildResult, Generator, Param

STAKE_W = 5.0
TIP_MM = 8.0


def _stake(x: float, top: float, length: float):
    """Stake from ``top`` (inside the topper) down ``length`` mm with a pointed tip."""
    y1 = top - length
    return Polygon([(x - STAKE_W / 2, top), (x + STAKE_W / 2, top), (x + STAKE_W / 2, y1 + TIP_MM), (x, y1), (x - STAKE_W / 2, y1 + TIP_MM)])


def _bottom_at(outline, x: float) -> float | None:
    """Lowest point of the outline on the vertical line through x."""
    x0, y0, x1, y1 = outline.bounds
    hit = outline.intersection(LineString([(x, y0 - 1), (x, y1 + 1)]))
    return None if hit.is_empty else hit.bounds[1]


def _script(g, art, txt: str, v: dict, y0: float):
    """Bare lettering held together by a thin bar on each baseline (hidden behind joined script letters) and posts
    through the lines where the stakes go; the 0.4 mm grow merges letters that nearly touch."""
    bases, cap = core.text_baselines(txt, v["font"], v["width_mm"])
    x0, _, x1, _ = g.bounds
    bar = max(2.4, cap * 0.12)
    joins = []
    for b in bases:
        line = g.intersection(box(x0 - 1, b - 0.5, x1 + 1, b + cap))
        if line.is_empty:
            continue
        lx0, _, lx1, _ = line.bounds
        joins.append(box(lx0 + 1.0, b - y0 - bar * 0.25, lx1 - 1.0, b - y0 + bar * 0.75))
    if len(bases) > 1:
        lo, hi = min(bases) - y0, max(bases) - y0 + bar
        joins += [box(x - STAKE_W / 2, lo, x + STAKE_W / 2, hi) for x in _stake_xs(x1 - x0)]
    out = unary_union([art.buffer(0.4, quad_segs=8)] + joins)
    while out.geom_type != "Polygon":  # loose bits (i dots, accents, stars): tie each to the nearest piece
        pieces = sorted(out.geoms, key=lambda q: -q.area)
        main, rest = pieces[0], unary_union(pieces[1:])
        nearest = min(pieces[1:], key=lambda q: q.distance(main))
        a, b = nearest_points(nearest, main)
        out = unary_union([main, rest, LineString([a, b]).buffer(max(1.6, bar * 0.6), cap_style=1)])
    return out


def _stake_xs(width: float) -> list[float]:
    return [0.0] if width < 60 else [-width * 0.28, width * 0.28]


def build(v: dict) -> BuildResult:
    w: list[str] = []
    txt = v["text"].replace("\\n", "\n").strip()
    if not txt:
        raise ValueError("Pasta süsü için bir yazı girin.")
    g = flat.text(txt, v["font"], w, width_mm=v["width_mm"])
    x0, y0, x1, y1 = g.bounds
    g = affinity.translate(g, -(x0 + x1) / 2, -y0)
    deco = None
    if v["accent"] != "none":
        s = min(18.0, (y1 - y0) * 0.6)
        a = shape_polygon("heart" if v["accent"] == "hearts" else "star", s)
        hw = (x1 - x0) / 2
        deco = unary_union([affinity.translate(a, sx * (hw + s * 0.6), (y1 - y0) * 0.7) for sx in (-1, 1)])
    art = unary_union([g] + ([deco] if deco is not None else []))
    t, r = v["thick_mm"], v["relief_mm"]
    bc, tc = core.norm_hex(v["base_color"]), core.norm_hex(v["text_color"])
    if v["style"] == "outline":
        outline = flat.bubble(art, v["border_mm"])
        layers_top = [("text", "Yazı", art, tc)]
    else:
        outline = _script(g, art, txt, v, y0)
        layers_top = []
    ox0, oy0, ox1, oy1 = outline.bounds
    xs = _stake_xs(g.bounds[2] - g.bounds[0]) if v["style"] == "script" else _stake_xs(ox1 - ox0)
    n = len(xs)
    stakes = []
    for x in xs:
        b = _bottom_at(outline, x)
        if b is None:
            b = oy0
            w.append("Kazık yazının altına tam denk gelmiyor; önizlemede kontrol edin.")
        stakes.append(_stake(x, b + 4.0, v["stake_mm"] + 4.0))
    base = unary_union([outline] + stakes)
    layers = [("topper", "Pasta süsü", base, 0.0, t, bc)] + [(nm, lb, gg, t, t + r, c) for nm, lb, gg, c in layers_top]
    parts = flat.layer_parts(layers, "topper", material=v["material"])
    for p in parts:
        p.meta["count"] = v["count"]
    bx0, by0, bx1, by1 = base.bounds
    if bx1 - bx0 > core.BED_MM or by1 - by0 > core.BED_MM:
        w.append("Pasta süsü tablaya sığmıyor; genişliği ya da kazık boyunu azaltın.")
    grams = sum(p.meta["grams"] for p in parts)
    notes = [f"Pasta süsü {bx1 - bx0:.0f} × {by1 - by0:.0f} mm ({v['stake_mm']:g} mm kazık × {n}), ~{grams:.0f} g ≈ "
             f"{sum(p.meta['cost_try'] for p in parts):.0f} TL.",
             "Düz basılır. Kazıkları pastaya batırmadan önce streç film ya da alüminyum folyoyla sarın (gıdaya doğrudan değmesin)."]
    if len(parts) > 1:
        notes.append("İki renk üst üste: CANVAS bir kez filament değiştirir.")
    return BuildResult(parts, w, {"size_mm": [round(bx1 - bx0, 1), round(by1 - by0, 1), round(t + (r if layers_top else 0), 1)]}, notes)


GENERATOR = Generator(
    key="cake_topper", label="Pasta süsü", group="Doğum günü",
    description="El yazısı pasta süsü: 1–2 satır, iki renkli yazı çevresi tabanı ya da yalın bitişik yazı, kalp / yıldız süs, sivri kazıklar.",
    params=[
        Param("text", "Yazı", "text", "İyi ki doğdun\\nAyşe", section="Yazı", help="İki satır için \\n"),
        Param("font", "Yazı tipi", "font", "Pacifico", section="Yazı"),
        Param("width_mm", "Yazı genişliği", "number", 140, min=50, max=230, step=5, unit="mm", section="Yazı"),
        Param("accent", "Süs", "choice", "hearts", options=[("none", "Yok"), ("hearts", "Kalpler"), ("stars", "Yıldızlar")], section="Yazı"),
        Param("style", "Taban", "choice", "outline", options=[("outline", "Yazı çevresi (iki renk)"), ("script", "Yalın yazı")], section="Taban"),
        Param("border_mm", "Kenar payı", "number", 3, min=1.5, max=8, step=0.5, unit="mm", section="Taban", show_if={"style": "outline"}),
        Param("thick_mm", "Kalınlık", "number", 3, min=2, max=6, step=0.2, unit="mm", section="Taban"),
        Param("relief_mm", "Kabartma", "number", 1.2, min=0.4, max=3, step=0.2, unit="mm", section="Taban", show_if={"style": "outline"}),
        Param("stake_mm", "Kazık boyu", "number", 50, min=20, max=100, step=5, unit="mm", section="Taban"),
        Param("material", "Malzeme", "choice", "PLA", options=[("PLA", "PLA"), ("PETG", "PETG")], section="Baskı"),
        Param("base_color", "Taban rengi", "color", "#D4AF37", section="Baskı"),
        Param("text_color", "Yazı rengi", "color", "#FFFFFF", section="Baskı"),
        Param("count", "Adet", "int", 1, min=1, max=6, section="Baskı"),
    ],
    build=build,
)
