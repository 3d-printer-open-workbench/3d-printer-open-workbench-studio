"""Plain, documented tool functions exposed through the Gradio MCP server (docstrings are the tool descriptions)."""
from __future__ import annotations

from pathlib import Path

from workbench_core.tools import color_info, read_job, save_prompt  # noqa: F401  (shared tools, re-exported)

DEFAULT_OUT = Path("output")


def make_glow(job: dict, output_dir: str = "") -> dict:
    """Generate a print-ready LED lightbox (3MF, STL parts, lit/unlit renders, assembly_tr.pdf, BOM, prompts) from a job description.

    Args:
        job: Job fields. design is "rect", "round" or "contour". Examples:
            {"design": "rect", "text": "Workbench", "font": "Montserrat", "width_mm": 200, "frame_color": "#1F4D3A",
             "led": "ws2812b_10mm", "controller": "bt_rgb_mini", "diffuser": "pla_white", "mount": "desk", "lit": "text"}
            {"design": "round", "text": "Workbench", "diameter_mm": 200, "depth_mm": 45, "mount": "stand"}
            {"design": "contour", "logo": "/path/logo.png", "width_mm": 220, "rim_mm": 6, "relief": "raised", "mount": "stand"}
            Optional: lit ("text" glows | "background" glows), led_fill ("normal" | "dense"), led_color (render only),
            split_ok (allow > 25 cm, split into pieces), interior_white, relief, relief_mm, margin_mm, depth_mm (20-100).
            Lightbox Maker style: shape (contour only: "heart" | "star" | "star4" | "circle" | "square" | "triangle" | "hexagon";
            "auto" = silhouette of the text/logo), front_mm (0.6-2.4 light face), back_mm (2-8), diffusion_mm (0.1-1.0 white
            layer behind the light regions), stroke_mm + stroke_color + stroke_glow (outline ring around the text/logo),
            stand_color, logo_colors (2-4), holes ([{"type": "rect"|"circle"|"key", "w": mm, "h": mm, "x": mm, "y": mm}] on the back).
            LED mounting: led_mount ("rails" | "channel" = U-channel that holds the strip), channel_cover (true: snap-on diffuser covers).
            LED types: cob_5mm, cob_8mm, cob_10mm, smd2835_8mm (single colour, controller usb_dimmer); ws2812b_5mm, ws2812b_10mm (RGB).
        output_dir: Folder that receives the job folder (default ./output).

    Returns:
        Dict with job_dir, files, a text summary and warnings (Turkish).
    """
    from .job import run_box

    raw = dict(job)
    design = raw.get("design")
    res = run_box(design, raw, output_dir or DEFAULT_OUT)
    out = Path(res["out_dir"])
    stl_files = sorted(str(p) for p in (out / "parts").glob("*.stl"))
    all_files = sorted([*(str(p) for p in out.iterdir() if p.is_file()), *stl_files])
    return {"job_dir": str(out), "files": all_files, "stl_files": stl_files,
            "summary": job_summary(str(out)), "warnings": list(res["warnings"])}


def job_summary(job_dir: str) -> str:
    """Describe a generated lightbox job: design, text, real dimensions, colours (HEX / RAL / name), LED, controller, power, cost, render paths.

    Args:
        job_dir: Path of a job folder that contains job.json.

    Returns:
        Plain multi-line text, suitable for writing an image-generation prompt.
    """
    from workbench_core.colorlib import color_code

    d = Path(job_dir)
    data = read_job(d)
    inp, meta, ov = data["inputs"], data["meta"], data["overall_mm"]
    lines = [f"Job: {d.name}", f"Design: {meta['design']} (lit: {meta['lit']} glows)", f"Text: {inp.get('text') or '(logo)'}",
             f"Font: {inp.get('font', '-')}" if inp.get("text") else f"Logo: {inp.get('logo')}",
             f"Real size: {ov['width_mm'] / 10:.1f} cm wide x {ov['height_mm'] / 10:.1f} cm high x {ov['depth_mm'] / 10:.1f} cm deep",
             f"Mount: {meta['mount']}", f"LED: {meta['led']}, controller: {meta.get('controller_used', meta['controller'])} ({meta.get('controller_mode', 'normal')}), diffuser: {meta['diffuser']}",
             f"Power: {data['power']['total_typical_w']} W typical, {data['power']['total_full_w']} W full white; supply {data['power']['supply']}",
             f"Cost: {data['bom']['total_try']} TRY (filament {data['bom']['filament_try']} TRY)", "Colours:"]
    seen = []
    for p in data["parts"]:
        if p["color"] in seen:
            continue
        seen.append(p["color"])
        c = color_code(p["color"])
        lines.append(f"- {c['text']} | HEX {c['hex']} | {c['ral']['code']} | {c['name_en']} | part {p['name']}")
    lines.append("Warnings: " + ("; ".join(data["warnings"]) if data["warnings"] else "none"))
    lines.append("Renders: " + ", ".join(sorted(str(p) for p in d.glob("*.png"))))
    return "\n".join(lines)


