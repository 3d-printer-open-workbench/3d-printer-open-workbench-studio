"""The editor server every Workbench web editor shares (Maker, Topo): page + static files that never go stale,
background jobs with progress, previews, output files, uploads, opening the output folder.

A program gives its own preview / make functions and adds its own routes (``/api/config`` ...) to the returned app."""
from __future__ import annotations

import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

UPLOAD_MAX = 20 * 1024 * 1024


class Jobs:
    """Background jobs: ``start`` runs ``fn(progress)`` in a thread; known errors become a Turkish message."""

    def __init__(self, known_errors: tuple[type[BaseException], ...] = (ValueError, KeyError, FileNotFoundError, RuntimeError)):
        self.known = known_errors
        self.items: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, kind: str, fn: Callable[[str, Callable[[str], None]], dict]) -> str:
        jid = uuid.uuid4().hex[:12]
        with self.lock:
            self.items[jid] = {"status": "running", "progress": "Başlıyor…", "kind": kind, "t0": time.time()}
        threading.Thread(target=self._run, args=(jid, fn), daemon=True).start()
        return jid

    def _run(self, jid: str, fn) -> None:
        st = self.items[jid]

        def progress(msg: str) -> None:
            st["progress"] = msg

        try:
            st["result"] = fn(jid, progress)
            st["status"] = "done"
        except self.known as e:
            from .hatalar import turkce

            st["status"], st["error"] = "error", turkce(str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e))
        except Exception as e:  # pragma: no cover - surfaced to the UI
            st["status"], st["error"] = "error", f"Beklenmeyen hata: {e}"
            traceback.print_exc()

    def status(self, jid: str) -> dict:
        st = self.items.get(jid)
        if not st:
            raise HTTPException(404, "iş yok")
        return {k: v for k, v in st.items() if k != "t0"} | {"seconds": round(time.time() - st["t0"], 1)}


def output_links(out_root: Path, out_dir: Path, files: dict, extra_globs: dict[str, str] | None = None) -> dict:
    """URLs (/files/...) for a finished job's files, STL parts and any extra globs, relative to ``out_root``."""
    root, od = out_root.resolve(), Path(out_dir).resolve()
    rel = od.relative_to(root)
    out = {"out_dir": str(od), "files": {k: f"/files/{rel}/{Path(v).resolve().relative_to(od)}" for k, v in files.items()},
           "stls": [f"/files/{rel}/parts/{p.name}" for p in sorted((od / "parts").glob("*.stl"))]}
    for key, pattern in (extra_globs or {}).items():
        out[key] = [f"/files/{rel}/{p.relative_to(od)}" for p in sorted(od.glob(pattern))]
    return out


def editor_app(*, title: str, version: str, web: Path, out_dir: Path, preview_dir: Path, jobs: Jobs,
               run: Callable[[str, dict, str, Callable[[str], None]], dict], validate: Callable[[dict], None] | None = None,
               upload_ext: set[str] | None = None, lifespan=None) -> FastAPI:
    """FastAPI app with the shared editor routes. ``run(kind, payload, jid, progress)`` returns the job result;
    ``kind`` is "preview" or "make". Preview files (``<jid>.glb`` / ``.png``) go to ``preview_dir``."""
    app = FastAPI(title=title, lifespan=lifespan)
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=web), name="static")

    @app.middleware("http")
    async def revalidate_pages(request, call_next):
        """Editor files are revalidated on every load (no stale app.js after an update)."""
        resp = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (web / "index.html").read_text(encoding="utf-8").replace("{{VERSION}}", version).replace("{{TITLE}}", title)
        for name in ("app.js", "app.css"):  # versioned URLs: a browser never runs a stale copy after an update
            html = html.replace(f"/static/{name}", f"/static/{name}?v={int((web / name).stat().st_mtime)}")
        return html

    @app.post("/api/jobs")
    def start(payload: dict):
        payload = dict(payload)
        kind = payload.pop("kind", "preview")
        if validate:
            validate(payload)
        return {"id": jobs.start(kind, lambda jid, progress: run(kind, payload, jid, progress))}

    @app.get("/api/jobs/{jid}")
    def status(jid: str):
        return jobs.status(jid)

    @app.get("/preview/{name}")
    def preview_file(name: str):
        f = (preview_dir / name).resolve()
        if f.parent != preview_dir.resolve() or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f, media_type="image/png" if f.suffix == ".png" else "model/gltf-binary")

    @app.get("/files/{path:path}")
    def files(path: str):
        root = out_dir.resolve()
        f = (root / path).resolve()
        if root not in f.parents or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f, filename=f.name)

    @app.post("/api/open")
    def open_folder(payload: dict):
        p = Path(payload.get("path", "")).resolve()
        if not p.is_dir() or out_dir.resolve() not in (p, *p.parents):  # only the program's own output folders
            raise HTTPException(404, "klasör yok")
        subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}

    if upload_ext:
        @app.post("/api/upload")
        async def upload(request: Request, name: str = "dosya"):
            """Raw file body (logo / image ...); returns the local path to put in the job."""
            import re

            ext = Path(name).suffix.lower()
            if ext not in upload_ext:
                raise HTTPException(400, f"desteklenmeyen dosya türü: {ext or '?'} ({', '.join(sorted(e[1:].upper() for e in upload_ext))})")
            data = await request.body()
            if not data or len(data) > UPLOAD_MAX:
                raise HTTPException(400, "dosya boş ya da 20 MB'tan büyük")
            d = preview_dir.parent / "uploads"
            d.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem)[:40] or "dosya"
            f = d / f"{uuid.uuid4().hex[:8]}_{stem}{ext}"
            f.write_bytes(data)
            return {"path": str(f), "name": Path(name).name}

    return app
