"""Helpers every Workbench editor server shares: is a port free / ours / taken, and the output folder."""
from __future__ import annotations

import os
import socket
import urllib.request
from pathlib import Path

WORK_ROOT = Path(os.environ.get("STUDIO_WORK_DIR") or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
                 / "workbench-studio" / "output").expanduser()


def port_state(host: str, port: int, marker: str) -> str:
    """'free', 'ours' (a page containing ``marker`` answers) or 'busy' (another program)."""
    with socket.socket() as s:
        s.settimeout(0.3)
        if s.connect_ex((host, port)) != 0:
            return "free"
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=2) as r:
            return "ours" if marker.lower() in r.read(200_000).decode("utf-8", "ignore").lower() else "busy"
    except OSError:
        return "busy"


def enter_work_dir(env_var: str, name: str) -> Path | None:
    """When ``env_var`` is set (Studio sets it), work in that folder so ``output/`` lands under
    $STUDIO_WORK_DIR/<name> (default ~/.local/share/workbench-studio/output); otherwise stay where the program was
    started."""
    if not os.environ.get(env_var):
        return None
    d = Path(os.environ[env_var])
    d.mkdir(parents=True, exist_ok=True)
    os.chdir(d)
    return d


def port_busy_message(label: str, port: int, env_var: str) -> str:
    return f"HATA: {port} numaralı kapı başka bir program tarafından kullanılıyor ({label} açılamadı; {env_var} ile değiştirin)."
