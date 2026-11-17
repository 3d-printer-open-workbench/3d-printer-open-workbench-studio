"""Agent tools every Workbench program shares (MCP tools: docstrings are the tool descriptions)."""
from __future__ import annotations

import json
from pathlib import Path

from .colorlib import color_code


def color_info(hex: str) -> str:
    """Universal colour code for a colour.

    Args:
        hex: Colour as #RRGGBB (the # is optional).

    Returns:
        One line "name (#HEX, ~RAL xxxx)" followed by RGB, nearest RAL Classic with its CIEDE2000
        distance, and the English descriptive name.
    """
    c = color_code(hex)
    ral = c["ral"]
    return (f"{c['text']}\nHEX {c['hex']}; RGB {tuple(c['rgb'])}; nearest RAL Classic {ral['code']} {ral['name']} "
            f"({ral['hex']}, dE2000 {ral['delta_e']}); English name: {c['name_en']}")


def read_job(job_dir: str | Path) -> dict:
    """job.json of a finished job (FileNotFoundError if the folder has none)."""
    f = Path(job_dir) / "job.json"
    if not f.is_file():
        raise FileNotFoundError(f"no job.json in {Path(job_dir)}")
    return json.loads(f.read_text(encoding="utf-8"))


def save_prompt(job_dir: str, prompt_tr: str, prompt_en: str) -> str:
    """Save the final image-generation prompts into the job folder as prompt_ai_tr.txt and prompt_ai_en.txt.

    Args:
        job_dir: Path of the job folder.
        prompt_tr: Final prompt in Turkish.
        prompt_en: Final prompt in English.

    Returns:
        The two written file paths.
    """
    d = Path(job_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"job folder not found: {d}")
    a, b = d / "prompt_ai_tr.txt", d / "prompt_ai_en.txt"
    a.write_text(prompt_tr.strip() + "\n", encoding="utf-8")
    b.write_text(prompt_en.strip() + "\n", encoding="utf-8")
    return f"{a}\n{b}"


def print_check(model: str) -> dict:
    """Slice a finished product with OrcaSlicer and check its print paths: grams per feature (walls, infill, bridges,
    gap fill, support, prime tower), colour changes, retractions, travel, and Turkish findings (waste, sagging bridges,
    too-thin regions, slicer warnings). Writes baski_raporu.txt / .json next to the model.
    Args: model: a model.3mf file or the job folder that contains it."""
    import json
    from pathlib import Path

    from .slicer import check_3mf, report_text

    p = Path(model).expanduser()
    if p.is_dir():
        p = p / "model.3mf"
    if not p.is_file():
        raise FileNotFoundError(f"model.3mf bulunamadı: {p}")
    res = check_3mf(p)
    (p.parent / "baski_raporu.txt").write_text(report_text(res), encoding="utf-8")
    (p.parent / "baski_raporu.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"report": str(p.parent / "baski_raporu.txt"),
            "plates": [{k: pl[k] for k in ("plate", "slicer_grams", "time", "colour_changes", "share", "findings")} for pl in res["plates"]]}
