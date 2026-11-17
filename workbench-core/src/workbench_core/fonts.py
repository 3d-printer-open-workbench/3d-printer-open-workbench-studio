"""Font registry and resolver.

Registry lives in ``fonts/fonts.yaml``. A font is looked up first in the
project ``fonts/`` directory, then in system font directories. Licensing
problems only produce warnings; a missing file raises :class:`FontNotFoundError`
for that font only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from fontTools.ttLib import TTFont

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FONTS_DIR = Path(os.environ.get("WORKBENCH_FONTS_DIR", REPO_ROOT / "fonts"))

SYSTEM_FONT_DIRS: tuple[Path, ...] = (
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
    Path.home() / ".local/share/fonts",
)

LICENSES = ("ofl", "apache", "system", "commercial")
CATEGORIES = ("basic", "print", "cursive")


class FontError(Exception):
    """Base class for font problems."""


class FontNotFoundError(FontError):
    """Raised when the font file for a registered font cannot be found."""


@dataclass(frozen=True)
class FontSpec:
    id: str
    name: str  # display name = real family name
    family: str
    category: str  # basic | print | cursive
    file: str
    source: str
    license: str  # ofl | apache | system | commercial
    licensed: bool
    weight: float = 400
    axes: tuple[tuple[str, float], ...] = ()  # variable-font axis pins, e.g. (('wght', 400),)
    source_note: str = ""  # internal only (never shown to customers)


@dataclass(frozen=True)
class ResolvedFont:
    spec: FontSpec
    path: Path
    warnings: tuple[str, ...] = field(default_factory=tuple)


def load_registry(fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> dict[str, FontSpec]:
    """Load ``fonts.yaml``; returns specs keyed by display name."""
    data = yaml.safe_load((Path(fonts_dir) / "fonts.yaml").read_text(encoding="utf-8"))
    specs: dict[str, FontSpec] = {}
    for item in data["fonts"]:
        if item["license"] not in LICENSES:
            raise ValueError(f"{item['display_name']}: unknown license {item['license']!r}")
        if item["category"] not in CATEGORIES:
            raise ValueError(f"{item['display_name']}: unknown category {item['category']!r}")
        spec = FontSpec(
            id=item["id"],
            name=item["display_name"],
            family=item["family"],
            category=item["category"],
            file=item["file"],
            source=item["source"],
            license=item["license"],
            licensed=bool(item["licensed"]),
            weight=float(item.get("weight", 400)),
            axes=tuple((k, float(v)) for k, v in (item.get("axes") or {}).items()),
            source_note=item.get("source_note", ""),
        )
        specs[spec.name] = spec
    return specs


def find_spec(registry: dict[str, FontSpec], name_or_id: str) -> FontSpec:
    """Look a font up by display name or id (case-insensitive)."""
    key = name_or_id.strip().lower()
    for spec in registry.values():
        if key in (spec.name.lower(), spec.id.lower()):
            return spec
    raise KeyError(f"Unknown font {name_or_id!r}. Known: {', '.join(registry)}")


def _find_in_dir(directory: Path, filenames: list[str]) -> Path | None:
    """Case-insensitive recursive search for any of ``filenames`` under ``directory``."""
    if not directory.is_dir():
        return None
    wanted = {n.lower() for n in filenames}
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.lower() in wanted:
                return Path(root) / f
    return None


def _candidates(file: str) -> list[str]:
    """The file name itself plus same stem with other font extensions."""
    stem = Path(file).stem
    return [file] + [stem + ext for ext in (".ttf", ".otf") if stem + ext != file]


def resolve_font(
    name: str,
    fonts_dir: Path | str = DEFAULT_FONTS_DIR,
    system_dirs: tuple[Path, ...] | None = None,
) -> ResolvedFont:
    """Resolve a registered font (display name or id) to a file.

    Raises FontNotFoundError (font-specific) if the file is missing, KeyError for an
    unknown font. Fonts that are not licensed in the registry (``licensed: false``, e.g.
    a commercial font a user adds) only produce a warning.
    """
    fonts_dir = Path(fonts_dir)
    system_dirs = SYSTEM_FONT_DIRS if system_dirs is None else system_dirs
    spec = find_spec(load_registry(fonts_dir), name)
    path = _find_in_dir(fonts_dir, _candidates(spec.file))
    if path is None and spec.license == "system":
        for d in system_dirs:
            path = _find_in_dir(d, [spec.file])
            if path:
                break
    if path is None:
        hint = {
            "ofl": "run scripts/fetch_fonts.sh",
            "apache": "run scripts/fetch_fonts.sh",
            "system": "install it on the system",
            "commercial": f"drop {spec.file} into {fonts_dir}",
        }[spec.license]
        raise FontNotFoundError(f"Font '{spec.name}' file not found ({spec.file}); {hint}.")
    warnings: list[str] = []
    if not spec.licensed:
        warnings.append(
            f"Font '{spec.name}' is {spec.license}/unlicensed in the registry: make sure you hold "
            "a commercial license before selling products made with it."
        )
    return ResolvedFont(spec=spec, path=path, warnings=tuple(warnings))


@lru_cache(maxsize=16)
def _load_ttfont(path: str, axes: tuple[tuple[str, float], ...] = ()) -> TTFont:
    font = TTFont(path, lazy=False)
    if "fvar" in font:
        from fontTools.varLib import instancer

        pins = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
        pins.update({k: v for k, v in axes if k in pins})
        font = instancer.instantiateVariableFont(font, pins, inplace=False)
    return font


def load_ttfont(resolved: ResolvedFont | Path | str) -> TTFont:
    """Load a font file; variable fonts are instantiated (registry ``axes`` pins, else defaults)."""
    if isinstance(resolved, ResolvedFont):
        return _load_ttfont(str(resolved.path), resolved.spec.axes)
    return _load_ttfont(str(Path(resolved)))


def missing_glyphs(font: TTFont, text: str) -> list[str]:
    """Characters of ``text`` (excluding whitespace/newlines) the font has no glyph for."""
    cmap = font.getBestCmap()
    seen: list[str] = []
    for ch in text:
        if ch.isspace() or ch in seen:
            continue
        if ord(ch) not in cmap:
            seen.append(ch)
    return seen


def with_weight(font: ResolvedFont, weight: float) -> ResolvedFont:
    """The same variable font pinned to another weight (e.g. Montserrat 700); static fonts are returned unchanged."""
    from dataclasses import replace

    axes = dict(font.spec.axes)
    if "wght" not in axes and not font.path.name.lower().endswith("-variable.ttf"):
        return font
    axes["wght"] = float(weight)
    spec = replace(font.spec, id=f"{font.spec.id}-{int(weight)}", weight=float(weight), axes=tuple(axes.items()))
    return replace(font, spec=spec)
