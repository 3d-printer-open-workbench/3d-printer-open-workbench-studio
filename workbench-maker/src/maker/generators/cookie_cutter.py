"""Cookie cutter from a shape, text silhouette or logo, with an optional stamp (text / logo / contour line, mirrored)
that fits inside the cutter and a push-in handle; the long handle makes the stamp an ejector."""
from __future__ import annotations

from shapely import affinity

from .. import baking, core
from ..shapes import SHAPES_TR
from .base import BuildResult, Generator, Param

GAP = 8.0  # between parts in the layout


def build(v: dict) -> BuildResult:
    w: list[str] = []
    inside, w0, own = baking.outline_from(v, v["width_mm"])
    w += w0
    inside = baking.check_dough(inside, w)
    H, mat = v["height_mm"], v["material"]
    cc, sc = core.norm_hex(v["cutter_color"]), core.norm_hex(v["stamp_color"])
    blade = baking.cutter_blade(baking.mirror(inside), H, v["wall_mm"], v["flange_mm"], 1.2)
    parts = [baking.part("cutter", "Kesici", blade, cc, mat, group="cutter", batch=cc)]
    notes = [f"Kesici {inside.bounds[2] - inside.bounds[0]:.0f} × {inside.bounds[3] - inside.bounds[1]:.0f} mm, {H:g} mm yüksek: "
             "geniş kenar tablada, ince kesme ağzı yukarıda basılır; kullanırken ters çevirin."]
    x_next = inside.bounds[2] + v["wall_mm"] + v["flange_mm"] + GAP
    if v["stamp"] != "none" or v["handle"] != "none":
        plate = inside.buffer(-baking.STAMP_CLEAR, quad_segs=12)
        relief = baking.relief_from(v, plate, w, own=own)
        plate, relief = baking.mirror(plate), baking.mirror(relief)  # both turned over in use
        base, rel, socket = baking.stamp_plate(plate, relief, 3.0, v["relief_mm"], w, socket=v["handle"] != "none")
        dx = x_next - plate.bounds[0]
        stamp = core.union_all([base] + ([rel] if rel is not None else [])).translate((dx, 0, 0))
        label = "Damga" if v["handle"] != "ejector" else "Damga / itici"
        parts.append(baking.part("stamp", label, stamp, sc, mat, group="stamp", batch=sc))
        x_next = plate.bounds[2] + dx + GAP
        if socket:
            reach = H - 3.0 - (v["relief_mm"] if rel is not None else 0) + 8.0 if v["handle"] == "ejector" else 8.0
            grip = min(28.0, (plate.bounds[3] - plate.bounds[1]) * 0.8, (plate.bounds[2] - plate.bounds[0]) * 0.8)
            h = baking.handle(reach, max(16.0, grip)).translate((x_next + max(16.0, grip) / 2, 0, 0))
            parts.append(baking.part("handle", "Sap", h, sc, mat, group="handle", batch=sc))
            notes.append("Sapı damganın arkasındaki yuvaya bastırarak takın (sıkı geçme; gevşekse bir damla gıdaya uygun yapıştırıcı)."
                         + (" Uzun sap itici olarak çalışır: kestikten sonra damgayla hamuru bastırıp kesiciden çıkarın."
                            if v["handle"] == "ejector" else ""))
        if rel is not None:
            notes.append("Damga kabartması aynalı: kurabiyede doğru okunur. Hamuru kesip damgayı 2–3 mm bastırın.")
    if v["source"] != "shape":
        notes.append("Kesici de aynalı basılır (ters çevrilip kullanıldığı için): kurabiye şekli doğru yönde çıkar.")
    for p in parts:
        p.meta["count"] = v["count"]
    g = sum(p.meta["grams"] * v["count"] for p in parts)
    notes.insert(0, f"Toplam ~{g:.0f} g ≈ {sum(p.meta['cost_try'] for p in parts) * v['count']:.0f} TL ({v['count']} takım).")
    notes += baking.FOOD_NOTES
    return BuildResult(parts, w, {"cut_mm": [round(x, 1) for x in inside.bounds]}, notes)


STAMP_PARAMS = [
    Param("stamp", "Damga", "choice", "contour", options=[("none", "Yok"), ("contour", "Kenar çizgisi"), ("text", "Yazı"), ("logo", "Logo")],
          section="Damga", help="Kurabiyenin üstüne basılan desen"),
    Param("stamp_text", "Damga yazısı", "text", "", section="Damga", show_if={"stamp": "text"}, help="Boş + yazı silüeti = aynı yazı"),
    Param("stamp_font", "Damga yazı tipi", "font", "Righteous", section="Damga", show_if={"stamp": "text"}),
    Param("stamp_logo", "Damga logosu", "file", "", section="Damga", show_if={"stamp": "logo"}, help="SVG, PNG ya da JPG (tek renk)"),
    Param("stamp_pct", "Damga genişliği", "int", 70, min=20, max=95, unit="%", section="Damga", show_if={"stamp": ["text", "logo"]}),
    Param("relief_mm", "Damga kabartması", "number", 2.0, min=0.8, max=4, step=0.2, unit="mm", section="Damga"),
]

GENERATOR = Generator(
    key="cookie_cutter", label="Kurabiye kesici + damga", group="Mutfak",
    description="Hazır şekil, yazı ya da logodan kurabiye kesici; içine giren aynalı damga (yazı, logo, kenar çizgisi) ve takılır sap / itici.",
    params=[
        Param("source", "Şekil kaynağı", "choice", "shape", options=[("shape", "Hazır şekil"), ("text", "Yazı silüeti"), ("logo", "Logo / görsel")], section="Şekil"),
        Param("shape", "Şekil", "choice", "heart", options=list(SHAPES_TR.items()), section="Şekil", show_if={"source": "shape"}),
        Param("text", "Yazı", "text", "Ayşe", section="Şekil", show_if={"source": "text"}),
        Param("font", "Yazı tipi", "font", "Righteous", section="Şekil", show_if={"source": "text"}),
        Param("logo", "Dosya", "file", "", section="Şekil", show_if={"source": "logo"}, help="SVG, PNG ya da JPG; tek parça silüete çevrilir"),
        Param("width_mm", "Genişlik", "number", 70, min=25, max=200, step=1, unit="mm", section="Şekil"),
        Param("height_mm", "Kesici yüksekliği", "number", 15, min=8, max=30, step=1, unit="mm", section="Kesici"),
        Param("wall_mm", "Duvar", "number", 1.2, min=0.8, max=2.4, step=0.2, unit="mm", section="Kesici", help="Kesme ağzı her zaman 0.8 mm"),
        Param("flange_mm", "Tutma kenarı", "number", 3, min=0, max=8, step=0.5, unit="mm", section="Kesici"),
        *STAMP_PARAMS,
        Param("handle", "Sap", "choice", "ejector", options=[("none", "Yok"), ("short", "Kısa sap"), ("ejector", "İtici (uzun sap)")], section="Damga"),
        Param("material", "Malzeme", "choice", "PLA", options=[("PLA", "PLA"), ("PETG", "PETG")], section="Baskı"),
        Param("cutter_color", "Kesici rengi", "color", "#E3A23B", section="Baskı"),
        Param("stamp_color", "Damga rengi", "color", "#E3A23B", section="Baskı", help="Kesiciyle aynıysa hepsi tek tablada"),
        Param("count", "Takım", "int", 1, min=1, max=10, section="Baskı"),
    ],
    build=build,
)
