"""OrcaSlicer CLI (optional) and a print-path quality report read from the sliced G-code.

``slice_3mf`` runs the local OrcaSlicer on a model.3mf; ``gcode_report`` reads a G-code file move by move (relative E,
M83) and sums filament per feature (;TYPE: comments), retractions, travel, colour changes and layers; ``check_3mf``
does both and turns the numbers into Turkish findings (what is wasted, what may print badly)."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

ORCA = os.environ.get("WORKBENCH_ORCA") or os.environ.get("MAKER_ORCA", "orcaslicer")
WORK = Path(os.environ.get("WORKBENCH_SLICE_DIR", Path.home() / ".cache" / "workbench-studio" / "slice"))  # flatpak/snap Orca sees $HOME only
_G = re.compile(r"^; total filament used \[g\] = ([\d.]+)", re.M)
_T = re.compile(r"^; estimated printing time \(normal mode\) = (.+)$", re.M)
_D = re.compile(r"^; filament_density: ([\d.]+)", re.M)
_DIA = re.compile(r"^; filament_diameter: ([\d.]+)", re.M)

FEATURE_TR = {"Outer wall": "Dış duvar", "Inner wall": "İç duvar", "Overhang wall": "Sarkan duvar", "Sparse infill": "Seyrek dolgu",
              "Internal solid infill": "İç katı dolgu", "Top surface": "Üst yüzey", "Bottom surface": "Alt yüzey",
              "Bridge": "Köprü", "Internal Bridge": "İç köprü", "Gap infill": "Boşluk dolgusu", "Support": "Destek",
              "Support interface": "Destek arayüzü", "Prime tower": "Kule (renk temizleme)", "Brim": "Kenar (brim)",
              "Skirt": "Etek", "Custom": "Başlangıç / bitiş", "Ironing": "Ütüleme"}


def available() -> bool:
    return shutil.which(ORCA) is not None


def gcode_stats(text: str) -> dict:
    g, t = _G.search(text), _T.search(text)
    return {"grams": float(g.group(1)) if g else None, "time": t.group(1).strip() if t else None}


def parse_duration(s: str | None) -> int | None:
    """'5h 52m 11s' / '1d 2h 3m' -> seconds."""
    if not s:
        return None
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    found = re.findall(r"(\d+)\s*([dhms])", s)
    return sum(int(n) * mult[u] for n, u in found) if found else None


def slice_3mf(path: Path | str, out_dir: Path | str, timeout: int = 900) -> list[dict]:
    """plate_<n>.gcode for every plate in ``out_dir``; returns per-plate {grams, time, gcode}. Raises RuntimeError."""
    if not available():
        raise RuntimeError("OrcaSlicer bulunamadı (WORKBENCH_ORCA ile yolunu verin)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([ORCA, "--slice", "0", "--outputdir", str(out_dir.resolve()), str(Path(path).resolve())],
                       capture_output=True, text=True, timeout=timeout)
    files = sorted(out_dir.glob("plate_*.gcode"), key=lambda f: int(re.findall(r"\d+", f.stem)[0]))
    if r.returncode != 0 or not files:
        msg = (r.stderr or r.stdout).strip()[-300:]
        res = out_dir / "result.json"
        if res.is_file():
            msg = json.loads(res.read_text()).get("error_string", msg)
        if "No such file" in msg or "not found" in msg:
            msg += " (flatpak/snap OrcaSlicer yalnızca ev klasörünü görür; dosya ve çıktı klasörü ev klasöründe olmalı)"
        raise RuntimeError(f"OrcaSlicer dilimleyemedi (kod {r.returncode}): {msg}")
    out = []
    for f in files:
        with f.open("rb") as fh:  # the stats block sits just before the config dump at the end
            fh.seek(max(0, f.stat().st_size - 600_000))
            tail = fh.read().decode("utf-8", errors="ignore")
        out.append({**gcode_stats(tail), "gcode": f.name})
    return out


def gcode_report(path: Path | str) -> dict:
    """Move-by-move totals of an OrcaSlicer G-code (relative extrusion)."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    dens = float(_D.search(text).group(1)) if _D.search(text) else 1.24
    dia = float(_DIA.search(text).group(1)) if _DIA.search(text) else 1.75
    g_per_mm = math.pi * (dia / 2) ** 2 * dens / 1000.0
    body = text.split("; EXECUTABLE_BLOCK_END")[0]
    feat: dict[str, float] = {}
    cur = "Custom"
    x = y = 0.0
    retracts = 0
    travel = 0.0
    tool_changes = 0
    layers = 0
    started_tool = None
    for line in body.splitlines():
        if not line:
            continue
        c = line[0]
        if c == ";":
            if line.startswith(";TYPE:"):
                cur = line[6:].strip()
            elif line.startswith(";LAYER_CHANGE"):
                layers += 1
            continue
        if c == "T" and line[1:2].isdigit():
            t = line.split()[0]
            if started_tool is None:
                started_tool = t
            elif t != started_tool:
                tool_changes += 1
                started_tool = t
            continue
        if c != "G" or not (line.startswith("G1 ") or line.startswith("G0 ") or line.startswith("G2 ") or line.startswith("G3 ")):
            continue
        nx, ny, e = x, y, 0.0
        for tok in line.split(";")[0].split()[1:]:
            k, v = tok[0], tok[1:]
            try:
                if k == "X":
                    nx = float(v)
                elif k == "Y":
                    ny = float(v)
                elif k == "E":
                    e = float(v)
            except ValueError:
                pass
        moved = (nx, ny) != (x, y) or line[1] in "23"
        if e > 0 and (moved or e > 1.5):  # a small E-only move is the un-retract after a retraction; a big one is a purge
            feat[cur] = feat.get(cur, 0.0) + e
        elif e < 0:
            retracts += 1
        elif (nx, ny) != (x, y):
            travel += math.hypot(nx - x, ny - y)
        x, y = nx, ny
    grams = {k: round(v * g_per_mm, 2) for k, v in sorted(feat.items(), key=lambda kv: -kv[1])}
    total = sum(grams.values()) or 1.0
    stats = gcode_stats(text[-600_000:])
    return {"grams_by_feature": grams, "share": {k: round(v / total, 4) for k, v in grams.items()},
            "grams_total": round(total, 1), "slicer_grams": stats["grams"], "time": stats["time"],
            "seconds": parse_duration(stats["time"]), "layers": layers, "retractions": retracts,
            "travel_m": round(travel / 1000, 1), "colour_changes": tool_changes}


def findings(rep: dict, warning: str = "") -> list[dict]:
    """Turkish verdicts from a report: level 'iyi' | 'dikkat' | 'sorun'."""
    s = rep["share"]
    out = []

    def add(level, text):
        out.append({"seviye": level, "mesaj": text})

    tower = s.get("Prime tower", 0) + s.get("Flush", 0)
    if tower > 0.25:
        add("dikkat", f"Filamentin %{tower * 100:.0f}'i renk temizleme kulesine gidiyor ({rep['colour_changes']} renk değişimi). "
                      "Renk sayısını ya da renkli katman sayısını azaltmak israfı düşürür.")
    elif tower > 0:
        add("iyi", f"Renk temizleme israfı makul: %{tower * 100:.0f} ({rep['colour_changes']} renk değişimi).")
    bridge = s.get("Bridge", 0)
    if bridge > 0.02:
        add("dikkat", f"Açık köprü oranı %{bridge * 100:.1f}: havada geçen çizgiler sarkabilir, alt yüzey pürüzlü olabilir.")
    over = s.get("Overhang wall", 0)
    if over > 0.02:
        add("dikkat", f"Sarkan duvar oranı %{over * 100:.1f}: eğimli kenarlarda sarkma görülebilir.")
    if s.get("Support", 0) + s.get("Support interface", 0) > 0:
        add("dikkat", "Destek kullanılıyor: destek temas eden yüzeyler daha pürüzlü çıkar, temizlik gerekir.")
    gap = s.get("Gap infill", 0)
    if gap > 0.03:
        add("dikkat", f"Boşluk dolgusu %{gap * 100:.1f}: çok ince bölgeler var (duvar genişliğinin altında); "
                      "bu yerler zayıf ya da eksik basılabilir.")
    walls = s.get("Outer wall", 0) + s.get("Inner wall", 0)
    if walls < 0.15 and s.get("Sparse infill", 0) > 0.4 and rep["grams_total"] > 20:
        add("dikkat", f"Duvar payı düşük (%{walls * 100:.0f}): parça kırılgan olabilir, duvar sayısını artırmayı düşünün.")
    if rep["travel_m"] > 0 and rep["retractions"] / max(rep["layers"], 1) > 60:
        add("dikkat", f"Katman başına {rep['retractions'] / max(rep['layers'], 1):.0f} geri çekme: çok sayıda küçük ada var, "
                      "ipliklenme (stringing) görülebilir.")
    if warning:
        add("sorun" if "floating" in warning.lower() else "dikkat", f"OrcaSlicer uyarısı: {warning}")
    if not any(f["seviye"] != "iyi" for f in out):
        add("iyi", "Baskı yolunda belirgin bir sorun görünmüyor.")
    return out


def check_3mf(path: Path | str, work_dir: Path | str | None = None, timeout: int = 900) -> dict:
    """Slice ``path`` with OrcaSlicer and report every plate: totals, feature shares and findings."""
    path = Path(path).resolve()
    work = Path(work_dir) if work_dir else WORK / re.sub(r"[^A-Za-z0-9_-]", "_", path.parent.name or "model")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    src = work / path.name
    shutil.copy2(path, src)  # Orca (flatpak/snap) may not see the original folder
    plates = slice_3mf(src, work, timeout)
    res = work / "result.json"
    warn = ""
    if res.is_file():
        info = json.loads(res.read_text())
        warn = " ".join(p.get("warning_message", "") for p in info.get("sliced_plates", []) if p.get("warning_message"))
    out = []
    for i, pl in enumerate(plates):
        rep = gcode_report(work / pl["gcode"])
        out.append({"plate": i + 1, **rep, "findings": findings(rep, warn if i == 0 else "")})
    return {"model": str(path), "plates": out, "work_dir": str(work)}


def report_text(check: dict) -> str:
    """Human-readable Turkish report."""
    lines = [f"Baskı yolu raporu: {check['model']}"]
    for pl in check["plates"]:
        lines.append(f"\nTabla {pl['plate']}: {pl['slicer_grams'] or pl['grams_total']} g, {pl['time']}, {pl['layers']} katman, "
                     f"{pl['colour_changes']} renk değişimi, {pl['retractions']} geri çekme, {pl['travel_m']} m boş gezinme")
        for k, g in pl["grams_by_feature"].items():
            lines.append(f"  {FEATURE_TR.get(k, k):<24} {g:8.1f} g  %{pl['share'][k] * 100:5.1f}")
        for f in pl["findings"]:
            mark = {"iyi": "✓", "dikkat": "!", "sorun": "✗"}[f["seviye"]]
            lines.append(f"  {mark} {f['mesaj']}")
    return "\n".join(lines) + "\n"
