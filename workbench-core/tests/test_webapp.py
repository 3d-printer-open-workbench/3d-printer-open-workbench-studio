import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench_core.webapp import Jobs, editor_app, output_links


def _app(tmp_path, run):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<title>Deneme {{VERSION}}</title><script src="/static/app.js"></script>', encoding="utf-8")
    (web / "app.js").write_text("1", encoding="utf-8")
    (web / "app.css").write_text("", encoding="utf-8")
    return editor_app(title="Deneme", version="9.9", web=web, out_dir=tmp_path / "out", preview_dir=tmp_path / "prev",
                      jobs=Jobs(), run=run, upload_ext={".svg"})


def _wait(c, jid):
    for _ in range(100):
        st = c.get(f"/api/jobs/{jid}").json()
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_page_jobs_files_and_safety(tmp_path):
    def run(kind, payload, jid, progress):
        progress("çalışıyor")
        if payload.get("fail"):
            raise ValueError("geçersiz değer")
        if payload.get("boom"):
            raise ZeroDivisionError
        d = tmp_path / "out" / "is1"
        (d / "parts").mkdir(parents=True, exist_ok=True)
        (d / "parts" / "a.stl").write_text("solid")
        (d / "model.3mf").write_text("x")
        return {"kind": kind, **output_links(tmp_path / "out", d, {"3mf": d / "model.3mf"})}

    with TestClient(_app(tmp_path, run)) as c:
        r = c.get("/")
        assert "Deneme 9.9" in r.text and "/static/app.js?v=" in r.text and r.headers["cache-control"] == "no-cache"
        st = _wait(c, c.post("/api/jobs", json={"kind": "make"}).json()["id"])
        assert st["status"] == "done" and st["result"]["files"]["3mf"] == "/files/is1/model.3mf"
        assert st["result"]["stls"] == ["/files/is1/parts/a.stl"] and c.get("/files/is1/model.3mf").status_code == 200
        assert _wait(c, c.post("/api/jobs", json={"fail": 1}).json()["id"])["error"] == "geçersiz değer"
        st = _wait(c, c.post("/api/jobs", json={"boom": 1}).json()["id"])
        assert st["status"] == "error" and st["error"].startswith("Beklenmeyen hata")
        assert c.get("/api/jobs/yok").status_code == 404
        assert c.get("/files/../../etc/passwd").status_code == 404 and c.get("/preview/../x.glb").status_code == 404
        assert c.post("/api/open", json={"path": str(Path.home())}).status_code == 404  # only the output folder
        assert c.post("/api/upload?name=x.exe", content=b"MZ").status_code == 400
        up = c.post("/api/upload?name=logo.svg", content=b"<svg/>").json()
        assert Path(up["path"]).read_bytes() == b"<svg/>" and Path(up["path"]).parent == tmp_path / "uploads"
