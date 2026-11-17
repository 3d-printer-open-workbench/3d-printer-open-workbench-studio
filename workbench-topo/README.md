# workbench-topo

Print-ready 3D maps from open data (OpenStreetMap via Nominatim / Overpass, Copernicus DEM elevation):

| Mode | What it makes |
|---|---|
| `rota` | a route (GPX file or OSM relation) raised on real terrain, start / end markers, a caption band with distance, climb and an elevation profile |
| `sehir` | city topography: buildings at real height, roads, rail, water, green areas, sea |
| `ani` | a "memory" map in a heart / circle / hexagon shape with markers, names and a date |
| `arazi` | pure terrain with elevation colour bands |

Maps larger than the bed are split into pinned tiles; colours map to filament slots (up to 4). Downloaded data is
cached in `$TOPO_CACHE` (default `~/.cache/workbench-topo`); `TOPO_OFFLINE=1` rebuilds from the cache only. Set
`TOPO_USER_AGENT` to identify your install to the OpenStreetMap services. Every job records the required data
attribution (© OpenStreetMap contributors, ODbL; Copernicus DEM) — keep it when you publish a map.

New mode: add `MODE = Mode(...)` in `src/topo/modes/<name>.py` and list it in `modes/__init__.py`.

Tests: `../.venv/bin/python -m pytest -q` (offline: they use `tests/data/`).
