"""Colour card ("kartela"): fine-tune the HEX of each filament in your palette with a slider (`/kartela`).

The palette file is ``workbench_core.colorlib.palette_path()`` (``$WORKBENCH_PALETTE`` ...; format:
``examples/palette.example.yaml``). The saved HEX is written back to the palette and marked verified. When
``WORKBENCH_ERP_URL`` is set and the colour has an ``erp_filament_id``, the new colour is also sent to the optional
Open Workbench ERP (``PATCH /api/filaments/{id}/renk``).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

import yaml

ERP_URL = (os.environ.get("WORKBENCH_ERP_URL") or "").rstrip("/")
BASLIK = ("# Filament renk paleti (Open Workbench Studio /kartela sayfasından da düzenlenir).\n"
          "# dogrulandi: true = HEX ölçülerek / gözle ayarlanarak doğrulandı; false = tahmin, doğrulanmalı.\n")


def palet_yolu() -> Path:
    from workbench_core.colorlib import palette_path

    return palette_path()


def oku(yol: Path | None = None) -> list[dict[str, Any]]:
    yol = yol or palet_yolu()
    if not yol.exists():
        return []
    return list((yaml.safe_load(yol.read_text(encoding="utf-8")) or {}).get("renkler") or [])


def _yaz(renkler: list[dict[str, Any]], yol: Path) -> None:
    yol.write_text(BASLIK + yaml.safe_dump({"renkler": renkler}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _erp_guncelle(filament_id: int, hx: str) -> str | None:
    """ERP filament rengini günceller; hata metni ya da None (ERP ayarlı değilse hiçbir şey yapmaz)."""
    if not ERP_URL:
        return None
    try:
        req = urllib.request.Request(f"{ERP_URL}/api/filaments/{int(filament_id)}/renk", method="PATCH",
                                     data=json.dumps({"color_hex": hx, "kaynak": "kartela slider"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8):
            return None
    except Exception as e:  # ERP kapalı olabilir; palet yine kaydedilir
        return str(e)[:200]


def kaydet(indeks: int, hx: str, yol: Path | None = None, erp: bool = True) -> dict[str, Any]:
    hx = (hx or "").strip().upper()
    if not hx.startswith("#"):
        hx = "#" + hx
    if not re.fullmatch(r"#[0-9A-F]{6}", hx):
        raise ValueError("Renk #RRGGBB biçiminde olmalı")
    yol = yol or palet_yolu()
    renkler = oku(yol)
    if not 0 <= indeks < len(renkler):
        raise ValueError("Kartelada böyle bir renk yok")
    r = renkler[indeks]
    eski = r.get("hex")
    r["hex"] = hx
    r["dogrulandi"] = True
    r["kaynak"] = "kartela slider (göz ve referans fotoğrafla ayarlandı)"
    r["tarih"] = dt.date.today().isoformat()
    _yaz(renkler, yol)
    erp_hata = _erp_guncelle(r["erp_filament_id"], hx) if erp and r.get("erp_filament_id") else None
    return {"renk": r, "eski_hex": eski, "erp_hata": erp_hata,
            "erp": bool(erp and ERP_URL and r.get("erp_filament_id"))}
