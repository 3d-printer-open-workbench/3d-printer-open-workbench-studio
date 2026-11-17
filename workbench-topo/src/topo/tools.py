"""Plain functions exposed as MCP tools (and used by the UI)."""
from __future__ import annotations


from . import data
from .job import Job
from .modes import MODES


def list_modes() -> list[dict]:
    """Available map modes with their themes and default layers.

    Returns:
        list of {key, label, description, area_source, themes, layers}
    """
    return [{"key": m.key, "label": m.label, "description": m.description, "area_source": m.area_source,
             "themes": [t.name for t in m.themes], "layers": m.layers} for m in MODES.values()]


def find_place(query: str) -> list[dict]:
    """Search a place name (OpenStreetMap Nominatim).

    Args:
        query: place name, e.g. "Alsancak, İzmir"
    Returns:
        up to 5 hits {name, lat, lon, width_km, height_km}
    """
    out = []
    for h in data.geocode(query):
        w, hh = h["bbox"].size_m()
        out.append({"name": h["name"], "lat": h["lat"], "lon": h["lon"], "width_km": round(w / 1000, 2), "height_km": round(hh / 1000, 2)})
    return out


def find_route(query: str) -> list[dict]:
    """Search an OpenStreetMap route relation (hiking trail) by name.

    Args:
        query: e.g. "Likya Yolu", "Karia Yolu", "Frig Yolu"
    Returns:
        list of {name, relation_id, type}
    """
    return data.find_routes(query)


def make_map(job: dict, output_dir: str = "output") -> dict:
    """Build a print-ready 3D map (3MF + STL + renders) from a job.

    Args:
        job: Job fields, e.g. {"name": "efes", "mode": "sehir", "place": "Efes, Selçuk", "width_km": 1.5, "size_mm": 200}
             or {"mode": "rota", "osm_relation": 123456, "size_mm": 220}. See README for all fields.
        output_dir: folder for the job folder
    Returns:
        {out_dir, scale, overall_mm, filaments, estimate, warnings, files}
    """
    from .output import run_job

    res = run_job(Job.from_dict(job), output_dir)
    d = res.data
    return {"out_dir": str(res.out_dir), "scale": d["scale"], "overall_mm": d["overall_mm"], "filaments": d["filaments"],
            "estimate": d["estimate"], "warnings": d["warnings"], "files": {k: str(v) for k, v in res.files.items()}}


def job_summary(job_dir: str) -> dict:
    """Read job.json of a finished job.

    Args:
        job_dir: the job folder
    """
    from workbench_core.tools import read_job

    return read_job(job_dir)
