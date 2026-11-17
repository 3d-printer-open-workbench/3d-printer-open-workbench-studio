import glob
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from maker.generators import GENERATORS
from studio import apps, cli, server

ROOT = Path(__file__).resolve().parents[1]


def test_catalogue_has_every_product():
    items = apps.catalogue()
    ids = {i["id"] for i in items}
    assert {"kaligraf_flat", "kaligraf_letters", "glow_rect", "topo_rota", "topo_sehir", "topo_ani", "topo_arazi"} <= ids
    for k, g in GENERATORS.items():
        if g.status == "ready" and k != "plate":
            assert f"maker_{k}" in ids
    assert all(i["app"] in apps.APPS for i in items)


@pytest.mark.parametrize("path", sorted(glob.glob(str(ROOT / "workbench-*/examples/*.yaml"))))
def test_every_example_job_finds_its_program(path):
    prog = cli.program_of(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    assert prog == Path(path).parts[-3].removeprefix("workbench-")


def test_unknown_job_is_refused():
    with pytest.raises(ValueError, match="tanınmadı"):
        cli.program_of({"foo": 1})


def test_window_api_and_mcp_tools():
    with TestClient(server.create_app()) as c:
        assert "Open Workbench Studio" in c.get("/").text
        cat = c.get("/api/catalog").json()
        assert len(cat["items"]) > 20 and set(cat["apps"]) == {"kaligraf", "glow", "topo", "maker"}
    from mcp.server.fastmcp import FastMCP

    from studio import mcp_tools

    names = mcp_tools.register(FastMCP("t"))
    assert {"make", "job_summary", "color_info", "save_prompt", "maker_list_generators", "topo_find_place"} <= set(names)
    assert not any(n.endswith("color_info") and n != "color_info" for n in names)  # one shared tool, not one per program
    assert len(names) == len(set(names))


def test_studio_make_maker_job(tmp_path):
    assert cli.main(["make", str(ROOT / "workbench-maker/examples/kupon.yaml"), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "kupon_petg05" / "model.3mf").is_file()


def test_job_summary_recognises_every_program(tmp_path):
    from studio.mcp_tools import program_of_job_dir

    assert program_of_job_dir({"app": "workbench-maker"}) == "maker"
    assert program_of_job_dir({"tool": "Workbench - Topo 1.2.0"}) == "topo"
    assert program_of_job_dir({"bom": {}, "power": {}}) == "glow"
    assert program_of_job_dir({"inputs": {"mode": "flat"}}) == "kaligraf"


def test_kontrol_missing_model(tmp_path, capsys):
    from studio import cli

    assert cli.main(["kontrol", str(tmp_path / "yok")]) == 2
    assert "model.3mf bulunamadı" in capsys.readouterr().err


def test_print_check_tool_registered():
    from studio import mcp_tools

    class M:
        def __init__(self):
            self.names = []

        def tool(self, name=None, description=None):
            self.names.append(name)
            return lambda fn: fn

    m = M()
    mcp_tools.register(m)
    assert "print_check" in m.names


# --------------------------------------------------------------------------- the one editor (phase 2)
import time  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    from studio import products

    monkeypatch.setattr(apps, "WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(products, "WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(products, "PREVIEW_DIR", tmp_path / "preview")
    monkeypatch.setattr(products, "FILAMENT_FILE", tmp_path / "fil.json")
    monkeypatch.setattr(products, "STATE_DIR", tmp_path)
    with TestClient(server.create_app()) as c:
        yield c


def _wait(c, jid, limit=120):
    t = time.time()
    while time.time() - t < limit:
        st = c.get(f"/api/jobs/{jid}").json()
        if st["status"] != "running":
            return st
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_config_has_every_family_and_product(studio):
    cfg = studio.get("/api/config").json()
    fams = {f["key"] for f in cfg["families"]}
    assert fams == {"yazi", "isik", "harita", "atolye"}
    ids = {p["id"] for p in cfg["products"]}
    assert {"kaligraf_flat", "kaligraf_letters", "glow_rect", "glow_round", "glow_contour", "topo_arazi", "topo_rota"} <= ids
    assert len([p for p in cfg["products"] if p["family"] == "atolye"]) >= 10
    for p in cfg["products"]:
        assert p["family"] in fams and p["params"], p["id"]
        for q in p["params"]:
            assert {"key", "label", "type", "default", "section", "show_if"} <= set(q), (p["id"], q)
            for k in q["show_if"]:
                assert k in {x["key"] for x in p["params"]}, (p["id"], q["key"], k)
    assert cfg["fonts"] and cfg["palette"]
    assert studio.get("/static/img/harita.png").status_code == 200


def test_preview_and_make_through_one_api(studio):
    cfg = studio.get("/api/config").json()
    p = next(x for x in cfg["products"] if x["id"] == "maker_keychain")
    values = {q["key"]: q["default"] for q in p["params"]}
    st = _wait(studio, studio.post("/api/jobs", json={"kind": "preview", "product": p["id"], "values": values}).json()["id"])
    assert st["status"] == "done", st
    r = st["result"]
    assert studio.get(r["png"]).status_code == 200 and studio.get(r["glb"]).status_code == 200
    assert r["filaments"] and all(f["color"].startswith("#") and f["roles"] for f in r["filaments"])
    st = _wait(studio, studio.post("/api/jobs", json={"kind": "make", "product": p["id"], "values": values}).json()["id"])
    assert st["status"] == "done", st
    assert studio.get(st["result"]["files"]["3mf"]).status_code == 200
    rec = studio.get("/api/recent").json()
    assert rec and rec[0]["product"] == "maker_keychain" and rec[0]["values"] == values and rec[0]["family"] == "atolye"
    assert studio.post("/api/jobs", json={"kind": "preview", "product": "yok", "values": {}}).status_code == 400


def test_kaligraf_letters_preview_summary(studio):
    st = _wait(studio, studio.post("/api/jobs", json={"kind": "preview", "product": "kaligraf_letters",
                                                      "values": {"text": "Ayşe", "font": "Pacifico", "letter_height_cm": 12,
                                                                 "depth_mm": "15", "letter_colors": ["#C0392B"], "face_color": "",
                                                                 "mounting": ["tape"], "letter_joints": True}}).json()["id"])
    assert st["status"] == "done", st
    r = st["result"]
    assert [f["color"] for f in r["filaments"]] == ["#C0392B"] and r["estimate"]["grams"] > 0 and r["estimate"]["text"]


def test_place_is_required_for_maps(studio):
    st = _wait(studio, studio.post("/api/jobs", json={"kind": "preview", "product": "topo_arazi", "values": {}}).json()["id"])
    assert st["status"] == "error" and "yer" in st["error"]


def test_filaments_round_trip(studio):
    assert len(studio.get("/api/filaments").json()) == 4
    items = [{"color": "#3f8f3a", "name": "Yeşil PLA", "grams": 640}]
    assert studio.put("/api/filaments", json=items).json() == [{"slot": 1, "color": "#3F8F3A", "name": "Yeşil PLA", "grams": 640}]
    assert studio.get("/api/filaments").json()[0]["color"] == "#3F8F3A"
    assert studio.put("/api/filaments", json=[{"color": "yeşil"}]).status_code == 400


def test_check_only_inside_work_root(studio, tmp_path):
    assert studio.post("/api/check", json={"out_dir": str(tmp_path)}).status_code == 404


def test_glow_logo_colours_holes_and_bom(studio, tmp_path):
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (400, 240), "white")
    d = ImageDraw.Draw(im)
    d.ellipse((20, 20, 220, 220), fill="#C0392B")
    d.rectangle((240, 60, 380, 180), fill="#1F6FB2")
    f = tmp_path / "logo.png"
    im.save(f)
    up = studio.post("/api/upload?name=logo.png", content=f.read_bytes()).json()
    cols = studio.get("/api/logo-colors", params={"path": up["path"]}).json()["colors"]
    assert len(cols) == 2 and "#C0392B" in cols  # quantised logo colours (blue may come back a step off)
    assert studio.get("/api/logo-colors", params={"path": str(f)}).status_code == 404  # only uploads
    new = ["#2E7D32" if c == "#C0392B" else c for c in cols]
    values = {"logo": up["path"], "logo_map": {"orig": cols, "new": new, "light": [c for c in cols if c != "#C0392B"]},
              "holes": [{"type": "daire", "w": 6, "h": 6, "x": 40, "y": 0}], "width_r": 20, "frame_color": "#1E1E1E"}
    st = _wait(studio, studio.post("/api/jobs", json={"kind": "preview", "product": "glow_rect", "values": values}).json()["id"], 300)
    assert st["status"] == "done", st
    assert "#2E7D32" in {x["color"] for x in st["result"]["filaments"]}  # the recoloured logo colour is printed
    st = _wait(studio, studio.post("/api/jobs", json={"kind": "make", "product": "glow_rect", "values": values}).json()["id"], 600)
    assert st["status"] == "done", st
    assert studio.get(st["result"]["files"]["bom"]).status_code == 200


def test_color_name(studio):
    r = studio.get("/api/color-name", params={"hex": "#C0392B"}).json()
    assert r["hex"] == "#C0392B" and r["ral"].startswith("RAL")


def test_hardware_catalogue_api(studio, tmp_path, monkeypatch):
    from glow import hardware

    monkeypatch.delenv("GLOW_HARDWARE", raising=False)
    monkeypatch.setattr(hardware, "USER_HARDWARE", tmp_path / "hardware.yaml")  # never touch the real user catalogue
    hardware.default_hardware.cache_clear()
    hw = studio.get("/api/hardware").json()
    assert set(hw["rows"]) == {"leds", "controllers", "diffusers"} and hw["user"] is False
    assert len(hw["cols"]["leds"]) == len(hw["rows"]["leds"][0])
    rows = hw["rows"]
    rows["leds"][0][1] = "Deneme LED adı"
    assert studio.post("/api/hardware/validate", json={"rows": rows}).json()["errors"] == []
    assert studio.put("/api/hardware", json={"rows": rows}).status_code == 200
    cfg = studio.get("/api/config").json()
    leds = next(q for q in next(p for p in cfg["products"] if p["id"] == "glow_rect")["params"] if q["key"] == "led")
    assert "Deneme LED adı" in [l for _, l in leds["options"]]  # the forms see the saved catalogue
    bad = {k: [list(r) for r in v] for k, v in rows.items()}
    bad["leds"][0][0] = "Bozuk ID!"
    assert studio.put("/api/hardware", json={"rows": bad}).status_code == 400
    assert studio.delete("/api/hardware").json()["reset"] is True
    cfg = studio.get("/api/config").json()
    leds = next(q for q in next(p for p in cfg["products"] if p["id"] == "glow_rect")["params"] if q["key"] == "led")
    assert "Deneme LED adı" not in [l for _, l in leds["options"]]
