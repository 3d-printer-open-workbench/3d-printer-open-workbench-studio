"""T2: dome profiles, draft / undercut check, relief on the shell; plus economy molds and cost estimates."""
import numpy as np
import pytest
import trimesh
from shapely import affinity

from maker import core, estimate, thermo
from maker.job import build, run_job
from maker.shapes import shape_polygon
from maker.sheets import get_sheet


def _dome(profile="pillow", kind="circle", depth=15, relief=None, draft=5.0, sheet="petg_05"):
    s = get_sheet(sheet)
    o, _ = thermo.clean_outline(shape_polygon(kind, 80), s, depth)
    o = thermo.centred(o)
    return s, o, thermo.Dome(o, depth, profile=profile, draft_deg=draft, soften_mm=s.min_radius_mm, relief=relief)


def _relief_text(text="2026", width=40, height=1.2, raised=True):
    g, _ = core.text_geometry(text, "Righteous", width_mm=width)
    x0, y0, x1, y1 = g.bounds
    return thermo.Relief(affinity.translate(g, -(x0 + x1) / 2, -(y0 + y1) / 2), height, raised)


@pytest.mark.parametrize("profile", list(thermo.PROFILES_TR))
def test_profiles_no_undercut_and_draft(profile):
    s, o, d = _dome(profile, relief=_relief_text() if profile in ("flat", "dome") else None)
    assert d.max_height == pytest.approx(15 + (1.2 if profile in ("flat", "dome") else 0), abs=0.6)
    m = thermo.press_molds(d, s)
    assert core.is_part_valid(m.female) and core.is_part_valid(m.male)
    # no cavity face points downwards (no undercut) and walls keep the draft angle (0.5 % rim slivers aside)
    draft, undercuts = thermo.cavity_draft(m, d)
    assert undercuts == 0 and draft >= 5.0 - 1.0
    assert d.steepest_wall_deg() <= 90 - 5.0 + 0.5


def test_draft_limiter_caps_hemisphere():
    s = get_sheet()
    res = {}
    for dr in (2.0, 15.0):
        _, o, d = _dome("dome", draft=dr)
        res[dr] = (d.steepest_wall_deg(), thermo.cavity_draft(thermo.press_molds(d, s), d))
    assert res[15.0][0] <= 75.5 < res[2.0][0]  # the hemisphere's near-vertical rim is cut back to 90 - draft
    assert res[15.0][1][0] >= 14.0 and res[15.0][1][1] == 0


def test_profiles_differ():
    hs = {p: _dome(p)[2].grid_h for p in thermo.PROFILES_TR}
    vol = {p: h.sum() for p, h in hs.items()}
    assert vol["flat"] > vol["pillow"] > vol["stepped"] * 0.5
    assert len({round(v, -2) for v in vol.values()}) == 4


@pytest.mark.parametrize("raised", [True, False])
def test_relief_formed_into_both_molds(raised):
    """Relief changes the cavity and the male follows it at the same gap (ball erosion)."""
    s, o, d = _dome("flat", relief=_relief_text(raised=raised))
    _, _, d0 = _dome("flat")
    centre = np.array([[0.0, 0.0]])
    # "0" of 2026 near the centre: the dome there is 1.2 mm higher (raised) or lower (sunk) than without relief
    probe = np.array([[x, 0.0] for x in np.linspace(-15, 15, 61)])
    diff = d.height(probe) - d0.height(probe)
    assert (diff.max() if raised else -diff.min()) == pytest.approx(1.2, abs=0.15)
    m = thermo.press_molds(d, s)
    male = thermo.male_in_use(m)
    assert core.to_trimesh(core.from_trimesh(m.female) ^ core.from_trimesh(male)).volume == pytest.approx(0, abs=1e-3)
    c, n = male.triangles_center, male.face_normals
    pts = c[(n[:, 2] < -0.3) & (c[:, 2] < m.female_top_z + m.gap_mm - 0.3)]
    _, dist, _ = trimesh.proximity.closest_point(m.female, pts)
    assert np.mean(np.abs(dist - m.gap_mm) < 0.1) > 0.98


def test_relief_min_detail_warning():
    s = get_sheet("petg_10")
    thin = _relief_text("Ilık", width=14).geometry  # ~1.5 mm strokes
    assert any("ince çizgiler" in w for w in thermo.relief_warnings(thin, s, 1.5))
    bold = _relief_text("O", width=30).geometry
    assert not thermo.relief_warnings(bold, s, 2.5)
    assert any("iki katından" in w for w in thermo.relief_warnings(bold, s, 1.0))


def test_relief_job_and_fit():
    res, _ = build({"generator": "thermoform", "params": {"relief": "text", "relief_text": "Mutlu Yıllar", "relief_pct": 85}})
    assert any("küçültüldü" in w for w in res.warnings)
    with pytest.raises(ValueError, match="Kabartma için bir yazı"):
        build({"generator": "thermoform", "params": {"relief": "text", "relief_text": " "}})


def test_economy_molds_save_filament():
    s, o, d = _dome("pillow", kind="star")
    full, eco = thermo.press_molds(d, s, economy=False), thermo.press_molds(d, s, economy=True)
    g = lambda m: estimate.part_estimate(m, "PETG", "mold").grams
    assert g(eco.female) + g(eco.male) < 0.75 * (g(full.female) + g(full.male))
    # forming surfaces are identical: the cavity volume is the same
    hull = lambda m: core.extrude(affinity.scale(o, 1, -1, origin=(0, 0)).buffer(1), m.female_top_z - d.max_height - 0.5, m.female_top_z)
    cav = lambda m: hull(m).volume() - (core.from_trimesh(m.female) ^ hull(m)).volume()
    assert cav(eco) == pytest.approx(cav(full), rel=1e-3)
    for m in (eco.female, eco.male):
        assert core.is_part_valid(m)


def test_cost_estimate_and_user_prices(tmp_path, monkeypatch):
    res = run_job({"generator": "thermoform", "name": "k", "params": {}}, tmp_path)
    d = res.data
    assert all(p["grams"] > 0 and p["cost_try"] > 0 for p in d["parts"])
    assert d["meta"]["cost_try"]["sheet_counted"] is False and "levha fiyatı girilmedi" in d["notes"][0]
    assert "gyroid" in d["notes"][1]
    user = tmp_path / "costs.yaml"
    user.write_text("filament_try_kg: {PETG: 1200}\nsheet_try_m2: {petg_05: 500}\n")
    monkeypatch.setattr(estimate, "USER_FILE", user)
    estimate._load.cache_clear()
    d2 = run_job({"generator": "thermoform", "name": "k2", "params": {}}, tmp_path).data
    assert d2["meta"]["cost_try"]["molds"] == pytest.approx(2 * d["meta"]["cost_try"]["molds"], rel=0.02)
    assert d2["meta"]["cost_try"]["sheet_counted"] and d2["meta"]["cost_try"]["per_ornament"] > d["meta"]["cost_try"]["per_ornament"]
