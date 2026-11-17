#!/usr/bin/env python3
"""End-to-end sanity: run the example jobs into output/ and validate STLs and the 3MF."""
from pathlib import Path

import trimesh

from kaligraf.export3mf import inspect_3mf
from kaligraf.geometry import is_part_valid
from kaligraf.job import Job, run_job

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ok = True
    for y in sorted((ROOT / "examples").glob("*.yaml")):
        res = run_job(Job.from_yaml(y), ROOT / "output")
        d = res.data
        stls = sorted((res.out_dir / "parts").glob("*.stl"))
        bad = [s.name for s in stls if not is_part_valid(trimesh.load(s))]
        info = inspect_3mf(res.files["3mf"])
        n3 = sum(len(o["parts"]) for o in info["objects"])
        exts = {p["extruder"] for o in info["objects"] for p in o["parts"]}
        good = not bad and n3 == len(stls) and len(exts) <= 4
        ok &= good
        o = d["overall_mm"]
        print(f"{y.name}: {o['width_mm']:.0f}x{o['height_mm']:.0f}x{o['depth_mm']:.0f} mm, "
              f"{len(stls)} STL (all watertight={not bad}), 3MF parts={n3}, extruders={sorted(exts)}, "
              f"plates={d['plates']}, {d['filament_grams']['total']:.0f} g, {d['estimated_print_time']['text']}")
        for w in d["warnings"]:
            print("   warning:", w)
    print("ALL OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
