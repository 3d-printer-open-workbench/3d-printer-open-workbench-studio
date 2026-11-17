"""Command line: ``maker make job.yaml``, ``maker list``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import core




def cmd_make(a) -> int:
    from .core import FontError
    from .job import load_job, run_job

    job_path = a.job.resolve()
    if a.out == Path("output"):
        core.enter_work_dir("MAKER_WORK_DIR", "Maker")
    try:
        job = load_job(job_path)
        if a.slice:
            job["slice"] = True
        res = run_job(job, a.out)
    except (ValueError, KeyError, FileNotFoundError, RuntimeError, FontError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    d = res.data
    w, h, z = d["overall_mm"]
    print(f"Hazır: {res.out_dir.resolve()}")
    print(f"  Boyut: {w / 10:.1f} x {h / 10:.1f} x {z / 10:.1f} cm, {len(d['parts'])} parça")
    for p in d["parts"]:
        print(f"  - {p['label']}: {p['material']} {p['color']}  {p['stl']}")
    for i, pl in enumerate(d.get("plates", []), 1):
        real = f"  {pl['grams']:.0f} g, {pl['time']}" if pl.get("grams") is not None else ""
        print(f"  Tabla {i} ({pl['material']}): {', '.join(pl['objects'])}{real}")
    print("  Belgeler: " + ", ".join(v for k, v in d.get("files", {}).items() if k in ("assembly_pdf", "sheet_pdf", "3mf")))
    for x in d["warnings"]:
        print(f"  Uyarı: {x}")
    return 0


def cmd_list(a) -> int:
    from .tools import list_generators

    for g in list_generators():
        st = "hazır" if g["status"] == "ready" else f"planlandı ({g['milestone']})"
        print(f"{g['key']:14s} {g['label']:28s} [{g['group']}] {st}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="maker", description="Workbench - Maker: kişiselleştirilebilir baskıya hazır modeller")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="job.yaml dosyasından model üret")
    mk.add_argument("job", type=Path)
    mk.add_argument("--out", type=Path, default=Path("output"))
    mk.add_argument("--slice", action="store_true", help="model.3mf'i OrcaSlicer ile dilimle (G-code, gerçek gram/süre)")
    mk.set_defaults(func=cmd_make)
    sub.add_parser("list", help="jeneratörleri listele").set_defaults(func=cmd_list)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
