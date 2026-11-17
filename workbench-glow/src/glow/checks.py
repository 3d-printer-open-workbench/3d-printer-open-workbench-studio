"""Acceptance checks: watertight, bed fit, assembly interference, LED/controller fit, clearances."""
from __future__ import annotations

import itertools

from workbench_core.geometry import BED_MM

INTERFERENCE_TOL_MM3 = 0.5  # the 0.01 mm extrusion closing of kaligraf can touch-overlap coplanar contacts


def _vol_inter(a, b) -> float:
    return float((a ^ b).volume())


def assembly_report(box) -> dict:
    """``box``: LightBox (duck typed: .model.parts, .solids, .model.meta)."""
    model, solids = box.model, box.solids
    meta = model.meta
    problems: list[str] = []
    parts_info = []
    for p in model.parts:
        m = p.mesh
        ok_w = bool(m.is_watertight and m.is_winding_consistent and m.volume > 0)
        ex = m.extents
        fits = bool(ex[0] <= BED_MM + 1e-6 and ex[1] <= BED_MM + 1e-6)
        parts_info.append({"name": p.name, "watertight": ok_w, "extents_mm": [round(float(v), 2) for v in ex], "fits_bed": fits,
                           "volume_cm3": round(float(m.volume) / 1000, 2)})
        if not ok_w:
            problems.append(f"Part {p.name} is not watertight.")
        if not fits and not getattr(getattr(box, "spec", None), "split_ok", False):
            problems.append(f"Part {p.name} exceeds the {BED_MM:.0f} mm bed.")
    group = {p.name: p.group for p in model.parts}
    names = [p.name for p in model.parts] + ["_led_strips", "_controller"]
    pairs = []
    for a, b in itertools.combinations(names, 2):
        if group.get(a) is not None and group.get(a) == group.get(b):
            continue  # colours of one printed unit are fused by design (only the 0.01 mm extrusion closing overlaps)
        v = _vol_inter(solids[a], solids[b])
        pairs.append({"a": a, "b": b, "overlap_mm3": round(v, 4)})
        if v > INTERFERENCE_TOL_MM3:
            problems.append(f"Interference between {a} and {b}: {v:.2f} mm3.")
    # clearance of the plug-in lips against the body wall (2D, designed values)
    polys = meta["polys"]
    c_back = polys["inner"].exterior.distance(polys["lip_out"].exterior)
    clearance_ok = 0.2 - 1e-6 <= c_back <= 0.3 + 1e-6
    if not clearance_ok:
        problems.append(f"Lip clearance {c_back:.2f} mm outside 0.2-0.3 mm.")
    ctrl_fit = polys["pocket_in"].contains(box_ctrl(meta))
    if not ctrl_fit:
        problems.append("Controller does not fit its pocket.")
    return {"parts": parts_info, "interference": pairs, "max_overlap_mm3": max(p["overlap_mm3"] for p in pairs),
            "lip_clearance_mm": round(c_back, 3), "clearance_ok": clearance_ok, "controller_fits": bool(ctrl_fit),
            "gap_mm": meta["gap_mm"], "min_gap_mm": meta["min_gap_mm"], "gap_ok": meta["gap_mm"] >= meta["min_gap_mm"] - 1e-6,
            "problems": problems}


def box_ctrl(meta):
    from shapely.geometry import Polygon

    return Polygon(meta["controller_pocket"]["controller_polygon"])
