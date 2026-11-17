"""Letter stamp for cookies / fondant / clay: 1-2 lines of mirrored raised text on a plate (bubble or rounded
rectangle) with a push-in handle."""
from __future__ import annotations

from shapely import affinity
from shapely.geometry import box

from .. import baking, core, flat
from .base import BuildResult, Generator, Param


def build(v: dict) -> BuildResult:
    w: list[str] = []
    txt = v["text"].replace("\\n", "\n").strip()
    if not txt:
        raise ValueError("Damga için bir yazı girin.")
    g = flat.text(txt, v["font"], w, height_mm=v["letter_mm"])
    x0, y0, x1, y1 = g.bounds
    g = affinity.translate(g, -(x0 + x1) / 2, -(y0 + y1) / 2)
    m = v["margin_mm"]
    if v["plate"] == "bubble":
        plate = flat.bubble(g, m)
    else:
        hw, hh = (x1 - x0) / 2 + m, (y1 - y0) / 2 + m
        plate = box(-hw, -hh, hw, hh).buffer(-2, quad_segs=8).buffer(2, quad_segs=8)
    g = flat.thicken(g, w, "Yazı", plate.buffer(-0.5))
    plate, relief = baking.mirror(plate), baking.mirror(g)  # turned over in use: reads right in the dough
    mat, c = v["material"], core.norm_hex(v["color"])
    base, rel, socket = baking.stamp_plate(plate, relief, v["plate_mm"], v["relief_mm"], w)
    parts = [baking.part("stamp", "Harf damgası", core.union_all([base, rel]), c, mat)]
    if socket:
        bx0, by0, bx1, by1 = plate.bounds
        grip = max(16.0, min(30.0, (by1 - by0) * 0.9))
        parts.append(baking.part("handle", "Sap", baking.handle(15.0, grip).translate((bx1 + 8 + grip / 2, 0, 0)), c, mat))
    for p in parts:
        p.meta["count"] = v["count"]
    bx0, by0, bx1, by1 = plate.bounds
    notes = [f"Damga {bx1 - bx0:.0f} × {by1 - by0:.0f} mm, harf yüksekliği {v['letter_mm']:g} mm, ~{sum(p.meta['grams'] for p in parts):.0f} g.",
             "Yazı aynalı basılır; hamurda / şeker hamurunda doğru okunur. 2–3 mm bastırın; yapışırsa damgayı una ya da nişastaya batırın.",
             "İki satır için yazıya \\n koyun (ör. 'Mutlu\\nYıllar')."] + baking.FOOD_NOTES
    return BuildResult(parts, w, {"size_mm": [round(bx1 - bx0, 1), round(by1 - by0, 1)]}, notes)


GENERATOR = Generator(
    key="letter_stamp", label="Harf damgası", group="Mutfak",
    description="Kurabiye, şeker hamuru ya da kil için aynalı yazı damgası: 1–2 satır, balon ya da dikdörtgen taban, takılır sap.",
    params=[
        Param("text", "Yazı", "text", "Afiyet olsun", section="Yazı", help="İki satır için \\n"),
        Param("font", "Yazı tipi", "font", "Pacifico", section="Yazı"),
        Param("letter_mm", "Harf yüksekliği", "number", 12, min=5, max=40, step=0.5, unit="mm", section="Yazı"),
        Param("plate", "Taban", "choice", "bubble", options=[("bubble", "Yazı çevresi"), ("rect", "Dikdörtgen")], section="Taban"),
        Param("margin_mm", "Kenar payı", "number", 3, min=1.5, max=10, step=0.5, unit="mm", section="Taban"),
        Param("plate_mm", "Taban kalınlığı", "number", 3, min=2, max=6, step=0.2, unit="mm", section="Taban"),
        Param("relief_mm", "Kabartma", "number", 2.0, min=0.8, max=4, step=0.2, unit="mm", section="Taban"),
        Param("material", "Malzeme", "choice", "PLA", options=[("PLA", "PLA"), ("PETG", "PETG")], section="Baskı"),
        Param("color", "Renk", "color", "#E3A23B", section="Baskı"),
        Param("count", "Adet", "int", 1, min=1, max=10, section="Baskı"),
    ],
    build=build,
)
