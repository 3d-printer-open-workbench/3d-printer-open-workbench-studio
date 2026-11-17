"""One MCP server for every program. Shared tools once (colour info, prompt saving, job summary, make), plus each
program's discovery tools (Maker products and parameters, Topo modes / places / routes). Output goes to each program's
usual work folder."""
from __future__ import annotations

from .apps import APPS, WORK_ROOT


def _out(key: str) -> str:
    d = WORK_ROOT / APPS[key].work_sub
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def program_of_job_dir(data: dict) -> str:
    """Which program wrote this job.json."""
    if data.get("app") == "workbench-maker":
        return "maker"
    if str(data.get("tool", "")).startswith("Workbench - Topo"):
        return "topo"
    if "bom" in data and "power" in data:
        return "glow"
    return "kaligraf"


def register(mcp) -> list[str]:
    from glow import tools as gt
    from kaligraf import tools as kt
    from maker import tools as mt
    from workbench_core import tools as ct
    from topo import tools as tt

    from .cli import program_of

    names = []

    def add(fn, name):
        mcp.tool(name=name, description=(fn.__doc__ or "").strip() or None)(fn)
        names.append(name)

    add(ct.color_info, "color_info")
    add(ct.save_prompt, "save_prompt")
    add(ct.print_check, "print_check")

    def job_summary(job_dir: str):
        """Describe a finished job of any program (sign, lightbox, map or Maker product): text, real size, colours
        (HEX / RAL / name), parts, cost, renders. Args: job_dir: the job folder that contains job.json."""
        prog = program_of_job_dir(ct.read_job(job_dir))
        return {"kaligraf": kt.job_summary, "glow": gt.job_summary, "topo": tt.job_summary}.get(prog, ct.read_job)(job_dir)
    add(job_summary, "job_summary")

    def make(job: dict) -> dict:
        """Build any Workbench product from a job dict; the program is recognised from the job:
        - Maker products: {generator: key, name, params: {...}} (see maker_list_generators / maker_generator_params);
        - Kaligraf signs (each letter exported as its own STL in parts/letter_01_P.stl ...):
          {mode: "flat" | "letters", text, font, width_cm | letter_height_cm (+ letter_width_mm, depth_mm), split_letters: true, colors, ...};
        - Glow lightboxes: {design: "rect" | "round" | "contour", ...};
        - Topo maps: {mode: "rota" | "sehir" | "ani" | "arazi", place | lat/lon | gpx | osm_relation, size_mm, ...} (see topo_list_modes)."""
        raw = dict(job)
        gen = str(raw.get("generator") or "")
        if gen in ("kaligraf_flat", "flat"):
            params = dict(raw.get("params") or {})
            raw = {k: v for k, v in raw.items() if k not in ("generator", "params", "name")} | params | {"mode": "flat"}
        elif gen in ("kaligraf_letters", "letters"):
            params = dict(raw.get("params") or {})
            raw = {k: v for k, v in raw.items() if k not in ("generator", "params", "name")} | params | {"mode": "letters"}
        elif gen in ("glow_rect", "glow_round", "glow_contour"):
            params = dict(raw.get("params") or {})
            raw = {k: v for k, v in raw.items() if k not in ("generator", "params", "name")} | params | {"design": gen.removeprefix("glow_")}
        prog = program_of(raw)
        if prog == "maker":
            return mt.make(raw, _out("maker"))
        if prog == "kaligraf":
            return kt.make_model(raw, _out("kaligraf"))
        if prog == "glow":
            return gt.make_glow(raw, _out("glow"))
        return tt.make_map(raw, _out("topo"))
    add(make, "make")

    def maker_list_generators() -> list[dict]:
        """All Open Workbench Studio generators and sign/lightbox modes (Maker + Kaligraf flat/letters + Glow rect/round/contour)."""
        extra = [
            {
                "key": "kaligraf_flat",
                "label": "Düz tabela / Duvar yazısı (Harf harf STL)",
                "group": "Yazı ve Tabela (Kaligraf)",
                "description": "2.5B duvar yazısı, işletme tabelası ve logo. split_letters=True (varsayılan) ile her harf ayrı STL (parts/letter_01_P.stl vb.) ve 1:1 A4 duvar şablonu (template.pdf) olarak çıkar; thickness_mm (1-250 mm) ve stroke_offset_mm (-1.5..+5 mm) serbestçe verilebilir. make içinde mode='flat' veya generator='kaligraf_flat' kullanılır.",
                "status": "ready",
                "milestone": "kaligraf",
            },
            {
                "key": "kaligraf_letters",
                "label": "3B harfler (Harf harf kutu harf STL)",
                "group": "Yazı ve Tabela (Kaligraf)",
                "description": "Her harf için 3 eksende ölçü: letter_width_mm (X, 0=yazı tipi oranı, ≤250), letter_height_cm (Y, büyük harf; UI'da letter_height_mm ≤250), depth_mm (Z, 2-250 mm) ve harf et kalınlığı (stroke_offset_mm: -1.5..+5 mm) ile 3B bağımsız harfler; tek harf en fazla 250×250×250 mm. Her harf ayrı STL (parts/letter_01_P.stl vb.) ve 1:1 A4 duvar şablonu olarak çıkar; el yazısında yapboz kilitli bölme yapar. make içinde mode='letters' veya generator='kaligraf_letters' kullanılır.",
                "status": "ready",
                "milestone": "kaligraf",
            },
            {
                "key": "glow_rect",
                "label": "Işık kutusu (Dikdörtgen LED Lightbox)",
                "group": "Işıklı Ürünler (Glow)",
                "description": "Dikdörtgen LED ışıklı tabela / lightbox (model.3mf, parts/*.stl, Türkçe LED montaj PDF'i assembly_tr.pdf ve bom.csv TL maliyet üretir). make içinde design='rect' kullanılır.",
                "status": "ready",
                "milestone": "glow",
            },
            {
                "key": "glow_round",
                "label": "Işık kutusu (Yuvarlak LED Lightbox)",
                "group": "Işıklı Ürünler (Glow)",
                "description": "Yuvarlak LED ışıklı logo / tabela (model.3mf, parts/*.stl, assembly_tr.pdf ve bom.csv üretir). make içinde design='round' kullanılır.",
                "status": "ready",
                "milestone": "glow",
            },
            {
                "key": "glow_contour",
                "label": "Şekilli ışık / Neon (Kontur LED Lightbox)",
                "group": "Işıklı Ürünler (Glow)",
                "description": "Yazının veya logonun kendi kontur şeklinde LED ışıklı tabela (model.3mf, parts/*.stl, assembly_tr.pdf ve bom.csv üretir). make içinde design='contour' kullanılır.",
                "status": "ready",
                "milestone": "glow",
            },
        ]
        return extra + mt.list_generators()

    def maker_generator_params(key: str) -> dict:
        """Parameter schema of one generator or Kaligraf/Glow product (type, default, range, options, Turkish label)."""
        from .products import products

        prods = products()
        alias = {
            "flat": "kaligraf_flat",
            "letters": "kaligraf_letters",
            "rect": "glow_rect",
            "round": "glow_round",
            "contour": "glow_contour",
        }
        pid = alias.get(key, key)
        if pid in prods:
            return prods[pid].schema()
        return mt.generator_params(key)

    add(maker_list_generators, "maker_list_generators")
    add(maker_generator_params, "maker_generator_params")
    add(mt.list_sheets, "maker_list_sheets")
    for fn in (tt.list_modes, tt.find_place, tt.find_route):
        add(fn, f"topo_{fn.__name__}")
    return names
