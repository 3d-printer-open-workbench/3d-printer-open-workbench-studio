"""Plain, documented tool functions exposed through the Gradio MCP server (and usable directly).

Every function takes and returns JSON-friendly values; docstrings are the tool descriptions.
"""

from __future__ import annotations

from pathlib import Path

from workbench_core.tools import color_info, read_job, save_prompt  # noqa: F401  (shared tools, re-exported)

DEFAULT_OUT = Path("output")


def make_model(job: dict, output_dir: str = "") -> dict:
    """Generate a print-ready model (3MF, renders, template PDF, prompts) from a job description.

    Args:
        job: Job fields, e.g. {"mode": "flat", "text": "Workbench", "font": "Montserrat", "width_cm": 40,
            "thickness_mm": 5, "color_style": "two_tone", "colors": ["#222222", "#F5F5F5"],
            "finishes": {"#F5F5F5": "ipek"}} or {"mode": "letters", "text": "ŞÜKRÜ", "letter_height_cm": 20,
            "depth_mm": 30, "face_color": "beyaz", "letter_colors": ["siyah"]}. Finishes (mat, parlak, ipek,
            ahşap, mermer, simli) only change the renders.
        output_dir: Folder that receives the job folder (default: ./output).

    Returns:
        Dict with job_dir, output file paths, a text summary and warnings.
    """
    from .job import Job, run_job

    raw = dict(job)
    if (
        raw.get("mode") == "flat"
        and "split_letters" not in raw
        and raw.get("color_style", "single") != "backplate"
        and not raw.get("logo")
        and "connector_bar" not in (raw.get("mounting") or [])
    ):
        raw["split_letters"] = True
    j = Job.from_dict(raw)
    res = run_job(j, output_dir or DEFAULT_OUT)
    out_dir = Path(res.out_dir)
    stl_files = sorted(str(p) for p in (out_dir / "parts").glob("*.stl"))
    all_files = sorted([*(str(p) for p in out_dir.iterdir() if p.is_file()), *stl_files])
    return {"job_dir": str(out_dir), "files": all_files, "stl_files": stl_files,
            "summary": job_summary(str(out_dir)), "warnings": list(res.data.get("warnings", []))}


def job_summary(job_dir: str) -> str:
    """Describe a generated job: text, real dimensions, colours (HEX / RAL / name / finish), font, mode, mounting, render paths.

    Args:
        job_dir: Path of a job folder that contains job.json.

    Returns:
        Plain multi-line text, suitable for writing an image-generation prompt.
    """
    d = Path(job_dir)
    data = read_job(d)
    inp = data.get("inputs", {})
    dims = data.get("overall_mm") or data.get("dimensions_mm") or {}
    mode = "flat sign" if inp.get("mode") == "flat" else "3D letters"
    lines = [f"Job: {d.name}", f"Mode: {mode}", f"Text: {inp.get('text') or '(logo only)'}", f"Font: {inp.get('font')}"]
    if dims:
        w, h, dp = dims.get("width_mm"), dims.get("height_mm"), dims.get("depth_mm")
        lines.append(f"Real size: {w / 10:.1f} cm wide x {h / 10:.1f} cm high x {dp:.0f} mm deep")
        if dims.get("cap_height_mm"):
            lines.append(f"Letter (cap) height: {dims['cap_height_mm'] / 10:.1f} cm")
    lines.append("Colours:")
    for c in data.get("colors", []):
        lines.append(f"- {c.get('text_en') or c.get('hex')} | HEX {c['hex']} | {c['ral']['code']} | {c['name_en']} | finish {c.get('finish', 'matte')}")
    lines.append(f"Mounting: {', '.join(inp.get('mounting', []))}")
    renders = sorted(str(p) for p in d.glob("*.png"))
    lines.append("Renders: " + (", ".join(renders) if renders else "(none)"))
    return "\n".join(lines)


