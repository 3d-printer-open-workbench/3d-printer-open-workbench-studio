"""AI image prompts (TR + EN) for a finished lightbox, from ``ai_prompt.yaml`` (structure as in Kaligraf's prompts)."""
from __future__ import annotations

from pathlib import Path

import yaml

from workbench_core.colorlib import descriptor
from workbench_core.prompt import join as _join, user_text as _user_text

TEMPLATE_FILE = Path(__file__).with_name("ai_prompt.yaml")
PRODUCT = {
    "rect": ("arkadan LED ile aydınlatılan dikdörtgen lightbox (isimlik)", "a rectangular LED-backlit lightbox sign"),
    "round": ("arkadan LED ile aydınlatılan yuvarlak lightbox", "a round LED-backlit lightbox"),
    "contour": ("logo silüetini izleyen, arkadan LED ile aydınlatılan lightbox", "a logo-shaped LED-backlit lightbox following the silhouette"),
}
MOUNT = {"desk": ("masa üstünde ayakları üzerinde duruyor", "standing on its feet on a desk"),
         "stand": ("küçük bir stand üzerinde duruyor", "standing on a small stand"),
         "wall": ("duvara asılı", "hanging on the wall")}


def load_template(path: Path | str = TEMPLATE_FILE) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def user_field_choices(tpl: dict | None = None) -> dict[str, dict]:
    tpl = tpl or load_template()
    return {k: {"label": v["label"], "default": v.get("default", ""),
                "choices": {ck: cv["tr"] for ck, cv in v.get("choices", {}).items()}} for k, v in tpl["user_fields"].items()}


def auto_fields(data: dict) -> dict[str, str]:
    inp, meta, ov = data["inputs"], data["meta"], data["overall_mm"]
    w, h, d = ov["width_mm"] / 10, ov["height_mm"] / 10, ov["depth_mm"] / 10
    design = meta["design"]
    cols = []
    for p in data["parts"]:
        if p["color"] not in cols and not p["name"].startswith(("stand", "back")):
            cols.append(p["color"])
    desc = [descriptor(c) for c in cols]
    lit = meta["lit"]
    led = meta["led"]
    glow_tr = "sıcak beyaz" if inp.get("led_color") is None else inp["led_color"]
    mount = MOUNT.get(meta["mount"], MOUNT["desk"])
    return {
        "text": inp.get("text") or "logo",
        "product_tr": PRODUCT[design][0], "product_en": PRODUCT[design][1],
        "dimension_tr": f"Gerçek boyut: {w:.1f} cm genişlik x {h:.1f} cm yükseklik, {d:.1f} cm derinlik.",
        "dimension_en": f"Real size: {w:.1f} cm wide x {h:.1f} cm tall, {d:.1f} cm deep.",
        "color_tr": "Gövde/çerçeve ve renkler: " + _join([x["text_tr"] for x in desc], "tr") + ".",
        "color_en": "Body/frame and colours: " + _join([x["text_en"] for x in desc], "en") + ".",
        "lit_tr": ("Yazı/logo içeriden aydınlanır (ışık geçiren difüzör), arka zemin ve çerçeve opaktır." if lit == "text"
                   else "Arka zemin içeriden aydınlanır (ışık geçiren difüzör), yazı/logo ve çerçeve opaktır.")
                  + (f" Işık rengi: {glow_tr}; RGB LED olduğundan renk değişebilir." if "ws2812" in led else " Işık tek renktir."),
        "lit_en": ("The text/logo is backlit through a translucent diffuser; the background and frame are opaque." if lit == "text"
                   else "The background is backlit through a translucent diffuser; the text/logo and frame are opaque.")
                  + (f" Light colour: {inp.get('led_color') or 'warm white'}; RGB LEDs, so the colour can change." if "ws2812" in led else " Single-colour light."),
        "font_tr": f"Yazı tipi: {inp.get('font', '-')}." if inp.get("text") else "", "font_en": f"Typeface: {inp.get('font', '-')}." if inp.get("text") else "",
        "mounting_tr": mount[0].capitalize() + ".", "mounting_en": mount[1].capitalize() + ".",
    }


def build_prompts(data: dict, user: dict[str, str] | None = None, tpl: dict | None = None) -> dict[str, str]:
    tpl = tpl or load_template()
    user = user or {}
    auto = auto_fields(data)
    out = {}
    for lang in ("tr", "en"):
        vals = dict(auto)
        for name in ("scene", "wall", "lighting", "camera"):
            vals[name] = _user_text(tpl, user, name, lang)
        ref = _user_text(tpl, user, "scale_ref", lang)
        extra = _user_text(tpl, user, "extra", lang)
        if lang == "tr":
            vals["scale_tr"] = f"Ölçek için görselde {ref} bulunsun." if ref else ""
            vals["extra_tr"] = f" Ek ayrıntılar: {extra}" if extra else ""
        else:
            vals["scale_en"] = f"For scale, include {ref} in the shot." if ref else ""
            vals["extra_en"] = f" Extra details: {extra}" if extra else ""
        out[lang] = " ".join(tpl["templates"][lang].format(**vals).split())
    return out


def write_prompts(prompts: dict[str, str], out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    paths = {}
    for lang, text in prompts.items():
        paths[lang] = out / f"prompt_{lang}.txt"
        paths[lang].write_text(text + "\n", encoding="utf-8")
    return paths
