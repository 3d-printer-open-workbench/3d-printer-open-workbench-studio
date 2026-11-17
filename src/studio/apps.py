"""The programs inside Studio (their job runners and output folders) and the product catalogue."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from workbench_core.app import port_state as _port_state

TITLE = os.environ.get("STUDIO_TITLE") or "Open Workbench Studio"  # user-facing name (window, menu, CLI)
_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
STATE_DIR = Path(os.environ.get("STUDIO_HOME") or _DATA_HOME / "workbench-studio").expanduser()
WORK_ROOT = Path(os.environ.get("STUDIO_WORK_DIR") or STATE_DIR / "output").expanduser()


@dataclass
class App:
    key: str
    label: str
    module: str  # python -m <module>.cli make job.yaml
    work_sub: str  # output folder under WORK_ROOT


APPS = {
    "kaligraf": App("kaligraf", "Kaligraf", "kaligraf", "Kaligraf"),
    "glow": App("glow", "Glow", "glow", "Glow"),
    "topo": App("topo", "Topo", "topo", "Topo"),
    "maker": App("maker", "Maker", "maker", "Maker"),
}


def port_state(port: int, marker: str) -> str:
    """'free', 'ours' (the expected page answers) or 'busy' (something else) on 127.0.0.1."""
    return _port_state("127.0.0.1", port, marker)


def catalogue() -> list[dict]:
    """Every product Studio offers: {id, group, label, description, app}, in editor order (one source: studio.products)."""
    from .products import FAMILIES, products

    fam = {f["key"]: f["label"] for f in FAMILIES}
    return [{"id": p.id, "group": p.extra.get("group") or fam[p.family], "label": p.label, "description": p.description, "app": p.program}
            for p in products().values()]


