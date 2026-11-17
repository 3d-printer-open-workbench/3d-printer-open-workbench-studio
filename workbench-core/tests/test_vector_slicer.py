"""Vector cut paths (SVG/DXF) and the G-code print-path report."""
import math
import re
import xml.etree.ElementTree as ET

import trimesh
from shapely.geometry import LineString, MultiLineString, Point, box

from workbench_core.slicer import findings, gcode_report, parse_duration, report_text
from workbench_core.vector import export_cut_paths, part_outlines, read_dxf_rings


def test_svg_and_dxf_round_trip(tmp_path):
    ring = box(0, 0, 100, 40).difference(Point(20, 20).buffer(8))  # outline with a hole
    led = LineString([(10, 5), (90, 5), (90, 35)])
    items = [("govde", "#C0392B", ring), ("beyaz", "#FFFFFF", box(110, 0, 130, 20)), ("LED yolu", "#FF8A1F", MultiLineString([led]))]
    f = export_cut_paths(items, tmp_path, title="deneme")
    svg = ET.parse(f["svg"]).getroot()
    assert svg.get("width") == f"{130 + 10:.3f}mm" and svg.get("height") == f"{40 + 10:.3f}mm"  # 1:1 mm, 5 mm margin
    paths = svg.findall(".//{http://www.w3.org/2000/svg}path")
    assert len(paths) == 3
    d0 = paths[0].get("d")
    assert d0.count("M") == 2 and d0.count("Z") == 2  # outer ring + hole, both closed
    assert paths[1].get("stroke") == "#9A9A9A"  # white drawn grey so it stays visible
    assert "Z" not in paths[2].get("d")  # the LED path is an open line
    layers = read_dxf_rings(f["dxf"])
    assert set(layers) == {"govde", "beyaz", "LED_yolu"}
    assert len(layers["govde"]) == 2
    xs = [x for r in layers["govde"] for x, _ in r]
    assert min(xs) == 0 and max(xs) == 100  # real millimetres, no scaling
    assert re.search(r"\n70\n0\n", f["dxf"].read_text())  # one open polyline


def test_part_outlines_skip_duplicate_faces():
    class P:
        def __init__(self, name, mesh):
            self.name, self.color, self.mesh = name, "#111111", mesh

    body = trimesh.creation.box((30, 20, 10))
    face = trimesh.creation.box((30, 20, 1)).apply_translation((0, 0, 5.5))
    other = trimesh.creation.box((10, 10, 5)).apply_translation((40, 0, 0))
    items = part_outlines([P("govde", body), P("yuz", face), P("ayak", other)])
    assert [n for n, _, _ in items] == ["govde", "ayak"]
    assert math.isclose(items[0][2].area, 600, rel_tol=1e-3)


GCODE = """; HEADER_BLOCK_START
; filament_density: 1.24
; filament_diameter: 1.75
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
T0
;LAYER_CHANGE
;TYPE:Outer wall
G1 X10 Y0 E5
G1 X10 Y10 E5
G1 E-0.8
G1 X50 Y50
G1 E0.8
;TYPE:Sparse infill
G1 X60 Y50 E10
;TYPE:Bridge
G1 X70 Y50 E4
T1
;TYPE:Prime tower
G1 E30
G1 X80 Y50 E6
;LAYER_CHANGE
;TYPE:Gap infill
G1 X81 Y50 E2
; EXECUTABLE_BLOCK_END
; total filament used [g] = 0.21
; estimated printing time (normal mode) = 1h 2m 3s
"""


def test_gcode_report(tmp_path):
    f = tmp_path / "plate_1.gcode"
    f.write_text(GCODE)
    r = gcode_report(f)
    gpm = math.pi * 0.875 ** 2 * 1.24 / 1000
    assert math.isclose(r["grams_by_feature"]["Outer wall"], round(10 * gpm, 2))  # the 0.8 mm un-retract is not counted
    assert math.isclose(r["grams_by_feature"]["Prime tower"], round(36 * gpm, 2))  # the 30 mm purge is
    assert r["retractions"] == 1 and r["colour_changes"] == 1 and r["layers"] == 2
    assert r["seconds"] == 3723 and r["slicer_grams"] == 0.21
    assert math.isclose(r["travel_m"], round(math.hypot(40, 40) / 1000, 1))
    fs = findings(r, "It seems object x has floating regions.")
    levels = {f["seviye"] for f in fs}
    assert "sorun" in levels and "dikkat" in levels
    assert any("kule" in f["mesaj"] for f in fs) and any("köprü" in f["mesaj"].lower() for f in fs)
    assert any("Boşluk dolgusu" in f["mesaj"] for f in fs)
    txt = report_text({"model": "m.3mf", "plates": [{"plate": 1, **r, "findings": fs}]})
    assert "Dış duvar" in txt and "✗" in txt


def test_clean_report_says_so(tmp_path):
    f = tmp_path / "p.gcode"
    f.write_text("; EXECUTABLE_BLOCK_START\nT0\n;LAYER_CHANGE\n;TYPE:Outer wall\nG1 X10 Y0 E40\n;TYPE:Sparse infill\nG1 X20 Y0 E40\n"
                 "; EXECUTABLE_BLOCK_END\n")
    fs = findings(gcode_report(f))
    assert [x["seviye"] for x in fs] == ["iyi"]


def test_parse_duration():
    assert parse_duration("5h 52m 11s") == 21131 and parse_duration("1d 2h") == 93600 and parse_duration(None) is None
