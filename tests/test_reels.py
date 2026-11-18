"""Reels takvimi sayfasının API'si: okuma, güncelleme doğrulaması, not ve Claude isteği."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio import reels


def test_klasor_ortam_degiskenleri(monkeypatch, tmp_path: Path) -> None:
    for ad in ("WORKBENCH_REELS_DIR", "WORKBENCH_DATA", "WORKBENCH_ROOT"):
        monkeypatch.delenv(ad, raising=False)
    monkeypatch.setenv("STUDIO_HOME", str(tmp_path / "home"))
    assert reels.klasor() == tmp_path / "home" / "reels_takvimi"
    monkeypatch.setenv("WORKBENCH_ROOT", str(tmp_path / "kok"))
    assert reels.klasor() == tmp_path / "kok" / "veri" / "03_Magaza" / "reels_takvimi"
    monkeypatch.setenv("WORKBENCH_DATA", str(tmp_path / "veri"))
    assert reels.klasor() == tmp_path / "veri" / "03_Magaza" / "reels_takvimi"
    monkeypatch.setenv("WORKBENCH_REELS_DIR", str(tmp_path / "r"))
    assert reels.klasor() == tmp_path / "r"


def test_reels_akisi(tmp_path: Path) -> None:
    (tmp_path / "takvim.json").write_text(json.dumps({"fikirler": [
        {"id": "b", "baslik": "B", "tarih": "2026-11-22"}, {"id": "a", "baslik": "A", "tarih": "2026-11-20"}]}))
    v = reels.oku(tmp_path)
    assert [f["id"] for f in v["fikirler"]] == ["a", "b"] and v["istekler"] == []
    assert reels.guncelle("a", {"durum": "onaylandi", "cekim_tamam": [1]}, tmp_path)["durum"] == "onaylandi"
    for kotu in ({"durum": "x"}, {"id": "z"}, {"tarih": "yarın"}):
        with pytest.raises(ValueError):
            reels.guncelle("a", kotu, tmp_path)
    with pytest.raises(KeyError):
        reels.guncelle("yok", {"durum": "fikir"}, tmp_path)
    assert reels.not_ekle("a", "  sesi değiştir ", tmp_path)["notlar"][-1]["metin"] == "sesi değiştir"
    with pytest.raises(ValueError):
        reels.istek_ekle("revize", "", "a", k=tmp_path)
    reels.istek_ekle("revize", "daha kısa", "a", k=tmp_path)
    reels.istek_ekle("yeni_fikirler", adet=99, k=tmp_path)
    v = reels.oku(tmp_path)
    assert [i["tur"] for i in v["istekler"]] == ["revize", "yeni_fikirler"] and v["istekler"][1]["adet"] == 14
    assert v["fikirler"][0]["notlar"][-1]["metin"].startswith("Revize isteği")
