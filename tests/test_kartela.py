"""Kartela slider kaydı: palete doğru HEX yazılır, doğrulandı işaretlenir, geçersiz girdi reddedilir."""
from __future__ import annotations

import pytest
import yaml

from studio import kartela


def test_kaydet_paleti_gunceller(tmp_path):
    yol = tmp_path / "renk_paleti.yaml"
    yol.write_text(yaml.safe_dump({"renkler": [{"ad": "Kemik", "hex": "#1F2937", "dogrulandi": False},
                                                {"ad": "Siyah", "hex": "#1E1E1E"}]}, allow_unicode=True))
    s = kartela.kaydet(0, "e3d9c6", yol=yol, erp=False)
    assert s["eski_hex"] == "#1F2937" and s["renk"]["hex"] == "#E3D9C6"
    r = kartela.oku(yol)
    assert r[0]["hex"] == "#E3D9C6" and r[0]["dogrulandi"] is True and "slider" in r[0]["kaynak"]
    assert r[1]["hex"] == "#1E1E1E"
    assert yol.read_text(encoding="utf-8").startswith("# Filament renk paleti")
    with pytest.raises(ValueError):
        kartela.kaydet(0, "#12345", yol=yol, erp=False)
    with pytest.raises(ValueError):
        kartela.kaydet(5, "#123456", yol=yol, erp=False)


def test_palette_path_precedence(monkeypatch, tmp_path):
    from workbench_core.colorlib import palette_path

    for k in ("WORKBENCH_PALETTE", "WORKBENCH_CONFIG", "WORKBENCH_ROOT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STUDIO_HOME", str(tmp_path / "state"))
    assert palette_path() == tmp_path / "state" / "renk_paleti.yaml"
    monkeypatch.setenv("WORKBENCH_ROOT", str(tmp_path / "root"))
    assert palette_path() == tmp_path / "root" / "config" / "renk_paleti.yaml"
    monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "cfg"))
    assert palette_path() == tmp_path / "cfg" / "renk_paleti.yaml"
    monkeypatch.setenv("WORKBENCH_PALETTE", str(tmp_path / "p.yaml"))
    assert palette_path() == tmp_path / "p.yaml"


def test_example_palette_feeds_the_colour_pickers(monkeypatch):
    from pathlib import Path

    from workbench_core.colorlib import PALETTE, filament_palette

    example = Path(__file__).resolve().parents[1] / "examples" / "palette.example.yaml"
    monkeypatch.setenv("WORKBENCH_PALETTE", str(example))
    pal = filament_palette()
    assert pal[0] == ("#F2F2EE", "Matte White (Generic PLA) ~") and len(pal) > len(PALETTE)
    monkeypatch.setenv("WORKBENCH_PALETTE", str(example.with_name("missing.yaml")))
    assert filament_palette() == PALETTE


def test_erp_sync_is_off_without_url(tmp_path, monkeypatch):
    monkeypatch.setattr(kartela, "ERP_URL", "")
    yol = tmp_path / "renk_paleti.yaml"
    yol.write_text(yaml.safe_dump({"renkler": [{"ad": "Gri", "hex": "#888888", "erp_filament_id": 3}]}))
    s = kartela.kaydet(0, "#777777", yol=yol)
    assert s["erp_hata"] is None and s["erp"] is False
