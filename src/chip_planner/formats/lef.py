"""Minimal LEF reader: macro size and pins (LibreLane ``final/lef`` output). Stdlib only."""

from __future__ import annotations

import re
from typing import List

from ..model.floorplan import MacroDef, MacroPin

_NUM = re.compile(r"^-?\d+(\.\d*)?([eE][-+]?\d+)?$")


_LINE_STATEMENTS = {"MACRO", "PIN", "PORT", "OBS", "END", "UNITS", "PROPERTYDEFINITIONS"}


def _statements(text):
    """Yield the token lists of the statements. Most end with ``;``; block lines such as
    ``MACRO x``, ``PIN x``, ``PORT`` and ``END x`` end at the line end."""
    cur = []
    for raw in text.splitlines():
        toks = re.findall(r'"[^"]*"|;|[^\s;]+', raw.split("#", 1)[0])
        if not cur and toks and toks[0].upper() in _LINE_STATEMENTS and ";" not in toks:
            yield toks
            continue
        for tok in toks:
            if tok == ";":
                if cur:
                    yield cur
                cur = []
            else:
                cur.append(tok)
    if cur:
        yield cur


def _coords(tokens):
    return [float(t) for t in tokens if _NUM.match(t)]


def parse_lef(text) -> List[MacroDef]:
    """All macros of a LEF text. Raises ``ValueError`` if there is none."""
    macros = []
    macro = pin = None
    origin = (0.0, 0.0)
    pin_shape = None        # bounding box of the first shape of the current pin
    shapes = {}             # pin name -> bounding box (x0, y0, x1, y1) in LEF coordinates
    in_obs = in_port = False
    for st in _statements(text):
        key = st[0].upper()
        if in_obs:
            if key == "END" and len(st) == 1:
                in_obs = False
            continue
        if key == "MACRO" and len(st) > 1:
            macro = MacroDef(st[1], 0.0, 0.0)
            origin, shapes = (0.0, 0.0), {}
        elif macro is None:
            continue
        elif key == "ORIGIN":
            c = _coords(st[1:])
            origin = (c[0], c[1]) if len(c) >= 2 else origin
        elif key == "SIZE":
            c = _coords(st[1:])
            if len(c) >= 2:
                macro.w, macro.h = c[0], c[1]
        elif key == "PIN" and len(st) > 1 and pin is None:
            pin = MacroPin(st[1])
            pin_shape = None
        elif key == "OBS":
            in_obs = True
        elif pin is not None:
            if key == "DIRECTION":
                pin.direction = " ".join(st[1:]).upper()
            elif key == "USE" and len(st) > 1:
                pin.use = st[1].upper()
            elif key == "PORT":
                in_port = True
            elif key in ("RECT", "POLYGON") and in_port and pin_shape is None:
                c = _coords(st[1:])
                if len(c) >= 4:
                    xs, ys = c[0::2], c[1::2]
                    pin_shape = (min(xs), min(ys), max(xs), max(ys))
            elif key == "END":
                if len(st) == 1 and in_port:
                    in_port = False
                elif len(st) > 1 and st[1] == pin.name:
                    macro.pins.append(pin)
                    if pin_shape:
                        shapes[pin.name] = pin_shape
                    pin = None
        elif key == "END" and len(st) > 1 and st[1] == macro.name:
            for p in macro.pins:  # LEF: origin lower-left, y up -> model: top-left, y down
                if p.name in shapes:
                    x0, y0, x1, y1 = shapes[p.name]
                    p.x = (x0 + x1) / 2 + origin[0]
                    p.y = macro.h - ((y0 + y1) / 2 + origin[1])
                else:
                    p.x, p.y = macro.w / 2, macro.h / 2
            macros.append(macro)
            macro = None
    if not macros:
        raise ValueError("no MACRO in the LEF file")
    return macros


def read_lef(path) -> List[MacroDef]:
    """Read a LEF file. Raises ``OSError`` or ``ValueError``."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_lef(f.read())


def pick_macro(macros: List[MacroDef], dirname: str) -> MacroDef:
    """The macro named ``<dirname>_top`` if present, else the first one."""
    for m in macros:
        if m.name == f"{dirname}_top":
            return m
    return macros[0]
