"""Studio window (FastAPI): one editor for every product (home screen, numbered steps, 3D preview, filament strip),
built on the shared Workbench editor server; every program's jobs run inside Studio (studio.products). One MCP server
at /mcp. Start with ``studio ui``."""
from __future__ import annotations

import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from . import __version__, apps, mcp_tools

WEB = Path(__file__).with_name("web")
DEFAULT_PORT = 7870
PID_FILE = apps.STATE_DIR / "studio.pid"
UPLOAD_EXT = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gpx"}


def create_app() -> FastAPI:
    from mcp.server.fastmcp import FastMCP
    from workbench_core.webapp import Jobs, editor_app

    from . import products

    mcp = FastMCP("workbench-studio", stateless_http=True)
    mcp.settings.streamable_http_path = "/"
    mcp_tools.register(mcp)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    jobs = Jobs()
    apps.WORK_ROOT.mkdir(parents=True, exist_ok=True)
    app = editor_app(title=apps.TITLE, version=__version__, web=WEB, out_dir=apps.WORK_ROOT,
                     preview_dir=products.PREVIEW_DIR, jobs=jobs, run=products.run, validate=products.validate,
                     upload_ext=UPLOAD_EXT, lifespan=lifespan)
    app.mount("/mcp", mcp_app)

    @app.get("/api/config")
    def config():
        return {"version": __version__, **products.config()}

    @app.get("/api/recent")
    def recent():
        return products.recent()

    from fastapi.responses import FileResponse

    from . import kartela

    @app.get("/kartela")
    def kartela_sayfasi():
        return FileResponse(WEB / "kartela.html", media_type="text/html")

    @app.get("/api/kartela")
    def kartela_oku():
        return kartela.oku()

    @app.put("/api/kartela/{indeks}")
    def kartela_kaydet(indeks: int, govde: dict):
        try:
            return kartela.kaydet(indeks, str(govde.get("hex") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/filaments")
    def get_filaments():
        return products.filaments()

    @app.put("/api/filaments")
    def put_filaments(items: list[dict]):
        try:
            return products.save_filaments(items)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/geocode")
    def geocode(q: str):
        from topo import data, tools

        try:
            return tools.find_place(q)
        except data.DataError as e:
            raise HTTPException(502, str(e))

    @app.get("/api/routes")
    def routes(q: str):
        from topo import data, tools

        try:
            return tools.find_route(q)
        except data.DataError as e:
            raise HTTPException(502, str(e))

    @app.post("/api/gpx")
    def gpx(payload: dict):
        """A GPX file uploaded with /api/upload -> its name, track points (for the outline) and bbox."""
        from topo import data

        p = Path(payload.get("path", ""))
        if not p.is_file() or p.suffix.lower() != ".gpx":
            raise HTTPException(400, "GPX dosyası yok")
        try:
            name, segs = data.parse_gpx(p)
        except Exception as e:
            raise HTTPException(400, f"GPX okunamadı: {e}")
        return {"path": str(p), "name": name, "points": sum(len(s) for s in segs)}

    @app.get("/api/logo-colors")
    def logo_colors(path: str):
        """Colours of an uploaded logo as Glow sees them (at most 4), for the per-colour editor."""
        from glow.form import detect_logo_colors

        p = Path(path).resolve()
        if p.parent != (products.PREVIEW_DIR.parent / "uploads").resolve() or not p.is_file():
            raise HTTPException(404, "dosya yok")
        try:
            return {"colors": detect_logo_colors(p)}
        except Exception as e:
            raise HTTPException(400, f"Logo okunamadı: {e}")

    @app.get("/api/color-name")
    def color_name(hex: str):
        from workbench_core.colorlib import color_code

        try:
            c = color_code(hex)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"hex": c["hex"], "text": c["text"], "ral": f"RAL {c['ral']['code']} {c['ral']['name']}"}

    # ---- Glow hardware catalogue (LED strips, controllers, diffusers): the old "Donanım" tab
    HW_KINDS = ("leds", "controllers", "diffusers")

    @app.get("/api/hardware")
    def hardware():
        from glow import hwedit

        raw = hwedit.load_raw()
        return {"rows": hwedit.to_rows(raw), "user": hwedit.user_path().is_file(), "path": str(hwedit.user_path()),
                "cols": {"leds": hwedit.LED_COLS, "controllers": hwedit.CTRL_COLS, "diffusers": hwedit.DIFF_COLS},
                "new": {k: hwedit.new_row(k, []) for k in HW_KINDS}}

    def _hw_raw(payload: dict) -> dict:
        from glow import hwedit

        rows = payload.get("rows") or {}
        if set(rows) != set(HW_KINDS):
            raise HTTPException(400, "LED, kontrolcü ve difüzör tabloları gerekli")
        try:
            return hwedit.from_rows(rows, hwedit.load_raw())
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/hardware/validate")
    def hardware_validate(payload: dict):
        from glow import hwedit

        return {"errors": hwedit.validate_raw(_hw_raw(payload))}

    @app.put("/api/hardware")
    def hardware_save(payload: dict):
        from glow import hwedit

        raw = _hw_raw(payload)
        errs = hwedit.validate_raw(raw)
        if errs:
            raise HTTPException(400, "Kaydedilmedi: " + "; ".join(errs))
        path = hwedit.save_user(raw)
        products.reset()  # LED / controller / diffuser choices of the light box forms
        return {"path": str(path)}

    @app.delete("/api/hardware")
    def hardware_reset():
        from glow import hwedit

        existed = hwedit.reset_user()
        products.reset()
        return {"reset": existed}

    @app.post("/api/check")
    def check(payload: dict):
        """Slice a finished job with OrcaSlicer and report its print paths (workbench_core.tools.print_check)."""
        from workbench_core.tools import print_check

        p = Path(payload.get("out_dir", "")).resolve()
        if not p.is_dir() or apps.WORK_ROOT.resolve() not in p.parents:
            raise HTTPException(404, "iş klasörü yok")
        return {"id": jobs.start("check", lambda jid, progress: print_check(str(p)))}

    @app.get("/api/catalog")
    def catalog():  # kept for older clients / scripts
        return {"version": __version__, "items": apps.catalogue(),
                "apps": {k: {"label": a.label} for k, a in apps.APPS.items()}}

    return app


def launch(host: str = "127.0.0.1", port: int | None = None, open_browser: bool = True) -> int:
    import threading
    import webbrowser

    import uvicorn

    port = port or int(os.environ.get("STUDIO_PORT", DEFAULT_PORT))
    with socket.socket() as s:
        if s.connect_ex((host, port)) == 0:
            print(f"HATA: {port} numaralı kapı kullanımda (Studio zaten açık olabilir: studio open). STUDIO_PORT ile değiştirin.")
            return 1
    apps.STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    url = f"http://{host}:{port}"
    print(f"{apps.TITLE}: {url}  (MCP: {url}/mcp/)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0
