"""Thermoform sheet table (``sheets.yaml``, user override in ~/.config/workbench-maker/sheets.yaml)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_FILE = Path(__file__).with_name("sheets.yaml")
USER_FILE = Path(os.environ.get("MAKER_SHEETS", Path.home() / ".config/workbench-maker/sheets.yaml"))


@dataclass(frozen=True)
class Sheet:
    id: str
    label: str
    material: str
    thickness_mm: float
    clearance_mm: float
    form_temp_c: tuple[float, float]
    max_draw: float
    min_radius_mm: float
    price_try: float = 0.0
    note: str = ""

    @property
    def mold_gap_mm(self) -> float:
        """Gap between male and female mold surfaces."""
        return self.thickness_mm + self.clearance_mm


def _parse(d: dict) -> tuple[str, dict[str, Sheet]]:
    out = {}
    for k, v in (d.get("sheets") or {}).items():
        t = v["thickness_mm"]
        if not 0.1 <= t <= 3.0:
            raise ValueError(f"{k}: levha kalınlığı 0.1–3.0 mm olmalı")
        out[k] = Sheet(id=k, label=v.get("label", k), material=v.get("material", "PETG"), thickness_mm=float(t),
                       clearance_mm=float(v.get("clearance_mm", 0.2)), form_temp_c=tuple(v.get("form_temp_c", (130, 160))),
                       max_draw=float(v.get("max_draw", 0.4)), min_radius_mm=float(v.get("min_radius_mm", 2.0)),
                       price_try=float(v.get("price_try", 0)), note=str(v.get("note", "")))
    if not out:
        raise ValueError("sheets.yaml: hiç levha yok")
    default = d.get("default") if d.get("default") in out else next(iter(out))
    return default, out


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[str, dict[str, Sheet]]:
    return _parse(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


def load_sheets() -> tuple[str, dict[str, Sheet]]:
    """(default id, sheets by id) from the user override if present, else the shipped table."""
    return _load(str(USER_FILE if USER_FILE.is_file() else DEFAULT_FILE))


def get_sheet(sid: str | None = None) -> Sheet:
    default, sheets = load_sheets()
    try:
        return sheets[sid or default]
    except KeyError:
        raise ValueError(f"bilinmeyen levha: {sid} (seçenekler: {', '.join(sheets)})") from None
