"""``glow`` command line. G0 skeleton: ``make`` is wired to the design builders as they land (G2+)."""
from __future__ import annotations

import argparse
import sys


from . import __version__

DESIGNS = ("round", "rect", "contour")


def cmd_make(args: argparse.Namespace) -> int:
    from .job import run_job_file

    try:
        res = run_job_file(args.job, args.out)
    except (ValueError, KeyError, FileNotFoundError, NotImplementedError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    print(f"Hazır: {res['out_dir']}")
    for w in res["warnings"]:
        print(f"  Uyarı: {w}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="glow", description="Workbench - Glow: LED lightbox generator")
    p.add_argument("--version", action="version", version=f"glow {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make", help="build a lightbox from a job YAML")
    m.add_argument("job")
    m.add_argument("--out", default="output")
    m.set_defaults(func=cmd_make)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
