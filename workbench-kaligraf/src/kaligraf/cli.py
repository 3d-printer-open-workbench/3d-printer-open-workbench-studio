"""Command line: ``kaligraf make job.yaml`` (the editor is Open Workbench Studio's: ``studio open``)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .estimate import format_duration

from .job import Job, run_job


def cmd_make(args: argparse.Namespace) -> int:
    try:
        job = Job.from_yaml(args.job)
        res = run_job(job, args.out)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    d = res.data
    o = d["overall_mm"]
    print(f"Hazır: {res.out_dir}")
    print(f"  Boyut: {o['width_mm'] / 10:.1f} x {o['height_mm'] / 10:.1f} x {o['depth_mm'] / 10:.1f} cm")
    print(f"  Parça: {len(d['pieces'])} (tabla: {d['plates']})")
    print(f"  Filament: {d['filament_grams']['total']:.0f} g  " + ", ".join(f"{c} {g:.0f} g" for c, g in d["filament_grams"]["by_color"].items()))
    print(f"  Tahmini baskı süresi: {d['estimated_print_time']['text']}")
    names = [res.files[k].name for k in ("3mf", "template", "render_front", "render_34", "dims", "prompt_tr", "prompt_en") if k in res.files]
    print("  Dosyalar: " + ", ".join(names))
    for w in d["warnings"]:
        print(f"  Uyarı: {w}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kaligraf")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="job.yaml dosyasından model üret")
    mk.add_argument("job", type=Path)
    mk.add_argument("--out", type=Path, default=Path("output"), help="çıktı klasörü (varsayılan: output)")
    mk.set_defaults(func=cmd_make)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
