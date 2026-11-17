"""AI image prompt (Turkish + English) from ``templates/ai_prompt.yaml``.

Auto fields come from the job (text, font, mode, real dimensions, depth, colours, material,
mounting); user fields (scene, wall, lighting, camera, scale reference, extra details) have defaults
and are filled from the UI form.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from workbench_core import prompt as _core
from workbench_core.prompt import _rgb, color_names  # noqa: F401  (shared helpers, re-exported)

from .colorlib import CANON as _CANON  # noqa: F401
from .colorlib import descriptor


TEMPLATE_FILE = Path(__file__).resolve().parents[2] / "templates" / "ai_prompt.yaml"


def load_template(path: Path | str = TEMPLATE_FILE) -> dict:
    return _core.load_template(path)


def default_user_fields(tpl: dict | None = None) -> dict[str, str]:
    return _core.default_user_fields(tpl or load_template())


def user_field_choices(tpl: dict | None = None) -> dict[str, dict]:
    """{field: {"label": str, "default": str, "choices": {key: Turkish text}}} for the UI form."""
    return _core.user_field_choices(tpl or load_template())


_user_text = _core.user_text
_join = _core.join


def auto_fields(job, data: dict, model) -> dict[str, str]:
    """Texts derived from the job; every value exists in ``_tr`` and ``_en`` form."""
    ov = data["overall_mm"]
    w, h, d = ov["width_mm"] / 10, ov["height_mm"] / 10, ov["depth_mm"] / 10
    text = job.text or "logo"
    if job.mode == "letters":
        prod_tr = "tek tek 3 boyutlu, mat PLA'dan basılmış harflerden oluşan dekoratif duvar yazısı"
        prod_en = "decorative wall lettering made of individual 3D-printed matte PLA letters"
    else:
        styles = {"single": ("tek renkli", "single-colour"), "two_tone": ("iki renkli", "two-tone"),
                  "backplate": ("arka plakalı iki renkli", "two-tone with a backing plate")}
        st = styles.get(job.color_style, styles["single"])
        what_tr, what_en = ("logolu ", "logo ") if job.logo else ("", "")
        prod_tr = f"{st[0]} düz (2,5 boyutlu) {what_tr}duvar yazısı"
        prod_en = f"{st[1]} flat {what_en}wall sign"
    parts = [(p.role, p.color) for p in model.parts if p.role not in ("rail", "boss")]
    cols: list[str] = []
    for _, c in parts:
        if c not in cols:
            cols.append(c)
    desc = {c["hex"].upper(): c for c in data.get("colors", [])}
    for c in cols:
        if c.upper() not in desc:
            desc[c.upper()] = descriptor(c)
    dc = lambda c: desc[c.upper()]
    if job.mode == "letters" and len(cols) == 2:
        face = next((c for r, c in parts if r == "letter_face"), cols[-1])
        body = next((c for r, c in parts if r != "letter_face"), cols[0])
        color_tr = f"Harflerin ön yüzü {dc(face)['text_tr']}, yanları {dc(body)['text_tr']}."
        color_en = f"The letter faces are {dc(face)['text_en']} and the sides are {dc(body)['text_en']}."
    else:
        color_tr = f"Renkler: {_join([dc(c)['text_tr'] for c in cols], 'tr')}."
        color_en = f"Colours: {_join([dc(c)['text_en'] for c in cols], 'en')}."
    fins = []
    for c in cols:
        if dc(c)["finish"] not in fins:
            fins.append(dc(c)["finish"])
    if fins == ["matte"]:
        mat_tr, mat_en = "Malzeme: mat PLA, 3D yazıcıdan basılmış.", "Material: matte PLA, 3D printed."
    else:
        mat_tr = f"Malzeme: PLA ({', '.join(dict.fromkeys(dc(c)['finish_tr'] for c in cols))} yüzeyler), 3D yazıcıdan basılmış."
        mat_en = f"Material: 3D-printed PLA ({', '.join(fins)} finishes)."
    mounts = {
        "tape": ("çift taraflı bantla yapıştırılmış, görünür vida yok", "attached with double-sided tape, no visible screws"),
        "keyhole": ("arkadaki gizli anahtar deliğiyle asılmış", "hung on hidden keyhole slots at the back"),
        "holes": ("görünür küçük vida delikleriyle monte edilmiş", "fixed with small visible screw holes"),
        "connector_bar": ("harfler arkadan bir çubukla tek parça gibi asılıyor", "the letters hang as one unit on a rail at the back"),
    }
    sel = [m for m in job.mounting if m in mounts] or ["tape"]
    mount_tr = _join([mounts[m][0] for m in sel], "tr").capitalize() + "."
    mount_en = _join([mounts[m][1] for m in sel], "en").capitalize() + "."
    font = job.font
    return {
        "text": text,
        "product_tr": prod_tr, "product_en": prod_en,
        "dimension_tr": f"Gerçek boyut: {w:.1f} cm genişlik x {h:.1f} cm yükseklik, {d:.1f} cm derinlik.",
        "dimension_en": f"Real size: {w:.1f} cm wide x {h:.1f} cm tall, {d:.1f} cm deep.",
        "color_tr": color_tr, "color_en": color_en,
        "material_tr": mat_tr, "material_en": mat_en,
        "font_tr": f"Yazı tipi: {font}.", "font_en": f"Typeface: {font}.",
        "mounting_tr": mount_tr, "mounting_en": mount_en,
        "width_cm": f"{w:.1f}", "height_cm": f"{h:.1f}",
    }


def build_prompts(job, data: dict, model, user: dict[str, str] | None = None, tpl: dict | None = None) -> dict[str, str]:
    """{"tr": ..., "en": ...} prompts."""
    tpl = tpl or load_template()
    user = user or {}
    auto = auto_fields(job, data, model)
    out = {}
    for lang in ("tr", "en"):
        vals = dict(auto)
        for name in ("scene", "wall", "lighting", "camera"):
            vals[name] = _user_text(tpl, user, name, lang)
        ref = _user_text(tpl, user, "scale_ref", lang)
        if lang == "tr":
            vals["scale_tr"] = f"Ölçek için görselde {ref} bulunsun." if ref else ""
            extra = _user_text(tpl, user, "extra", lang)
            vals["extra_tr"] = f" Ek ayrıntılar: {extra}" if extra else ""
        else:
            vals["scale_en"] = f"For scale, include {ref} in the shot." if ref else ""
            extra = _user_text(tpl, user, "extra", lang)
            vals["extra_en"] = f" Extra details: {extra}" if extra else ""
        # unused-language keys are harmless: str.format ignores extra kwargs
        out[lang] = " ".join(tpl["templates"][lang].format(**vals).split())
    return out


def write_prompts(prompts: dict[str, str], out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    paths = {}
    for lang, text in prompts.items():
        paths[lang] = out / f"prompt_{lang}.txt"
        paths[lang].write_text(text + "\n", encoding="utf-8")
    return paths
