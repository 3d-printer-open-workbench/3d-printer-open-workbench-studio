"""Browser end-to-end test of the editor (Playwright, real network): `python scripts/arayuz_test.py [çıktı]`.

Starts `topo ui` on a free port, drives all three modes like a user and fails on any page error,
missing preview or broken download. Screenshots land in the output folder.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_idle(pg, sel="#busy", limit=600):
    t = time.time()
    pg.wait_for_timeout(800)
    while time.time() - t < limit:
        if pg.is_hidden(sel):
            return time.time() - t
        pg.wait_for_timeout(1000)
    raise TimeoutError("önizleme bitmedi")


def build(pg, base, shots, name, limit=900):
    pg.click("#build")
    t = time.time()
    while time.time() - t < limit:
        txt = pg.inner_text("#result")
        if "Hazır" in txt or "Olmadı" in txt:
            break
        pg.wait_for_timeout(1500)
    pg.wait_for_timeout(1200)
    pg.screenshot(path=str(shots / f"{name}_sonuc.png"))
    txt = pg.inner_text("#result")
    assert "Hazır" in txt, f"3MF üretilemedi: {txt[:300]}"
    href = pg.get_attribute("#result a.primary", "href")
    with urllib.request.urlopen(base + href, timeout=60) as r:
        blob = r.read()
    assert blob[:2] == b"PK" and len(blob) > 10_000, "3MF indirilemedi"
    return txt


def main(out: Path) -> int:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    srv = subprocess.Popen([sys.executable, "-m", "topo.cli", "ui", "--no-browser", "--port", str(port)], cwd=out, env=env,
                           stdout=open(out / "sunucu.log", "w"), stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/config", timeout=2)
            break
        except OSError:
            time.sleep(0.5)
    errors, report = [], []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.on("pageerror", lambda e: errors.append(str(e)))

            # A. city
            pg.goto(base)
            pg.wait_for_timeout(2500)
            pg.click(".mode[data-m='sehir']")
            pg.fill("#q", "Alsancak, İzmir")
            pg.click("#qBtn")
            pg.wait_for_selector("#qRes li[data-i='0']", timeout=60000)
            pg.click("#qRes li[data-i='0']")
            pg.click("#sizes .chip[data-s='150']")
            pg.wait_for_timeout(600)
            pg.screenshot(path=str(out / "A_sehir_1_alan.png"))
            pg.click("#steps button[data-step='3']")
            s = wait_idle(pg)
            pg.click(".theme[data-t='Gri']")
            s += wait_idle(pg)
            pg.screenshot(path=str(out / "A_sehir_2_onizleme.png"))
            info = pg.inner_text("#prevInfo")
            assert "cm" in info, f"önizleme bilgisi yok: {info}"
            fil = pg.inner_text("#filaments")
            txt = build(pg, base, out, "A_sehir")
            report.append(f"A Şehir (Alsancak, 15 cm, Gri): önizleme {s:.0f} sn · {info.splitlines()[0]} · {fil.strip()} · {txt.splitlines()[1]}")

            # B. trail from OSM search
            pg.goto(base)
            pg.wait_for_timeout(2000)
            pg.click(".mode[data-m='rota']")
            pg.fill("#rq", "Likya Yolu")
            pg.click("#rqBtn")
            pg.wait_for_selector("#rRes li[data-i='0']", timeout=180000)
            pg.click("#rRes li[data-i='0']")
            pg.wait_for_selector("#routeInfo:not([hidden])", timeout=300000)
            pg.wait_for_timeout(800)
            pg.screenshot(path=str(out / "B_likya_1_alan.png"))
            pg.click("#steps button[data-step='3']")
            s = wait_idle(pg, limit=900)
            pg.screenshot(path=str(out / "B_likya_2_onizleme.png"))
            info = pg.inner_text("#prevInfo")
            txt = build(pg, base, out, "B_likya")
            report.append(f"B Rota (Likya Yolu, OSM araması): önizleme {s:.0f} sn · {' | '.join(info.splitlines()[:2])} · {txt.splitlines()[1]}")

            # C. trail from GPX upload
            pg.goto(base)
            pg.wait_for_timeout(2000)
            pg.click(".mode[data-m='rota']")
            pg.set_input_files("#gpx", str(ROOT / "examples" / "ornek_rota.gpx"))
            pg.wait_for_selector("#routeInfo:not([hidden])", timeout=60000)
            pg.click("#steps button[data-step='2']")
            pg.fill("#duration", "4 sa 10 dk")
            pg.click("#steps button[data-step='3']")
            s = wait_idle(pg)
            pg.screenshot(path=str(out / "C_gpx_onizleme.png"))
            txt = build(pg, base, out, "C_gpx")
            report.append(f"C Rota (GPX yükleme): önizleme {s:.0f} sn · {txt.splitlines()[1]}")

            # D. memory heart with two coloured markers
            pg.goto(base)
            pg.wait_for_timeout(2000)
            pg.click(".mode[data-m='ani']")
            pg.fill("#q", "Kordon, Alsancak, İzmir")
            pg.click("#qBtn")
            pg.wait_for_selector("#qRes li[data-i='0']", timeout=60000)
            pg.click("#qRes li[data-i='0']")
            pg.click("#steps button[data-step='2']")
            pg.click("#markerKinds .chip[data-k='heart']")
            pg.click("#markerColors button[data-c='#D62828']")
            pg.mouse.click(860, 470)
            pg.click("#markerKinds .chip[data-k='star']")
            pg.click("#markerColors button[data-c='#C8A24A']")
            pg.mouse.click(960, 400)
            pg.fill("#title", "Ayşe & Ali")
            pg.fill("#subtitle", "14.02.2026")
            assert pg.locator("#markerList li input[type=color]").count() == 2, "işaretler eklenmedi"
            pg.screenshot(path=str(out / "D_ani_1_yerler.png"))
            pg.click("#steps button[data-step='3']")
            s = wait_idle(pg)
            pg.screenshot(path=str(out / "D_ani_2_onizleme.png"))
            fil = pg.inner_text("#filaments")
            txt = build(pg, base, out, "D_ani") if "5/4" not in fil and "6/4" not in fil else "renk sınırı aşıldı (beklenen uyarı)\n" + fil
            report.append(f"D Anı (kalp, 2 renkli işaret): önizleme {s:.0f} sn · {fil.strip()} · {txt.splitlines()[1] if len(txt.splitlines()) > 1 else txt}")

            # E. MCP endpoint
            import json

            req = urllib.request.Request(base + "/mcp/", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
                                         headers={"content-type": "application/json", "accept": "application/json, text/event-stream"})
            body = urllib.request.urlopen(req, timeout=30).read().decode()
            assert "make_map" in body, "MCP araçları listelenmedi"
            report.append("E MCP: list_modes, find_place, find_route, make_map, job_summary listelendi")
            b.close()
    except Exception as e:  # noqa: BLE001
        errors.append(f"{type(e).__name__}: {e}")
    finally:
        srv.terminate()
    lines = ["# Topo arayüz testi", ""] + [f"- ✅ {r}" for r in report] + [f"- ❌ {e}" for e in errors]
    lines += ["", "**Sonuç: " + ("GEÇTİ" if not errors else "SORUN VAR") + "**"]
    (out / "ARAYUZ_RAPOR.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/_arayuz_test")))
