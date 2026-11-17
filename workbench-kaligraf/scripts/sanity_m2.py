#!/usr/bin/env python3
"""Generate example STLs into output/ and verify them (watertight, volume, bbox)."""
from pathlib import Path

import trimesh

from kaligraf.fonts import resolve_font
from kaligraf.geometry import export_stl, fits_bed, is_part_valid, make_flat, make_letters

OUT = Path(__file__).resolve().parents[1] / "output"


def report(label: str, model, out: Path) -> bool:
    paths = export_stl(model, out)
    ok = True
    print(f"== {label} -> {out}")
    for p, path in zip(model.parts, paths):
        mesh = trimesh.load(path)
        good = is_part_valid(mesh)
        ok &= good
        e = mesh.extents
        print(
            f"  {path.name:28s} {e[0]:6.1f} x {e[1]:6.1f} x {e[2]:5.1f} mm  "
            f"vol {mesh.volume / 1000:7.1f} cm3  watertight={mesh.is_watertight}  "
            f"fits_bed={fits_bed(mesh)}  extruder={p.extruder}"
        )
    for w in model.warnings:
        print("  WARNING:", w)
    return ok


def main() -> int:
    a = make_flat("Portalin", resolve_font("Montserrat"), 400, thickness=5, style="two_tone")
    b = make_letters("ŞÜKRÜ", resolve_font("Bebas Neue"), 200, depth=30)
    ok = report("Mode A: Portalin, Montserrat, 40 cm, two_tone", a, OUT / "modeA_sample")
    ok &= report("Mode B: ŞÜKRÜ, Bebas Neue, 20 cm, 30 mm", b, OUT / "modeB_sukru")
    print("ALL WATERTIGHT" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
