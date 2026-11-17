import json
import zipfile
from pathlib import Path

import pytest

from topo.build import build_model
from topo.data import parse_gpx, route_stats
from topo.geom import heightfield, outline, text_shape
from topo.job import Job
from topo.modes import MODES
from topo.output import run_job

ROOT = Path(__file__).resolve().parents[1]
GPX = str(ROOT / "examples" / "ornek_rota.gpx")


def test_modes_registry():
    assert set(MODES) == {"rota", "sehir", "ani", "arazi"}
    for m in MODES.values():
        for t in m.themes:
            assert all(c.startswith("#") and len(c) == 7 for c in t.colors.values())


@pytest.mark.parametrize("shape", ["rect", "square", "circle", "octagon", "hexagon", "heart"])
def test_outlines(shape):
    p = outline(shape, 100, 80 if shape == "rect" else 100)
    x0, y0, x1, y1 = p.bounds
    assert p.is_valid and abs((x1 - x0) - 100) < 0.5


def test_heightfield_is_manifold():
    import numpy as np

    xs = np.linspace(-10, 10, 21)
    z = 3 + np.random.default_rng(1).random((21, 21))
    hf = heightfield(xs, xs, z)
    assert hf.volume() > 20 * 20 * 3


def test_turkish_text():
    g = text_shape("Çığ Şöğüt İzmir", 6)
    assert not g.is_empty and g.bounds[3] - g.bounds[1] > 5


def test_gpx_stats():
    name, segs = parse_gpx(GPX)
    st = route_stats(segs, elev=lambda a, b: a * 0 + 100)
    assert name.startswith("Örnek") and 10 < st["length_km"] < 14


def test_city_job(tmp_path):
    r = run_job(Job(name="sehir", mode="sehir", lat=37.939, lon=27.340, width_km=1.2, size_mm=120), tmp_path)
    d = r.data
    roles = {p for f in d["filaments"] for p in f["parts"]}
    assert {"buildings", "roads", "terrain"} <= roles
    assert len(d["filaments"]) <= 4 and d["tiles"] == 1
    with zipfile.ZipFile(r.files["3mf"]) as z:
        names = z.namelist()
        proj = json.loads(z.read("Metadata/project_settings.config"))
    assert "3D/3dmodel.model" in names and len(proj["filament_colour"]) == len(d["filaments"])
    assert (r.out_dir / "render_34.png").is_file() and (r.out_dir / "preview.glb").is_file()


def test_route_job_caption_profile(tmp_path):
    r = run_job(Job(name="rota", mode="rota", gpx=GPX, size_mm=140, duration="4 sa"), tmp_path)
    d = r.data
    assert d["route"]["length_km"] > 10
    assert "km" in d["caption"]["subtitle"] and "4 sa" in d["caption"]["subtitle"]
    roles = {p for f in d["filaments"] for p in f["parts"]}
    assert {"route", "markers", "text", "frame"} <= roles


def test_memory_heart(tmp_path):
    j = Job(name="ani", mode="ani", lat=37.9395, lon=27.3415, width_km=1.0, size_mm=100, title="Ayşe & Ali",
            markers=[{"lat": 37.9395, "lon": 27.3415, "kind": "heart"}])
    r = run_job(j, tmp_path)
    assert any("markers" in f["parts"] for f in r.data["filaments"])


def test_too_many_colours(tmp_path):
    cols = {"terrain": "#111111", "roads": "#222222", "buildings": "#333333", "frame": "#444444", "text": "#555555"}
    with pytest.raises(ValueError, match="4 filament"):
        run_job(Job(name="x", mode="sehir", lat=37.939, lon=27.340, width_km=1.2, size_mm=100, colors=cols,
                    layers={"frame": True, "caption": True}, title="Test"), tmp_path)


def test_split_into_tiles(tmp_path):
    r = run_job(Job(name="buyuk", mode="sehir", lat=37.939, lon=27.340, width_km=1.2, size_mm=380, res_mm=1.5), tmp_path)
    assert r.data["tiles"] >= 2
    assert any("parçaya bölündü" in w for w in r.data["warnings"])


def test_place_requires_location():
    with pytest.raises(ValueError):
        Job(mode="sehir").resolved()


def test_marker_colours(tmp_path):
    j = Job(name="renk", mode="ani", lat=37.9395, lon=27.3415, width_km=1.0, size_mm=100,
            markers=[{"lat": 37.9395, "lon": 27.3415, "kind": "heart", "color": "#D62828"},
                     {"lat": 37.9405, "lon": 27.3425, "kind": "dot", "color": "#222222"}])
    r = run_job(j, tmp_path)
    cols = {f["color"] for f in r.data["filaments"]}
    assert {"#D62828", "#222222"} <= cols


def test_railway_layer(tmp_path, monkeypatch):
    import osmxml
    import topo.data as d

    els = osmxml.elements(Path(__file__).parent / "data" / "efes_osm.xml")
    els.append({"type": "way", "id": 1, "tags": {"railway": "rail"},
                "geometry": [{"lat": 37.935, "lon": 27.336}, {"lat": 37.944, "lon": 27.346}]})
    monkeypatch.setattr(d, "osm_features", lambda bb, sel: els)
    r = run_job(Job(name="tren", mode="sehir", lat=37.939, lon=27.340, width_km=1.2, size_mm=120,
                    colors={"rail": "#8B1E1E"}, layers={"green": False}), tmp_path)
    assert any("rail" in f["parts"] and f["color"] == "#8B1E1E" for f in r.data["filaments"])


def test_coastline_sea_and_road_clip():
    from shapely.geometry import LineString, box

    from topo.build import coast_sea

    region = box(-50, -50, 50, 50)
    # coastline running north along x=0: land on the left (west), sea on the right (east)
    sea = coast_sea([LineString([(0, -60), (0, 60)])], [], region, 0.0)
    assert 4900 < sea.area < 5100 and sea.centroid.x > 0


def test_forest_and_park_are_separate_layers():
    from topo.modes import default_classify

    assert default_classify({"landuse": "forest"}) == "forest"
    assert default_classify({"natural": "wood"}) == "forest"
    assert default_classify({"leisure": "park"}) == "green"
    assert default_classify({"landuse": "orchard"}) == "green"
    assert default_classify({"natural": "scrub"}) == "green"


def test_forest_colour_and_theme_layers(tmp_path, monkeypatch):
    import osmxml
    import topo.data as d

    els = osmxml.elements(Path(__file__).parent / "data" / "efes_osm.xml")
    els.append({"type": "way", "id": 2, "tags": {"landuse": "forest"},
                "geometry": [{"lat": 37.936, "lon": 27.336}, {"lat": 37.936, "lon": 27.338}, {"lat": 37.938, "lon": 27.338},
                             {"lat": 37.938, "lon": 27.336}, {"lat": 37.936, "lon": 27.336}]})
    monkeypatch.setattr(d, "osm_features", lambda bb, sel: els)
    r = run_job(Job(name="orman", mode="sehir", theme="Doğa", lat=37.939, lon=27.340, width_km=1.2, size_mm=120), tmp_path)
    assert any("forest" in f["parts"] and f["color"] == "#3F7D3A" for f in r.data["filaments"])
    j = Job(mode="rota", gpx=GPX, theme="Orman").resolved()
    assert j.layers["forest"] is True


# --------------------------------------------------------------------------- decorative landscape (arazi)
def _way(i, tags, pts):
    return {"type": "way", "id": i, "tags": tags, "geometry": [{"lat": a, "lon": b} for a, b in pts]}


def _width_along(poly, line, n=40):
    """River width measured across the course at n stations (length of the normal cut through the polygon)."""
    import numpy as np
    from shapely.geometry import LineString

    out = []
    for d in np.linspace(line.length * 0.05, line.length * 0.95, n):
        p, q = line.interpolate(d), line.interpolate(min(d + 0.5, line.length))
        tx, ty = q.x - p.x, q.y - p.y
        k = (tx * tx + ty * ty) ** 0.5 or 1
        nx, ny = -ty / k * 50, tx / k * 50
        cut = LineString([(p.x - nx, p.y - ny), (p.x + nx, p.y + ny)]).intersection(poly)
        out.append(cut.length)
    return np.array(out)


def test_river_widens_downstream_and_varies():
    import numpy as np
    from shapely.geometry import LineString

    from topo.geom import line_seed, river_shape

    line = LineString([(0, 0), (40, 8), (80, -5), (120, 4)])
    poly = river_shape(line, 1.2, line_seed(line), min_w=0.8)
    assert poly.is_valid and poly.geom_type == "Polygon"  # one connected river, no gaps
    w = _width_along(poly, line)
    assert w.min() >= 0.8 - 0.05  # always printable
    assert w[-8:].mean() > w[:8].mean() * 1.3  # widens toward the mouth
    d = np.diff(w)
    assert (d < -0.02).sum() >= 3 and (d > 0.02).sum() >= 3  # swells AND narrows along the way, not a plain taper
    again = river_shape(line, 1.2, line_seed(line), min_w=0.8)
    assert again.equals(poly)  # same river, same drawing
    other = river_shape(line, 1.2, line_seed(line) + 1, min_w=0.8)
    assert not other.equals(poly)


def test_river_shape_edge_cases():
    from shapely.geometry import LineString

    from topo.geom import river_shape

    assert river_shape(LineString([(0, 0), (0, 0)]), 1.0).is_empty
    tiny = river_shape(LineString([(0, 0), (0.3, 0)]), 0.2, min_w=0.8)  # shorter than one step, thinner than printable
    assert tiny.is_valid and tiny.area > 0 and (tiny.bounds[3] - tiny.bounds[1]) >= 0.79


def test_osm_width_tag():
    from topo.build import _width_m

    assert _width_m("12") == 12 and _width_m("12.5 m") == 12.5 and _width_m("7,5") == 7.5
    assert _width_m(None) is None and _width_m("wide") is None and _width_m("") is None


def test_rocks_and_streams_classified():
    from topo.modes import LAYER_ORDER, SELECTORS, default_classify

    for t in ("bare_rock", "scree", "rock", "stone", "shingle", "cliff"):
        assert default_classify({"natural": t}) == "rocks"
    assert default_classify({"waterway": "stream"}) == "streams"
    assert default_classify({"waterway": "river"}) == "water"
    assert {"rocks", "streams"} <= set(SELECTORS) and {"rocks", "streams"} <= set(LAYER_ORDER)
    assert LAYER_ORDER.index("rocks") < LAYER_ORDER.index("roads") < LAYER_ORDER.index("buildings")


def _arazi_elements():
    import osmxml

    els = osmxml.elements(Path(__file__).parent / "data" / "efes_osm.xml")
    els += [
        _way(9001, {"waterway": "river", "name": "Küçük Menderes"},
             [(37.931, 27.336), (37.935, 27.340), (37.938, 27.343), (37.944, 27.347)]),
        _way(9002, {"waterway": "stream"}, [(37.943, 27.336), (37.940, 27.338), (37.937, 27.339)]),
        _way(9003, {"natural": "bare_rock"},
             [(37.9405, 27.3435), (37.9405, 27.3455), (37.9420, 27.3455), (37.9420, 27.3435), (37.9405, 27.3435)]),
        _way(9004, {"natural": "cliff"}, [(37.9330, 27.3440), (37.9340, 27.3470)]),
    ]
    return els


def test_arazi_mode_defaults_and_theme():
    from topo.modes import MODES

    m = MODES["arazi"]
    t = m.themes[0]
    assert t.name == "Yeşil dağlar" and t.road_scale < 1
    assert t.colors["terrain"] == "#3F8F3A" and t.colors["roads"] == "#1E1E1E"
    assert t.colors["buildings"] == t.colors["rocks"] == "#FFFFFF"
    assert t.colors["water"] == t.colors["sea"] == t.colors["streams"] == "#2AA7E0"
    for th in m.themes:  # every theme fits 4 filaments for the layers the mode draws
        used = {th.colors[k] for k, on in m.layers.items() if on and k in th.colors}
        assert len(used) <= 4, th.name
    j = Job(mode="arazi", lat=37.939, lon=27.340).resolved()
    assert j.layers["terrain"] and j.layers["rocks"] and j.layers["streams"] and not j.layers["green"]
    assert j.z_exag == 2.0


def test_arazi_job_four_colours(tmp_path, monkeypatch):
    import topo.data as d

    monkeypatch.setattr(d, "osm_features", lambda bb, sel: _arazi_elements())
    r = run_job(Job(name="arazi", mode="arazi", lat=37.939, lon=27.340, width_km=1.6, size_mm=120), tmp_path)
    fil = {f["color"]: set(f["parts"]) for f in r.data["filaments"]}
    assert set(fil) == {"#3F8F3A", "#1E1E1E", "#FFFFFF", "#2AA7E0"}  # exactly the four decorative colours
    assert "terrain" in fil["#3F8F3A"] and "roads" in fil["#1E1E1E"]
    assert {"buildings", "rocks"} <= fil["#FFFFFF"]
    assert {"water", "streams"} <= fil["#2AA7E0"]
    assert (r.out_dir / "render_34.png").is_file()
    with zipfile.ZipFile(r.files["3mf"]) as z:
        proj = json.loads(z.read("Metadata/project_settings.config"))
    assert [c.upper() for c in proj["filament_colour"]] == [f["color"].upper() for f in r.data["filaments"]]


def test_road_scale_thins_roads(monkeypatch):
    import topo.data as d
    from topo.modes import MODES

    monkeypatch.setattr(d, "osm_features", lambda bb, sel: _arazi_elements())
    job = Job(mode="arazi", lat=37.939, lon=27.340, width_km=0.4, size_mm=120)  # close-up: roads above the 0.8 mm floor
    fine = build_model(job, coarse=True).layers["roads"].area
    monkeypatch.setattr(MODES["arazi"].themes[0], "road_scale", 1.0)
    full = build_model(job, coarse=True).layers["roads"].area
    assert fine < full * 0.85
    assert fine > full * 0.4  # thinner, never vanishing




def test_estimate_counts_colour_change_waste():
    import trimesh

    from topo.output import PURGE_G_PER_CHANGE, _estimate

    a, b = trimesh.creation.box((20, 20, 4)), trimesh.creation.box((20, 20, 4)).apply_translation((0, 0, 4))
    e = _estimate([[("terrain", 1, a), ("roads", 2, b)]], 0.15)
    assert e["colour_changes"] >= 1
    assert e["grams_purge"] == round(e["colour_changes"] * PURGE_G_PER_CHANGE)
    assert e["grams_total"] == round(sum(e["grams_by_slot"].values()) + e["colour_changes"] * PURGE_G_PER_CHANGE) or \
        abs(e["grams_total"] - sum(e["grams_by_slot"].values()) - e["grams_purge"]) <= 1
