"""Command line: ``topo make job.yaml``, ``topo modes``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from workbench_core.app import enter_work_dir

from .job import Job




def cmd_make(a) -> int:
    from .data import DataError
    from .output import run_job

    if a.out == Path("output"):
        enter_work_dir("TOPO_WORK_DIR", "Topo")
    try:
        res = run_job(Job.from_yaml(a.job), a.out, progress=lambda m: print("  " + m))
    except (ValueError, KeyError, FileNotFoundError, DataError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    d = res.data
    o = d["overall_mm"]
    print(f"Hazır: {res.out_dir}")
    print(f"  Boyut: {o['width'] / 10:.1f} x {o['depth'] / 10:.1f} x {o['height'] / 10:.1f} cm  ölçek {d['scale']}  yükseklik x{d['z_exag']}")
    print(f"  Tabla: {d['tiles']}  Filament: " + ", ".join(f"{f['slot']}={f['color']} ({'+'.join(f['parts'])})" for f in d["filaments"]))
    print(f"  Tahmin: {d['estimate']['grams_total']} g, {d['estimate']['text']}")
    for w in d["warnings"]:
        print(f"  Uyarı: {w}")
    return 0


def cmd_modes(a) -> int:
    from .modes import MODES

    for m in MODES.values():
        print(f"{m.key:7s} {m.label} — temalar: {', '.join(t.name for t in m.themes)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="topo", description="Workbench - Topo: baskıya hazır 3B haritalar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="job.yaml dosyasından harita üret")
    mk.add_argument("job", type=Path)
    mk.add_argument("--out", type=Path, default=Path("output"))
    mk.set_defaults(func=cmd_make)
    sub.add_parser("modes", help="modları listele").set_defaults(func=cmd_modes)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
