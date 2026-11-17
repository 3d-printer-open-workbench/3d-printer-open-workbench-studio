"""Template helpers for the AI image prompts (Turkish + English) every Workbench program writes.

A template (YAML) has ``user_fields`` (scene, wall, lighting, ... with Turkish/English choices and a default) and the
program's own sentence templates; each program builds its auto fields (text, sizes, colours) and fills them in."""
from __future__ import annotations

from pathlib import Path

import yaml

from .colorlib import CANON


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def color_names(hex_color: str) -> tuple[str, str]:
    """(Turkish, English) name of the nearest named filament colour."""
    r = _rgb(hex_color)
    best = min(CANON, key=lambda c: sum((a - b) ** 2 for a, b in zip(r, _rgb(c[0]))))
    return best[1], best[2]


def load_template(path: Path | str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def default_user_fields(tpl: dict) -> dict[str, str]:
    return {k: v.get("default", "") for k, v in tpl["user_fields"].items()}


def user_field_choices(tpl: dict) -> dict[str, dict]:
    """{field: {"label": str, "default": str, "choices": {key: Turkish text}}} for the UI form."""
    out = {}
    for k, v in tpl["user_fields"].items():
        out[k] = {"label": v["label"], "default": v.get("default", ""),
                  "choices": {ck: cv["tr"] for ck, cv in v.get("choices", {}).items()}}
    return out


def user_text(tpl: dict, user: dict[str, str], name: str, lang: str) -> str:
    """A user field in ``lang``: the choice's wording, or the free text as typed."""
    spec = tpl["user_fields"][name]
    val = (user.get(name) if user.get(name) is not None else spec.get("default", "")) or ""
    choice = spec.get("choices", {}).get(val)
    return choice[lang] if choice else str(val).strip()


def join(items: list[str], lang: str) -> str:
    """'a, b ve c' / 'a, b and c'."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" ve " if lang == "tr" else " and ") + items[-1]


def write_prompts(prompts: dict[str, str], out_dir: str | Path, stem: str = "prompt") -> dict[str, Path]:
    """``{lang: text}`` -> ``<out_dir>/<stem>_<lang>.txt``."""
    out = {}
    for lang, text in prompts.items():
        p = Path(out_dir) / f"{stem}_{lang}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text.rstrip() + "\n", encoding="utf-8")
        out[lang] = p
    return out
