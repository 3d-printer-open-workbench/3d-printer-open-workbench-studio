"""Clearance calibration coupon: one small press female and 2-5 males with different sheet clearances (told apart by
1-5 marker holes in the clamp band). Form a sheet with each, pick the best, write its clearance into the user's sheets.yaml."""
from __future__ import annotations

from dataclasses import replace

from .. import core, estimate, thermo
from ..sheets import get_sheet
from ..shapes import shape_polygon
from .base import BuildResult, Generator, Param, Part, SheetLayout

SIZE_MM, DEPTH_MM = 32.0, 8.0
MARK_R = 1.0  # marker holes through the male base, in the clamp band (they also print dots on the test sheet)
MARK_PITCH = 4.0


def clearances(v: dict) -> list[float]:
    return [round(v["clear_min"] + i * v["clear_step"], 3) for i in range(v["count"])]


def _marked(male, outline, k: int):
    """Male with ``k`` holes in the clamp band in front (-y) of the plug: the coupon's number."""
    y = outline.bounds[1] - thermo.CLAMP_MM / 2
    x0 = -(k - 1) * MARK_PITCH / 2
    cuts = [core.cylinder(MARK_R, 2 * thermo.MALE_BASE_MM + 2, "z", (x0 + i * MARK_PITCH, y, 0.0)) for i in range(k)]
    return core.to_trimesh(core.from_trimesh(male) - core.union_all(cuts))


def build(v: dict) -> BuildResult:
    sheet = get_sheet(v["sheet"] or None)
    outline = thermo.centred(shape_polygon("square", SIZE_MM))
    outline, warnings = thermo.clean_outline(outline, sheet, DEPTH_MM)
    dome = thermo.Dome(outline, DEPTH_MM, profile="flat", draft_deg=v["draft_deg"], soften_mm=sheet.min_radius_mm)
    cl = clearances(v)
    sets = [thermo.press_molds(dome, replace(sheet, clearance_mm=c), economy=True) for c in cl]
    parts = [Part("female", "Dişi kupon kalıbı", sets[-1].female, "#3E7CB1", "PETG", {"role": "mold"})]
    gap = 10.0
    w = sets[0].male.extents[0]
    x = sets[-1].female.bounds[1][0] + gap
    for i, (c, ms) in enumerate(zip(cl, sets), 1):
        m = _marked(ms.male, outline, i)
        m.apply_translation([x - m.bounds[0][0], -m.bounds[0][1] - m.extents[1] / 2, 0])
        x += w + gap
        parts.append(Part(f"male_{i}", f"Erkek kupon {i} ({i} delik): tolerans {c:g} mm", m, "#E3A23B", "PETG", {"role": "mold", "clearance_mm": c}))
    for p in parts:
        e = estimate.part_estimate(p.mesh, p.material, "mold")
        p.meta.update(grams=e.grams, minutes=e.minutes, cost_try=e.try_)
    sw, sh = sets[0].sheet_size_mm
    t0, t1 = sheet.form_temp_c
    grams = sum(p.meta["grams"] for p in parts)
    notes = [
        f"Kupon seti ~{grams:.0f} g PETG ≈ {sum(p.meta['cost_try'] for p in parts):.0f} TL. Amaç: {sheet.label} levhanız için doğru kalıp toleransını ölçmek.",
        f"{len(cl)} adet {sw:.0f} × {sh:.0f} mm levha kesin. Her biriyle aynı dişi kalıbı, sırayla 1…{len(cl)} delikli erkek kalıpla basın; delikler levhanın kenarına nokta olarak çıkar, numarayı gösterir "
        f"(ısıtma {t0:.0f}–{t1:.0f} °C, hepsinde aynı sıcaklık ve süre).",
        "En iyi sonuç: köşeler ve düz üst yüzey keskin, levhada parlak ezik ya da yırtık yok, erkek kalıp zorlanmadan oturuyor. "
        "Ezik/yırtık varsa tolerans dar; köşeler yuvarlak ve yüzey dalgalıysa geniş.",
        f"Seçtiğiniz toleransı ~/.config/workbench-maker/sheets.yaml dosyasında '{sheet.id}' levhasının clearance_mm değerine yazın "
        f"(şimdiki değer {sheet.clearance_mm:g} mm). Bütün kalıplar bundan sonra bu toleransla üretilir.",
        "Aynı kuponla ısıtma sıcaklığını da deneyebilirsiniz: en iyi toleransta 10 °C arayla basıp sonucu karşılaştırın.",
    ]
    layout = SheetLayout((sw, sh), [outline], [outline.buffer(5.0, quad_segs=16)], title=f"Kupon levhası — {sheet.label}",
                         lines=[f"{len(cl)} adet kesin (her erkek kupon için bir levha).", f"Isıtma {t0:.0f}–{t1:.0f} °C (varsayım)"])
    meta = {"clearances_mm": cl, "sheet": sheet.id, "sheet_size_mm": [round(sw), round(sh)], "grams": grams}
    return BuildResult(parts, warnings, meta, notes, layout)


GENERATOR = Generator(
    key="thermo_coupon", label="Kalibrasyon kuponu", group="Yılbaşı",
    description="Küçük bir pres kalıbı ve farklı toleranslı 2–5 erkek kalıp: levhanız için en iyi kalıp boşluğunu gerçek baskıyla ölçün.",
    params=[
        Param("sheet", "Levha", "sheet", "", section="Kupon"),
        Param("clear_min", "En dar tolerans", "number", 0.1, min=0.0, max=0.6, step=0.05, unit="mm", section="Kupon",
              help="Levha kalınlığına eklenen boşluk"),
        Param("clear_step", "Tolerans adımı", "number", 0.1, min=0.05, max=0.3, step=0.05, unit="mm", section="Kupon"),
        Param("count", "Erkek kupon sayısı", "int", 4, min=2, max=5, section="Kupon"),
        Param("draft_deg", "Kalıp çıkış açısı", "number", 5, min=2, max=15, step=0.5, unit="°", section="Kupon"),
    ],
    build=build,
)
