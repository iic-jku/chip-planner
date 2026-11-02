"""Floorplan: hard macros placed in the core. Pure Python, no GUI imports.

Macro coordinates are in µm with the origin at the top-left corner of the macro and y pointing
down, like the rest of the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


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
