"""Form helpers of the sign editor (Turkish): editor form values -> Job, font / colour info texts, previews.
The editor itself is Open Workbench Studio's (studio.products); the Gradio UI was removed in phase 2."""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path


from .fontinfo import load_metrics, size_warnings
from .colorlib import FINISH_UI, basic_names
from .fonts import DEFAULT_FONTS_DIR, load_registry
from .job import Job, JobResult, run_job
from .mounting import MOUNTING_OPTIONS
from .prompt import build_prompts, default_user_fields, load_template, user_field_choices, write_prompts

APP_TITLE = "Workbench - Kaligraf"
OUT_DIR = Path("output")
CAT_TR = {"basic": "Temel", "print": "Matbaa", "cursive": "El yazısı"}
MOUNT_LABELS = {
    "tape": "Çift taraflı bant (düz arka yüz)",
    "keyhole": "Gizli anahtar deliği",
    "holes": "Görünür vida delikleri (Ø3)",
    "connector_bar": "Bağlantı çubuğu (arkadan tek parça)",
}
STYLE_LABELS = {"single": "Tek renk", "two_tone": "İki renk (yüzey katmanı)", "backplate": "Arka plakalı"}
BASIC_COLORS = basic_names()


def color_choices() -> list[str]:
    """Colour dropdown choices (built-in names; any #RRGGBB can be typed)."""
    return list(BASIC_COLORS)


def sample_color(img, x: int, y: int, size: int = 7) -> str:
    """HEX of the per-channel median of a ``size`` x ``size`` window around (x, y)."""
    import numpy as np

    from .colorlib import rgb_to_hex

    a = np.asarray(img)
    if a.ndim == 2:
        a = np.stack([a] * 3, axis=-1)
    a = a[..., :3]
    h, w = a.shape[:2]
    x, y = int(min(max(x, 0), w - 1)), int(min(max(y, 0), h - 1))
    r = size // 2
    win = a[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3)
    return rgb_to_hex(np.median(win, axis=0))


def capture_report(hex_color: str) -> str:
    """Markdown card for "Renk yakala": HEX, RGB, nearest RAL Classic (ΔE2000) and English name."""
    from .colorlib import color_code

    c = color_code(hex_color)
    sw = (f'<span style="display:inline-block;width:64px;height:32px;background:{c["hex"]};border:1px solid #888;'
          f'vertical-align:middle;border-radius:4px"></span>')
    return "\n".join([
        f"{sw} &nbsp; **`{c['hex']}`**  |  RGB {tuple(c['rgb'])}",
        f"**En yakın RAL Classic:** {c['ral']['code']} {c['ral']['name']} (`{c['ral']['hex']}`, ΔE2000 {c['ral']['delta_e']})",
        f"**İngilizce renk adı:** {c['name_en']}  ->  {c['text']}",
    ])


def colors_info_md(specs: list[str]) -> str:
    """Universal codes of the selected colours (built-in name or HEX)."""
    from .colorlib import color_code
    from .job import resolve_color

    lines = []
    for sp in specs:
        try:
            c = color_code(resolve_color(sp))
        except ValueError:
            lines.append(f"- `{sp}`: geçersiz renk")
            continue
        lines.append(f"- {c['text']} — RGB {tuple(c['rgb'])}")
    return "\n".join(lines)


def font_choices(fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> list[tuple[str, str]]:
    """(label, font name) in catalog order, numbered like the specimen sheet."""
    reg = load_registry(Path(fonts_dir))
    out, n = [], 0
    for cat in CAT_TR:
        for s in reg.values():
            if s.category == cat:
                n += 1
                out.append((f"{n}. {s.name} ({CAT_TR[cat]})", s.name))
    return out


def font_info_md(font: str, mode: str, size_cm: float | None, fonts_dir: Path | str = DEFAULT_FONTS_DIR,
                 text: str | None = None) -> str:
    """Min recommended cap heights of a font and a warning for the current job.

    ``size_cm`` is the width (flat) or letter height (letters); for flat signs the width is converted to
    the resulting cap height of ``text`` before comparing."""
    reg = load_registry(Path(fonts_dir))
    spec = next((s for s in reg.values() if s.name == font or s.id == font), None)
    if spec is None:
        return ""
    m = load_metrics(fonts_dir).get(spec.id)
    if not m:
        return f"**{spec.name}**: boyut bilgisi yok (`scripts/font_report.py` çalıştırın)."
    f = lambda v: "yok" if v is None else f"{v:g} cm"
    lines = [f"**{spec.name}** önerilen en küçük büyük harf yüksekliği: düz tabela **{f(m['min_cap_flat_cm'])}**, "
             f"3D harf **{f(m['min_cap_letters_cm'])}**."]
    cap = size_cm
    if size_cm and mode == "flat":
        cap = None
        if text and text.strip():
            try:
                from .fonts import resolve_font
                from .text2d import build_text

                r = build_text(text.strip(), resolve_font(spec.id, fonts_dir), "flat", width_mm=size_cm * 10)
                cap = r.cap_height_mm / 10
                lines.append(f"Bu metinle {size_cm:g} cm genişlik = {cap:.1f} cm büyük harf yüksekliği.")
            except Exception:  # unusable text/size: the job itself reports the error
                cap = None
    if cap:
        lines += [f"⚠️ {w}" for w in size_warnings(m, mode, cap)]
    return "\n\n".join(lines)


def _list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def _finish_map(colors: list[str], finishes: list) -> dict[str, str]:
    """Pair the i-th colour with the i-th finish (empty/matte entries are skipped)."""
    out = {}
    for c, f in zip(colors, finishes):
        if c and f and f != "mat":
            out[c] = f
    return out


def inputs_to_job(v: dict) -> Job:
    """Form values -> validated Job (raises ValueError with a Turkish message)."""
    mode = "flat" if v.get("mode") in ("Düz tabela", "flat") else "letters"
    d: dict = dict(
        mode=mode, text=(v.get("text") or "").strip(), font=v.get("font") or "Montserrat",
        mounting=_list(v.get("mounting")) or ["tape"], tracking=float(v.get("tracking") or 0),
        line_spacing=float(v.get("line_spacing") or 1.0), oversize_policy=v.get("oversize_policy") or "split",
        stroke_offset_mm=float(v.get("stroke_offset_mm") or 0.0),
    )
    if v.get("infill"):
        d["infill_percent"] = float(v["infill"])
    if mode == "flat":
        d.update(width_cm=float(v.get("width_cm") or 0), thickness_mm=float(v.get("thickness_mm") or 5),
                 color_style=v.get("color_style") or "single", colors=_list(v.get("colors")),
                 plate_offset_mm=float(v.get("plate_offset_mm") or 6), n_colors=int(v.get("n_colors") or 4),
                 keyhole_boss=bool(v.get("keyhole_boss")), logo_layout=v.get("logo_layout") or "logo_above",
                 logo_gap_mm=float(v.get("logo_gap_mm") or 10), logo_share=float(v.get("logo_share") or 0.5),
                 split_letters=bool(v.get("split_letters", False)))
        if v.get("logo"):
            d["logo"] = str(v["logo"])
        d["finishes"] = _finish_map(d["colors"], [v.get(f"finish{i}") for i in range(1, 5)])
    else:
        h_cm = float(v["letter_height_mm"]) / 10 if v.get("letter_height_mm") else float(v.get("letter_height_cm") or 0)
        d.update(letter_height_cm=h_cm, letter_width_mm=float(v.get("letter_width_mm") or 0) or None,
                 fit_letter_box=bool(v.get("letter_height_mm")),
                 depth_mm=float(v.get("depth_mm") or 20),
                 face_color=(v.get("face_color") or None), letter_colors=_list(v.get("letter_colors")),
                 open_back_shell=bool(v.get("open_back_shell")),
                 letter_joints="puzzle" if v.get("letter_joints", True) else "none")
        d["finishes"] = {**_finish_map([d["face_color"]] if d["face_color"] else [], [v.get("finish_face")]),
                         **_finish_map(d["letter_colors"], [v.get("finish_body")] * max(1, len(d["letter_colors"])))}
    return Job.from_dict(d)


def glb_preview(result: JobResult, path: Path) -> Path:
    """Coloured GLB of the assembled model (wall orientation) for gr.Model3D."""
    from workbench_core.render import write_glb

    return write_glb([(p.mesh_wall, p.color, p.name) for p in result.model.parts], path)


def zip_outputs(result: JobResult) -> Path:
    zpath = result.out_dir / f"{result.out_dir.name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(result.out_dir.rglob("*")):
            if f.is_file() and f != zpath and f.suffix != ".glb":
                z.write(f, f.relative_to(result.out_dir))
    return zpath


def estimate_md(data: dict) -> str:
    o = data["overall_mm"]
    g = data["filament_grams"]
    ov = data["oversize"]
    lines = [
        f"**Boyut:** {o['width_mm'] / 10:.1f} x {o['height_mm'] / 10:.1f} x {o['depth_mm'] / 10:.1f} cm (genişlik x yükseklik x derinlik)",
        f"**Parça / tabla:** {len(data['pieces'])} parça, {data['plates']} tabla (250x250 mm)",
        f"**Filament:** {g['total']:.0f} g — " + ", ".join(f"{c}: {x:.0f} g" for c, x in g["by_color"].items()),
        f"**Tahmini baskı süresi:** {data['estimated_print_time']['text']} ({data['estimated_print_time']['colour_changes']} renk değişimi)",
        f"**Önerilen dolgu:** {data.get('recommended_infill', '-')}",
    ]
    if ov.get("max_no_split_size_mm"):
        lines.append(f"**Bölmeden basılabilecek en büyük boyut:** {ov['max_no_split_size_mm'] / 10:.1f} cm "
                     f"(istenen {ov['size_requested_mm'] / 10:.1f} cm, uygulanan {ov['size_applied_mm'] / 10:.1f} cm, politika: {ov['policy']})")
    return "\n\n".join(lines)


def generate(values: dict, out_root: Path | str = OUT_DIR, prompt_values: dict | None = None,
             fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> dict:
    """Run the job for form ``values``; returns everything the UI shows."""
    job = inputs_to_job(values)
    res = run_job(job, out_root, fonts_dir, prompt_fields=prompt_values)
    glb = glb_preview(res, res.out_dir / "preview.glb")
    zpath = zip_outputs(res)
    files = [res.files[k] for k in ("3mf", "template", "render_front", "render_34", "dims", "prompt_tr", "prompt_en", "job", "warnings")]
    return {
        "result": res, "glb": glb, "zip": zpath, "files": [*map(str, files), str(zpath)],
        "warnings": "\n".join(f"- {w}" for w in res.data["warnings"]) or "Uyarı yok.",
        "estimate": estimate_md(res.data),
        "images": [str(res.files["render_front"]), str(res.files["render_34"]), str(res.files["dims"])],
        "prompt_tr": res.data["prompts"]["tr"], "prompt_en": res.data["prompts"]["en"],
    }


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


class _PartView:  # minimal stand-in for Part, built from job.json
    def __init__(self, d: dict):
        self.role, self.color = d["role"], d["color"]


class _ModelView:
    def __init__(self, data: dict):
        self.parts = [_PartView(p) for p in data["parts"]]


def _prompts_from_data(job: Job, data: dict, user: dict) -> dict[str, str]:
    return build_prompts(job, data, _ModelView(data), user)

