"""Command line: ``studio open`` (window), ``studio ui``, ``studio stop``, ``studio make job.yaml`` (any program's job
file), ``studio list``. The old stand-alone commands are gone: everything runs through Studio."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import yaml

from . import __version__
from .apps import APPS, STATE_DIR, TITLE, WORK_ROOT, port_state
from .server import DEFAULT_PORT, PID_FILE

LOG_FILE = STATE_DIR / "studio.log"


def program_of(job: dict) -> str:
    """Which program a job file belongs to (the formats never overlap)."""
    if "generator" in job:
        return "maker"
    if "design" in job:
        return "glow"
    if job.get("mode") in ("flat", "letters"):
        return "kaligraf"
    from topo.modes import MODES

    keys = MODES.keys() if isinstance(MODES, dict) else [m.key for m in MODES]
    if job.get("mode") in keys:
        return "topo"
    raise ValueError("iş dosyası tanınmadı: 'generator' (Maker), 'design' (Glow), mode flat/letters (Kaligraf) ya da "
                     "harita modu (Topo) bekleniyordu")


def cmd_make(a) -> int:
    job = yaml.safe_load(Path(a.job).read_text(encoding="utf-8")) or {}
    try:
        prog = program_of(job)
    except ValueError as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    out = a.out or str(WORK_ROOT / APPS[prog].work_sub / "output")
    argv = ["make", a.job, "--out", out] + (["--slice"] if a.slice and prog == "maker" else [])
    print(f"{APPS[prog].label} işi")
    mod = __import__(f"{APPS[prog].module}.cli", fromlist=["main"])
    return mod.main(argv) or 0


def cmd_check(a) -> int:
    from workbench_core.tools import print_check

    try:
        res = print_check(a.model)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    print(Path(res["report"]).read_text(encoding="utf-8"))
    return 0


def cmd_list(a) -> int:
    from .apps import catalogue

    group = None
    for it in catalogue():
        if it["group"] != group:
            group = it["group"]
            print(f"\n{group}")
        print(f"  {it['label']}  [{APPS[it['app']].label}]")
    return 0


def cmd_ui(a) -> int:
    from .server import launch

    return launch(a.host, a.port, open_browser=not a.no_browser)


def cmd_open(a) -> int:
    import webbrowser

    port = a.port or int(os.environ.get("STUDIO_PORT", DEFAULT_PORT))
    st = port_state(port, TITLE)
    if st == "busy":
        print(f"HATA: {port} numaralı kapı başka bir program tarafından kullanılıyor (STUDIO_PORT ile değiştirin).")
        return 1
    if st == "free":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "ab") as log:
            subprocess.Popen([sys.executable, "-m", "studio.cli", "ui", "--port", str(port), "--no-browser"],
                             stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        for _ in range(120):
            time.sleep(0.5)
            if port_state(port, TITLE) == "ours":
                break
        else:
            print(f"HATA: Studio başlamadı; günlük: {LOG_FILE}")
            return 1
    url = f"http://127.0.0.1:{port}"
    if a.app:
        url += f"/#{a.app}"
    webbrowser.open(url)
    return 0


def cmd_stop(a) -> int:
    try:
        pid = int(PID_FILE.read_text().strip())
        if "studio" not in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="ignore"):
            raise ProcessLookupError
        os.kill(pid, signal.SIGTERM)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        print("Çalışan Studio bulunamadı.")
        return 1
    print("Studio kapatıldı.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="studio", description=f"{TITLE}: tabela, ışıklı kutu, harita ve bütün Maker ürünleri")
    ap.add_argument("--version", action="version", version=f"{TITLE} {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="herhangi bir programın job.yaml dosyasından ürün üret")
    mk.add_argument("job")
    mk.add_argument("--out", default=None)
    mk.add_argument("--slice", action="store_true", help="Maker işlerinde OrcaSlicer ile dilimle")
    mk.set_defaults(func=cmd_make)
    sub.add_parser("list", help="bütün ürünleri listele").set_defaults(func=cmd_list)
    ck = sub.add_parser("kontrol", help="model.3mf'yi OrcaSlicer'da dilimle, baskı yolu kalite raporu çıkar")
    ck.add_argument("model", help="model.3mf ya da iş klasörü")
    ck.set_defaults(func=cmd_check)
    for name, fn, hlp in (("ui", cmd_ui, "Studio penceresini başlat (ön planda)"), ("open", cmd_open, "Studio'yu arka planda başlat, tarayıcıyı aç")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=None)
        p.add_argument("--no-browser", action="store_true")
        if name == "open":
            p.add_argument("--app", choices=list(APPS), default=None, help="açılışta bu programın ürününü seç")
        p.set_defaults(func=fn)
    sub.add_parser("stop", help="çalışan Studio'yu kapat").set_defaults(func=cmd_stop)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
