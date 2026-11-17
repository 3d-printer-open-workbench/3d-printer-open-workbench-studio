"""AI image prompt (Turkish + English) for a Maker job, from ``ai_prompt.yaml`` with the shared template helpers
(Kaligraf / Glow standard: prompt_tr.txt, prompt_en.txt, reference image = renders/urun.png)."""
from __future__ import annotations

from pathlib import Path

from . import core
from .generators import BuildResult

TEMPLATE_FILE = Path(__file__).with_name("ai_prompt.yaml")
TEXT_KEYS = ("text", "name", "caption", "side_text", "lid_text", "stamp_text", "title")


def load_template() -> dict:
    return core.prompt_tools.load_template(TEMPLATE_FILE)


def _cm(v: float) -> str:
    return f"{v / 10:.1f}".rstrip("0").rstrip(".")


def build_prompts(generator: str, values: dict, res: BuildResult, data: dict, user: dict | None = None) -> dict[str, str]:
    tpl = load_template()
    pt = core.prompt_tools
    prod = tpl["products"].get(generator, tpl["products"]["plate"])
    user = {"scene": prod.get("scene", "masa"), **(user or {})}
    shown = [p for p in res.parts if p.meta.get("product")] or [p for p in res.parts if p.printable]
    colors = list(dict.fromkeys(p.color.upper() for p in shown))
    names = [pt.color_names(c) for c in colors]
    mats = sorted({p.material for p in shown})
    lo = min(p.mesh.bounds[0][0] for p in shown), min(p.mesh.bounds[0][1] for p in shown), min(p.mesh.bounds[0][2] for p in shown)
    hi = max(p.mesh.bounds[1][0] for p in shown), max(p.mesh.bounds[1][1] for p in shown), max(p.mesh.bounds[1][2] for p in shown)
    w, d, h = (float(b - a) for a, b in zip(lo, hi))  # the product only, not molds / stands laid out next to it
    texts = (str(values.get(k) or "").replace("\\n", " ").strip() for k in TEXT_KEYS)
    text = next((t for t in texts if t and t.lower() != "auto"), "")
    out = {}
    for lang in ("tr", "en"):
        i = 0 if lang == "tr" else 1
        vals = {k: pt.user_text(tpl, user, k, lang) for k in ("scene", "lighting", "camera")}
        vals["product_tr"], vals["product_en"] = prod["tr"], prod["en"]
        vals["text_tr"] = f', üzerinde "{text}" yazıyor' if text else ""
        vals["text_en"] = f', reading "{text}"' if text else ""
        vals["dimension_tr"] = f"Boyut yaklaşık {_cm(w)} × {_cm(d)} × {_cm(h)} cm."
        vals["dimension_en"] = f"About {_cm(w)} × {_cm(d)} × {_cm(h)} cm."
        cn = pt.join([n[i] for n in names], lang)
        vals["color_tr"] = f"Renkler: {cn}." if cn else ""
        vals["color_en"] = f"Colours: {cn}." if cn else ""
        vals["material_tr"] = f"Malzeme: {', '.join(mats)} (3B baskı)."
        vals["material_en"] = f"Material: {', '.join(mats)} (3D printed)."
        extra = pt.user_text(tpl, user, "extra", lang)
        vals["extra_tr"] = f" Ek ayrıntılar: {extra}" if extra and lang == "tr" else ""
        vals["extra_en"] = f" Extra details: {extra}" if extra and lang == "en" else ""
        out[lang] = " ".join(tpl["templates"][lang].format(**vals).split())
    return out


def write_prompts(prompts: dict[str, str], out_dir: Path) -> dict[str, Path]:
    return core.prompt_tools.write_prompts(prompts, out_dir)
