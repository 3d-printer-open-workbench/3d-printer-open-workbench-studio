"""Live end-to-end check with real data (network): `python scripts/canli_test.py [çıktı_klasörü]`.

Runs every mode on real places/routes, validates each 3MF (structure, filament slots, plate fit,
watertight parts) and writes RAPOR.md + a contact sheet of the renders.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from topo import data, tools  # noqa: E402
from topo.export3mf import BED, PLATE_MAX_MONO, PLATE_MAX_MULTI  # noqa: E402
from topo.job import Job  # noqa: E402
from topo.output import run_job  # noqa: E402

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}

CASES = [
    ("Şehir · Alsancak (Klasik)", dict(name="qa_sehir_alsancak", mode="sehir", place="Alsancak, Konak, İzmir", width_km=1.5, size_mm=200)),
    ("Şehir · Kadifekale (Gri, arazi açık)", dict(name="qa_sehir_kadifekale", mode="sehir", place="Kadifekale, Konak, İzmir", width_km=1.6,
                                                   size_mm=200, theme="Gri", layers={"terrain": True})),
    ("Anı · Kordon kalp, 2 renkli işaret", dict(name="qa_ani_kordon", mode="ani", lat=38.4386, lon=27.1413, width_km=1.6, size_mm=180,
                                               title="Ayşe & Ali", subtitle="14.02.2026",
                                               markers=[{"lat": 38.4375, "lon": 27.1418, "kind": "heart", "color": "#C9184A"},
                                                        {"lat": 38.4400, "lon": 27.1440, "kind": "star", "color": "#C9184A"}])),
    ("Rota · örnek GPX", dict(name="qa_rota_gpx", mode="rota", gpx=str(ROOT / "examples" / "ornek_rota.gpx"), size_mm=200, duration="4 sa 10 dk")),
    ("Rota · Likya Yolu (OSM)", dict(name="qa_rota_likya", mode="rota", osm_relation=51855, size_mm=230, margin_pct=5, title="LİKYA YOLU")),
    ("Büyük · Alsancak 40 cm (parçalı)", dict(name="qa_buyuk_alsancak", mode="sehir", place="Alsancak, Konak, İzmir", width_km=3.0, size_mm=400)),
]


def check_3mf(path: Path, n_colors: int) -> list[str]:
    """Problems found in a 3MF written by Topo (empty list = OK)."""
    bad = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for need in ("[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model", "Metadata/model_settings.config", "Metadata/project_settings.config"):
            if need not in names:
                bad.append(f"eksik dosya: {need}")
        model = ET.fromstring(z.read("3D/3dmodel.model"))
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
        proj = json.loads(z.read("Metadata/project_settings.config"))
    if len(proj.get("filament_colour", [])) != n_colors:
        bad.append(f"filament_colour {len(proj.get('filament_colour', []))} != {n_colors}")
    for k, v in proj.items():  # Orca crashes when per-filament vectors disagree in length
        if isinstance(v, list) and k.startswith("filament_") and k not in ("filament_colour",) and len(v) not in (1, n_colors) and "matrix" not in k and "vector" not in k:
            bad.append(f"{k}: {len(v)} değer")
    objs = {o.get("id"): o for o in model.findall("m:resources/m:object", NS)}
    meshes = {}
    for oid, o in objs.items():
        mesh = o.find("m:mesh", NS)
        if mesh is not None:
            v = np.array([[float(x.get(a)) for a in "xyz"] for x in mesh.findall("m:vertices/m:vertex", NS)])
            f = np.array([[int(t.get(a)) for a in ("v1", "v2", "v3")] for t in mesh.findall("m:triangles/m:triangle", NS)])
            if len(f) == 0 or f.max() >= len(v):
                bad.append(f"nesne {oid}: bozuk üçgen indeksi")
                continue
            meshes[oid] = trimesh.Trimesh(v, f, process=False)  # 3MF keeps vertex indices: check that topology
    builds = model.findall("m:build/m:item", NS)
    for o in cfg.findall("object"):
        for p in o.findall("part"):
            ext = int({m.get("key"): m.get("value") for m in p.findall("metadata")}["extruder"])
            if not 1 <= ext <= n_colors:
                bad.append(f"parça {p.get('id')}: filament {ext}")
    for it in builds:
        comp = objs[it.get("objectid")].findall("m:components/m:component", NS)
        vs = np.vstack([meshes[c.get("objectid")].vertices for c in comp if c.get("objectid") in meshes])
        ext = np.ptp(vs[:, :2], axis=0)
        lim = PLATE_MAX_MULTI if n_colors > 1 else PLATE_MAX_MONO
        if ext[0] > lim[0] + 0.5 or ext[1] > lim[1] + 0.5:
            bad.append(f"tabla taşması: {ext[0]:.0f}x{ext[1]:.0f} mm > {lim[0]:.0f}x{lim[1]:.0f}")
        t = [float(x) for x in it.get("transform").split()]
        ox, oy = t[9], t[10]
        pl = round(ox / (BED[0] * 1.2)), round(-oy / (BED[1] * 1.2))
        lx, ly = ox - pl[0] * BED[0] * 1.2, oy + pl[1] * BED[1] * 1.2
        if not (0 <= lx - ext[0] / 2 and lx + ext[0] / 2 <= BED[0] and 0 <= ly - ext[1] / 2 and ly + ext[1] / 2 <= BED[1]):
            bad.append(f"nesne tabla dışında konumlanmış ({lx:.0f},{ly:.0f})")
    for oid, m in meshes.items():
        if not m.is_watertight:
            bad.append(f"nesne {oid}: kapalı değil (watertight değil)")
        else:  # STL readers merge vertices by position: count edges that would then touch (slicers auto-fix these)
            mm = trimesh.Trimesh(m.vertices, m.faces, process=True)
            if not mm.is_watertight:
                from collections import Counter

                n = sum(1 for v in Counter(map(tuple, mm.edges_sorted)).values() if v != 2)
                if n > 20:
                    bad.append(f"nesne {oid}: STL'de {n} temas kenarı")
        if m.volume <= 0:
            bad.append(f"nesne {oid}: hacim {m.volume:.1f}")
    return bad


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    lines = ["# Topo canlı test raporu", "", f"Tarih: {time.strftime('%Y-%m-%d %H:%M')}", ""]
    ok_all = True
    # data sources
    lines += ["## Veri kaynakları", ""]
    for label, fn in [("Yer arama (Nominatim)", lambda: tools.find_place("Alsancak, İzmir")[0]["name"][:60]),
                      ("Rota arama: Likya Yolu", lambda: tools.find_route("Likya Yolu")[0]),
                      ("Rota arama: Karia Yolu", lambda: tools.find_route("Karia Yolu")[0]),
                      ("Rota arama: Frig Yolu", lambda: tools.find_route("Frig Yolu")[0]),
                      ("Rota arama: Aziz Pavlus Yolu", lambda: tools.find_route("Aziz Pavlus Yolu")[0])]:
        t = time.time()
        try:
            r = fn()
            lines.append(f"- ✅ {label}: {r} ({time.time() - t:.1f} sn)")
        except Exception as e:
            ok_all = False
            lines.append(f"- ❌ {label}: {e}")
    lines += ["", "## Modeller", "", "| Test | Sonuç | Boyut (cm) | Ölçek | Tabla | Filament | Tahmin | Süre | Not |", "|---|---|---|---|---|---|---|---|---|"]
    thumbs = []
    for label, d in CASES:
        t = time.time()
        try:
            r = run_job(Job.from_dict(d), out)
            dd = r.data
            probs = check_3mf(r.files["3mf"], len(dd["filaments"]))
            o = dd["overall_mm"]
            res = "✅" if not probs else "❌ " + "; ".join(probs[:3])
            ok_all &= not probs
            fil = " ".join(f["color"] for f in dd["filaments"])
            note = "; ".join(w[:70] for w in dd["warnings"])
            lines.append(f"| {label} | {res} | {o['width'] / 10:.1f}×{o['depth'] / 10:.1f}×{o['height'] / 10:.1f} | {dd['scale']} | {dd['tiles']} | {fil} | "
                         f"{dd['estimate']['grams_total']} g, {dd['estimate']['text']} | {time.time() - t:.0f} sn | {note} |")
            thumbs.append((label, r.files["render_34"]))
        except Exception as e:
            ok_all = False
            lines.append(f"| {label} | ❌ {type(e).__name__}: {str(e)[:120]} | | | | | | {time.time() - t:.0f} sn | |")
            traceback.print_exc()
    # contact sheet
    if thumbs:
        W = 560
        tiles = []
        for label, p in thumbs:
            im = Image.open(p).convert("RGB")
            im.thumbnail((W, W))
            c = Image.new("RGB", (W, im.height + 34), (247, 240, 230))
            c.paste(im, ((W - im.width) // 2, 34))
            from PIL import ImageFont

            from topo.geom import default_font

            ImageDraw.Draw(c).text((10, 8), label, fill=(58, 46, 40), font=ImageFont.truetype(str(default_font()), 18))
            tiles.append(c)
        cols = 2
        rows = (len(tiles) + 1) // cols
        h = max(t.height for t in tiles)
        sheet = Image.new("RGB", (W * cols, h * rows), (247, 240, 230))
        for i, tl in enumerate(tiles):
            sheet.paste(tl, ((i % cols) * W, (i // cols) * h))
        sheet.save(out / "ozet.png")
        lines += ["", "Görseller: `ozet.png`"]
    lines += ["", "**Genel sonuç: " + ("TÜM TESTLER GEÇTİ" if ok_all else "SORUN VAR") + "**"]
    (out / "RAPOR.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/_canli_test")))
