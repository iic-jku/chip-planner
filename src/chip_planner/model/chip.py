"""Chip view: pads and macros together. Analysis (flylines, crossings, analog and power checks)
and the edits of the Chip view. Pure Python, no GUI imports.

Positions are die coordinates in µm (origin top-left, y down). Line indices are in physical
order (top/bottom left → right, left/right top → bottom), as in the side editors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .constants import SIDES
from .floorplan import _function, _overlap, core_area, floorplan_warnings, nearest_side
from .parse import parse_line

Point = Tuple[float, float]


@dataclass
class Flyline:
    instance: str
    pin: str
    pad: str
    side: str
    line: int            # physical line index of the pad
    p: Point             # macro pin
    q: Point             # inner edge of the IO ring at the pad
    length: float
    sensitive: bool
    crossing: bool = False


@dataclass
class MissingPin:
    """A checked macro pin without a pad; ``q`` and ``pos`` where it would go."""
    instance: str
    pin: str
    name: str
    side: str
    pos: float           # along the side, die coordinates
    function: Optional[str]
    p: Point
    q: Point


@dataclass
class SupplySuggestion:
    instance: str
    name: str
    function: str        # "vdd" or "vss"
    side: str
    index: int           # insert position, physical line index


@dataclass
class ChipCheck:
    flylines: List[Flyline] = field(default_factory=list)
    missing: List[MissingPin] = field(default_factory=list)
    crossings: int = 0
    longest: Optional[Flyline] = None
    supplies: List[SupplySuggestion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def diff_partner(name: str) -> Optional[str]:
    """Name of the other half of a differential pair (final P ↔ N), or ``None``."""
    if len(name) > 1 and name[-1] in "PN":
        return name[:-1] + ("N" if name[-1] == "P" else "P")
    return None


def _inner_point(layout, side, along) -> Point:
    """Point on the inner edge of the IO ring at ``along`` (die coordinate along the side)."""
    H, W, D = layout.ring_depth, layout.die_width, layout.die_height
    return {"T": (along, H), "B": (along, D - H), "L": (H, along), "R": (W - H, along)}[side]


def _along(pin_or_split, layout) -> float:
    return layout.ring_depth + (pin_or_split.a + pin_or_split.b) / 2


def _pad_names(project) -> Dict[str, Tuple[str, int]]:
    """Name of every single-pad line → (side, physical line index); first one wins."""
    out = {}
    for s in SIDES:
        for i, line in enumerate(project.physical_lines(s)):
            e = parse_line(line)
            if e and not e["split"] and not e["group"] and e["name"] not in out:
                out[e["name"]] = (s, i)
    return out


def _pad_name_of(project) -> Dict[Tuple[str, str], str]:
    """(instance, pin) → pad name: the pin name, or ``<instance>_<pin>`` if several instances use it."""
    pins = [(m.name, p.name) for m in project.floorplan.macros for p in m.io_pins()]
    count = {}
    for _, n in pins:
        count[n] = count.get(n, 0) + 1
    return {(i, n): n if count[n] == 1 else f"{i}_{n}" for i, n in pins}


def _pins_by_line(project, layout):
    """(side, physical line index) → list of layout pins on that line."""
    out = {}
    for pin in layout.pins:
        i = project.physical_line_index(pin.side, pin.line)
        out.setdefault((pin.side, i), []).append(pin)
    return out


def drop_index(layout, project, side, along) -> int:
    """Physical insert index for a drop at ``along`` (die coordinate along ``side``), by slot centres.

    Spacer lines have no geometry in the layout; their centres are interpolated from the neighbours.
    """
    lines = project.physical_lines(side)
    by_line = _pins_by_line(project, layout)
    centres: List[Optional[float]] = []
    splits = {project.physical_line_index(sp.side, sp.line): sp for sp in layout.splits if sp.side == side}
    for i in range(len(lines)):
        pins = by_line.get((side, i))
        if pins:
            centres.append(sum(_along(p, layout) for p in pins) / len(pins))
        elif i in splits:
            centres.append(_along(splits[i], layout))
        else:
            centres.append(None)
    pitch = project.settings.sanitized().std.pitch
    for i, c in enumerate(centres):  # spacers: half way between known neighbours
        if c is None:
            prev = next((centres[j] for j in range(i - 1, -1, -1) if centres[j] is not None), None)
            nxt = next((centres[j] for j in range(i + 1, len(centres)) if centres[j] is not None), None)
            if prev is not None and nxt is not None:
                centres[i] = (prev + nxt) / 2
            elif prev is not None:
                centres[i] = prev + pitch
            elif nxt is not None:
                centres[i] = nxt - pitch
            else:
                centres[i] = layout.ring_depth + pitch * (i + 0.5)
    for i, c in enumerate(centres):
        if along < c:
            return i
    return len(lines)


def _cross(a: Flyline, b: Flyline) -> bool:
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-9) - (v < -1e-9)
    if {a.p, a.q} & {b.p, b.q}:
        return False
    return (orient(a.p, a.q, b.p) * orient(a.p, a.q, b.q) < 0
            and orient(b.p, b.q, a.p) * orient(b.p, b.q, a.q) < 0)


def _rect(m, grow=0.0):
    w, h = m.size()
    return m.x - grow, m.y - grow, m.x + w + grow, m.y + h + grow


def _gap(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return math.hypot(max(0.0, ax0 - bx1, bx0 - ax1), max(0.0, ay0 - by1, by0 - ay1))


def _type_class(typ):
    return "sensitive" if typ in ("ana", "rf") else "noisy" if typ in ("clk", "dig") else None


def _supply_name(m, function, domain):
    use = "POWER" if function == "vdd" else "GROUND"
    for p in (m.cache.pins if m.cache else []):
        if p.use == use:
            return p.name
    base = "VDD" if function == "vdd" else "VSS"
    return f"{base}_{domain}" if domain else base


def analyse(project, layout=None) -> ChipCheck:
    """Flylines, crossings, missing pads, analog/RF and power checks of a project."""
    layout = layout or project.layout()
    st = project.settings.sanitized()
    x0, y0, _, _ = core_area(layout)
    W, D = layout.die_width, layout.die_height
    out = ChipCheck(warnings=list(floorplan_warnings(project, layout)))
    macros = project.floorplan.macros

    by_line = _pins_by_line(project, layout)
    names = _pad_names(project)
    pad_of = _pad_name_of(project)
    pad_class = {}  # pad name -> class taken from a connected macro
    for m in macros:
        for p in m.io_pins():
            px, py = m.pin_xy(p)
            pt = (x0 + px, y0 + py)
            name = pad_of[(m.name, p.name)]
            if name in names:
                side, i = names[name]
                pin = by_line[(side, i)][0]
                q = _inner_point(layout, side, _along(pin, layout))
                cls = m.cls if m.cls != "normal" else _type_class(pin.type)
                if m.cls != "normal":
                    pad_class[name] = m.cls
                out.flylines.append(Flyline(m.name, p.name, name, side, i, pt, q,
                                            math.hypot(pt[0] - q[0], pt[1] - q[1]), cls == "sensitive"))
            else:
                side = nearest_side(pt[0], pt[1], W, D)
                along = pt[0] if side in "TB" else pt[1]
                out.missing.append(MissingPin(m.name, p.name, name, side, along, _function(p), pt,
                                              _inner_point(layout, side, along)))

    fl = out.flylines
    for i, a in enumerate(fl):
        for b in fl[i + 1:]:
            if _cross(a, b):
                a.crossing = b.crossing = True
                out.crossings += 1
    sens = [f for f in fl if f.sensitive]
    out.longest = max(sens, key=lambda f: f.length) if sens else None

    # differential pairs and sensitive/noisy neighbours, per side in physical order
    for s in SIDES:
        lines = project.physical_lines(s)
        entries = [parse_line(l) for l in lines]
        single = {e["name"]: i for i, e in enumerate(entries) if e and not e["split"] and not e["group"]}
        for n, i in single.items():
            q = diff_partner(n)
            if n.endswith("P") and q in single and abs(single[q] - i) != 1:
                out.warnings.append(f"Differential pair {n}/{q} not adjacent")
        for i in range(len(lines) - 1):
            a, b = entries[i], entries[i + 1]
            if not (a and b) or a["split"] or b["split"] or a["group"] or b["group"]:
                continue  # spacers, splits and shielded groups break the adjacency
            pa, pb = by_line.get((s, i)), by_line.get((s, i + 1))
            if not (pa and pb):
                continue
            ca = pad_class.get(a["name"]) or _type_class(pa[0].type)
            cb = pad_class.get(b["name"]) or _type_class(pb[0].type)
            if {ca, cb} == {"sensitive", "noisy"}:
                out.warnings.append(f"Sensitive pad next to noisy pad: {a['name']} – {b['name']}")

    # halos and spacing between sensitive and noisy macros
    for i, a in enumerate(macros):
        for b in macros[i + 1:]:
            ha = st.halo if a.halo is None else a.halo
            hb = st.halo if b.halo is None else b.halo
            gap = _gap(_rect(a), _rect(b))
            if not _overlap(a, b) and gap < ha + hb:  # overlapping macros get their own warning
                out.warnings.append(f"Halos of {a.name} and {b.name} overlap")
            if {a.cls, b.cls} == {"sensitive", "noisy"} and gap < st.spacing:
                s_, n_ = (a, b) if a.cls == "sensitive" else (b, a)
                out.warnings.append(f"{s_.name} (sensitive) closer than {st.spacing:g} µm to {n_.name} (noisy)")
    for f in sens:
        if f.length > st.max_flyline:
            out.warnings.append(f"Flyline {f.pin} {round(f.length)} µm (limit {st.max_flyline:g} µm)")

    # supplies: a VDD and a VSS pad (by function) of the macro's domain within reach
    splits = bool(layout.splits)
    for m in macros:
        w, h = m.size()
        cx, cy = x0 + m.x + w / 2, y0 + m.y + h / 2
        dom_pins = [q for q in layout.pins if not m.domain or not splits or q.domain == m.domain]
        for function, kind in (("vdd", "VDD"), ("vss", "VSS")):
            near = [math.hypot(*(a - b for a, b in zip(_inner_point(layout, q.side, _along(q, layout)), (cx, cy))))
                    for q in dom_pins if q.function == function]
            if near and min(near) <= st.max_supply_dist:
                continue
            dom = m.domain if splits and m.domain else "ring"
            out.warnings.append(f"{m.name}: no {kind} pad of domain {dom} within {st.max_supply_dist:g} µm")
            out.supplies.append(_suggest(project, layout, m, function, dom_pins, (cx, cy), splits))
    if out.missing:
        out.warnings.append(f"{len(out.missing)} checked pins without pad: "
                            + ", ".join(x.name for x in out.missing))
    return out


def _suggest(project, layout, m, function, dom_pins, centre, splits) -> SupplySuggestion:
    """Next to the domain pad closest to the macro, on the macro's side of it."""
    name = _supply_name(m, function, m.domain if splits else "")
    cx, cy = centre
    if dom_pins:
        q = min(dom_pins, key=lambda q: math.hypot(*(a - b for a, b in
                                                     zip(_inner_point(layout, q.side, _along(q, layout)), centre))))
        i = project.physical_line_index(q.side, q.line)
        toward = (cx if q.side in "TB" else cy) > _along(q, layout)
        return SupplySuggestion(m.name, name, function, q.side, i + 1 if toward else i)
    side = nearest_side(cx, cy, layout.die_width, layout.die_height)
    return SupplySuggestion(m.name, name, function, side,
                            drop_index(layout, project, side, cx if side in "TB" else cy))
