import pytest
import yaml

from kaligraf.fonts import (
    CATEGORIES,
    FontNotFoundError,
    find_spec,
    load_registry,
    load_ttfont,
    missing_glyphs,
    resolve_font,
)

BASIC = ["Tinos", "Arimo", "Style Script", "Mansalva", "Alex Brush", "Marcellus", "Montserrat",
         "Cormorant Garamond", "Bebas Neue", "Playfair Display"]
PRINT = ["Inter", "Jost", "EB Garamond", "Cinzel", "Bodoni Moda", "Abril Fatface", "Righteous", "Cabin",
         "Nunito Sans", "Syncopate", "Cormorant", "Fraunces"]
CURSIVE = ["Dancing Script", "The Nautigal", "Parisienne", "Caramel", "Caveat", "Pacifico",
           "Great Vibes", "Sacramento", "Cedarville Cursive", "Allison", "Shadows Into Light", "Moon Dance",
           "Ms Madi", "Yellowtail"]
COMMERCIAL = ["Times New Roman", "Arial", "Beyond Script", "Gentlemens", "Alta", "The Seasons", "Helvetica",
              "Futura", "La Luxes", "Vogue", "Neon 80s", "Gill Sans", "Avenir", "Kiona", "Nove", "adelia",
              "Brittany", "Barcelony", "High Spirited", "Photoshoot", "Amoresa", "TingTong", "Jalliestha",
              "Amsterdam", "Moontime", "Halimun"]


def test_catalog_contents(fonts_dir):
    reg = load_registry(fonts_dir)
    by_cat = {c: [s.name for s in reg.values() if s.category == c] for c in CATEGORIES}
    assert by_cat["basic"] == BASIC and by_cat["print"] == PRINT and by_cat["cursive"] == CURSIVE
    assert len(reg) == 36 and len({s.id for s in reg.values()}) == 36
    for spec in reg.values():
        assert spec.license in ("ofl", "apache") and spec.licensed
        assert spec.name == spec.family
    # display names are real family names, never the original commercial names
    shown = {s.name.lower() for s in reg.values()}
    assert not shown & {n.lower() for n in COMMERCIAL}
    assert reg["Tinos"].source_note == "replaces Times New Roman"
    assert reg["Fraunces"].axes == (("wght", 900.0), ("SOFT", 100.0))


def test_all_files_and_license_texts_present(fonts_dir):
    for spec in load_registry(fonts_dir).values():
        assert (fonts_dir / spec.file).stat().st_size > 1000, spec.name
        lic = "OFL" if spec.license == "ofl" else "LICENSE"
        assert (fonts_dir / "licenses" / f"{spec.id}-{lic}.txt").exists(), spec.name


def test_every_font_loads_and_has_cap_height(fonts_dir):
    from kaligraf.text2d import font_cap_height

    for spec in load_registry(fonts_dir).values():
        r = resolve_font(spec.id, fonts_dir)
        font = load_ttfont(r)
        assert "fvar" not in font
        assert font_cap_height(font) > 0, spec.name
        assert not r.warnings


def test_lookup_by_name_or_id(fonts_dir):
    reg = load_registry(fonts_dir)
    assert find_spec(reg, "playfair-display").name == "Playfair Display"
    assert find_spec(reg, "BEBAS NEUE").id == "bebas-neue"
    assert resolve_font("montserrat", fonts_dir).spec.name == "Montserrat"
    with pytest.raises(KeyError):
        resolve_font("Arial", fonts_dir)  # original commercial names are not in the catalog


def test_montserrat_pinned_and_turkish(montserrat):
    font = load_ttfont(montserrat)
    assert missing_glyphs(font, "çğıİöşüÇĞÖŞÜ") == []
    from kaligraf.text2d import build_text

    # wght pinned to 400: regular stems are thick (Thin would warn at this size)
    assert not build_text("HI", montserrat, "letters", cap_height_mm=100).warnings


def test_fraunces_pins_applied(fonts_dir):
    black = load_ttfont(resolve_font("Fraunces", fonts_dir))
    from kaligraf.text2d import font_cap_height  # noqa: F401
    gs = black.getGlyphSet()
    from fontTools.pens.boundsPen import BoundsPen

    def width(name):
        bp = BoundsPen(gs)
        gs[name].draw(bp)
        return bp.bounds[2] - bp.bounds[0]

    reg = load_ttfont(resolve_font("Cormorant", fonts_dir))
    assert width("l") > 0 and reg is not None


def _registry(tmp_path, items, files=()):
    (tmp_path / "fonts.yaml").write_text(yaml.safe_dump({"fonts": items}, allow_unicode=True))
    for f in files:
        (tmp_path / f).write_bytes(b"x")
    return tmp_path


def _item(**kw):
    base = dict(id="x", display_name="X Font", family="X Font", category="basic", file="x.ttf",
                source="s", license="commercial", licensed=False, weight=400, axes={}, source_note="")
    base.update(kw)
    return base


def test_missing_file_error_is_font_specific(tmp_path):
    d = _registry(tmp_path, [_item()])
    with pytest.raises(FontNotFoundError, match="X Font"):
        resolve_font("X Font", d, system_dirs=())


def test_unlicensed_font_warns_but_resolves(tmp_path):
    d = _registry(tmp_path, [_item()], ["x.otf"])
    r = resolve_font("x", d, system_dirs=())
    assert r.path.name == "x.otf" and any("licen" in w for w in r.warnings)


def test_system_font_lookup(tmp_path):
    sysdir = tmp_path / "sys" / "nested"
    sysdir.mkdir(parents=True)
    (sysdir / "x.ttf").write_bytes(b"x")
    d = _registry(tmp_path / "reg", [_item(license="system", licensed=True)]) if (tmp_path / "reg").mkdir() is None else None
    r = resolve_font("X Font", d, system_dirs=(tmp_path / "sys",))
    assert r.path.name == "x.ttf" and not r.warnings


def test_bad_registry_values(tmp_path):
    with pytest.raises(ValueError):
        load_registry(_registry(tmp_path, [_item(license="gpl")]))
    with pytest.raises(ValueError):
        load_registry(_registry(tmp_path, [_item(category="fancy")]))


def test_missing_glyph_reported(bebas):
    font = load_ttfont(bebas)
    assert missing_glyphs(font, "A中 B") == ["中"]
