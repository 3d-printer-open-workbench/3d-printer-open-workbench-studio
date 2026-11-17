"""Per-font metrics for the catalog: Turkish coverage and minimum printable sizes.

The minimum size is the smallest cap height (cm, text-independent) at which the min-feature check
passes for the sample text, per mode (Mode A limit 2.0 mm, Mode B 3.0 mm); it is found by bisection
on the scale of a once-built layout, rounded up to 0.5 cm. Results are cached in ``fonts/metrics.json``.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from shapely import affinity

from .fonts import DEFAULT_FONTS_DIR, load_registry, load_ttfont, missing_glyphs, resolve_font
from .text2d import MIN_FEATURE_MM, build_text, thin_regions

SAMPLE = "Portalin | Your Brand"
TURKISH = "çğıİöşüÇĞÖŞÜ"
METRICS_FILE = "metrics.json"
STEP_CM = 0.5
MIN_A_CM, MIN_B_CM = 1.0, 2.0  # smallest cap heights searched
MAX_A_CM, MAX_B_CM = 40.0, 40.0  # above this the font is reported as unusable


def _passes(geometry, factor: float, limit_mm: float) -> bool:
    g = affinity.scale(geometry, factor, factor, origin=(0, 0))
    return not thin_regions(g, limit_mm)


def _min_scale(geometry, size_cm: float, min_cm: float, max_cm: float, limit_mm: float) -> float | None:
    """Smallest size (cm) >= ``min_cm`` at which the check passes, given geometry built at ``size_cm``."""
    hi = max_cm
    if not _passes(geometry, hi / size_cm, limit_mm):
        return None
    lo = min_cm
    if _passes(geometry, lo / size_cm, limit_mm):
        return lo
    for _ in range(14):
        mid = math.sqrt(lo * hi)
        if _passes(geometry, mid / size_cm, limit_mm):
            hi = mid
        else:
            lo = mid
    return math.ceil(hi / STEP_CM - 1e-9) * STEP_CM


def font_metrics(font_id: str, fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> dict:
    rf = resolve_font(font_id, fonts_dir)
    ttf = load_ttfont(rf)
    miss = missing_glyphs(ttf, TURKISH)
    out: dict = {"id": rf.spec.id, "name": rf.spec.name, "category": rf.spec.category,
                 "turkish_missing": miss, "turkish_ok": not miss}
    a = build_text(SAMPLE, rf, "flat", width_mm=400.0)
    out["min_cap_flat_cm"] = _min_scale(a.geometry, a.cap_height_mm / 10, MIN_A_CM, MAX_A_CM, MIN_FEATURE_MM["flat"])
    b = build_text(SAMPLE, rf, "letters", cap_height_mm=100.0)
    out["min_cap_letters_cm"] = _min_scale(b.geometry, 10.0, MIN_B_CM, MAX_B_CM, MIN_FEATURE_MM["letters"])
    return out


def compute_all(fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> dict[str, dict]:
    reg = load_registry(Path(fonts_dir))
    return {s.id: font_metrics(s.id, fonts_dir) for s in reg.values()}


def write_metrics(fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> dict[str, dict]:
    data = compute_all(fonts_dir)
    (Path(fonts_dir) / METRICS_FILE).write_text(
        json.dumps({"sample": SAMPLE, "fonts": data}, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def load_metrics(fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> dict[str, dict]:
    """Cached metrics (empty dict if ``metrics.json`` is missing)."""
    p = Path(fonts_dir) / METRICS_FILE
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))["fonts"]


def size_warnings(metrics: dict | None, mode: str, cap_cm: float) -> list[str]:
    """Turkish warnings when the cap height (cm) is below the font's minimum for ``mode``
    ("flat" or "letters") or the font lacks Turkish glyphs."""
    if not metrics:
        return []
    out = []
    if not metrics.get("turkish_ok", True):
        out.append(f"{metrics['name']} yazı tipinde eksik Türkçe karakter var: {' '.join(metrics['turkish_missing'])}")
    m = metrics.get("min_cap_flat_cm" if mode == "flat" else "min_cap_letters_cm")
    if m is None:
        out.append(f"{metrics['name']} bu modda ince çizgileri nedeniyle güvenilir şekilde basılamaz.")
    elif cap_cm < m:
        out.append(f"{metrics['name']} için önerilen en küçük büyük harf yüksekliği {m:g} cm; mevcut {cap_cm:.1f} cm çok küçük, ince kısımlar basılamayabilir.")
    return out
