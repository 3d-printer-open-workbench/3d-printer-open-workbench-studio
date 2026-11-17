from pathlib import Path

import pytest

FONTS_DIR = Path(__file__).resolve().parents[1] / "fonts"


@pytest.fixture(scope="session")
def fonts_dir() -> Path:
    return FONTS_DIR


@pytest.fixture(scope="session")
def montserrat(fonts_dir):
    from kaligraf.fonts import FontNotFoundError, resolve_font

    try:
        return resolve_font("Montserrat", fonts_dir)
    except FontNotFoundError:
        pytest.skip("Montserrat missing; run scripts/fetch_fonts.sh")


@pytest.fixture(scope="session")
def bebas(fonts_dir):
    from kaligraf.fonts import FontNotFoundError, resolve_font

    try:
        return resolve_font("Bebas Neue", fonts_dir)
    except FontNotFoundError:
        pytest.skip("Bebas Neue missing; run scripts/fetch_fonts.sh")
