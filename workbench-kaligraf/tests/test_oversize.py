import pytest

from kaligraf.geometry import BED_MM, fits_without_split, make_flat, make_letters


@pytest.mark.parametrize("style", ["single", "backplate"])
def test_limit_flat_clamps_width(montserrat, style):
    m = make_flat("Portalin", montserrat, 400, thickness=5, style=style, oversize_policy="limit")
    assert fits_without_split(m)
    assert all(p.mesh.extents[0] <= BED_MM and p.mesh.extents[1] <= BED_MM for p in m.parts)
    applied = m.meta["size_applied_mm"]
    assert 245 < applied <= 250
    assert m.meta["size_requested_mm"] == 400
    assert m.meta["oversize_policy"] == "limit"
    assert m.meta["max_no_split_size_mm"] == pytest.approx(250, abs=0.5)
    assert "requested width 40.0 cm" in m.warnings[0] and "applied 25.0 cm" in m.warnings[0]
    assert max(p.mesh.extents[0] for p in m.parts) == pytest.approx(applied, abs=0.5)


def test_limit_letters_clamps_cap_height(bebas):
    m = make_letters("AB", bebas, 400, oversize_policy="limit")
    assert fits_without_split(m)
    assert m.meta["size_applied_mm"] == pytest.approx(250, abs=1.0)
    assert "requested letter height 40.0 cm" in m.warnings[0]
    assert not any("will be split" in w for w in m.warnings)


def test_limit_accounts_for_accents(bebas):
    m = make_letters("ŞÜKRÜ", bebas, 400, oversize_policy="limit")
    assert fits_without_split(m)
    assert m.meta["size_applied_mm"] < 210  # Ü/Ş exceed cap height, so the cap is clamped further
    assert m.meta["max_no_split_size_mm"] == pytest.approx(m.meta["size_applied_mm"] / 0.9995, rel=0.01)


def test_limit_no_clamp_when_it_fits(bebas):
    m = make_letters("AB", bebas, 100, oversize_policy="limit")
    assert m.meta["size_applied_mm"] == 100
    assert not any("oversize_policy" in w for w in m.warnings)
    assert m.meta["max_no_split_size_mm"] > 100


def test_split_policy_default_exposes_max_size(montserrat, bebas):
    m = make_flat("Portalin", montserrat, 400, thickness=5)
    assert m.meta["oversize_policy"] == "split"
    assert m.meta["size_applied_mm"] == 400
    assert m.meta["max_no_split_size_mm"] == pytest.approx(250, abs=0.5)
    assert any("will be split" in w for w in m.warnings)
    k = make_letters("ŞÜKRÜ", bebas, 200)
    assert k.meta["max_no_split_size_mm"] == pytest.approx(203.7, abs=1.0)
    assert not k.warnings


def test_invalid_policy(bebas):
    with pytest.raises(ValueError):
        make_letters("A", bebas, 100, oversize_policy="shrink")
