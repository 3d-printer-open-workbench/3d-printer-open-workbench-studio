"""Thermoform ornament generator: press molds (female + male) or a vacuum buck + box, 1-9 cavities, back plate and
rim with a closure (glued, snap, magnet, screw cap). Geometry lives in thermo / closures / vacuum."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shapely import affinity
from shapely.ops import polylabel, unary_union

from .. import closures, core, estimate, thermo, vacuum
from ..sheets import get_sheet
from ..shapes import SHAPES_TR, shape_polygon
from .base import BuildResult, Generator, Param, Part, SheetLayout

BRIDGE_MM = 3.0  # letters / logo pieces are merged into one bubble silhouette this far around


def source_outline(v: dict, width: float, regions: list | None = None) -> tuple:
    """Raw silhouette (before clean-up) about ``width`` mm wide, and its warnings. A logo's coloured regions are
    appended to ``regions`` as (colour, geometry) in the same frame (for a multi-colour back plate)."""
    if v["source"] == "shape":
        return shape_polygon(v["shape"], width), []
    inner = width - 2 * BRIDGE_MM
    if v["source"] == "text":
        if not v["text"].strip():
            raise ValueError("Yazı silüeti için bir yazı girin.")
        g, warnings = core.text_geometry(v["text"], v["font"], width_mm=inner)
    else:
        if not v["logo"] or not Path(v["logo"]).is_file():
            raise ValueError("Logo / görsel dosyası seçin (SVG, PNG ya da JPG).")
        logo = core.load_logo(v["logo"], inner)
        g, warnings = [r.geometry for r in logo.regions], list(logo.warnings)
        if regions is not None:
            regions += [(r.color, r.geometry) for r in logo.regions]
    poly, w2 = thermo.solid_outline(g, BRIDGE_MM)
    return poly, warnings + w2


def relief_geometry(v: dict, outline) -> tuple:
    """Relief text / logo centred on the dome, ``relief_pct`` of the outline width, shrunk until it fits inside."""
    if v["relief"] == "none":
        return None, []
    x0, y0, x1, y1 = outline.bounds
    width = (x1 - x0) * v["relief_pct"] / 100
    if v["relief"] == "text":
        if not v["relief_text"].strip():
            raise ValueError("Kabartma için bir yazı girin.")
        g, warnings = core.text_geometry(v["relief_text"], v["relief_font"], width_mm=width)
    else:
        if not v["relief_logo"] or not Path(v["relief_logo"]).is_file():
            raise ValueError("Kabartma logosu için dosya seçin (SVG, PNG ya da JPG).")
        logo = core.load_logo(v["relief_logo"], width)
        g, warnings = unary_union([r.geometry for r in logo.regions]), list(logo.warnings)
    inner = outline.buffer(-max(3.0, 0.1 * min(x1 - x0, y1 - y0)))
    c = polylabel(outline, tolerance=0.5)
    gx0, gy0, gx1, gy1 = g.bounds
    g = affinity.translate(g, c.x - (gx0 + gx1) / 2, c.y - (gy0 + gy1) / 2)
    k = 1.0
    while not inner.contains(g) and k > 0.3:
        g = affinity.scale(g, 0.95, 0.95, origin=c)
        k *= 0.95
    if not inner.contains(g):
        warnings.append("Kabartma şeklin içine sığmıyor; kısaltın ya da şekli büyütün.")
        g = g.intersection(inner)
    elif k < 0.999:
        warnings.append(f"Kabartma şekle sığsın diye %{round(k * 100)} oranında küçültüldü.")
    return g, warnings


def build(v: dict) -> BuildResult:
    sheet = get_sheet(v["sheet"] or None)
    mesh = v["formed"] == "mesh"
    if mesh:
        if v["method"] != "press":
            raise ValueError("Baskı kafes yalnızca pres kalıbıyla biçimlendirilir; vakum deliklerden hava kaçırır.")
        if v["mesh_cell"] < 3 * v["mesh_strand"]:
            raise ValueError(f"Hücre, tel kalınlığının en az 3 katı olmalı ({3 * v['mesh_strand']:g} mm ya da daha büyük).")
        # the molds are spaced for the printed mesh instead of a sheet
        sheet = replace(sheet, id="pla_mesh", label=f"PLA baskı kafes {v['mesh_t']:g} mm", material="PLA",
                        thickness_mm=v["mesh_t"], clearance_mm=0.2, form_temp_c=(70.0, 80.0), min_radius_mm=2.0,
                        note="ASSUMPTION")
    if v["back_holes"] and v["hole_pitch"] < v["hole_d"] + 2:
        raise ValueError(f"Delik aralığı delik çapından en az 2 mm büyük olmalı ({v['hole_d'] + 2:g} mm ya da daha fazla).")
    regions: list = []
    raw, warnings = source_outline(v, v["width_mm"], regions)
    outline, w = thermo.clean_outline(raw, sheet, v["depth_mm"])
    warnings += w
    x0, y0, x1, y1 = outline.bounds
    outline = thermo.centred(outline)
    accents = []
    if v["back_colors"] == "logo":
        if v["source"] != "logo":
            warnings.append("Logonun renkleri yalnızca şekil kaynağı logo / görsel iken kullanılır; taban tek renk yapıldı.")
        else:
            shift = (-(x0 + x1) / 2, -(y0 + y1) / 2)
            by_col: dict = {}
            for col, g in regions:
                by_col.setdefault(col.upper(), []).append(affinity.translate(g, *shift))
            ranked = sorted(by_col.items(), key=lambda kv: -unary_union(kv[1]).area)
            # the largest colour stays the back plate colour; the others become pieces of their own
            accents = [(col, unary_union(gs).buffer(BRIDGE_MM / 2, quad_segs=8).buffer(-BRIDGE_MM / 2, quad_segs=8))
                       for col, gs in ranked[1:]]
            if len(ranked) < 2:
                warnings.append("Logoda tek renk var; taban tek renk yapıldı. İkinci renk için SVG'de ayrı renkli bölge çizin.")
            elif v["back_color_from_logo"]:
                v = {**v, "back_color": ranked[0][0]}
    rgeom, w = relief_geometry(v, outline)
    warnings += w
    relief = None
    if rgeom is not None and not rgeom.is_empty:
        relief = thermo.Relief(rgeom, v["relief_mm"], v["relief_dir"] == "out")
        warnings += thermo.relief_warnings(rgeom, sheet, v["relief_mm"])
    dome = thermo.Dome(outline, v["depth_mm"], profile=v["profile"], draft_deg=v["draft_deg"], steps=v["steps"],
                       soften_mm=sheet.min_radius_mm, relief=relief)
    offs, n = thermo.cavity_layout(outline, v["cavities"], v["flange_mm"])
    if n < v["cavities"]:
        warnings.append(f"Bu boyutta tablaya en çok {n} göz sığıyor ({v['cavities']} istendi); {n} gözlü kalıp yapıldı.")
    orn = closures.ornament_parts(dome, sheet, v["flange_mm"], v["hanger"], v["closure"], (v["magnet_d"], v["magnet_h"]),
                                  holes=(v["hole_d"], v["hole_pitch"]) if v["back_holes"] else None, accents=accents)
    if v["back_holes"] and not orn.holes:
        warnings.append("Taban delik açılamayacak kadar küçük; delik çapını ya da aralığını küçültün.")
    lat = None
    if mesh:
        hollow = v["mesh_halves"] == "two"
        lat = closures.lattice_parts(dome, v["mesh_t"], v["flange_mm"], v["hanger"] and hollow, v["mesh_pattern"], v["mesh_cell"],
                                     v["mesh_strand"], 2 if hollow else 1, z0=0.0 if hollow else closures.BACK_MM)
        if not lat.holes:
            warnings.append("Şekil bu hücre boyu için küçük: kafeste açıklık oluşmadı. Hücreyi küçültün.")
        if dome.depth / max(v["mesh_cell"], 1e-6) > 4:
            warnings.append("Kubbe hücreye göre derin: teller biçimlendirirken fazla uzar ve kopabilir. Kubbeyi alçaltın ya da hücreyi büyütün.")
    pet = f"{sheet.material} {sheet.thickness_mm:g} mm"
    if v["method"] == "press":
        molds = thermo.press_molds(dome, sheet, economy=v["economy"], offsets=offs)
        draft, undercuts = thermo.cavity_draft(molds, dome)
        mold_parts = [Part("female", "Dişi kalıp", molds.female, "#3E7CB1", "PETG", {"note": "ısıya dayanıklı olsun diye PETG", "role": "mold"}),
                      Part("male", "Erkek kalıp", molds.male, "#E3A23B", "PETG", {"role": "mold"})]
        sw, sh = molds.sheet_size_mm
    else:
        vac = vacuum.vacuum_molds(dome, sheet, offs, v["hose_d"])
        draft, undercuts = 90 - dome.steepest_wall_deg(), 0  # a height field pulled along +z has no undercut
        mold_parts = [Part("buck", "Vakum kalıbı (delikli tabla)", vac.buck, "#E3A23B", "PETG", {"role": "mold"}),
                      Part("box", "Vakum kutusu", vac.box, "#9AA5B1", "PLA", {"role": "mold", "note": "bir kez basılır, tüm kalıplarla kullanılır"})]
        sw, sh = vac.sheet_size_mm
    if undercuts:
        warnings.append(f"Kalıpta {undercuts} ters açılı yüzey var: levha kalıptan çıkmaz. Kubbe profilini ya da kabartmayı değiştirin.")
    if draft < v["draft_deg"] - 1.0 and v["method"] == "press":
        warnings.append(f"Kalıpta {draft:.1f}° çıkış açılı dik duvar var (istenen {v['draft_deg']:g}°); levha kalıptan zor çıkabilir.")
    back_meta = {"role": "part", "product": True} | ({"group": "back"} if orn.accents else {})
    blank = None
    if lat is not None:
        blank = Part("blank", "Düz kafes (basılır, sonra biçimlendirilir)", lat.blank, v["mesh_color"], "PLA",
                     {"role": "part", "product": True} | ({"count": 2} if v["mesh_halves"] == "two" else {}))
    orn_parts = [Part("back", "Arka taban", orn.back, v["back_color"], "PLA", back_meta),
                 *[Part(f"back_{i + 1}", f"Arka taban, {i + 2}. renk", m, col, "PLA", dict(back_meta))
                   for i, (col, m) in enumerate(orn.accents)],
                 Part("rim", closures.CLOSURES_TR[v["closure"]] if v["closure"] in ("rim", "snap") else "Yapıştırma kenarı",
                      orn.rim, v["rim_color"], "PLA", {"role": "part"}),
                 *[Part(nm, lb, m, "#7FB069", "PLA", {"role": "part"}) for nm, lb, m in orn.extra]]
    if lat is None:
        shell = Part("shell", f"Biçimlenmiş levha ({pet}, basılmaz)", orn.shell, "#BFE3F5", pet, {"product": True, "gloss": 0.6}, printable=False)
        _arrange([mold_parts, orn_parts], shell_on=orn_parts[0], shell=shell, follow=orn_parts[1:1 + len(orn.accents)])
    else:
        shell = Part("shell", "Biçimlenmiş kafes (önizleme)", lat.formed, v["mesh_color"], "PLA", {"product": True}, printable=False)
        if v["mesh_halves"] == "two":  # hollow piece: two shells, no back plate or rim
            orn_parts = [blank]
            _arrange([mold_parts, [blank, shell]], shell_on=None, shell=shell)
        else:  # one lattice shell on the printed back plate, held by the rim
            _arrange([mold_parts, orn_parts + [blank]], shell_on=orn_parts[0], shell=shell, follow=orn_parts[1:1 + len(orn.accents)])
            orn_parts = orn_parts + [blank]
    parts = mold_parts + orn_parts + [shell]

    est = {}
    for p in parts:
        if p.printable:
            e = estimate.part_estimate(p.mesh, p.material, p.meta["role"])
            est[p.name] = e
            p.meta.update(grams=e.grams, minutes=e.minutes, cost_try=e.try_)
            if p.meta["role"] == "part" and (n > 1 or p.meta.get("count")):
                p.meta["count"] = n * p.meta.get("count", 1)
    t0, t1 = sheet.form_temp_c
    molds_e = [est[p.name] for p in mold_parts]
    orn_e = [est[p.name] for p in orn_parts]
    mold_try = sum(e.try_ for e in molds_e)
    orn_try = sum(e.try_ for e in orn_e)
    s_try = 0.0 if mesh else estimate.sheet_try(sheet.id, sw, sh)
    each = orn_try + (s_try or 0) / n
    mats = " + ".join(sorted({f"{sum(est[p.name].grams for p in mold_parts if p.material == m):.0f} g {m}" for m in {p.material for p in mold_parts}}))
    notes = [
        f"Maliyet (tahmini, varsayım fiyatlarla): kalıp seti bir kez ~{mats} ≈ {mold_try:.0f} TL, "
        f"~{sum(e.minutes for e in molds_e) / 60:.1f} saat. Süs başına ~{sum(e.grams for e in orn_e):.0f} g PLA"
        + (f" + levha ≈ {each:.1f} TL." if s_try is not None else f" ≈ {orn_try:.1f} TL + levha (levha fiyatı girilmedi)."),
        f"En ucuz baskı: kalıplar %{estimate.costs()['infill']['mold'] * 100:.0f} gyroid dolgu, 3 duvar, 5 üst katman yeterli; "
        "taban ve kenar %15 dolgu. Kalıp setini her süs için yeniden kullanın.",
    ]
    if n > 1:
        notes.append(f"Çok gözlü kalıp: tek levhada {n} süs biçimlenir; taban ve kenar parçalarından {n}'er adet basın.")
    if v["method"] == "press":
        notes += [
            f"Levha kesim ölçüsü: {sw:.0f} × {sh:.0f} mm ({sheet.label}); pimlerin içinde kalmalı.",
            f"Kalıp boşluğu {molds.gap_mm:.2f} mm (levha {sheet.thickness_mm:g} + tolerans {sheet.clearance_mm:g} mm). "
            f"Isıtma {t0:.0f}–{t1:.0f} °C (varsayım; kalibrasyon kuponuyla doğrulanacak).",
            f"Kalıptan çıkış: duvarlar dikeyden en az {max(draft, 0):.0f}° eğik" + ("; ters açı yok." if not undercuts else "."),
            "Dişi kalıpta şekil ayna görünür; levha ters çevrilince doğru okunur.",
        ]
        if molds.vents:
            notes.append(f"Dişi kalıpta {len(molds.vents)} hava deliği var (Ø{thermo.VENT_D:g} mm); baskıdan sonra açık olduğunu kontrol edin.")
    else:
        notes += [
            f"Vakum: tablayı kutunun üstüne koyup kenarı bantla sızdırmaz yapın, Ø{v['hose_d']:g} mm ağza süpürge hortumunu takın.",
            f"Levha kesim ölçüsü: {sw:.0f} × {sh:.0f} mm (tablanın {vacuum.FRAME_MM:g} mm dışı, çerçeveye tutturmak için). "
            f"Levhayı çerçevede {t0:.0f}–{t1:.0f} °C'ye ısıtın (varsayım), sarkınca kalıba indirip vakumu açın.",
            f"Hava delikleri: her kalıbın çevresinde {len(vac.ring_holes) // n} delik (en çok {vacuum.RING_PITCH:g} mm arayla)"
            + (f", çukurlarda {len(vac.valley_holes) // n} delik" if vac.valley_holes else "") + f", Ø{vacuum.HOLE_D:g} mm.",
            "Levhanın iç yüzü kalıba değer; dış (görünen) yüz pürüzsüz kalır.",
        ]
    if lat is None:
        notes.append(f"Biçimlenen levhayı şeklin {v['flange_mm']:g} mm dışından kesin; kenar parçasının iç çizgisi kesim yerini gösterir.")
        notes += orn.notes
    else:
        notes = [x for x in notes if not x.startswith("Levha kesim ölçüsü")] + lat.notes
        if v["mesh_halves"] != "two":
            notes += orn.notes
    x0, y0, x1, y1 = outline.bounds
    meta = {"outline_mm": [round(x1 - x0, 1), round(y1 - y0, 1)], "sheet": sheet.id, "method": v["method"], "cavities": n,
            "closure": v["closure"], "sheet_size_mm": [round(sw), round(sh)], "trim_offset_mm": v["flange_mm"],
            "draft_deg": round(draft, 1), "back_holes": orn.holes, "back_colors": 1 + len(orn.accents),
            "formed": v["formed"], "mesh_openings": lat.holes if lat else 0, "undercuts": undercuts, "steepest_wall_deg": round(dome.steepest_wall_deg(), 1),
            "cost_try": {"molds": round(mold_try, 1), "per_ornament": round(each, 1), "sheet_counted": s_try is not None},
            "grams": {k: e.grams for k, e in est.items()}}
    if v["method"] == "press":
        meta |= {"gap_mm": molds.gap_mm, "vents": len(molds.vents)}
    else:
        meta |= {"ring_holes": len(vac.ring_holes), "valley_holes": len(vac.valley_holes)}
    layout = SheetLayout(
        (sw, sh), [affinity.translate(outline, dx, dy) for dx, dy in offs],
        [affinity.translate(outline.buffer(v["flange_mm"], quad_segs=16), dx, dy) for dx, dy in offs],
        title=f"Levha şablonu — {sheet.label}, {n} göz",
        lines=["1) Levhayı siyah çizgiden kesin.",
               "2) Biçimlendirdikten sonra levhayı kubbe yukarıda şablonun üstüne koyun, kubbeleri kesikli çizgiye hizalayıp kırmızı çizgiden kesin.",
               f"{'Pres' if v['method'] == 'press' else 'Vakum'} · ısıtma {t0:.0f}–{t1:.0f} °C (varsayım) · kesim payı {v['flange_mm']:g} mm"])
    if lat is not None:
        return BuildResult(parts, warnings, meta, notes)  # the blank is printed: no sheet to cut, no template
    notes.append("Levha şablonunu (levha_sablonu.pdf) %100 ölçekte yazdırın: levhayı kesmek ve biçimlenmiş levhayı kırpmak için.")
    return BuildResult(parts, warnings, meta, notes, layout)


def _arrange(rows: list[list[Part]], shell_on: Part, shell: Part, gap: float = 12.0, follow: list | None = None) -> None:
    """Preview layout: each row left to right, rows stacked front to back; the formed sheet sits on the back plate.
    ``follow`` = parts of the back plate in other colours: they move with it and take no slot of their own."""
    follow = follow or []
    rows = [[p for p in row if p not in follow] for row in rows]
    y = 0.0
    for row in rows:
        depth = max(p.mesh.extents[1] for p in row)
        width = sum(p.mesh.extents[0] for p in row) + gap * (len(row) - 1)
        x = -width / 2
        for p in row:
            (x0, y0, _), (x1, y1, _) = p.mesh.bounds
            dx, dy = x - x0, y - depth / 2 - (y0 + y1) / 2
            p.mesh.apply_translation([dx, dy, 0])
            if shell_on is not None and p is shell_on:
                shell.mesh.apply_translation([dx, dy, 0])
                for q in follow:
                    q.mesh.apply_translation([dx, dy, 0])
            x += x1 - x0 + gap
        y -= depth + gap


GENERATOR = Generator(
    key="thermoform", label="Thermoform kalıbı", group="Yılbaşı",
    description="PETG levhadan kabarık süs: pres (dişi + erkek) ya da vakum kalıbı, 1–9 gözlü, arka taban ve kenar "
                "(yapıştırma, geçmeli, mıknatıslı, vidalı kapak). Köşeler levhaya göre yuvarlanır, kubbeye yazı/logo kabartılabilir; maliyet tahmini gösterilir.",
    params=[
        Param("method", "Yöntem", "choice", "press", options=[("press", "Pres (dişi + erkek kalıp)"), ("vacuum", "Vakum (tek kalıp + kutu)")], section="Yöntem"),
        Param("formed", "Biçimlenen parça", "choice", "sheet", options=[("sheet", "Şeffaf levha (PETG)"), ("mesh", "Baskı kafes (PLA, delikli)")],
              section="Yöntem", help="Kafes: düz basılan delikli PLA parça sıcak suda yumuşatılıp kalıpta biçimlendirilir"),
        Param("sheet", "Levha", "sheet", "", section="Yöntem", show_if={"formed": "sheet"}),
        Param("mesh_halves", "Parça", "choice", "two", options=[("two", "İçi boş (iki kafes yapıştırılır)"), ("one", "Tek kafes, tabanlı")],
              section="Kafes", show_if={"formed": "mesh"}),
        Param("mesh_pattern", "Desen", "choice", "voronoi", options=list(closures.LATTICES_TR.items()), section="Kafes", show_if={"formed": "mesh"}),
        Param("mesh_cell", "Hücre boyu", "number", 7, min=3, max=25, step=0.5, unit="mm", section="Kafes", show_if={"formed": "mesh"}),
        Param("mesh_strand", "Tel kalınlığı", "number", 1.2, min=0.8, max=4, step=0.1, unit="mm", section="Kafes", show_if={"formed": "mesh"}),
        Param("mesh_t", "Kafes kalınlığı", "number", 0.8, min=0.4, max=2, step=0.1, unit="mm", section="Kafes", show_if={"formed": "mesh"},
              help="0,2 mm katmanla 4 katman; kalınlaştıkça zor biçimlenir"),
        Param("mesh_color", "Kafes rengi", "color", "#E0457B", section="Kafes", show_if={"formed": "mesh"}),
        Param("hose_d", "Süpürge hortumu ağzı", "number", 35, min=25, max=50, step=0.5, unit="mm", section="Yöntem", show_if={"method": "vacuum"},
              help="Hortumun iç çapına uyan ağız dış çapı"),
        Param("source", "Şekil kaynağı", "choice", "shape", options=[("shape", "Hazır şekil"), ("text", "Yazı silüeti"), ("logo", "Logo / görsel")], section="Şekil"),
        Param("shape", "Şekil", "choice", "heart", options=list(SHAPES_TR.items()), section="Şekil", show_if={"source": "shape"}),
        Param("text", "Yazı", "text", "Ela", section="Şekil", show_if={"source": "text"}),
        Param("font", "Yazı tipi", "font", "Righteous", section="Şekil", show_if={"source": "text"}),
        Param("logo", "Dosya", "file", "", section="Şekil", show_if={"source": "logo"}, help="SVG, PNG ya da JPG; tek parça silüete çevrilir"),
        Param("width_mm", "Genişlik", "number", 80, min=30, max=200, step=1, unit="mm", section="Şekil"),
        Param("profile", "Kubbe profili", "choice", "pillow", options=list(thermo.PROFILES_TR.items()), section="Kubbe"),
        Param("depth_mm", "Kubbe yüksekliği", "number", 12, min=3, max=40, step=0.5, unit="mm", section="Kubbe"),
        Param("steps", "Basamak sayısı", "int", 3, min=2, max=5, section="Kubbe", show_if={"profile": "stepped"}),
        Param("draft_deg", "Kalıp çıkış açısı", "number", 5, min=2, max=15, step=0.5, unit="°", section="Kubbe",
              help="Duvarlar dikeyden en az bu kadar eğik olur; levha kalıptan kolay çıkar"),
        Param("relief", "Kabartma", "choice", "none", options=[("none", "Yok"), ("text", "Yazı"), ("logo", "Logo / görsel")], section="Kabartma",
              help="Kubbenin üstüne kalıpla birlikte biçimlenir"),
        Param("relief_text", "Kabartma yazısı", "text", "2026", section="Kabartma", show_if={"relief": "text"}),
        Param("relief_font", "Yazı tipi", "font", "Righteous", section="Kabartma", show_if={"relief": "text"}),
        Param("relief_logo", "Dosya", "file", "", section="Kabartma", show_if={"relief": "logo"}),
        Param("relief_pct", "Kabartma genişliği", "int", 50, min=15, max=85, unit="%", section="Kabartma", show_if={"relief": ["text", "logo"]}),
        Param("relief_mm", "Kabartma yüksekliği", "number", 1.2, min=0.5, max=4, step=0.1, unit="mm", section="Kabartma", show_if={"relief": ["text", "logo"]}),
        Param("relief_dir", "Yön", "choice", "out", options=[("out", "Dışa kabarık"), ("in", "İçe gömük")], section="Kabartma", show_if={"relief": ["text", "logo"]}),
        Param("closure", "Kapanış", "choice", "rim", options=list(closures.CLOSURES_TR.items()), section="Kapanış"),
        Param("magnet_d", "Mıknatıs çapı", "number", 10, min=5, max=20, step=0.5, unit="mm", section="Kapanış", show_if={"closure": "magnet"}),
        Param("magnet_h", "Mıknatıs kalınlığı", "number", 2, min=1, max=5, step=0.5, unit="mm", section="Kapanış", show_if={"closure": "magnet"}),
        Param("flange_mm", "Yapıştırma payı", "number", 5, min=3, max=10, step=0.5, unit="mm", section="Kapanış", help="Levhanın şekil dışında kalan düz kenarı"),
        Param("hanger", "Askı deliği", "bool", True, section="Kapanış"),
        Param("back_color", "Taban rengi", "color", "#C8664A", section="Renk"),
        Param("rim_color", "Kenar rengi", "color", "#F4F1EA", section="Renk"),
        Param("back_colors", "Taban renkleri", "choice", "single", options=[("single", "Tek renk"), ("logo", "Logonun renkleri")],
              section="Renk", show_if={"source": "logo"},
              help="Çok renkli SVG: en geniş renk tabanın kendisi, diğer renkler ayrı parça olarak aynı anda basılır (ağacın gövdesi, kurdele)"),
        Param("back_color_from_logo", "Taban rengini logodan al", "bool", True, section="Renk", show_if={"back_colors": "logo"}),
        Param("back_holes", "Delikli taban", "bool", False, section="Taban",
              help="Tabana ışık delikleri: arkadaki ışık şeffaf levhadan görünür; ağaçta ve pencerede parlar"),
        Param("hole_d", "Delik çapı", "number", 5, min=2, max=15, step=0.5, unit="mm", section="Taban", show_if={"back_holes": True}),
        Param("hole_pitch", "Delik aralığı", "number", 9, min=4, max=30, step=0.5, unit="mm", section="Taban", show_if={"back_holes": True},
              help="Merkezden merkeze; çaptan en az 2 mm büyük olmalı"),
        Param("economy", "Ekonomik kalıp", "bool", True, section="Üretim",
              help="Kalıp yalnızca şeklin çevresinde dolu, köşeler ince; aynı yüzey, yaklaşık yarı filament", show_if={"method": "press"}),
        Param("cavities", "Göz sayısı", "int", 1, min=1, max=9, section="Üretim", help="Tek basışta kaç süs; sığmazsa azaltılır"),
    ],
    build=build,
)
