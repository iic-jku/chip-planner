"""Macro list of the Floorplan tab: one box per instance with its pins."""

from .qt import (QCheckBox, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                 QVBoxLayout, QWidget)
from .scene import mono_family


class MacroPanel(QWidget):
    """Shows ``floorplan`` and edits it in place; calls ``on_change(rebuild)`` after every edit.

    ``actions`` maps "add", "placeholder", "reload", "rotate", "duplicate", "remove" to callbacks of
    the main window (the last three take the macro).
    """

    def __init__(self, pal, on_change, actions, parent=None):
        super().__init__(parent)
        self.pal, self.on_change, self.actions = pal, on_change, actions
        self.floorplan = None
        lv = QVBoxLayout(self)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        lv.addWidget(self.scroll, 1)
        bar = QHBoxLayout()
        for text, key in (("Add Macro…", "add"), ("Add Placeholder…", "placeholder"), ("Reload", "reload")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=key: self.actions[k]())
            bar.addWidget(b)
        bar.addStretch(1)
        lv.addLayout(bar)
        hint = QLabel("Add a macro by its LibreLane run directory: size and pins come from "
                      "<code>final/lef/&lt;name&gt;_top.lef</code>. Check the pins that go off-chip. "
                      "Drag a macro to move it, double-click rotates it by 90°.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {pal['muted']};")
        lv.addWidget(hint)
        self.boxes = []

    def set_floorplan(self, floorplan):
        self.floorplan = floorplan
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.boxes = [self._box(m) for m in floorplan.macros]
        for b in self.boxes:
            v.addWidget(b)
        if not self.boxes:
            empty = QLabel("No macros yet.")
            empty.setStyleSheet(f"color: {self.pal['muted']};")
            v.addWidget(empty)
        v.addStretch(1)
        self.scroll.setWidget(inner)

    def _box(self, m):
        pal, mono = self.pal, mono_family()
        box = QGroupBox()
        bv = QVBoxLayout(box)
        bv.setSpacing(3)
        head = QHBoxLayout()
        name = QLineEdit(m.name)
        name.setToolTip("Instance name")

        def rename(m=m, name=name):
            new = name.text().strip()
            if new and new != m.name and all(o.name != new for o in self.floorplan.macros):
                m.name = new
                self.on_change(False)
            else:
                name.setText(m.name)
        name.editingFinished.connect(rename)
        head.addWidget(name, 1)
        w, h = m.size()
        size = QLabel(f"{w:g} × {h:g} µm · R{m.rot}")
        size.setStyleSheet(f"color: {pal['muted']}; font-family: '{mono}';")
        head.addWidget(size)
        bv.addLayout(head)
        path = m.path if len(m.path) <= 48 else "…" + m.path[-47:]
        src = QLabel(path if not m.placeholder else "placeholder, no LEF")
        src.setStyleSheet(f"color: {pal['muted']}; font-family: '{mono}';")
        src.setToolTip(m.path)
        bv.addWidget(src)
        power = []
        for p in (m.cache.pins if m.cache else []):
            if p not in m.signal_pins():
                power.append(p.name)
                continue
            cb = QCheckBox(p.name)
            cb.setStyleSheet(f"font-family: '{mono}';")
            cb.setChecked(p.name in m.io)
            cb.setToolTip(f"{p.direction or 'no direction'}, {p.use} · checked: off-chip IO, unchecked: internal")
            cb.toggled.connect(lambda on, m=m, n=p.name: self._toggle(m, n, on))
            bv.addWidget(cb)
        stale = [n for n in m.io if n not in {p.name for p in m.signal_pins()}]
        if power:
            lab = QLabel("Power: " + ", ".join(power))
            lab.setStyleSheet(f"color: {pal['muted']};")
            bv.addWidget(lab)
        if stale:
            lab = QLabel("Not in the LEF: " + ", ".join(stale))
            lab.setStyleSheet(f"color: {pal['warn']};")
            bv.addWidget(lab)
        btns = QHBoxLayout()
        for text, key in (("Rotate", "rotate"), ("Duplicate", "duplicate"), ("Remove", "remove")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=key, m=m: self.actions[k](m))
            btns.addWidget(b)
        btns.addStretch(1)
        bv.addLayout(btns)
        return box

    def _toggle(self, m, name, on):
        if on and name not in m.io:
            m.io.append(name)
        elif not on and name in m.io:
            m.io.remove(name)
        self.on_change(False)
