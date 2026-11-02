"""Main window: floorplan, side editors, padframe preview, pin list, settings and LibreLane output."""

import copy
import os
from pathlib import Path

from .. import APP_NAME
from ..formats import pinlist, project_file, svg
from ..formats.librelane import export_librelane, librelane_files
from ..model.chip import add_missing_pads as generate_pads
from ..model.floorplan import (Floorplan, Macro, MacroDef, floorplan_warnings, io_signals,
                               utilization)
from ..model.constants import FUNCTION_NAMES, FUNCTIONS, ORDER, SIDE_NAMES, SIDES, TYPE_NAMES, TYPES
from ..model.parse import format_entry, parse_line, split_lines
from ..model.pdk import get_package, get_pdk, package_names, pdk_names
from ..model.project import PadSettings, Project, Settings
from ..style import EXPORT_PALETTE
from .floorplan_view import fill_floorplan
from .macro_panel import MacroPanel
from .qt import (QAbstractItemView, QAction, QApplication, QBrush, QCheckBox, QColor, QComboBox,
                 QFileDialog, QFrame, QGraphicsScene, QGridLayout, QGroupBox, QHBoxLayout, QImage, QInputDialog,
                 QKeySequence, QLabel, QMainWindow, QMessageBox, QPainter, QPlainTextEdit, QPushButton, QRectF,
                 QSplitter, QStackedWidget, Qt, QTableWidget, QTableWidgetItem, QTabWidget, QTextCursor, QTimer,
                 QVBoxLayout, QWidget)
from .scene import fill_scene, mono_family
from .widgets import RingView, SideEditor, spin

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "chip-planner"
LAST_STATE = CONFIG_DIR / "last-qt.json"

MODE_LABELS = [("ccw", "Counter-clockwise from top left (package)"),
               ("cw", "Clockwise from top left")]
ALIGN_LABELS = [("center", "Centered"), ("start", "From start corner")]
DIE_MODES = [("pads", "Pad-limited"), ("die", "Fixed die size"), ("core", "Fixed core size (minimum)")]
# Editors list each side in physical order, as seen on the die
EDITOR_DIR = {"T": "left → right", "R": "top → bottom", "B": "left → right", "L": "top → bottom"}
PAD_FIELDS = ("pitch", "w", "h")
TABLE_COLUMNS = ["Pin", "Side", "Name", "Type", "Function", "Drive", "IO cell", "Domain", "Pkg pin",
                 "Pad W×H [µm]", "Pitch [µm]", "X [µm]", "Y [µm]"]
COL = {name: i for i, name in enumerate(TABLE_COLUMNS)}


class MainWindow(QMainWindow):
    def __init__(self, pal, path=None):
        super().__init__()
        self.pal = pal
        self.file = None
        self.selected = None
        self.layout_data = None
        self.project = None
        self.floorplan = Floorplan()
        self.macro_items = []
        self.fp_warnings = []  # from reading the macro LEFs
        self._loading = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.render)

        self._build()
        self._menus()

        project = None
        if path:
            project = self._read_project(Path(path))
            if project:
                self.file = Path(path)
        if project is None:
            project = self._read_project(LAST_STATE, quiet=True) or Project.example()
        self.set_project(project)
        self.setWindowModified(False)
        self._title()
        self.resize(1360, 880)

    # ---------- Construction ----------

    def _build(self):
        pal = self.pal
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # left: side editors, fixed order top, right, bottom, left
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)
        lv.setSpacing(8)

        self.ed_box = QVBoxLayout()
        self.ed_box.setSpacing(6)
        lv.addLayout(self.ed_box, 1)
        self.editors = {}
        for s in SIDES:
            ed = SideEditor(s, pal)
            ed.edit.textChanged.connect(self.changed)
            self.editors[s] = ed
            self.ed_box.addWidget(ed, 1)

        # syntax help below the editors
        hint = QLabel(
            "One line per pad, empty line = spacer slot, <code>NC</code> = no connection. "
            "Force type: <code>[p] [g] [a] [rf] [d] [c] [nc]</code>. "
            "Custom size <code>{80x60}</code>, custom pitch <code>@120</code>. "
            "RF groups: <code>RFIN [gsg]</code>, <code>LO [gsgsg]</code>, <code>[gs]</code>, <code>[sg]</code>. "
            "IO function: <code>[in] [out] [tri] [io] [analog] [vdd] [vss] [iovdd] [iovss] [none]</code>, "
            "drive <code>[16mA]</code>. Power split: a line <code>=== NAME</code> cuts the IO ring and starts "
            "power domain NAME.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {pal['muted']};")
        lv.addWidget(hint)

        # left on the Floorplan tab: the macro list instead of the side editors
        self.editor_page = left
        self.macro_panel = MacroPanel(pal, self.floorplan_changed, {
            "add": self.add_macro, "placeholder": self.ask_placeholder, "reload": self.reload_macros,
            "rotate": self.rotate_macro, "duplicate": self.duplicate_macro, "remove": self.remove_macro})
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(left)
        self.left_stack.addWidget(self.macro_panel)
        splitter.addWidget(self.left_stack)

        # right: tabs
        tabs = QTabWidget()
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 920])

        pv = QWidget()
        pvl = QVBoxLayout(pv)
        pvl.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        for t in TYPES:
            fill, outline = pal["types"][t]
            sw = QLabel()
            sw.setFixedSize(13, 13)
            style = "dashed" if t == "nc" else "solid"
            sw.setStyleSheet(f"background: {fill}; border: 2px {style} {outline}; border-radius: 2px;")
            bar.addWidget(sw)
            bar.addWidget(QLabel(TYPE_NAMES[t]))
            bar.addSpacing(8)
        bar.addStretch(1)
        for text, fn in (("−", lambda: self.view.zoom(1 / 1.25, False)),
                         ("Fit", lambda: self.view.fit()),
                         ("+", lambda: self.view.zoom(1.25, False))):
            b = QPushButton(text)
            if len(text) == 1:
                b.setFixedWidth(32)
            b.clicked.connect(fn)
            bar.addWidget(b)
        pvl.addLayout(bar)

        self.scene = QGraphicsScene(self)
        self.view = RingView(self.scene, self.pad_clicked, self.pad_hover)
        pvl.addWidget(self.view, 1)

        stats, self.stat, self.stat_cap = self._stat_tiles(
            (("pads", "Pads"), ("die", "Die (pad-limited)"), ("area", "Area"),
             ("pg", "Power / Ground"), ("sig", "Analog / RF / Digital / Clock")))
        pvl.addLayout(stats)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(f"color: {pal['warn']};")
        pvl.addWidget(self.warn)
        self.fp_page = self._build_floorplan()
        tabs.addTab(self.fp_page, "Floorplan")
        tabs.addTab(pv, "Padframe")
        self.pv_page = pv

        pl = QWidget()
        pll = QVBoxLayout(pl)
        pll.setContentsMargins(6, 6, 6, 6)
        bb = QHBoxLayout()
        b1 = QPushButton("Copy to Clipboard")
        b1.clicked.connect(self.copy_table)
        b2 = QPushButton("Export as CSV…")
        b2.clicked.connect(self.export_csv)
        note = QLabel("X/Y = bond pad centre, origin lower-left of the die")
        note.setStyleSheet(f"color: {pal['muted']};")
        bb.addWidget(b1)
        bb.addWidget(b2)
        bb.addSpacing(12)
        bb.addWidget(note)
        bb.addStretch(1)
        pll.addLayout(bb)
        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.table_selected)
        pll.addWidget(self.table, 1)
        tabs.addTab(pl, "Pin List")
        tabs.addTab(self._build_settings(), "Settings")
        self.ll_page = self._build_librelane()
        tabs.addTab(self.ll_page, "LibreLane")
        tabs.currentChanged.connect(self.tab_changed)
        self.tabs = tabs
        tabs.setCurrentWidget(pv)

        self.cb_mode.currentIndexChanged.connect(self.mode_changed)
        self.cb_align.currentIndexChanged.connect(self.changed)
        self.chk_square.toggled.connect(self.changed)
        self.cb_die.currentIndexChanged.connect(self.die_mode_changed)
        self.cb_pdk.currentIndexChanged.connect(self.pdk_changed)
        self.cb_pkg.currentIndexChanged.connect(self.changed)
        self.sp_die_w.valueChanged.connect(self.changed)
        self.sp_die_h.valueChanged.connect(self.changed)
        for sp in (self.sp_core_w, self.sp_core_h, self.sp_grid):
            sp.valueChanged.connect(self.changed)
        # the floorplan toolbar edits the same core size and grid as the Settings tab
        for a, b in ((self.sp_core_w, self.fp_core_w), (self.sp_core_h, self.fp_core_h), (self.sp_grid, self.fp_grid)):
            a.valueChanged.connect(lambda v, b=b: b.setValue(v))
            b.valueChanged.connect(lambda v, a=a: a.setValue(v))
        self.sp_cellh.valueChanged.connect(self.changed)
        for s in self.sp.values():
            s.valueChanged.connect(self.changed)

        self.statusBar().showMessage("Click a pad to select its line · Ctrl+wheel zooms · "
                                     "middle mouse button pans")

    def _stat_tiles(self, items):
        stats, vals, caps = QHBoxLayout(), {}, {}
        for key, label in items:
            box = QFrame()
            box.setFrameShape(QFrame.Shape.StyledPanel)
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 5, 10, 5)
            bl.setSpacing(0)
            cap = QLabel(label.upper())
            cap.setStyleSheet(f"color: {self.pal['muted']}; font-size: 8pt;")
            val = QLabel()
            val.setStyleSheet(f"font-family: '{mono_family()}'; font-size: 12pt; font-weight: 600;")
            bl.addWidget(cap)
            bl.addWidget(val)
            stats.addWidget(box, 1)
            vals[key], caps[key] = val, cap
        return stats, vals, caps

    def _build_floorplan(self):
        pal = self.pal
        page = QWidget()
        fl = QVBoxLayout(page)
        fl.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        for t in ("ana", "rf", "clk", "dig"):
            fill, outline = pal["types"][t]
            sw = QLabel()
            sw.setFixedSize(13, 13)
            sw.setStyleSheet(f"background: {fill}; border: 2px solid {outline}; border-radius: 2px;")
            bar.addWidget(sw)
            bar.addWidget(QLabel(TYPE_NAMES[t]))
            bar.addSpacing(8)
        bar.addStretch(1)
        self.fp_core_w = spin(1500, maximum=50000.0)
        self.fp_core_h = spin(1200, maximum=50000.0)
        self.fp_grid = spin(10, maximum=1000.0)
        self.fp_grid.setMinimum(0.1)
        bar.addWidget(QLabel("Core"))
        bar.addWidget(self.fp_core_w)
        bar.addWidget(QLabel("×"))
        bar.addWidget(self.fp_core_h)
        bar.addSpacing(8)
        bar.addWidget(QLabel("Grid"))
        bar.addWidget(self.fp_grid)
        self.chk_grid = QCheckBox("Show grid")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(lambda *_: self.render())
        bar.addWidget(self.chk_grid)
        bar.addSpacing(8)
        gen = QPushButton("Generate Padframe →")
        gen.clicked.connect(lambda: self.generate_padframe())
        bar.addWidget(gen)
        for text, fn in (("−", lambda: self.fp_view.zoom(1 / 1.25, False)),
                         ("Fit", lambda: self.fp_view.fit()),
                         ("+", lambda: self.fp_view.zoom(1.25, False))):
            b = QPushButton(text)
            if len(text) == 1:
                b.setFixedWidth(32)
            b.clicked.connect(fn)
            bar.addWidget(b)
        fl.addLayout(bar)
        self.fp_scene = QGraphicsScene(self)
        self.fp_view = RingView(self.fp_scene, lambda tag: None, lambda tag: None)
        fl.addWidget(self.fp_view, 1)
        stats, self.fp_stat, _ = self._stat_tiles(
            (("core", "Core"), ("macros", "Macros"), ("util", "Utilization"), ("io", "IO signals (T/R/B/L)")))
        fl.addLayout(stats)
        self.fp_warn = QLabel()
        self.fp_warn.setWordWrap(True)
        self.fp_warn.setStyleSheet(f"color: {pal['warn']};")
        fl.addWidget(self.fp_warn)
        return page

    def _build_settings(self):
        pal = self.pal
        page = QWidget()
        sv = QVBoxLayout(page)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(10)

        tech = QGroupBox("Technology")
        tg = QGridLayout(tech)
        self.cb_pdk = QComboBox()
        self.cb_pdk.addItem("None (generic planning, no IO cells)", "")
        for name in pdk_names():
            self.cb_pdk.addItem(f"{get_pdk(name).label} ({name})", name)
        self.cb_pkg = QComboBox()
        self.cb_pkg.addItem("None", "")
        for name in package_names():
            self.cb_pkg.addItem(get_package(name).label, name)
        tg.addWidget(QLabel("PDK"), 0, 0)
        tg.addWidget(self.cb_pdk, 0, 1)
        tg.addWidget(QLabel("Package"), 1, 0)
        tg.addWidget(self.cb_pkg, 1, 1)
        self.pdk_note = QLabel()
        self.pdk_note.setWordWrap(True)
        self.pdk_note.setStyleSheet(f"color: {pal['muted']};")
        tg.addWidget(self.pdk_note, 2, 0, 1, 3)
        tg.setColumnStretch(2, 1)
        sv.addWidget(tech)

        die = QGroupBox("Die")
        dg = QGridLayout(die)
        self.cb_die = QComboBox()
        for key, label in DIE_MODES:
            self.cb_die.addItem(label, key)
        self.sp_die_w = spin(2000, maximum=50000.0)
        self.sp_die_h = spin(2000, maximum=50000.0)
        self.sp_core_w = spin(1500, maximum=50000.0)
        self.sp_core_h = spin(1200, maximum=50000.0)
        self.sp_grid = spin(10, maximum=1000.0)
        self.sp_grid.setMinimum(0.1)
        dg.addWidget(QLabel("Size"), 0, 0)
        dg.addWidget(self.cb_die, 0, 1, 1, 4)
        for r_, (label, w_, h_) in enumerate((("Die", self.sp_die_w, self.sp_die_h),
                                             ("Core", self.sp_core_w, self.sp_core_h)), start=1):
            dg.addWidget(QLabel(label), r_, 0)
            dg.addWidget(QLabel("Width"), r_, 1)
            dg.addWidget(w_, r_, 2)
            dg.addWidget(QLabel("Height"), r_, 3)
            dg.addWidget(h_, r_, 4)
        dg.addWidget(QLabel("Floorplan grid"), 3, 0)
        dg.addWidget(self.sp_grid, 3, 2)
        note = QLabel("Pad-limited: the die grows with the pads. Fixed die: size including the IO ring. "
                      "Fixed core: the die is at least core + IO ring (+ core margin of the PDK) and grows "
                      "when the pads need more room.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {pal['muted']};")
        dg.addWidget(note, 4, 0, 1, 6)
        dg.setColumnStretch(5, 1)
        sv.addWidget(die)

        ring = QGroupBox("Ring")
        rg = QGridLayout(ring)
        self.cb_mode = QComboBox()
        for key, label in MODE_LABELS:
            self.cb_mode.addItem(label, key)
        self.cb_align = QComboBox()
        for key, label in ALIGN_LABELS:
            self.cb_align.addItem(label, key)
        self.chk_square = QCheckBox("Keep square")
        self.sp_cellh = spin(120)
        rg.addWidget(QLabel("Numbering"), 0, 0)
        rg.addWidget(self.cb_mode, 0, 1, 1, 3)
        rg.addWidget(QLabel("Short sides"), 1, 0)
        rg.addWidget(self.cb_align, 1, 1)
        rg.addWidget(self.chk_square, 1, 2, 1, 2)
        rg.addWidget(QLabel("IO cell height"), 2, 0)
        rg.addWidget(self.sp_cellh, 2, 1)
        rg.setColumnStretch(3, 1)
        sv.addWidget(ring)

        pads = QGroupBox("Pads")
        pg = QGridLayout(pads)
        for c, t in enumerate(("", "Pitch", "Width", "Height"), start=0):
            if t:
                lab = QLabel(t)
                lab.setStyleSheet(f"color: {pal['muted']};")
                pg.addWidget(lab, 0, c)
        self.sp = {}
        for r, (key, label, vals) in enumerate((("std", "Standard", (80, 60, 60)),
                                                ("rf", "RF / GSG", (100, 70, 70))), start=1):
            pg.addWidget(QLabel(label), r, 0)
            for c, (fld, v) in enumerate(zip(PAD_FIELDS, vals), start=1):
                s = spin(v)
                self.sp[(key, fld)] = s
                pg.addWidget(s, r, c)
        pg.setColumnStretch(4, 1)
        sv.addWidget(pads)
        sv.addStretch(1)
        return page

    def _build_librelane(self):
        page = QWidget()
        lv = QVBoxLayout(page)
        lv.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        self.ll_status = QLabel()
        self.ll_status.setWordWrap(True)
        self.ll_status.setStyleSheet(f"color: {self.pal['muted']};")
        b_copy = QPushButton("Copy File")
        b_copy.clicked.connect(self.copy_librelane_file)
        b_exp = QPushButton("Export Files…")
        b_exp.clicked.connect(self.export_librelane_files)
        bar.addWidget(self.ll_status, 1)
        bar.addWidget(b_copy)
        bar.addWidget(b_exp)
        lv.addLayout(bar)
        self.ll_tabs = QTabWidget()
        self.ll_texts = {}
        lv.addWidget(self.ll_tabs, 1)
        return page

    def _menus(self):
        mf = self.menuBar().addMenu("&File")

        def act(menu, text, fn, key=None):
            a = QAction(text, self)
            if key is not None:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            menu.addAction(a)
            return a

        act(mf, "New", self.new_file, QKeySequence.StandardKey.New)
        act(mf, "Open…", self.open_file, QKeySequence.StandardKey.Open)
        act(mf, "Save", self.save_file, QKeySequence.StandardKey.Save)
        act(mf, "Save As…", self.save_file_as, QKeySequence.StandardKey.SaveAs)
        mf.addSeparator()
        act(mf, "Export Pin List as CSV…", self.export_csv)
        act(mf, "Export Padframe as SVG…", self.export_svg)
        act(mf, "Export Padframe as PNG…", self.export_png)
        act(mf, "Export LibreLane Files…", self.export_librelane_files)
        mf.addSeparator()
        act(mf, "Add Macro…", self.add_macro)
        act(mf, "Reload Macros", self.reload_macros, "F5")
        mf.addSeparator()
        act(mf, "Load Example", self.load_example)
        mf.addSeparator()
        act(mf, "Quit", self.close, QKeySequence.StandardKey.Quit)

        mv = self.menuBar().addMenu("&View")
        act(mv, "Zoom In", lambda: self.view.zoom(1.25, False), QKeySequence.StandardKey.ZoomIn)
        act(mv, "Zoom Out", lambda: self.view.zoom(1 / 1.25, False), QKeySequence.StandardKey.ZoomOut)
        act(mv, "Fit", lambda: self.view.fit(), "Ctrl+0")

    # ---------- State ----------

    def get_project(self):
        settings = Settings(
            mode=self.cb_mode.currentData(), align=self.cb_align.currentData(),
            square=self.chk_square.isChecked(), cell_height=self.sp_cellh.value(),
            std=PadSettings(*(self.sp[("std", f)].value() for f in PAD_FIELDS)),
            rf=PadSettings(*(self.sp[("rf", f)].value() for f in PAD_FIELDS)),
            fixed_die=self.cb_die.currentData() == "die",
            die_width=self.sp_die_w.value(), die_height=self.sp_die_h.value(),
            fixed_core=self.cb_die.currentData() == "core",
            core_width=self.sp_core_w.value(), core_height=self.sp_core_h.value(), grid=self.sp_grid.value(),
            pdk=self.cb_pdk.currentData() or "", package=self.cb_pkg.currentData() or "",
        )
        project = Project(settings, floorplan=copy.deepcopy(self.floorplan))
        for s in SIDES:
            project.set_physical_lines(s, split_lines(self.editors[s].text()))
        return project

    def set_project(self, project):
        self.floorplan = copy.deepcopy(project.floorplan)
        self.fp_warnings = list(project.load_warnings)
        self.macro_panel.set_floorplan(self.floorplan)
        st = project.settings.sanitized()
        self._loading = True
        try:
            self.cb_mode.setCurrentIndex(max(0, self.cb_mode.findData(st.mode)))
            self.cb_align.setCurrentIndex(max(0, self.cb_align.findData(st.align)))
            self.chk_square.setChecked(st.square)
            self.sp_cellh.setValue(st.cell_height)
            self.cb_die.setCurrentIndex(self.cb_die.findData(
                "die" if st.fixed_die else "core" if st.fixed_core else "pads"))
            self.sp_die_w.setValue(st.die_width)
            self.sp_die_h.setValue(st.die_height)
            self.sp_core_w.setValue(st.core_width)
            self.sp_core_h.setValue(st.core_height)
            self.sp_grid.setValue(st.grid)
            self._update_die_widgets()
            self.cb_pdk.setCurrentIndex(max(0, self.cb_pdk.findData(st.pdk)))
            self.cb_pkg.setCurrentIndex(max(0, self.cb_pkg.findData(st.package)))
            self._update_pdk_widgets()
            for key in ("std", "rf"):
                pads = getattr(st, key)
                for f in PAD_FIELDS:
                    self.sp[(key, f)].setValue(getattr(pads, f))
            for s in SIDES:
                self.editors[s].set_text("\n".join(project.physical_lines(s)))
        finally:
            self._loading = False
        self.selected = None
        self.render()
        self.view.fit()
        self.fp_view.fit()

    def changed(self, *_):
        if self._loading:
            return
        self.setWindowModified(True)
        self.timer.start()

    def die_mode_changed(self, *_):
        if self.cb_die.currentData() == "die" and not self._loading and self.layout_data:
            # start from the current pad-limited size
            self._loading = True
            self.sp_die_w.setValue(self.layout_data.die_width)
            self.sp_die_h.setValue(self.layout_data.die_height)
            self._loading = False
        self._update_die_widgets()
        self.changed()

    def pdk_changed(self, *_):
        pdk = get_pdk(self.cb_pdk.currentData())
        if pdk and not self._loading:
            for key in ("std", "rf"):  # the IO cells need at least their width as pitch
                if self.sp[(key, "pitch")].value() < pdk.cell_width:
                    self.sp[(key, "pitch")].setValue(pdk.default_pitch)
        self._update_pdk_widgets()
        self.changed()

    def _update_pdk_widgets(self):
        pdk = get_pdk(self.cb_pdk.currentData())
        for key in ("std", "rf"):
            for f in ("w", "h"):
                self.sp[(key, f)].setEnabled(pdk is None)
        self.sp_cellh.setEnabled(pdk is None)
        if pdk:  # show the values the layout uses
            loading, self._loading = self._loading, True
            self.sp_cellh.setValue(pdk.ring_depth)
            for key in ("std", "rf"):
                self.sp[(key, "w")].setValue(pdk.bondpad_w)
                self.sp[(key, "h")].setValue(pdk.bondpad_h)
            self._loading = loading
            self.pdk_note.setText(
                f"IO ring from {pdk.io_library}: {pdk.edge_spacing:g} µm seal ring spacing + "
                f"{pdk.cell_depth:g} µm IO cells ({pdk.cell_width:g} µm wide), bondpads "
                f"{pdk.bondpad_w:g}×{pdk.bondpad_h:g} µm. Pad size and IO cell height come from the PDK, "
                f"pitches snap to {pdk.site:g} µm. Power splits leave a {pdk.split_gap:g} µm gap.")
        else:
            self.pdk_note.setText("Without a PDK the ring is planned abstractly; select one for IO cells "
                                  "and the LibreLane output.")

    def _update_die_widgets(self):
        mode = self.cb_die.currentData()
        for sp, on in ((self.sp_die_w, mode == "die"), (self.sp_die_h, mode == "die"),
                       (self.sp_core_w, mode == "core"), (self.sp_core_h, mode == "core")):
            sp.setEnabled(on)
        self.chk_square.setEnabled(mode != "die")  # a fixed die has its own aspect ratio

    def mode_changed(self, *_):
        # The editors show physical order, so pads keep their place; only the numbering changes
        self.selected = None
        self.changed()

    def tab_changed(self, *_):
        on_fp = self.tabs.currentWidget() is self.fp_page
        self.left_stack.setCurrentWidget(self.macro_panel if on_fp else self.editor_page)
        if on_fp and self.fp_view.fit_mode:
            self.fp_view.fit()
        self.update_librelane()

    # ---------- Floorplan ----------

    def floorplan_changed(self, rebuild=True):
        if rebuild:
            self.macro_panel.set_floorplan(self.floorplan)
        self.setWindowModified(True)
        self.render()

    def _ensure_core_mode(self):
        # a floorplan needs a die around the core; pad-limited dies start from the pads only
        if self.cb_die.currentData() == "pads":
            self.cb_die.setCurrentIndex(self.cb_die.findData("core"))

    def _place(self, m):
        """Put a new macro to the right of the others when it fits, else at the core origin."""
        w, _ = m.size()
        right = max((o.x + o.size()[0] for o in self.floorplan.macros), default=None)
        if right is not None:
            g = self.sp_grid.value()
            x = round((right + 5 * g) / g) * g
            if x + w <= self.sp_core_w.value():
                m.x = x

    def add_macro(self):
        path = QFileDialog.getExistingDirectory(self, "Add Macro (LibreLane run directory)",
                                                str(self.file.parent) if self.file else "")
        if path:
            self.add_macro_dir(path)

    def add_macro_dir(self, path):
        name = self.floorplan.instance_name(Path(path).name)
        try:
            m = Macro.from_dir(str(Path(path).resolve()), name)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Add Macro", str(e))
            return None
        self._place(m)
        self.floorplan.macros.append(m)
        self._ensure_core_mode()
        self.floorplan_changed()
        return m

    def ask_placeholder(self):
        name, ok = QInputDialog.getText(self, "Add Placeholder", "Name:")
        if not ok or not name.strip():
            return
        w, ok = QInputDialog.getDouble(self, "Add Placeholder", "Width [µm]:", 500.0, 1.0, 50000.0, 1)
        if not ok:
            return
        h, ok = QInputDialog.getDouble(self, "Add Placeholder", "Height [µm]:", 500.0, 1.0, 50000.0, 1)
        if ok:
            self.add_placeholder(name.strip(), w, h)

    def add_placeholder(self, name, w, h):
        if any(m.name == name for m in self.floorplan.macros):
            name = self.floorplan.instance_name(name)
        m = Macro(name, cache=MacroDef(name, float(w), float(h)))
        self._place(m)
        self.floorplan.macros.append(m)
        self._ensure_core_mode()
        self.floorplan_changed()
        return m

    def reload_macros(self):
        self.fp_warnings = self.floorplan.reload()
        self.floorplan_changed()

    def rotate_macro(self, m):
        m.rot = (m.rot + 90) % 360
        w, h = m.size()  # keep the top-left corner, stay inside the core
        m.x = max(0.0, min(m.x, self.sp_core_w.value() - w))
        m.y = max(0.0, min(m.y, self.sp_core_h.value() - h))
        self.floorplan_changed()

    def duplicate_macro(self, m):
        d = copy.deepcopy(m)
        d.cache = m.cache  # instances of one macro share the LEF values
        d.name = self.floorplan.instance_name(Path(m.path).name if m.path else m.name.rstrip("0123456789") or m.name)
        d.x += 10 * self.sp_grid.value()
        d.y += 10 * self.sp_grid.value()
        self.floorplan.macros.append(d)
        self.floorplan_changed()
        return d

    def remove_macro(self, m):
        self.floorplan.macros = [o for o in self.floorplan.macros if o is not m]
        self.floorplan_changed()

    def generate_padframe(self, confirm=True):
        """Add pads for the marked macro pins (see :func:`generate_pads`); returns the added names."""
        project = self.get_project()
        if confirm and (not project.settings.fixed_core or any(project.sides[s] for s in SIDES)):
            ans = QMessageBox.question(
                self, "Generate Padframe",
                "Add a pad for every marked macro pin that is not a pad yet? Existing lines stay as they are. "
                "The die size switches to 'Fixed core size'.")
            if ans != QMessageBox.StandardButton.Yes:
                return []
        added = generate_pads(project)
        file, modified = self.file, self.isWindowModified()
        self.set_project(project)
        self.file = file
        self.setWindowModified(modified or bool(added))
        self.tabs.setCurrentWidget(self.pv_page)
        self.statusBar().showMessage(f"Added {len(added)} pads: {', '.join(added)}" if added else
                                     "No new pads: all marked pins are pads already", 8000)
        return added

    def _macro_released(self, m):
        self.setWindowModified(True)
        self.timer.start()

    def _render_floorplan(self, project, lay):
        fp_project = copy.copy(project)
        fp_project.floorplan = self.floorplan  # the items move the macros of the window
        self.macro_items = fill_floorplan(
            self.fp_scene, fp_project, lay, self.pal, self.chk_grid.isChecked(),
            on_move=lambda m: self.setWindowModified(True), on_release=self._macro_released,
            on_rotate=self.rotate_macro)
        if self.fp_view.fit_mode:
            self.fp_view.fit()
        st = project.settings.sanitized()
        self.fp_stat["core"].setText(f"{st.core_width / 1000:.3f} × {st.core_height / 1000:.3f} mm")
        self.fp_stat["macros"].setText(str(len(self.floorplan.macros)))
        self.fp_stat["util"].setText(f"{100 * utilization(fp_project):.1f} %")
        cnt = {s: 0 for s in SIDES}
        for sig in io_signals(fp_project):
            cnt[sig["side"]] += 1
        self.fp_stat["io"].setText("/".join(str(cnt[s]) for s in SIDES))
        warnings = self.fp_warnings + floorplan_warnings(fp_project)
        self.fp_warn.setText("\n".join(warnings))
        self.fp_warn.setVisible(bool(warnings))

    def _title(self):
        name = self.file.name if self.file else "Untitled"
        self.setWindowTitle(f"{APP_NAME} — {name}[*]")

    # ---------- Rendering ----------

    def render(self):
        project = self.get_project()
        lay = project.layout(self.selected)
        self.project, self.layout_data = project, lay

        for s in SIDES:
            ed = self.editors[s]
            ed.dir.setText("· " + EDITOR_DIR[s])
            nos = project.to_physical(s, [p.no for p in lay.pins_on(s)])
            ed.count.setText(f"{len(nos)} pads · {lay.side_length[s]:g} µm" + (f" · {nos[0]}–{nos[-1]}" if nos else ""))
            labels = project.to_physical(s, lay.gutter[s])
            if project.is_reversed(s):  # group ranges descend as well, e.g. 29–25
                labels = ["–".join(l.split("–")[::-1]) for l in labels]
            ed.edit.set_labels(labels)
            sel_line = None
            if self.selected and self.selected.startswith(s + ":"):
                sel_line = self._editor_line(self.selected)[1]
            ed.edit.highlight_line(sel_line)

        fill_scene(self.scene, lay, self.pal)
        if self.view.fit_mode:
            self.view.fit()

        c = lay.counts
        ps = lay.pins_per_side
        self.stat["pads"].setText(f"{len(lay.pins)}  ({ps['T']}/{ps['R']}/{ps['B']}/{ps['L']})")
        self.stat_cap["die"].setText("DIE (FIXED)" if lay.fixed_die else
                                     "DIE (MIN. CORE)" if lay.core_limited else "DIE (PAD-LIMITED)")
        self.stat["die"].setText(f"{lay.die_width / 1000:.3f} × {lay.die_height / 1000:.3f} mm")
        self.stat["area"].setText(f"{lay.area_mm2:.3f} mm²")
        self.stat["pg"].setText(f"{c['pwr']} / {c['gnd']}")
        self.stat["sig"].setText(f"{c['ana']} / {c['rf']} / {c['dig']} / {c['clk']}")
        self.warn.setText("\n".join(lay.warnings))
        self.warn.setVisible(bool(lay.warnings))

        self.table.blockSignals(True)
        self.table.setRowCount(len(lay.pins))
        pdk = get_pdk(lay.pdk)
        for r, p in enumerate(lay.pins):
            vals = {"Pin": str(p.no), "Side": SIDE_NAMES[p.side], "Name": p.name, "Type": TYPE_NAMES[p.type],
                    "Function": FUNCTION_NAMES[p.function], "Drive": f"{p.drive} mA" if p.drive else "",
                    "IO cell": p.cell, "Domain": p.domain,
                    "Pkg pin": str(p.package_pin) if p.package_pin else "",
                    "Pad W×H [µm]": f"{p.w:g} × {p.h:g}", "Pitch [µm]": f"{p.pitch:g}",
                    "X [µm]": f"{p.x:.1f}", "Y [µm]": f"{p.y:.1f}"}
            for name, v in vals.items():
                col = COL[name]
                it = QTableWidgetItem(v)
                if name in ("Pin", "Pkg pin", "Pitch [µm]", "X [µm]", "Y [µm]"):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if name == "Type":
                    it.setForeground(QBrush(QColor(self.pal["types"][p.type][1])))
                it.setData(Qt.ItemDataRole.UserRole, p.tag)
                self.table.setItem(r, col, it)
            for col in (COL["Function"], COL["Drive"]):
                old = self.table.cellWidget(r, col)
                if old is not None:
                    old.hide()  # deleted later by Qt
                    self.table.removeCellWidget(r, col)
            if not p.grouped:  # one pad per line: function and drive editable here
                self.table.setCellWidget(r, COL["Function"], self._function_combo(p))
                drives = pdk.drives(p.function) if pdk else []
                if drives:
                    self.table.setCellWidget(r, COL["Drive"], self._drive_combo(p, pdk, drives))
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        self._render_floorplan(project, lay)
        self.update_librelane()

    def _function_combo(self, p):
        cb = QComboBox()
        for f in FUNCTIONS:
            cb.addItem(FUNCTION_NAMES[f], f)
        cb.setCurrentIndex(cb.findData(p.function))
        cb.currentIndexChanged.connect(lambda _i, tag=p.tag, cb=cb: self._set_line_option(tag, function=cb.currentData()))
        return cb

    def _drive_combo(self, p, pdk, drives):
        cb = QComboBox()
        default = pdk.cells[p.function]["default_drive"]
        cb.addItem(f"Default ({default} mA)", None)
        for d in drives:
            cb.addItem(f"{d} mA", d)
        cb.setCurrentIndex(max(0, cb.findData(p.drive)) if p.drive else 0)
        cb.currentIndexChanged.connect(lambda _i, tag=p.tag, cb=cb: self._set_line_option(tag, drive=cb.currentData()))
        return cb

    def _set_line_option(self, tag, **options):
        """Change the IO function or drive of one editor line (rewrites its tags)."""
        side, line = self._editor_line(tag)
        edit = self.editors[side].edit
        block = edit.document().findBlockByNumber(line)
        e = parse_line(block.text()) if block.isValid() else None
        if not e or e["split"]:
            return
        e.update(options)
        cur = QTextCursor(block)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cur.insertText(format_entry(e))

    # ---------- LibreLane ----------

    def update_librelane(self):
        if self.project is None or self.tabs.currentWidget() is not self.ll_page:
            return
        try:
            files = librelane_files(self.project, self.file.name if self.file else "")
        except ValueError as e:
            files = {}
            self.ll_status.setText(f"No LibreLane output: {e}.")
        if files:
            pkg = "" if "bondplan_pinout.yaml" in files else " Select a package for the bondplan PINOUT."
            self.ll_status.setText("Pad ring for LibreLane (flow: Chip): copy padring_config.yaml into your "
                                   "config.yaml, keep pad_cfg.tcl next to it and use chip_top.sv as top level." + pkg)
        if list(files) != list(self.ll_texts):
            self.ll_tabs.clear()
            self.ll_texts = {}
            for name in files:
                te = QPlainTextEdit()
                te.setReadOnly(True)
                te.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                font = te.font()
                font.setFamily(mono_family())
                te.setFont(font)
                self.ll_tabs.addTab(te, name)
                self.ll_texts[name] = te
        for name, text in files.items():
            te = self.ll_texts[name]
            if te.toPlainText() != text:
                v = te.verticalScrollBar().value()
                te.setPlainText(text)
                te.verticalScrollBar().setValue(v)

    def copy_librelane_file(self):
        te = self.ll_tabs.currentWidget()
        if te is not None:
            QApplication.clipboard().setText(te.toPlainText())
            self.statusBar().showMessage(f"{self.ll_tabs.tabText(self.ll_tabs.currentIndex())} copied to clipboard", 4000)

    def export_librelane_files(self):
        project = self.get_project()
        try:
            files = librelane_files(project)
        except ValueError as e:
            QMessageBox.warning(self, "LibreLane", f"No LibreLane output: {e}.")
            return
        start = str(self.file.parent) if self.file else ""
        d = QFileDialog.getExistingDirectory(self, "Export LibreLane Files to Folder", start)
        if not d:
            return
        existing = [n for n in files if (Path(d) / n).exists()]
        if existing and QMessageBox.question(
                self, "Overwrite Files", "These files exist and will be overwritten:\n" + "\n".join(existing),
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Ok:
            return
        try:
            paths = export_librelane(project, d, self.file.name if self.file else "")
        except OSError as e:
            QMessageBox.critical(self, "Export", f"Export failed:\n{e}")
            return
        self.statusBar().showMessage(f"{len(paths)} LibreLane files written to {d}", 6000)

    # ---------- Interaction ----------

    def pad_clicked(self, tag):
        self.selected = tag
        self.render()
        side, line = self._editor_line(tag)
        self.editors[side].edit.select_line(line)
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == tag:
                self.table.blockSignals(True)
                self.table.selectRow(r)
                self.table.blockSignals(False)
                self.table.scrollToItem(self.table.item(r, 0))
                break

    def _editor_line(self, tag):
        """Pin tag (side and line in numbering order) → (side, line index in the editor)."""
        side, line = tag.split(":")
        return side, self.project.physical_line_index(side, int(line))

    def pad_hover(self, tag):
        if not tag or not self.layout_data:
            self.statusBar().clearMessage()
            return
        side = tag.split(":")[0]
        pads = [p for p in self.layout_data.pins if p.tag == tag]
        splits = [sp for sp in self.layout_data.splits if f"{sp.side}:{sp.line}" == tag]
        if splits:
            self.statusBar().showMessage(f"{SIDE_NAMES[side]}: power split, domain {splits[0].domain} follows")
            return
        txt = " · ".join(f"Pin {p.no} {p.name} ({TYPE_NAMES[p.type]}, {FUNCTION_NAMES[p.function]}"
                         + (f", {p.cell}" if p.cell else "") + (f", domain {p.domain}" if p.domain else "")
                         + (f", package pin {p.package_pin}" if p.package_pin else "") + ")" for p in pads)
        self.statusBar().showMessage(f"{SIDE_NAMES[side]}: {txt}")

    def table_selected(self):
        items = self.table.selectedItems()
        if not items:
            return
        tag = items[0].data(Qt.ItemDataRole.UserRole)
        if tag and tag != self.selected:
            self.selected = tag
            self.render()

    # ---------- Files ----------

    def _read_project(self, path, quiet=False):
        try:
            return project_file.load(path)
        except FileNotFoundError:
            if not quiet:
                QMessageBox.critical(self, "Open", f"File not found:\n{path}")
        except (OSError, ValueError) as e:
            if not quiet:
                QMessageBox.critical(self, "Open", f"Could not read file:\n{e}")
        return None

    def _confirm_discard(self):
        if not self.isWindowModified() or not self.file:
            return True
        ans = QMessageBox.question(
            self, "Unsaved Changes", f"Save changes to {self.file.name}?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if ans == QMessageBox.StandardButton.Cancel:
            return False
        if ans == QMessageBox.StandardButton.Save:
            return self.save_file()
        return True

    def _reset_to(self, project):
        self.file = None
        self.set_project(project)
        self.setWindowModified(False)
        self._title()

    def new_file(self):
        if self._confirm_discard():
            project = Project(self.get_project().settings)
            self._reset_to(project)
            self.editors[ORDER[project.settings.mode][0]].edit.setFocus()

    def load_example(self):
        if self._confirm_discard():
            self._reset_to(Project.example())

    def open_file(self):
        if not self._confirm_discard():
            return
        p, _ = QFileDialog.getOpenFileName(self, "Open Pad Ring", "", "Pad ring (*.json);;All files (*)")
        if not p:
            return
        project = self._read_project(Path(p))
        if project:
            self.file = Path(p)
            self.set_project(project)
            self.setWindowModified(False)
            self._title()

    def save_file(self):
        if not self.file:
            return self.save_file_as()
        try:
            project_file.save(self.get_project(), self.file)
        except OSError as e:
            QMessageBox.critical(self, "Save", f"Saving failed:\n{e}")
            return False
        self.setWindowModified(False)
        self._title()
        self.statusBar().showMessage(f"Saved: {self.file}", 4000)
        return True

    def save_file_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save Pad Ring", "padring.json", "Pad ring (*.json)")
        if not p:
            return False
        if not p.lower().endswith(".json"):
            p += ".json"
        self.file = Path(p)
        return self.save_file()

    def copy_table(self):
        QApplication.clipboard().setText(pinlist.to_tsv(self.layout_data))
        self.statusBar().showMessage(f"{len(self.layout_data.pins)} pins copied to clipboard", 4000)

    def export_csv(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export Pin List", "pinlist.csv", "CSV (*.csv)")
        if not p:
            return
        try:
            pinlist.export_csv(self.get_project(), p)
            self.statusBar().showMessage(f"CSV exported: {p}", 4000)
        except OSError as e:
            QMessageBox.critical(self, "Export", f"Export failed:\n{e}")

    def export_svg(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export as SVG", "padring.svg", "SVG (*.svg)")
        if not p:
            return
        try:
            svg.export_svg(self.get_project(), p)
            self.statusBar().showMessage(f"SVG exported: {p}", 4000)
        except OSError as e:
            QMessageBox.critical(self, "Export", f"Export failed:\n{e}")

    def export_png(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export as PNG", "padring.png", "PNG (*.png)")
        if not p:
            return
        if self.render_png(p):
            self.statusBar().showMessage(f"PNG exported: {p}", 4000)
        else:
            QMessageBox.critical(self, "Export", "PNG could not be saved.")

    def render_png(self, path, size=3000):
        """Raster export needs Qt, so it lives in the GUI."""
        scene = fill_scene(QGraphicsScene(), self.get_project().layout(), EXPORT_PALETTE)
        r = scene.sceneRect()
        k = size / max(r.width(), r.height())
        img = QImage(int(r.width() * k), int(r.height() * k), QImage.Format.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        painter = QPainter(img)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        scene.render(painter, QRectF(0, 0, img.width(), img.height()), r)
        painter.end()
        return img.save(str(path))

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        try:
            project_file.save(self.get_project(), LAST_STATE)
        except OSError:
            pass
        event.accept()
