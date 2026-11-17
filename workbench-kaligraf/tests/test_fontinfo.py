from kaligraf.fontinfo import SAMPLE, font_metrics, load_metrics, size_warnings
from kaligraf.fonts import load_registry, resolve_font
from kaligraf.text2d import build_text


def test_cached_metrics_cover_catalog(fonts_dir):
    m = load_metrics(fonts_dir)
    assert set(m) == {s.id for s in load_registry(fonts_dir).values()}
    # every sellable font has the full Turkish set
    assert all(v["turkish_ok"] and not v["turkish_missing"] for v in m.values())


def test_min_size_matches_min_feature_check(fonts_dir):
    m = font_metrics("montserrat", fonts_dir)
    rf = resolve_font("montserrat", fonts_dir)
    ok = build_text(SAMPLE, rf, "letters", cap_height_mm=m["min_cap_letters_cm"] * 10)
    bad = build_text(SAMPLE, rf, "letters", cap_height_mm=(m["min_cap_letters_cm"] - 0.5) * 10)
    assert not ok.warnings and bad.warnings


def test_flat_min_cap_matches_check_and_is_text_independent(fonts_dir):
    m = font_metrics("abril-fatface", fonts_dir)
    rf = resolve_font("abril-fatface", fonts_dir)
    cap = m["min_cap_flat_cm"]
    for text in ("Portalin", "Portalin | Your Brand"):
        ref = build_text(text, rf, "flat", width_mm=400)
        ok = build_text(text, rf, "flat", width_mm=400 * cap / (ref.cap_height_mm / 10))
        assert not [w for w in ok.warnings if "thinner" in w], text  # same cap height passes for either text


def test_size_warnings(fonts_dir):
    m = load_metrics(fonts_dir)["abril-fatface"]
    assert size_warnings(m, "flat", m["min_cap_flat_cm"] - 0.5) and not size_warnings(m, "flat", m["min_cap_flat_cm"] + 0.5)
    broken = {"name": "X", "turkish_ok": False, "turkish_missing": ["Ş"], "min_cap_flat_cm": 1, "min_cap_letters_cm": 2}
    assert any("Türkçe" in w for w in size_warnings(broken, "letters", 50))
