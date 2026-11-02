"""Floorplan: hard macros placed in the core. Pure Python, no GUI imports.

Macro coordinates are in µm with the origin at the top-left corner of the macro and y pointing
down, like the rest of the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class MacroPin:
    """A pin of a macro as read from the LEF. ``x``/``y``: unrotated macro coordinates."""
    name: str
    direction: str = ""     # LEF DIRECTION, e.g. "INPUT", "OUTPUT TRISTATE"
    use: str = "SIGNAL"     # LEF USE: SIGNAL, POWER, GROUND, ANALOG, CLOCK
    x: float = 0.0
    y: float = 0.0


@dataclass
class MacroDef:
    """Size and pins of a macro (LEF ``MACRO``)."""
    name: str
    w: float
    h: float
    pins: List[MacroPin] = field(default_factory=list)


POWER_USES = ("POWER", "GROUND")


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class Macro:
    """A placed macro instance. ``x``/``y``: top-left of the placed (rotated) box in core coordinates.

    ``path`` is the macro directory (LibreLane run output); ``""`` makes a placeholder whose size is
    typed in. ``cache`` holds the last values read from the LEF. ``io`` lists the pins marked as
    off-chip signals.
    """
    name: str
    macro: str = ""
    path: str = ""
    x: float = 0.0
    y: float = 0.0
    rot: int = 0
    io: List[str] = field(default_factory=list)
    cache: Optional[MacroDef] = None

    @classmethod
    def from_dir(cls, path: str, name: str) -> "Macro":
        """New instance of the macro in a LibreLane run directory. Raises ``ValueError``/``OSError``."""
        lef = find_lef(path)
        if lef is None:
            raise ValueError(f"No LEF found in {Path(path) / 'final' / 'lef'}")
        mdef = _read_macro(lef, path)
        return cls(name, mdef.name, str(path), cache=mdef)

    @property
    def placeholder(self):
        return not self.path

    def size(self) -> Tuple[float, float]:
        w, h = (self.cache.w, self.cache.h) if self.cache else (0.0, 0.0)
        return (h, w) if self.rot % 180 else (w, h)

    def pin_xy(self, pin: MacroPin) -> Tuple[float, float]:
        """Core coordinates of a pin, with the rotation (90° steps clockwise) applied."""
        x, y = pin.x, pin.y
        w, h = self.cache.w, self.cache.h
        for _ in range((self.rot // 90) % 4):
            x, y = h - y, x
            w, h = h, w
        return self.x + x, self.y + y

    def signal_pins(self) -> List[MacroPin]:
        return [p for p in (self.cache.pins if self.cache else []) if p.use not in POWER_USES]

    def io_pins(self) -> List[MacroPin]:
        return [p for p in self.signal_pins() if p.name in self.io]

    def to_dict(self):
        d = {"name": self.name, "macro": self.macro, "path": self.path, "x": self.x, "y": self.y,
             "rot": self.rot, "io": list(self.io)}
        if self.cache:
            d["cache"] = {"name": self.cache.name, "w": self.cache.w, "h": self.cache.h,
                          "pins": [{"name": p.name, "dir": p.direction, "use": p.use, "x": p.x, "y": p.y}
                                   for p in self.cache.pins]}
        return d

    @classmethod
    def from_dict(cls, d):
        """Raises ``KeyError``/``TypeError``/``AttributeError`` for entries that are no macro."""
        c = d.get("cache")
        cache = None
        if isinstance(c, dict):
            pins = [MacroPin(str(p["name"]), str(p.get("dir", "")), str(p.get("use", "SIGNAL")),
                             _f(p.get("x")), _f(p.get("y"))) for p in c.get("pins", []) if isinstance(p, dict)]
            cache = MacroDef(str(c.get("name", "")), _f(c.get("w")), _f(c.get("h")), pins)
        rot = int(_f(d.get("rot"))) % 360
        return cls(str(d["name"]), str(d.get("macro", "")), str(d.get("path", "")), _f(d.get("x")),
                   _f(d.get("y")), rot - rot % 90, [str(n) for n in d.get("io", [])], cache)



@dataclass
class Floorplan:
    macros: List[Macro] = field(default_factory=list)

    def reload(self) -> List[str]:
        """Read the LEF of every macro again (once per directory); returns warnings.

        A macro whose LEF cannot be read keeps its last known values. Marked pins that are no
        longer in the LEF stay marked but are skipped.
        """
        warnings, read = [], {}
        for m in self.macros:
            if m.placeholder:
                continue
            if m.path not in read:
                lef = find_lef(m.path)
                try:
                    read[m.path] = _read_macro(lef, m.path) if lef else None
                except (OSError, ValueError):
                    read[m.path] = None
            mdef = read[m.path]
            if mdef is None:
                warnings.append(f"No LEF found for {m.name} ({m.path}), using last known values")
                continue
            m.cache, m.macro = mdef, mdef.name
            names = {p.name for p in mdef.pins}
            warnings += [f"Pin {n} of {m.name} no longer in the LEF" for n in m.io if n not in names]
        return warnings

    def instance_name(self, macro: str) -> str:
        """First free instance name ``<macro>0``, ``<macro>1``, …"""
        names = {m.name for m in self.macros}
        k = 0
        while f"{macro}{k}" in names:
            k += 1
        return f"{macro}{k}"

    def to_dict(self):
        return {"macros": [m.to_dict() for m in self.macros]}

    @classmethod
    def from_dict(cls, d):
        macros = []
        for m in (d.get("macros", []) if isinstance(d, dict) else []):
            try:
                macros.append(Macro.from_dict(m))
            except (KeyError, TypeError, AttributeError, ValueError):
                pass  # not a macro entry
        return cls(macros)


def find_lef(path) -> Optional[Path]:
    """``<path>/final/lef/<dirname>_top.lef``, else the only ``*.lef`` there, else ``None``."""
    d = Path(path) / "final" / "lef"
    top = d / f"{Path(path).name}_top.lef"
    if top.is_file():
        return top
    found = sorted(d.glob("*.lef")) if d.is_dir() else []
    return found[0] if len(found) == 1 else None


def _read_macro(lef, path) -> MacroDef:
    from ..formats.lef import pick_macro, read_lef  # formats imports the model
    return pick_macro(read_lef(lef), Path(path).name)


def core_origin(layout, settings) -> Tuple[float, float]:
    """Die coordinates of the top-left corner of the floorplan core, centred in the core area
    (die minus IO ring and core margin, LibreLane CORE_AREA)."""
    st = settings.sanitized()
    m = layout.ring_depth + layout.core_margin
    return (m + (layout.die_width - 2 * m - st.core_width) / 2,
            m + (layout.die_height - 2 * m - st.core_height) / 2)


def nearest_side(x: float, y: float, die_w: float, die_h: float) -> str:
    """Die side closest to a point in die coordinates; ties go T, R, B, L."""
    d = {"T": y, "R": die_w - x, "B": die_h - y, "L": x}
    return min(("T", "R", "B", "L"), key=lambda s: d[s])


def _overlap(a, b):
    (aw, ah), (bw, bh) = a.size(), b.size()
    return a.x < b.x + bw and b.x < a.x + aw and a.y < b.y + bh and b.y < a.y + ah


def floorplan_warnings(project) -> List[str]:
    st = project.settings.sanitized()
    macros = project.floorplan.macros
    out = []
    for i, a in enumerate(macros):
        for b in macros[i + 1:]:
            if _overlap(a, b):
                out.append(f"Macros {a.name} and {b.name} overlap")
    eps = 1e-6
    for m in macros:
        w, h = m.size()
        if m.x < -eps or m.y < -eps or m.x + w > st.core_width + eps or m.y + h > st.core_height + eps:
            out.append(f"Macro {m.name} outside the core")
    return out


def utilization(project) -> float:
    """Macro area / core area."""
    st = project.settings.sanitized()
    area = sum(w * h for w, h in (m.size() for m in project.floorplan.macros))
    return area / (st.core_width * st.core_height)
