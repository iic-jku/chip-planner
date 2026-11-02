"""Floorplan view: die and IO ring of the layout, the core and draggable macros."""

import math

from ..model.floorplan import core_origin, nearest_side, overlapping
from ..model.parse import classify
from .qt import (QBrush, QColor, QFont, QGraphicsItem, QGraphicsRectItem, QGraphicsSimpleTextItem, QPointF,
                 QRectF, Qt, QTimer, QTransform)
from .scene import fill_scene, make_pen, mono_family

MAX_GRID_LINES = 60  # per axis; a denser grid is drawn with every n-th line only


def pin_type(pin):
    """Palette type of a macro pin, for its marker and flyline."""
    if pin.use == "ANALOG":
        return "ana"
    if pin.use == "CLOCK":
        return "clk"
    t = classify(pin.name)
    return t if t in ("ana", "rf", "clk") else "dig"


def _text(scene_or_parent, text, size, color, bold=False):
    item = QGraphicsSimpleTextItem(text)
    font = QFont(mono_family())
    font.setPixelSize(100)
    font.setBold(bold)
    item.setFont(font)
    item.setBrush(QBrush(QColor(color)))
    item.setScale(size / 100.0)
    if isinstance(scene_or_parent, QGraphicsItem):
        item.setParentItem(scene_or_parent)
    else:
        scene_or_parent.addItem(item)
    return item


class MacroItem(QGraphicsRectItem):
    """A macro instance. The item position is the top-left of the placed macro in die coordinates."""

    def __init__(self, macro, ctx):
        w, h = macro.size()
        super().__init__(0.0, 0.0, w, h)
        self.macro, self.ctx = macro, ctx
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setZValue(2)
        self.flylines = []
        x0, y0 = ctx["origin"]
        self.setPos(x0 + macro.x, y0 + macro.y)  # as stored, also outside the core (warning)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            x0, y0 = self.ctx["origin"]
            g, (cw, ch) = self.ctx["grid"], self.ctx["core"]
            w, h = self.macro.size()
            x = min(max(round((value.x() - x0) / g) * g, 0.0), max(0.0, cw - w))
            y = min(max(round((value.y() - y0) / g) * g, 0.0), max(0.0, ch - h))
            return QPointF(x0 + x, y0 + y)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            x0, y0 = self.ctx["origin"]
            self.macro.x, self.macro.y = round(self.pos().x() - x0, 6), round(self.pos().y() - y0, 6)
            if self.ctx.get("on_move"):
                self.ctx["on_move"](self)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.ctx.get("on_release"):
            self.ctx["on_release"](self.macro)

    def mouseDoubleClickEvent(self, e):
        if self.ctx.get("on_rotate"):  # later: rotating rebuilds the scene, which deletes this item
            QTimer.singleShot(0, lambda m=self.macro, f=self.ctx["on_rotate"]: f(m))
        e.accept()


def _draw_flylines(scene, item, layout, pal, fs):
    for it in item.flylines:
        scene.removeItem(it)
    item.flylines = []
    m = item.macro
    x0, y0 = item.ctx["origin"]
    W, H = layout.die_width, layout.die_height
    for p in m.io_pins():
        px, py = m.pin_xy(p)
        x, y = x0 + px, y0 + py
        side = nearest_side(x, y, W, H)
        ex, ey = {"T": (x, 0.0), "B": (x, H), "L": (0.0, y), "R": (W, y)}[side]
        color = pal["types"][pin_type(p)][1]
        line = scene.addLine(x, y, ex, ey, make_pen(color, 1.2, [4, 3]))
        line.setZValue(1)
        label = _text(scene, p.name, fs, color, bold=True)
        br = label.boundingRect()
        k = fs / 100.0
        gap = fs * 0.4
        if side in "LR":
            lx = ex - gap - br.width() * k if side == "L" else ex + gap
            label.setPos(lx, ey - br.height() * k / 2)
        else:  # vertical text, reading upwards, outside the die
            label.setTransform(QTransform().rotate(-90))
            ly = ey - gap if side == "T" else ey + gap + br.width() * k
            label.setPos(ex - br.height() * k / 2, ly)
        item.flylines += [line, label]


def fill_floorplan(scene, project, layout, pal, show_grid=True, on_move=None, on_release=None, on_rotate=None):
    """Draw the floorplan; returns the :class:`MacroItem` list."""
    fill_scene(scene, layout, pal)
    st = project.settings.sanitized()
    x0, y0 = core_origin(layout, project.settings)
    cw, ch = st.core_width, st.core_height
    fs = min(st.std.pitch * 0.5, layout.ring_depth * 0.36)

    core = scene.addRect(QRectF(x0, y0, cw, ch), make_pen(pal["fg"], 1.5), QBrush(QColor(pal["surface"])))
    core.setZValue(0.5)
    if show_grid:
        step = st.grid * max(1, math.ceil(max(cw, ch) / st.grid / MAX_GRID_LINES))
        pen = make_pen(pal["line"], 0.5)
        n = int(cw / step + 1e-9)
        for i in range(n + 1):
            scene.addLine(x0 + i * step, y0, x0 + i * step, y0 + ch, pen).setZValue(0.6)
        n = int(ch / step + 1e-9)
        for i in range(n + 1):
            scene.addLine(x0, y0 + i * step, x0 + cw, y0 + i * step, pen).setZValue(0.6)
    label = _text(scene, f"Core {cw:g} × {ch:g} µm", fs, pal["muted"])
    label.setPos(x0, y0 - fs * 1.4)  # above the core, macros may cover its corners
    label.setZValue(0.7)

    bad = {m.name for pair in overlapping(project.floorplan.macros) for m in pair}
    ctx = {"origin": (x0, y0), "grid": st.grid, "core": (cw, ch), "on_release": on_release, "on_rotate": on_rotate}
    items = []
    for m in project.floorplan.macros:
        w, h = m.size()
        item = MacroItem(m, ctx)
        item.setPen(make_pen(pal["warn"] if m.name in bad else pal["accent"], 2.5 if m.name in bad else 1.5,
                             [6, 4] if m.placeholder else None))
        item.setBrush(QBrush(QColor(pal["cell"])))
        scene.addItem(item)
        mfs = max(fs, min(w, h) / 12)
        name = _text(item, m.name, mfs, pal["fg"], bold=True)
        k = mfs / 100.0
        name.setPos(w / 2 - name.boundingRect().width() * k / 2, h / 2 - name.boundingRect().height() * k)
        sub = _text(item, f"{w:g} × {h:g} µm" + (" · placeholder" if m.placeholder else ""), mfs * 0.6,
                    pal["muted"])
        sub.setPos(w / 2 - sub.boundingRect().width() * k * 0.6 / 2, h / 2)
        r = max(2.0, min(w, h) / 60)
        io = set(m.io)
        for p in m.signal_pins():
            px, py = m.pin_xy(p)
            fill, outline = pal["types"][pin_type(p)]
            marker = QGraphicsRectItem(px - m.x - r, py - m.y - r, 2 * r, 2 * r, item)
            marker.setPen(make_pen(outline, 1.2))
            marker.setBrush(QBrush(QColor(outline if p.name in io else fill)))
        items.append(item)

    def moved(item):
        _draw_flylines(scene, item, layout, pal, fs)
        if on_move:
            on_move(item.macro)
    for item in items:
        _draw_flylines(scene, item, layout, pal, fs)
    ctx["on_move"] = moved
    return items
