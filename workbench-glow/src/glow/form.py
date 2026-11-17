"""Form helpers of the light box editor (Turkish): editor form values -> job, hardware choices, logo colours, holes.
The editor itself is Open Workbench Studio's (studio.products); the Gradio UI was removed in phase 2."""
from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path


from workbench_core.colorlib import basic_names

from .hardware import default_hardware
from .job import run_box
from .prompt import build_prompts, load_template, user_field_choices, write_prompts

APP_TITLE = "Workbench - Glow"
OUT_DIR = Path("output")
DESIGN_IDS = ("rect", "round", "contour")
BASIC_COLORS = basic_names()
RELIEF_CH = [("Otomatik (kontur: kabarık, diğerleri: düz)", "auto"), ("Düz", "flush"), ("Kabarık", "raised"), ("Çukur", "recessed")]
MAX_LOGO_SLOTS = 4


# --------------------------------------------------------------------------- #
# form values -> job
# --------------------------------------------------------------------------- #
def _color(v) -> str | None:
    from kaligraf.job import resolve_color

    v = (v or "").strip() if isinstance(v, str) else v
    return resolve_color(v) if v else None


DESIGN_CH = [("▭  Dikdörtgen", "rect"), ("◯  Yuvarlak", "round"), ("♡  Şekil / Kontur", "contour")]
SHAPE_CH = [("Yazının / logonun kendi şekli (kontur)", "auto"), ("Kalp", "heart"), ("Yıldız", "star"), ("4 köşeli yıldız", "star4"),
            ("Daire", "circle"), ("Kare", "square"), ("Üçgen", "triangle"), ("Altıgen", "hexagon")]
MOUNT_CH = {"rect": [("Masa üstü (ayaklı)", "desk"), ("Duvara (anahtar deliği)", "wall")],
            "round": [("Stand / kaide (ayrı parça)", "stand"), ("Duvara (anahtar deliği)", "wall")],
            "contour": [("Stand / kaide (ayrı parça)", "stand"), ("Duvara (anahtar deliği)", "wall")]}
DEPTH_DEFAULT = {"rect": 35, "round": 45, "contour": 35}
VIEW_CH = [("💡 Işık açık", "lit"), ("Işık kapalı", "unlit"), ("Önden (açık)", "lit_front"), ("Ölçüler", "dims"), ("İç yapı / LED yolu", "preview")]
HOLE_TYPES_TR = {"daire": "circle", "circle": "circle", "yuvarlak": "circle", "dikdörtgen": "rect", "dikdortgen": "rect", "kare": "rect", "rect": "rect",
                 "anahtar": "key", "anahtar deliği": "key", "key": "key"}
PART_TR = {"body": "Gövde (yan duvarlar)", "back": "Arka kapak", "back_white": "Arka kapak iç beyaz katmanı", "led_cover": "LED kanal kapakları",
           "stand": "Stand / kaide", "face_lip": "Ön yüz dudağı"}


def led_md(led_id: str) -> str:
    try:
        l = default_hardware().led(led_id)
    except KeyError:
        return ""
    kind = "adreslenebilir RGB" if l.addressable else "tek renk"
    return (f"<small>{l.width_mm:g} mm genişlik, {l.thickness_mm:g} mm kalınlık, {kind}, kesim her {l.cut_pitch_mm:g} mm, "
            f"~{l.w_per_m:g} W/m. Değerler **Donanım** sekmesinden düzenlenir.</small>")


def _num(v, default=None):
    try:
        return default if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return default


def parse_holes(rows) -> list[dict]:
    """Dataframe rows [tür, w, h, x, y] -> job holes. Empty rows are skipped; unknown types raise a Turkish error."""
    out = []
    if rows is None:
        return out
    if hasattr(rows, "values"):  # pandas DataFrame
        rows = rows.values.tolist()
    for i, r in enumerate(rows, start=1):
        if not r or all(c in (None, "") for c in r):
            continue
        t = HOLE_TYPES_TR.get(str(r[0] or "").strip().lower())
        if t is None:
            raise ValueError(f"Delik {i}: tür '{r[0]}' anlaşılmadı (daire, dikdörtgen ya da anahtar yazın).")
        w = _num(r[1] if len(r) > 1 else None, 8.0)
        h = _num(r[2] if len(r) > 2 else None, w)
        out.append({"type": t, "w": w, "h": h, "x": _num(r[3] if len(r) > 3 else None, 0.0), "y": _num(r[4] if len(r) > 4 else None, 0.0)})
    return out


def inputs_to_raw(v: dict) -> tuple[str, dict]:
    """Form values -> (design, job dict). Raises ValueError with a Turkish message."""
    design = v.get("design")
    if design not in DESIGN_IDS:
        raise ValueError("Önce kutu tipini seçin (Dikdörtgen / Yuvarlak / Şekil-Kontur).")
    text = (v.get("text") or "").strip()
    logo = v.get("logo") or None
    if not text and not logo:
        raise ValueError("Metin yazın ya da bir logo yükleyin.")
    raw: dict = {"design": design, "font": v.get("font") or "Montserrat", "led": v.get("led"), "controller": v.get("controller"),
                 "diffuser": v.get("diffuser"), "lit": v.get("lit") or "text", "led_fill": v.get("led_fill") or "normal",
                 "split_ok": bool(v.get("split_ok")), "interior_white": v.get("interior_white") or "auto",
                 "block": v.get("block") or "layer", "margin_mm": float(v.get("margin_mm") or 10),
                 "depth_mm": float(v.get("depth_mm") or DEPTH_DEFAULT[design]),
                 "led_mount": v.get("led_mount") or "rails", "logo_colors": int(v.get("logo_colors") or 4)}
    raw["channel_cover"] = bool(v.get("channel_cover")) and raw["led_mount"] == "channel"
    for key in ("diffusion_mm", "stroke_mm"):
        x = _num(v.get(key), 0.0)
        if x:
            raw[key] = x
    for key in ("front_mm", "back_mm"):
        x = _num(v.get(key), 0.0)
        if x:
            raw[key] = x
    if raw.get("stroke_mm") and v.get("stroke_glow"):
        raw["stroke_glow"] = True
    if logo:
        raw["logo"] = str(logo)
    else:
        raw["text"] = text
    raw["frame_color"] = _color(v.get("frame_color")) or "#1F4D3A"
    for key in ("text_color", "background_color", "accent_color", "stroke_color", "stand_color"):
        c = _color(v.get(key))
        if c:
            raw[key] = c
    c = _color(v.get("led_color"))
    if c:
        raw["led_color"] = c
    relief = v.get("relief") or "auto"
    if relief == "auto":
        relief = "raised" if design == "contour" else "flush"
    raw["relief"] = relief
    if relief != "flush":
        raw["relief_mm"] = float(v.get("relief_mm") or 1.0)
    if logo and v.get("logo_orig"):  # per-colour edits of the detected logo colours
        recolor, light = {}, []
        for orig, new, glow in zip(v["logo_orig"], v.get("logo_new") or [], v.get("logo_light") or []):
            n = _color(new)
            if n and n.upper() != orig.upper():
                recolor[orig] = n
            if glow:
                light.append(orig)
        if recolor:
            raw["recolor"] = recolor
        if light:
            raw["light_colors"] = light
    hl = parse_holes(v.get("holes"))
    if hl:
        raw["holes"] = hl
    mount = v.get("mount")
    if design == "rect":
        raw.update(width_mm=float(v.get("width_r") or 20) * 10, mount=mount if mount in ("desk", "wall") else "desk",
                   frame_mm=float(v.get("frame_r") or 8), corner_radius_mm=float(_num(v.get("corner_r"), 8)),
                   tilt_deg=float(v.get("tilt_deg") or 0) if mount != "wall" else 0.0)
        if _num(v.get("height_r")):
            raw["height_mm"] = float(v["height_r"]) * 10
    elif design == "round":
        raw.update(diameter_mm=float(_num(v.get("diam_x")) or v.get("diam_c") or 20) * 10, rim_mm=float(v.get("rim_o") or 10),
                   mount=mount if mount in ("stand", "wall") else "stand")
    else:
        raw.update(width_mm=float(v.get("width_k") or 20) * 10, rim_mm=float(v.get("rim_k") or 6),
                   mount=mount if mount in ("stand", "wall") else "stand", shape=v.get("shape") or "auto")
    return design, raw


def detect_logo_colors(path: str | Path) -> list[str]:
    """Colours (HEX) of a logo as Kaligraf's extractor sees them (at most 4)."""
    from workbench_core.logo2d import load_logo

    lg = load_logo(path, 100.0, 4)
    out: list[str] = []
    for r in lg.regions:
        c = r.color.upper()
        if c not in out:
            out.append(c)
    return out[:MAX_LOGO_SLOTS]


# --------------------------------------------------------------------------- #
# outputs
# --------------------------------------------------------------------------- #
def glb_preview(box, path: Path) -> Path:
    from workbench_core.render import write_glb

    return write_glb([(p.mesh_wall, p.color, p.name) for p in box.model.parts], path)


def zip_outputs(out_dir: Path) -> Path:
    z = out_dir / f"{out_dir.name}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.rglob("*")):
            if f.is_file() and f != z and f.suffix != ".glb":
                zf.write(f, f.relative_to(out_dir))
    return z


def summary_md(data: dict) -> str:
    o, p, pw, b = data["overall_mm"], data["print"], data["power"], data["bom"]
    m = data["meta"]
    mode = {"normal": "kutu içinde", "relaxed": "kutu içinde (sıkı)", "smaller": "kutu içinde (daha küçük model)", "external": "HARİCİ (kutu dışında)"}
    lines = [f"**Boyut:** {o['width_mm'] / 10:.1f} x {o['height_mm'] / 10:.1f} x {o['depth_mm'] / 10:.1f} cm (genişlik x yükseklik x derinlik)",
             f"**Baskı:** {p['grams_total']:.0f} g filament, yaklaşık {p['time_h']:.1f} saat, {data['plates']} tabla",
             f"**LED:** {pw['strip_length_mm'] / 1000:.2f} m kullanılır ({pw['strip_to_buy_m']:g} m alın), {pw['n_leds']} LED; kapsama %{m['led_coverage'] * 100:.0f}",
             f"**Kontrolcü:** {m.get('controller_used', m['controller'])} — {mode.get(m.get('controller_mode', 'normal'), '')}",
             f"**Güç:** tipik {pw['total_typical_w']:.1f} W, tam beyaz {pw['total_full_w']:.1f} W ({pw['full_white_a']:.1f} A); önerilen adaptör {pw['supply'].replace('usb_', '').replace('_', ' ').upper()}",
             f"**Maliyet (TL):** toplam **{b['total_try']:.0f}** (filament {b['filament_try']:.0f})"]
    if "wled_abl_ma" in pw:
        lines.append(f"**WLED Maksimum Akım önerisi:** ~{pw['wled_abl_ma']} mA")
    if "max_brightness_pct" in pw:
        lines.append(f"**Dimmer sınırı:** %{pw['max_brightness_pct']}")
    return "\n\n".join(lines)


def bom_rows(data: dict) -> list[list]:
    unit = {"g": "g", "m": "m", "pcs": "adet"}
    rows = [[r.get("item_tr", r["item"]), f"{r['qty']:g} {unit.get(r['unit'], r['unit'])}", f"{r['unit_price_try']:.2f}", f"{r['total_try']:.2f}"] for r in data["bom"]["rows"]]
    rows.append(["TOPLAM", "", "", f"{data['bom']['total_try']:.2f}"])
    return rows


def plate_rows(data: dict) -> tuple[str, list[list]]:
    """Printed parts in Turkish (what goes on the bed), plus a one-line plate summary."""
    rows = []
    for p in data["parts"]:
        n = p["name"]
        if n.startswith("face_"):
            name, note = f"Ön yüz — {p['color']}", "ön yüzle tek baskı (çok renk)"
        else:
            name, note = PART_TR.get(n, n), ""
        if n == "led_cover":
            note = "kanalların üstüne geçer; ters (üst yüzü tablada) basılır"
        if n == "back_white":
            note = "arka kapakla tek baskı"
        sz = " x ".join(f"{v:.0f}" for v in p["size_mm"])
        rows.append([name, p["color"], sz, note])
    m = data["meta"]
    md = (f"**{data['plates']} tabla**, {m['extruders']} filament ({', '.join(m['colors'])}). "
          + ("LED kanalı" + (" + kapak" if m.get("channel_cover") else "") + " var. " if m.get("led_mount") == "channel" else "")
          + ("Difüzyon katmanı " + f"{m['diffusion_mm']:g} mm. " if m.get("diffusion_mm") else ""))
    return md, rows


def generate(values: dict, out_root: Path | str = OUT_DIR, prompt_values: dict | None = None) -> dict:
    """Run the job for form ``values``; returns everything the UI shows."""
    design, raw = inputs_to_raw(values)
    res = run_box(design, raw, out_root, hw=default_hardware(), prompt_user=prompt_values)
    out = Path(res["out_dir"])
    data = res["data"]
    glb = glb_preview(res["box"], out / "preview.glb")
    zpath = zip_outputs(out)
    files = [data["files"][k] for k in ("3mf", "assembly_pdf", "lit", "unlit", "dims", "prompt_tr", "prompt_en") if k in data["files"]]
    files += [str(out / "bom.csv"), str(out / "job.json"), str(out / "warnings.txt"), str(zpath)]
    image_map = {k: data["files"][k] for k in ("lit", "unlit", "lit_front", "dims", "preview") if k in data["files"]}
    pmd, prows = plate_rows(data)
    o, b = data["overall_mm"], data["bom"]
    headline = (f"{o['width_mm'] / 10:.1f} x {o['height_mm'] / 10:.1f} x {o['depth_mm'] / 10:.1f} cm · "
                f"{data['print']['grams_total']:.0f} g · ~{data['print']['time_h']:.1f} saat · {b['total_try']:.0f} TL")
    return {"out_dir": out, "glb": glb, "zip": zpath, "files": files, "data": data,
            "images": [data["files"]["lit"], data["files"]["unlit"], data["files"]["dims"]], "image_map": image_map,
            "warnings": "\n".join(f"- {w}" for w in data["warnings"]) or "Uyarı yok.", "headline": headline,
            "summary": summary_md(data), "bom": bom_rows(data), "plates": prows, "plates_md": pmd,
            "prompt_tr": data["prompts"]["tr"], "prompt_en": data["prompts"]["en"]}


def open_folder(path: Path | str) -> str:
    path = Path(path)
    if not path.exists():
        return "Önce bir model üretin."
    opener = shutil.which("xdg-open") or shutil.which("open")
    if not opener:
        return f"Klasör: {path.resolve()}"
    try:
        subprocess.Popen([opener, str(path.resolve())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Açıldı: {path.resolve()}"
    except OSError:
        return f"Klasör: {path.resolve()}"


def colors_info_md(specs: list[str]) -> str:
    from workbench_core.colorlib import color_code
    from kaligraf.job import resolve_color

    lines = []
    for sp in specs:
        if not sp:
            continue
        try:
            c = color_code(resolve_color(sp))
        except ValueError:
            lines.append(f"- `{sp}`: geçersiz renk")
            continue
        lines.append(f"- {c['text']} — RGB {tuple(c['rgb'])}")
    return "\n".join(lines)


def hw_choices() -> dict[str, list[tuple[str, str]]]:
    hw = default_hardware()
    return {"leds": [(v.label, k) for k, v in hw.leds.items()], "controllers": [(v.label, k) for k, v in hw.controllers.items()],
            "diffusers": [(v.label, k) for k, v in hw.diffusers.items()]}
