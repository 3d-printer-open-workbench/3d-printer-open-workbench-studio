"""Every product Studio makes, in one shape: a family, a form schema (sections become the editor's numbered steps)
and two actions, ``preview`` and ``make``. The programs' own job formats stay as they are; this module only maps the
editor's form values onto them.

Form schema = Maker's parameter format: {key, label, type, default, min, max, step, unit, options, help, section,
show_if}. Extra types for the other programs: textarea, colors (list of #RRGGBB), multi (several choices), theme
(Topo theme cards), place (geocoded centre), route (GPX / OSM route) and color with ``allow_empty`` ("" = automatic).

Preview result (all programs): {png, glb, filaments: [{color, grams, roles}], estimate: {grams, text, colour_changes},
warnings, info}. Make result: output links (/files/...) + the same summary."""
from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .apps import STATE_DIR, WORK_ROOT

PREVIEW_DIR = STATE_DIR / "preview"
FAMILIES = [
    {"key": "yazi", "label": "Yazı ve tabela", "description": "Harf harf kabartma yazı, logo, tabela, duvar yazısı.",
     "image": "/static/img/yazi.png"},
    {"key": "isik", "label": "Işıklı ürünler", "description": "LED'li ışık kutusu, neon görünümlü tabela, gece lambası.",
     "image": "/static/img/isik.png"},
    {"key": "harita", "label": "Harita ve arazi", "description": "Şehir, rota, anı haritası, dekoratif arazi kabartması.",
     "image": "/static/img/harita.png"},
    {"key": "atolye", "label": "Atölye ürünleri", "description": "Anahtarlık, kalıp, termoform, kalemlik, hediyelik.",
     "image": "/static/img/atolye.png"},
]


def P(key, label, type="text", default="", section="Genel", **kw) -> dict:
    d = {"key": key, "label": label, "type": type, "default": default, "min": None, "max": None, "step": None, "unit": "",
         "options": [], "help": "", "section": section, "show_if": {}}
    d.update(kw)
    return d


@dataclass
class Product:
    id: str
    family: str
    label: str
    description: str
    program: str  # kaligraf | glow | topo | maker
    params: list[dict]
    preview: Callable[[dict, str, Callable], dict]
    make: Callable[[dict, Callable], dict]
    extra: dict = field(default_factory=dict)

    def schema(self) -> dict:
        return {"id": self.id, "family": self.family, "label": self.label, "description": self.description,
                "program": self.program, "params": self.params, **self.extra}


# --------------------------------------------------------------------------- shared helpers
def _pdir(jid: str) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    return PREVIEW_DIR


def _purl(f: Path | None) -> str | None:
    return f"/preview/{f.name}" if f else None


def _out(program: str) -> Path:
    d = WORK_ROOT / {"kaligraf": "Kaligraf", "glow": "Glow", "topo": "Topo", "maker": "Maker"}[program] / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _links(out_dir: Path, files: dict) -> dict:
    from workbench_core.webapp import output_links

    files = {k: v for k, v in files.items() if v and Path(v).is_file()}
    return output_links(WORK_ROOT, out_dir, files)


def _remember(out_dir: Path, product: str, values: dict) -> None:
    """studio.json: lets the home screen reopen a finished job in the editor with the same settings."""
    (Path(out_dir) / "studio.json").write_text(json.dumps({"product": product, "values": values}, ensure_ascii=False, indent=1),
                                                encoding="utf-8")


def _filaments(by_color: dict, roles: dict) -> list[dict]:
    return [{"color": c.upper(), "grams": round(float(g), 1) if g is not None else None, "roles": roles.get(c.upper(), [])}
            for c, g in by_color.items()]


def _fmt_time(seconds: float) -> str:
    from workbench_core.estimate import format_duration

    return format_duration(seconds)


def _font_options() -> list[list[str]]:
    from workbench_core.fonts import load_registry

    cat = {"basic": "Temel", "print": "Matbaa", "cursive": "El yazısı"}
    return [[s.name, f"{s.name} · {cat.get(s.category, s.category)}"] for s in load_registry().values()]


# --------------------------------------------------------------------------- Kaligraf
MOUNT_TR = {"tape": "Çift taraflı bant", "keyhole": "Gizli anahtar deliği", "holes": "Görünür vida delikleri (Ø3)",
            "connector_bar": "Arkadan bağlantı çubuğu"}
ROLE_TR = {"letter": "Harfler", "letter_face": "Harf ön yüzü", "plate": "Plaka", "glyphs": "Yazı", "body": "Gövde", "face": "Yüzey",
           "logo": "Logo"}


def _kaligraf_params(mode: str) -> list[dict]:
    S1, S2, S3, S4, S5 = "İçerik", "Boyut", "Renkler", "Montaj", "Gelişmiş"
    ps = [P("text", "Metin", "textarea", "Workbench", S1, help="Birden çok satır olabilir."),
          P("font", "Yazı tipi", "font", "Montserrat", S1)]
    if mode == "flat":
        ps += [P("logo", "Logo (isteğe bağlı)", "file", "", S1, help="SVG, PNG ya da JPG; metinle birlikte ya da tek başına."),
               P("n_colors", "Logo renk sayısı", "int", 4, S1, min=1, max=4),
               P("logo_layout", "Logo ve metin düzeni", "choice", "logo_above", S1, options=[["logo_above", "Logo üstte"], ["logo_left", "Logo solda"]]),
               P("width_cm", "Genişlik", "number", 40, S2, min=5, max=200, step=1, unit="cm"),
               P("thickness_mm", "Harf kalınlığı (Z)", "number", 5, S2, min=1, max=250, step=0.5, unit="mm",
                 help="Tabelanın / harflerin duvardan çıkıntısı (1–250 mm)."),
               P("stroke_offset_mm", "Harf et kalınlığı (dolgunluk)", "number", 0, S2, min=-1.5, max=5.0, step=0.2, unit="mm",
                 help="0 = yazı tipinin kendi kalınlığı; + değer harfi dışa doğru kalınlaştırır, - değer inceltir."),
               P("split_letters", "Harf harf ayrı STL üret", "bool", True, S2,
                 help="Açıkken her harf ayrı STL dosyası (letter_01_P.stl vb.) ve ayrı parça olarak çıkar."),
               P("color_style", "Renk stili", "choice", "single", S3,
                 options=[["single", "Tek renk"], ["two_tone", "İki renk (yüzey katmanı)"], ["backplate", "Arka plakalı"]]),
               P("colors", "Renkler", "colors", ["#1E1E1E", "#FFFFFF"], S3, max=4, help="Sırayla gövde / yüzey ya da plaka / yazı."),
               P("plate_offset_mm", "Plaka payı", "number", 6, S3, min=0, max=40, unit="mm", show_if={"color_style": "backplate"}),
               P("keyhole_boss", "Anahtar deliği için Ø30 kabartma", "bool", False, S4, show_if={"color_style": "backplate"})]
    else:
        ps += [P("letter_width_mm", "Harf genişliği (X)", "number", 0, S2, min=0, max=250, step=1, unit="mm",
                 help="En geniş harf bu genişliğe getirilir, diğerleri aynı oranda. 0 = yazı tipinin kendi oranı. Tek harf en fazla 250 mm."),
               P("letter_height_mm", "Harf yüksekliği (Y)", "number", 200, S2, min=20, max=250, step=1, unit="mm",
                 help="En yüksek harfin boyu (i noktası, Ş çengeli dahil); hiçbir harf bu ölçüyü geçmez. En fazla 250 mm."),
               P("depth_mm", "Harf kalınlığı / derinliği (Z)", "number", 20, S2, min=2, max=250, step=1, unit="mm",
                 help="Harfin duvardan çıkıntısı (2–250 mm)."),
               P("stroke_offset_mm", "Harf et kalınlığı (dolgunluk)", "number", 0, S2, min=-1.5, max=5.0, step=0.2, unit="mm",
                 help="0 = yazı tipinin kendi kalınlığı; + değer harfi dışa doğru kalınlaştırır, - değer inceltir."),
               P("letter_colors", "Harf gövde rengi", "colors", ["#1E1E1E"], S3, max=4, help="Birden çok renk: harflere sırayla."),
               P("face_color", "Ön yüz rengi", "color", "", S3, allow_empty=True, help="Boş = tek renk (tek parça harf STL)."),
               P("letter_joints", "El yazısını harf harf böl, birleşme yerlerine yapboz kilidi", "bool", True, S2),
               P("open_back_shell", "Arkası açık kabuk (daha az filament)", "bool", False, S2)]
    ps += [P("mounting", "Montaj", "multi", ["tape"], S4, options=[[k, v] for k, v in MOUNT_TR.items()]),
           P("tracking", "Harf aralığı", "number", 0.0, S5, min=-0.2, max=0.5, step=0.01),
           P("line_spacing", "Satır aralığı", "number", 1.0, S5, min=0.7, max=2.0, step=0.05),
           P("oversize_policy", "Tablaya sığmayan parça", "choice", "split", S5,
             options=[["split", "Pimli parçalara böl"], ["limit", "Sığacak boyuta küçült"]]),
           P("infill", "Dolgu", "number", 0, S5, min=0, max=100, unit="%", help="0 = otomatik (harf 10, düz 15).")]
    return ps


def _kaligraf_job(values: dict, mode: str):
    from kaligraf.form import inputs_to_job

    v = dict(values, mode=mode)
    v["letter_joints"] = bool(v.get("letter_joints", True))
    if mode == "flat":
        v["split_letters"] = bool(v.get("split_letters", True))
    return inputs_to_job(v)


def _kaligraf_summary(res) -> dict:
    d = res.data
    roles: dict[str, list] = {}
    for p in res.model.parts:
        r = ROLE_TR.get(p.role, p.role)
        if r not in roles.setdefault(p.color.upper(), []):
            roles[p.color.upper()].append(r)
    t = d["estimated_print_time"]
    return {"filaments": _filaments(d["filament_grams"]["by_color"], roles),
            "estimate": {"grams": d["filament_grams"]["total"], "text": t["text"], "colour_changes": t["colour_changes"]},
            "warnings": d.get("warnings", []),
            "info": [f"Boyut: {d['overall_mm'].get('width_mm', 0) / 10:.1f} × {d['overall_mm'].get('height_mm', 0) / 10:.1f}"
                     f" × {d['overall_mm'].get('depth_mm', 0) / 10:.1f} cm (G × Y × D)",
                     *([f"En büyük harf: {_largest_letter(res)}"] if res.model.mode == "letters" else []),
                     f"Parça: {len(d.get('parts', []))}, tabla: {d.get('plates')}"]}


def _largest_letter(res) -> str:
    import numpy as np

    ext = np.max([p.mesh_wall.bounds[1] - p.mesh_wall.bounds[0] for p in res.model.parts if p.role.startswith("letter")], axis=0)
    return f"{ext[0]:.0f} × {ext[1]:.0f} × {ext[2]:.0f} mm"


def _kaligraf_preview(mode):
    def run(values, jid, progress):
        from kaligraf.job import run_job
        from kaligraf.form import glb_preview
        from workbench_core.render import render_model

        progress("Model kuruluyor…")
        tmp = _pdir(jid) / f"k_{jid}"
        res = run_job(_kaligraf_job(values, mode), tmp, extras=False)
        glb = glb_preview(res, PREVIEW_DIR / f"{jid}.glb")
        png = PREVIEW_DIR / f"{jid}.png"
        render_model(res.model, "34", 1200).save(png)
        out = {"png": _purl(png), "glb": _purl(glb), **_kaligraf_summary(res)}
        shutil.rmtree(tmp, ignore_errors=True)
        return out
    return run


def _kaligraf_make(mode, pid):
    def run(values, progress):
        from kaligraf.job import run_job

        progress("Dosyalar hazırlanıyor…")
        res = run_job(_kaligraf_job(values, mode), _out("kaligraf"))
        _remember(res.out_dir, pid, values)
        return {**_links(res.out_dir, res.files), **_kaligraf_summary(res),
                "png": None}
    return run


# --------------------------------------------------------------------------- Glow
def _glow_params(design: str) -> list[dict]:
    from glow.form import DEPTH_DEFAULT, MOUNT_CH, RELIEF_CH, SHAPE_CH, hw_choices

    hc = hw_choices()
    S1, S2, S3, S4, S5, S6 = "İçerik", "Şekil ve ölçüler", "Renkler", "Işık ve LED", "Montaj", "Gelişmiş"
    ps = [P("text", "Metin", "textarea", "Workbench", S1),
          P("font", "Yazı tipi", "font", "Montserrat", S1),
          P("logo", "Logo / görsel (isteğe bağlı)", "file", "", S1, help="Yüklenirse metin yerine kullanılır."),
          P("logo_colors", "Görsel renk sayısı", "int", 4, S1, min=2, max=4),
          P("logo_map", "Logo renkleri", "logocolors", {}, S1, source="logo",
            help="Logodaki her renk için: yeni renk ve ışık geçsin mi. Logo yükleyince renkler kendiliğinden bulunur."),
          P("stroke_mm", "Kontur çizgisi", "number", 0, S1, min=0, max=6, step=0.5, unit="mm", help="0 = yok"),
          P("stroke_glow", "Kontur ışık geçirsin", "bool", False, S1)]
    if design == "rect":
        ps += [P("width_r", "Genişlik", "number", 20, S2, min=10, max=60, step=0.5, unit="cm"),
               P("height_r", "Yükseklik", "number", 0, S2, min=0, max=60, step=0.5, unit="cm", help="0 = yazıdan"),
               P("frame_r", "Çerçeve", "number", 8, S2, min=6.25, max=30, unit="mm"),
               P("corner_r", "Köşe yarıçapı", "number", 8, S2, min=0, max=60, unit="mm")]
    elif design == "round":
        ps += [P("diam_c", "Çap", "choice", "20", S2, options=[["15", "15 cm"], ["20", "20 cm"], ["25", "25 cm"]]),
               P("diam_x", "Özel çap", "number", 0, S2, min=0, max=60, unit="cm", help="0 = üstteki çap"),
               P("rim_o", "Opak kenar", "number", 10, S2, min=6.25, max=40, unit="mm")]
    else:
        ps += [P("shape", "Şekil", "choice", "auto", S2, options=[[k, l] for l, k in SHAPE_CH]),
               P("width_k", "Genişlik", "number", 20, S2, min=8, max=60, step=0.5, unit="cm"),
               P("rim_k", "Kenar payı", "number", 6, S2, min=3, max=30, unit="mm")]
    ps += [P("depth_mm", "Kutu derinliği", "number", DEPTH_DEFAULT[design], S2, min=20, max=100, unit="mm"),
           P("margin_mm", "İçerik kenar boşluğu", "number", 10, S2, min=3, max=30, unit="mm"),
           P("frame_color", "Çerçeve / gövde", "color", "#1F4D3A", S3),
           P("text_color", "Yazı", "color", "", S3, allow_empty=True, help="Boş = otomatik"),
           P("background_color", "Zemin", "color", "", S3, allow_empty=True, help="Boş = çerçeve rengi"),
           P("stroke_color", "Kontur çizgisi", "color", "", S3, allow_empty=True),
           P("accent_color", "Vurgu çizgisi", "color", "", S3, allow_empty=True),
           P("stand_color", "Stand / kaide", "color", "", S3, allow_empty=True),
           P("led_color", "Işık rengi (görselde)", "color", "#FFF1D8", S3),
           P("lit", "Hangi bölge ışık geçirsin?", "choice", "text", S4, options=[["text", "Yazı / logo yansın"], ["background", "Zemin yansın"]]),
           P("led", "LED şerit", "choice", "cob_8mm", S4, options=[[k, l] for l, k in hc["leds"]]),
           P("controller", "Kontrolcü", "choice", "usb_dimmer", S4, options=[[k, l] for l, k in hc["controllers"]]),
           P("led_mount", "LED montajı", "choice", "channel", S4, options=[["channel", "LED kanalı"], ["rails", "İnce kılavuz ray"]]),
           P("channel_cover", "Kanal kapağı ekle", "bool", False, S4, show_if={"led_mount": "channel"}),
           P("led_fill", "LED dolgusu", "choice", "normal", S4, options=[["normal", "Normal"], ["dense", "Yoğun"]]),
           P("diffuser", "Difüzör", "choice", "pla_white", S4, options=[[k, l] for l, k in hc["diffusers"]]),
           P("diffusion_mm", "Difüzyon katmanı", "number", 0, S4, min=0, max=1, step=0.1, unit="mm"),
           P("interior_white", "Yansıtıcı katman", "choice", "auto", S4, options=[["auto", "Otomatik"], ["on", "Açık"], ["off", "Kapalı"]]),
           P("mount", "Montaj", "choice", MOUNT_CH[design][0][1], S5, options=[[k, l] for l, k in MOUNT_CH[design]]),
           P("back_mm", "Arka kapak kalınlığı", "number", 0, S5, min=0, max=8, step=0.5, unit="mm", help="0 = otomatik"),
           P("holes", "Ek delikler (arka kapak)", "holes", [], S5,
             help="X / Y kutu merkezine göre mm (sağ ve yukarı +). Kablo çıkışı ve vida delikleri zaten otomatik açılır."),
           P("split_ok", "25 cm'yi aşarsa parçala", "bool", False, S6),
           P("relief", "Yüz kabartması", "choice", "auto", S6, options=[[k, l] for l, k in RELIEF_CH]),
           P("relief_mm", "Kabartma", "number", 1.0, S6, min=0.5, max=2.5, step=0.1, unit="mm"),
           P("block", "Işık sızıntısı engeli", "choice", "layer", S6, options=[["layer", "Siyah engel katmanı"], ["none", "Yok"]])]
    if design == "rect":
        ps.insert(-4, P("tilt_deg", "Arkaya yatırma", "number", 0, S5, min=0, max=15, unit="°", show_if={"mount": "desk"}))
    return ps


def _glow_values(values: dict, design: str) -> dict:
    """Studio form -> the Gradio form keys glow.form.inputs_to_raw reads (logo colour rows, hole table rows)."""
    v = dict(values, design=design)
    lm = v.pop("logo_map", None) or {}
    if v.get("logo") and lm.get("orig"):
        v["logo_orig"], v["logo_new"], v["logo_light"] = lm["orig"], lm.get("new") or [], lm.get("light") or []
    v["holes"] = [[h.get("type", "daire"), h.get("w"), h.get("h"), h.get("x"), h.get("y")] for h in (v.get("holes") or [])]
    return v


def _glow_summary(r) -> dict:
    from glow.form import PART_TR

    d = r["data"]
    roles: dict[str, list] = {}
    for p in r["box"].model.parts:
        label = PART_TR.get(p.name.split("_")[0] if p.name not in PART_TR else p.name, "Ön yüz" if p.name.startswith("face") else p.name)
        if label not in roles.setdefault(p.color.upper(), []):
            roles[p.color.upper()].append(label)
    pr = d["print"]
    pw = d.get("power", {})
    return {"filaments": _filaments(pr["grams_by_color"], roles),
            "estimate": {"grams": pr["grams_total"], "text": _fmt_time(pr["time_h"] * 3600), "colour_changes": pr["colour_changes"]},
            "warnings": r["warnings"],
            "info": [f"Boyut: {d['overall_mm']['width_mm'] / 10:.1f} × {d['overall_mm']['height_mm'] / 10:.1f} cm",
                     *([f"LED: {pw.get('n_leds')} adet, {pw.get('watts', pw.get('power_w', ''))} W"] if pw.get("n_leds") else [])]}


def _glow_preview(design):
    def run(values, jid, progress):
        from glow.job import run_box
        from glow.renders import render_lit
        from glow.form import inputs_to_raw
        from workbench_core.render import write_glb

        progress("Kutu kuruluyor… (yarım dakika kadar sürebilir)")
        d, raw = inputs_to_raw(_glow_values(values, design))
        tmp = _pdir(jid) / f"g_{jid}"
        r = run_box(d, raw, tmp, renders=False)
        png = PREVIEW_DIR / f"{jid}.png"
        render_lit(r["box"], "34", 1200).save(png)
        glb = write_glb([(p.mesh_wall, p.color, p.name) for p in r["box"].model.parts], PREVIEW_DIR / f"{jid}.glb")
        out = {"png": _purl(png), "glb": _purl(glb), **_glow_summary(r)}
        shutil.rmtree(tmp, ignore_errors=True)
        return out
    return run


def _glow_make(design, pid):
    def run(values, progress):
        from glow.job import run_box
        from glow.form import inputs_to_raw

        progress("Dosyalar hazırlanıyor… (1-2 dakika)")
        d, raw = inputs_to_raw(_glow_values(values, design))
        r = run_box(d, raw, _out("glow"))
        _remember(r["out_dir"], pid, values)
        files = {k: v for k, v in r["data"]["files"].items() if k != "parts"}
        files["bom"] = Path(r["out_dir"]) / "bom.csv"  # hardware list (LED, controller, screws, wire)
        return {**_links(r["out_dir"], files), **_glow_summary(r)}
    return run


# --------------------------------------------------------------------------- Topo
def _topo_params(m) -> list[dict]:
    from topo.geom import SHAPES
    from topo.modes import COLOR_TR, LAYER_TR

    d = m.defaults
    S1, S2, S3, S4, S5, S6 = "Yer", "Görünüm", "Renkler", "Boyut ve kabartma", "Yazı ve çerçeve", "Gelişmiş"
    ps = []
    if m.area_source == "route":
        ps += [P("route", "Rota", "route", {}, S1, help="GPX dosyası yükleyin ya da OpenStreetMap'te rota arayın."),
               P("margin_pct", "Rota çevresi boşluk", "number", d.get("margin_pct", 8), S1, min=0, max=60, unit="%")]
    else:
        ps += [P("place", "Yer", "place", {}, S1, help="Yer adı yazıp arayın (ör. Abant Gölü, Kadıköy)."),
               P("width_km", "Alan genişliği", "number", d.get("area_km", 2.0), S1, min=0.2, max=60, step=0.1, unit="km")]
    ps.append(P("theme", "Tema", "theme", m.themes[0].name, S2,
                options=[{"name": t.name, "colors": t.colors, "layers": t.layers} for t in m.themes]))
    for k, on in m.layers.items():
        ps.append(P(f"layer_{k}", LAYER_TR.get(k, k), "bool", bool(on), S2))
    roles = []
    for t in m.themes:
        roles += [r for r in t.colors if r not in roles]
    for r in roles:
        ps.append(P(f"color_{r}", COLOR_TR.get(r, r), "color", "", S3, allow_empty=True, help="Boş = temanın rengi"))
    ps += [P("shape", "Şekil", "choice", d.get("shape", "square"), S4, options=[[k, v] for k, v in SHAPES.items()]),
           P("size_mm", "Harita boyu", "number", d.get("size_mm", 200), S4, min=60, max=600, step=5, unit="mm"),
           P("z_exag", "Dağ yüksekliği", "number", d.get("z_exag", 1.5), S4, min=0, max=8, step=0.1, unit="×", help="0 = otomatik"),
           P("base_mm", "Taban", "number", d.get("base_mm", 3.0), S4, min=1, max=10, step=0.5, unit="mm"),
           P("title", "Başlık", "text", "", S5, help="Boş = yer / rota adı"),
           P("subtitle", "Alt başlık", "text", "", S5)]
    if m.area_source == "route":
        ps.append(P("duration", "Süre (isteğe bağlı)", "text", "", S5, help="ör. 6 sa 30 dk"))
    ps += [P("wall_mount", "Duvara asma deliği", "bool", False, S6),
           P("split", "Tablaya sığmazsa pimli parçalara böl", "bool", True, S6),
           P("infill_percent", "Dolgu", "int", 15, S6, min=5, max=100, unit="%")]
    return ps


def _topo_job(values: dict, m) -> dict:
    v = dict(values)
    job = {"mode": m.key, "theme": v.get("theme") or "", "shape": v.get("shape") or "", "size_mm": float(v.get("size_mm") or 0),
           "z_exag": float(v["z_exag"]) if v.get("z_exag") not in (None, "") else -1, "base_mm": float(v.get("base_mm") or 0),
           "title": v.get("title") or "", "subtitle": v.get("subtitle") or "", "duration": v.get("duration") or "",
           "wall_mount": bool(v.get("wall_mount")), "split": bool(v.get("split", True)),
           "infill_percent": int(v.get("infill_percent") or 15),
           "layers": {k[6:]: bool(x) for k, x in v.items() if k.startswith("layer_")},
           "colors": {k[6:]: x for k, x in v.items() if k.startswith("color_") and x}}
    if m.area_source == "route":
        r = v.get("route") or {}
        if not (r.get("gpx") or r.get("osm_relation")):
            raise ValueError("Önce bir GPX yükleyin ya da rota seçin.")
        job.update(gpx=r.get("gpx") or "", osm_relation=int(r.get("osm_relation") or 0), margin_pct=float(v.get("margin_pct") or 8))
        job["name"] = r.get("name") or "rota"
    else:
        p = v.get("place") or {}
        if p.get("lat") is None or p.get("lon") is None:
            raise ValueError("Önce bir yer arayıp seçin.")
        w = float(v.get("width_km") or 0)
        job.update(lat=float(p["lat"]), lon=float(p["lon"]), width_km=w, height_km=w, area_fixed=True)
        job["name"] = (p.get("name") or "harita").split(",")[0]
    return job


def _topo_summary(info: dict) -> dict:
    from topo.modes import LAYER_TR

    e = info.get("estimate") or {}
    by = {c: e.get("grams_by_slot", {}).get(str(i + 1)) for i, c in enumerate(info.get("colors", []))}
    roles = {c: [LAYER_TR.get(r, r) for r in rs] for c, rs in (info.get("roles") or {}).items()}
    ov = info.get("overall_mm") or {}
    return {"filaments": _filaments(by, roles),
            "estimate": {"grams": e.get("grams_total"), "text": e.get("text"), "colour_changes": e.get("colour_changes")},
            "warnings": info.get("warnings", []),
            "info": [x for x in (f"Ölçek {info['scale']}" if info.get("scale") else "",
                                 f"Boyut: {ov.get('width', 0) / 10:.1f} × {ov.get('depth', 0) / 10:.1f} cm" if ov else "",
                                 "4'ten fazla renk: renkleri azaltın" if info.get("too_many_colors") else "") if x]}


def _topo_preview(m):
    def run(values, jid, progress):
        from topo.job import Job
        from topo.output import preview

        job = Job.from_dict(_topo_job(values, m))
        glb, png = PREVIEW_DIR / f"{jid}.glb", PREVIEW_DIR / f"{jid}.png"
        _pdir(jid)
        info = preview(job, glb, progress, png)
        return {"png": _purl(png), "glb": _purl(glb), **_topo_summary(info)}
    return run


def _topo_make(m, pid):
    def run(values, progress):
        from topo.job import Job
        from topo.output import run_job

        res = run_job(Job.from_dict(_topo_job(values, m)), _out("topo"), progress)
        _remember(res.out_dir, pid, values)
        d = res.data
        e = d.get("estimate") or {}
        by = {f["color"]: f.get("grams") for f in d.get("filaments", [])}
        if not any(by.values()):
            by = {f["color"]: e.get("grams_by_slot", {}).get(str(i + 1)) for i, f in enumerate(d.get("filaments", []))}
        roles = {f["color"].upper(): f.get("parts", []) for f in d.get("filaments", [])}
        return {**_links(res.out_dir, res.files), "filaments": _filaments(by, roles),
                "estimate": {"grams": e.get("grams_total"), "text": e.get("text"), "colour_changes": e.get("colour_changes")},
                "warnings": d.get("warnings", []), "info": []}
    return run


# --------------------------------------------------------------------------- Maker
def _maker_job(values: dict, g) -> dict:
    name = (values.get("text") or values.get("name") or g.label)
    return {"generator": g.key, "name": str(name)[:40], "params": values}


def _maker_summary(parts) -> dict:
    by: dict[str, float] = {}
    roles: dict[str, list] = {}
    for p in parts:
        if not p.printable:
            continue
        c = p.color.upper()
        n = int(p.meta.get("count") or 1)
        by[c] = by.get(c, 0.0) + float(p.meta.get("grams") or 0) * n
        if p.label not in roles.setdefault(c, []):
            roles[c].append(p.label)
    return {"filaments": _filaments(by, roles), "estimate": {"grams": round(sum(by.values()), 1), "text": None, "colour_changes": None}}


def _maker_preview(g):
    def run(values, jid, progress):
        from maker.job import build, preview_glb
        from maker.render import render_parts

        progress("Model kuruluyor…")
        res, _ = build(_maker_job(values, g))
        glb = preview_glb(res, PREVIEW_DIR / f"{jid}.glb")
        png = PREVIEW_DIR / f"{jid}.png"
        render_parts(res.parts, width_px=1200).save(png)
        return {"png": _purl(png), "glb": _purl(glb), **_maker_summary(res.parts), "warnings": res.warnings, "info": res.notes}
    return run


def _maker_make(g, pid):
    def run(values, progress):
        from maker.job import run_job

        progress("Dosyalar hazırlanıyor…")
        res = run_job(_maker_job(values, g), _out("maker"))
        _remember(res.out_dir, pid, values)
        d = res.data
        tot = d.get("estimate") or d.get("totals") or {}
        return {**_links(res.out_dir, res.files), "filaments": [], "estimate": {"grams": tot.get("grams"), "text": tot.get("time"),
                                                                                "colour_changes": None},
                "warnings": d.get("warnings", []), "info": []}
    return run


# --------------------------------------------------------------------------- registry
_CACHE: dict[str, Product] | None = None


def products() -> dict[str, Product]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    from maker.generators import GENERATORS
    from topo.modes import MODES

    items: list[Product] = []
    for mode, label, desc in (("flat", "Düz tabela", "Duvar tabelası ve logo: tek renk, iki renk ya da arka plakalı."),
                              ("letters", "3B harfler", "Kutu harf ve el yazısı: harf harf, birleşme yerinde yapboz kilidi.")):
        pid = f"kaligraf_{mode}"
        items.append(Product(pid, "yazi", label, desc, "kaligraf", _kaligraf_params(mode), _kaligraf_preview(mode),
                             _kaligraf_make(mode, pid)))
    for design, label, desc in (("rect", "Işık kutusu (dikdörtgen)", "Dikdörtgen LED ışık kutusu, masa üstü ya da duvar."),
                                ("round", "Işık kutusu (yuvarlak)", "Yuvarlak LED ışık kutusu, standlı ya da duvar."),
                                ("contour", "Şekilli ışık / neon", "Yazının ya da logonun kendi şeklinde ışıklı tabela.")):
        pid = f"glow_{design}"
        items.append(Product(pid, "isik", label, desc, "glow", _glow_params(design), _glow_preview(design), _glow_make(design, pid)))
    for m in MODES.values():
        pid = f"topo_{m.key}"
        items.append(Product(pid, "harita", m.label, m.description, "topo", _topo_params(m), _topo_preview(m), _topo_make(m, pid),
                             {"area_source": m.area_source}))
    for g in GENERATORS.values():
        if g.status == "ready" and g.key != "plate":
            s = g.schema()
            pid = f"maker_{g.key}"
            items.append(Product(pid, "atolye", g.label, g.description, "maker", s["params"], _maker_preview(g), _maker_make(g, pid),
                                 {"group": g.group}))
    _CACHE = {p.id: p for p in items}
    return _CACHE


def reset() -> None:
    """Forget the cached product list (after the hardware catalogue changed)."""
    global _CACHE
    _CACHE = None


def config() -> dict:
    from workbench_core.colorlib import filament_palette

    from maker import tools as mt

    return {"families": FAMILIES, "products": [p.schema() for p in products().values()], "fonts": _font_options(),
            "palette": filament_palette(), "sheets": mt.list_sheets()}


def run(kind: str, payload: dict, jid: str, progress) -> dict:
    p = products().get(payload.get("product", ""))
    if p is None:
        raise ValueError("bilinmeyen ürün")
    values = {q["key"]: q["default"] for q in p.params} | (payload.get("values") or {})  # missing fields: product defaults
    if kind == "preview":
        return p.preview(values, jid, progress)
    return p.make(values, progress)


def validate(payload: dict) -> None:
    from fastapi import HTTPException

    if payload.get("product") not in products():
        raise HTTPException(400, "bilinmeyen ürün")


# --------------------------------------------------------------------------- home screen data
THUMBS = ("render_34.png", "render_lit.png", "renders/urun.png", "render_front.png", "preview.png")
PROGRAM_FAMILY = {"Kaligraf": "yazi", "Glow": "isik", "Topo": "harita", "Maker": "atolye"}


def recent(limit: int = 12) -> list[dict]:
    """Finished jobs of every program, newest first: {name, family, when, thumb, out_dir, product?, files}."""
    jobs = []
    for prog, fam in PROGRAM_FAMILY.items():
        root = WORK_ROOT / prog / "output"
        if not root.is_dir():
            continue
        for d in root.iterdir():
            j = d / "job.json"
            if d.is_dir() and j.is_file():
                jobs.append((j.stat().st_mtime, prog, fam, d))
    jobs.sort(reverse=True)
    out = []
    for mt, prog, fam, d in jobs[:limit]:
        thumb = next((t for t in THUMBS if (d / t).is_file()), None)
        rel = d.resolve().relative_to(WORK_ROOT.resolve())
        st = {}
        if (d / "studio.json").is_file():
            try:
                st = json.loads((d / "studio.json").read_text(encoding="utf-8"))
            except ValueError:
                st = {}
        out.append({"name": d.name.replace("_", " "), "program": prog, "family": fam, "when": mt, "out_dir": str(d.resolve()),
                    "thumb": f"/files/{rel}/{thumb}" if thumb else None, "product": st.get("product"), "values": st.get("values"),
                    "model": f"/files/{rel}/model.3mf" if (d / "model.3mf").is_file() else None})
    return out


FILAMENT_FILE = STATE_DIR / "filamentler.json"
DEFAULT_FILAMENTS = [{"slot": 1, "color": "#1E1E1E", "name": "Siyah PLA", "grams": 1000},
                     {"slot": 2, "color": "#FFFFFF", "name": "Beyaz PLA", "grams": 1000},
                     {"slot": 3, "color": "#C0392B", "name": "Kırmızı PLA", "grams": 1000},
                     {"slot": 4, "color": "#2AA7E0", "name": "Mavi PLA", "grams": 1000}]


def filaments() -> list[dict]:
    try:
        return json.loads(FILAMENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_FILAMENTS


def save_filaments(items: list[dict]) -> list[dict]:
    import re

    clean = []
    for i, it in enumerate(items[:4]):
        c = str(it.get("color", "")).upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", c):
            raise ValueError(f"{i + 1}. yuva: renk #RRGGBB olmalı")
        clean.append({"slot": i + 1, "color": c, "name": str(it.get("name") or "")[:40],
                      "grams": max(0, int(float(it.get("grams") or 0)))})
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILAMENT_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    return clean


def new_id() -> str:
    return uuid.uuid4().hex[:12]
