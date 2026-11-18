"""Trend Reels calendar (`/reels`): ideas with script, shooting instructions, status and notes.

Single source: `<folder>/takvim.json` ({"fikirler": [...]}); folder = `$WORKBENCH_REELS_DIR`, else
`$WORKBENCH_DATA/03_Magaza/reels_takvimi`, else `$WORKBENCH_ROOT/veri/03_Magaza/reels_takvimi` (the layout of the
Open Workbench bot), else `$STUDIO_HOME/reels_takvimi`. Ideas are produced by the bot (`reels-tiktok-strategist`
agent); this module reads/updates them, adds notes and queues Claude jobs (new ideas / revise) in `istekler.json`,
which the bot processes in order. Same format as the bot's `coo/reels_takvim.py`.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import uuid
from pathlib import Path
from typing import Any

DURUMLAR = ("fikir", "onaylandi", "cekildi", "yayinlandi", "iptal")
DUZENLENEBILIR = {"durum", "tarih", "saat", "platform", "cekim_tamam", "sonuc", "baslik", "aciklama"}


def klasor() -> Path:
    if os.environ.get("WORKBENCH_REELS_DIR"):
        return Path(os.environ["WORKBENCH_REELS_DIR"]).expanduser()
    if os.environ.get("WORKBENCH_DATA"):
        return Path(os.environ["WORKBENCH_DATA"]).expanduser() / "03_Magaza" / "reels_takvimi"
    if os.environ.get("WORKBENCH_ROOT"):
        return Path(os.environ["WORKBENCH_ROOT"]).expanduser() / "veri" / "03_Magaza" / "reels_takvimi"
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return Path(os.environ.get("STUDIO_HOME") or data_home / "workbench-studio").expanduser() / "reels_takvimi"


@contextlib.contextmanager
def _kilit(k: Path):
    k.mkdir(parents=True, exist_ok=True)
    with open(k / ".kilit", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _oku(yol: Path, bos: Any) -> Any:
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return bos


def _yaz(yol: Path, veri: Any) -> None:
    gecici = yol.with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    gecici.replace(yol)


def oku(k: Path | None = None) -> dict[str, Any]:
    k = k or klasor()
    with _kilit(k):
        takvim = _oku(k / "takvim.json", {"fikirler": []})
        istekler = [i for i in _oku(k / "istekler.json", []) if i.get("durum") in ("bekliyor", "calisiyor")]
    takvim.setdefault("fikirler", [])
    takvim["fikirler"].sort(key=lambda f: (f.get("tarih") or "9999", f.get("saat") or ""))
    return {"fikirler": takvim["fikirler"], "istekler": istekler, "durumlar": list(DURUMLAR)}


def guncelle(fid: str, alanlar: dict[str, Any], k: Path | None = None) -> dict[str, Any]:
    k = k or klasor()
    bilinmeyen = set(alanlar) - DUZENLENEBILIR
    if bilinmeyen:
        raise ValueError(f"Düzenlenemez alan: {', '.join(sorted(bilinmeyen))}")
    if "durum" in alanlar and alanlar["durum"] not in DURUMLAR:
        raise ValueError("Geçersiz durum")
    if "tarih" in alanlar and alanlar["tarih"]:
        dt.date.fromisoformat(str(alanlar["tarih"]))
    with _kilit(k):
        takvim = _oku(k / "takvim.json", {"fikirler": []})
        for f in takvim.get("fikirler", []):
            if f.get("id") == fid:
                f.update(alanlar)
                f["guncellendi"] = dt.datetime.now().isoformat(timespec="seconds")
                _yaz(k / "takvim.json", takvim)
                return f
    raise KeyError(fid)


def not_ekle(fid: str, metin: str, k: Path | None = None) -> dict[str, Any]:
    metin = metin.strip()
    if not metin:
        raise ValueError("Not boş")
    k = k or klasor()
    with _kilit(k):
        takvim = _oku(k / "takvim.json", {"fikirler": []})
        for f in takvim.get("fikirler", []):
            if f.get("id") == fid:
                f.setdefault("notlar", []).append({"tarih": dt.datetime.now().isoformat(timespec="minutes"),
                                                   "kimden": "Patron", "metin": metin})
                _yaz(k / "takvim.json", takvim)
                return f
    raise KeyError(fid)


def istek_ekle(tur: str, metin: str = "", fid: str | None = None, adet: int = 7, k: Path | None = None) -> dict[str, Any]:
    """Claude'a iş: tur='yeni_fikirler' (adet, isteğe bağlı tema) ya da 'revize' (fid + Patron notu)."""
    if tur not in ("yeni_fikirler", "revize"):
        raise ValueError("Geçersiz istek türü")
    if tur == "revize" and (not fid or not metin.strip()):
        raise ValueError("Revize için fikir ve not gerekli")
    k = k or klasor()
    istek = {"id": uuid.uuid4().hex[:8], "tur": tur, "metin": metin.strip(), "fikir_id": fid,
             "adet": max(1, min(int(adet or 7), 14)), "durum": "bekliyor",
             "tarih": dt.datetime.now().isoformat(timespec="seconds")}
    with _kilit(k):
        istekler = _oku(k / "istekler.json", [])
        istekler.append(istek)
        _yaz(k / "istekler.json", istekler)
        if tur == "revize":
            takvim = _oku(k / "takvim.json", {"fikirler": []})
            for f in takvim.get("fikirler", []):
                if f.get("id") == fid:
                    f.setdefault("notlar", []).append({"tarih": istek["tarih"][:16], "kimden": "Patron",
                                                       "metin": f"Revize isteği: {istek['metin']}"})
            _yaz(k / "takvim.json", takvim)
    return istek
