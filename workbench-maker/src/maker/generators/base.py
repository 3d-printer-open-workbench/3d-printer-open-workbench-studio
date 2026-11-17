"""Generator = one product (thermoform mold, keychain, QR plaque, ...).

A generator declares its parameters (the web form and the MCP schema are built from them) and a ``build``
function that returns printable parts. To add one: create ``generators/<key>.py`` with ``GENERATOR = Generator(...)``
and list it in ``generators/__init__.py``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

import trimesh

ParamType = Literal["number", "int", "text", "bool", "choice", "color", "font", "sheet", "file"]


@dataclass
class Param:
    key: str
    label: str  # Turkish UI label
    type: ParamType
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)  # choice: (value, Turkish label)
    help: str = ""
    section: str = "Genel"  # form group heading
    show_if: dict = field(default_factory=dict)  # UI: only shown when other params have these values

    def coerce(self, v: Any) -> Any:
        if v is None or (v == "" and self.type != "text"):  # a cleared text field means "no text", not the default
            return self.default
        if self.type in ("number", "int"):
            x = float(v) if self.type == "number" else int(round(float(v)))
            if self.min is not None and x < self.min or self.max is not None and x > self.max:
                raise ValueError(f"{self.label}: {self.min}–{self.max} {self.unit} aralığında olmalı (verilen {x})")
            return x
        if self.type == "bool":
            return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "evet", "on")
        if self.type == "choice" and self.options and str(v) not in {o[0] for o in self.options}:
            raise ValueError(f"{self.label}: geçersiz seçim {v!r}")
        return str(v)


@dataclass
class Part:
    name: str  # ascii file stem
    label: str  # Turkish
    mesh: trimesh.Trimesh  # print orientation, mm
    color: str = "#DDDDDD"
    material: str = "PLA"
    meta: dict = field(default_factory=dict)
    printable: bool = True  # False: preview only (e.g. the formed sheet), no STL


@dataclass
class SheetLayout:
    """1:1 sheet template (front view of the finished piece, mm, sheet centred on the origin)."""
    size_mm: tuple[float, float]  # blank to cut
    shapes: list  # shapely polygons: dome footprints (for aligning the formed sheet)
    trims: list  # shapely polygons: trim lines after forming
    title: str = ""
    lines: list[str] = field(default_factory=list)  # info printed on the template


@dataclass
class BuildResult:
    parts: list[Part]
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # how-to lines for the user (not problems)
    sheet: SheetLayout | None = None  # thermoform: written as sheet_template.pdf


@dataclass
class Generator:
    key: str
    label: str
    group: str  # catalogue group (Turkish), e.g. "Yılbaşı", "Anahtarlık"
    description: str
    params: list[Param]
    build: Callable[[dict], BuildResult] | None = None
    status: Literal["ready", "planned"] = "ready"
    milestone: str = ""  # planned generators: when they arrive (T1, T5, ...)

    def values(self, given: dict | None) -> dict:
        """Validated parameter values (defaults filled in); unknown keys are rejected."""
        given = dict(given or {})
        known = {p.key for p in self.params}
        extra = set(given) - known
        if extra:
            raise ValueError(f"bilinmeyen parametre: {', '.join(sorted(extra))}")
        return {p.key: p.coerce(given.get(p.key)) for p in self.params}

    def run(self, given: dict | None) -> BuildResult:
        if self.status != "ready" or self.build is None:
            raise ValueError(f"{self.label} henüz hazır değil ({self.milestone or 'planlandı'})")
        return self.build(self.values(given))

    def schema(self) -> dict:
        return {"key": self.key, "label": self.label, "group": self.group, "description": self.description,
                "status": self.status, "milestone": self.milestone, "params": [asdict(p) for p in self.params]}
