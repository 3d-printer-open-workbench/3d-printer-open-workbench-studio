"""Desk name plates: a rounded plate with a raised name (and an optional title line) in a second colour, an optional
frame line, leaning in a separate slotted stand. Colours are stacked layers: one filament change per plate."""
from __future__ import annotations

from shapely import affinity
from shapely.geometry import box

from .. import core, estimate, flat
from .base import BuildResult, Generator, Param, Part

PAD = 5.0  # frame line (or plate edge) to the text
RIM_IN = 2.5  # plate edge to the frame line
RIM_MM = 1.2  # frame line width
GAP = 3.0  # between the name and the title line
SLOT_KEEP = 10.0  # bottom strip that sits in the stand: nothing raised here
STAND_ANGLE = 75.0  # plate lean from horizontal in the stand
STAND_CLEAR = 0.3  # slot clearance per side
TITLE_SHARE = 0.36  # of the text area height, when there is a title line


def _round_rect(x0, y0, x1, y1, r):
    r = max(0.0, min(r, (x1 - x0) / 2 - 0.01, (y1 - y0) / 2 - 0.01))
    return box(x0 + r, y0 + r, x1 - r, y1 - r).buffer(r, quad_segs=16) if r > 0 else box(x0, y0, x1, y1)


def _line(s: str, font: str, region, warnings: list[str], what: str):
    """One text line as large as fits ``region`` (its bounding box, so accents and descenders stay inside), centred."""
    x0, y0, x1, y1 = region.bounds
    max_w, max_h = x1 - x0, y1 - y0
    own: list[str] = []
    g = flat.text(s, font, own, width_mm=max_w)
    h = g.bounds[3] - g.bounds[1]
    if h > max_h:  # short text: the height limits the size
        own = []
        g = flat.text(s, font, own, width_mm=max_w * max_h / h)
    g = flat.thicken(g, own, what)
    gx0, gy0, gx1, gy1 = g.bounds
    g = affinity.translate(g, (x0 + x1) / 2 - (gx0 + gx1) / 2, (y0 + y1) / 2 - (gy0 + gy1) / 2)
    warnings += [f"{what}: {x}" if not x.startswith(what) else x for x in own if x not in warnings]
    return g


def build(v: dict) -> BuildResult:
    name, title = v["text"].strip(), v["title"].strip()
    if not name:
        raise ValueError("İsimlik için bir isim yazın.")
    w: list[str] = []
    W, H, t, r = v["width_mm"], v["height_mm"], v["base_mm"], v["relief_mm"]
    bc, tc = core.norm_hex(v["base_color"]), core.norm_hex(v["text_color"])
    outline = _round_rect(-W / 2, -H / 2, W / 2, H / 2, v["corner_mm"])
    low = SLOT_KEEP if v["stand"] else 0.0  # the stand slot hides and grips the bottom strip
    frame = _round_rect(-W / 2 + RIM_IN, -H / 2 + RIM_IN + low, W / 2 - RIM_IN, H / 2 - RIM_IN, max(v["corner_mm"] - RIM_IN, 1.0))
    top: list[tuple] = []
    if v["rim"]:
        top.append(("rim", "Çerçeve çizgisi", frame.difference(frame.buffer(-RIM_MM, quad_segs=12)), tc))
        area = frame.buffer(-(RIM_MM + PAD), quad_segs=12)
    else:
        area = frame.buffer(-PAD, quad_segs=12)
    if area.is_empty or area.bounds[3] - area.bounds[1] < 8:
        raise ValueError("Plaka yazı için çok alçak; yüksekliği artırın ya da çerçeve çizgisini kapatın.")
    ax0, ay0, ax1, ay1 = area.bounds
    if title:
        split = ay0 + (ay1 - ay0) * TITLE_SHARE
        g = _line(name, v["font"], flat.band(area, split + GAP / 2, ay1), w, "İsim")
        g2 = _line(title, v["title_font"] or v["font"], flat.band(area, ay0, split - GAP / 2), w, "Unvan")
        top += [("text", "İsim", g, tc), ("title", "Unvan", g2, tc)]
    else:
        g = _line(name, v["font"], area, w, "İsim")
        top.append(("text", "İsim", g, tc))
    layers = [("base", "Plaka", outline, 0.0, t, bc)] + [(n, lb, q, t, t + r, c) for n, lb, q, c in top]
    parts = flat.layer_parts(layers, "nameplate")
    notes: list[str] = []
    if v["stand"]:
        sm, L = flat.slot_stand(W, t, STAND_ANGLE, STAND_CLEAR)
        m = sm.copy()
        m.apply_translation([-W / 2 - m.bounds[0][0], -H / 2 - 10 - m.bounds[1][1], -m.bounds[0][2]])  # in front of the plate on the bed
        e = estimate.part_estimate(m, "PLA", "flat")
        parts.append(Part("stand", "Masa standı", m, core.norm_hex(v["stand_color"]), "PLA",
                          {"group": "stand", "batch": "stand", "grams": e.grams, "minutes": e.minutes, "cost_try": e.try_}))
        notes.append(f"Stand ayrı basılır ({L:.0f} mm); plaka yuvaya {STAND_ANGLE:.0f}° eğimle oturur (yuva {t + 2 * STAND_CLEAR:.1f} mm). "
                     f"Plakanın alt {SLOT_KEEP:.0f} mm'si yuvada kalır, o şeritte kabartma yoktur.")
    else:
        notes.append("Standsız: plaka düz durur; arkasına çift taraflı bant ya da kendi ayağınız gerekir.")
    for p in parts:
        p.meta["count"] = v["count"]
    colors = list(dict.fromkeys(p.color for p in parts if p.meta.get("group") == "nameplate"))
    grams = sum(p.meta["grams"] for p in parts)
    cost = sum(p.meta["cost_try"] for p in parts)
    notes.insert(0, f"İsimlik {W:.0f} × {H:.0f} × {t + r:.1f} mm, ~{grams:.0f} g ≈ {cost:.0f} TL / adet ({v['count']} adet).")
    if len(colors) > 1:
        notes.append("Yazı plakanın üstünde ayrı renk katmanıdır: CANVAS plaka başına bir kez filament değiştirir.")
    else:
        notes.append("Yazı ve plaka aynı renk: tek renk basılır, yazı yalnızca kabartmayla okunur.")
    notes.append("Kişiye özel üründür: basmadan önce önizlemeyi müşteriye onaylatın (isim yazımı, Türkçe harfler).")
    meta = {"size_mm": [W, H, round(t + r, 1)], "colors": colors, "grams_each": round(grams, 1),
            "text": name, "title": title, "stand": bool(v["stand"])}
    return BuildResult(parts, w, meta, notes)


GENERATOR = Generator(
    key="nameplate", label="Masaüstü isimlik", group="Hediyelik",
    description="Masada duran kişiye özel isimlik: iki renkli kabartma isim, isteğe bağlı unvan satırı ve çerçeve çizgisi, ayrı basılan eğimli stand.",
    params=[
        Param("text", "İsim", "text", "Ayşe Yılmaz", section="Yazı"),
        Param("title", "Unvan (ikinci satır)", "text", "", section="Yazı", help="Boş bırakılırsa tek satır"),
        Param("font", "Yazı tipi", "font", "Montserrat", section="Yazı"),
        Param("title_font", "Unvan yazı tipi", "font", "", section="Yazı", help="Boşsa isimle aynı"),
        Param("width_mm", "Genişlik", "number", 200, min=100, max=250, step=5, unit="mm", section="Plaka"),
        Param("height_mm", "Yükseklik", "number", 60, min=35, max=110, step=1, unit="mm", section="Plaka"),
        Param("corner_mm", "Köşe yuvarlaklığı", "number", 8, min=0, max=25, step=1, unit="mm", section="Plaka"),
        Param("rim", "Çerçeve çizgisi", "bool", True, section="Plaka", help="Yazı renginde ince çerçeve"),
        Param("base_color", "Plaka rengi", "color", "#1F2A44", section="Renk ve kalınlık"),
        Param("text_color", "Yazı rengi", "color", "#FFFFFF", section="Renk ve kalınlık", help="Plaka rengiyle aynıysa tek renk basılır"),
        Param("base_mm", "Plaka kalınlığı", "number", 3, min=2, max=6, step=0.2, unit="mm", section="Renk ve kalınlık"),
        Param("relief_mm", "Kabartma", "number", 1.2, min=0.4, max=3, step=0.2, unit="mm", section="Renk ve kalınlık"),
        Param("stand", "Masa standı", "bool", True, section="Stand"),
        Param("stand_color", "Stand rengi", "color", "#1F2A44", section="Stand", show_if={"stand": True}),
        Param("count", "Adet", "int", 1, min=1, max=20, section="Baskı"),
    ],
    build=build,
)
