# Floorplan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Floorplan tab where macros (read from LibreLane LEF output) are placed in a core rectangle, their pins marked as off-chip IO, and a first padframe is generated from them.

**Architecture:** Stdlib LEF reader in `formats/lef.py`; pure-Python floorplan model and geometry in `model/floorplan.py`, stored in `Project.floorplan`; a third die-size mode ("fixed core, minimum") in `model/layout.py`; GUI tab with a draggable macro scene and a macro panel in `gui/`.

**Tech Stack:** Python ≥ 3.9 stdlib, PySide6 (PyQt6 fallback via `gui/qt.py`), unittest.

**Spec:** `docs/superpowers/specs/2026-11-02-floorplan-design.md`

## Global Constraints

- No Qt imports in `model/`, `formats/`, `style.py`, `cli.py`, `__init__.py` (enforced by an existing test).
- All geometry in µm, y points down, origin top-left (die or core). LEF (origin lower-left, y up) is converted on read.
- Project files stay compatible: `normalize_state`/`from_dict` read files without the new keys; `tests/data/layout_baseline.json` must not change.
- UI, code, comments in English; numbers with decimal point; style from `style.py` palettes.
- Tests: `python3 -m unittest discover -s tests -t .` (stdlib only).
- Naming everywhere `chip-planner`.
- Generating pads never deletes or reorders existing editor lines.

## Decisions taken in this plan (refine the spec)

- **Die mode storage** (replaces the spec's `die_mode` key, simpler and backwards compatible): keep `Settings.fixed_die`, add `Settings.fixed_core: bool`. `fixed_die` wins if both are true. JSON keys `fixed_core`, `core_w`, `core_h`, `grid`. The spec gets this correction in Task 2.
- **Core rectangle position**: centred in the LibreLane `CORE_AREA` (die − 2 × (ring depth + core margin)). Macro `x`/`y` are relative to the core rectangle's top-left corner.
- **Paths**: in memory macro paths are absolute; `save()` writes them relative to the project file (absolute if `os.path.relpath` fails); `load()` resolves them against the project file directory.
- **Pins without shapes** get the macro centre as position.
- GUI starts on the Padframe tab; the left panel shows side editors on every tab except Floorplan, where it shows the macro panel.

## Review Focus

1. A LEF file with several `MACRO`s or with a macro name not equal to `<dir>_top` → pick `<dirname>_top` if present, else the first macro, never crash. (Task 1 test `test_picks_top_macro`.)
2. A macro that no longer fits the core (core shrunk in Settings, or LEF grew on reload) → warning "Macro X outside the core", no silent move. (Task 3 test `test_outside_core_warning`.)
3. Reload after a pin disappeared from the LEF → the stale name stays in `io` but is skipped on generate and reported. (Task 4 test `test_reload_drops_missing_pin`.)
4. Save As into another directory → relative macro paths still resolve. (Task 4 test `test_paths_relative_to_project_file`.)
5. Generate twice → second run adds nothing (names already present). (Task 5 test `test_generate_is_idempotent`.)

---

### Task 1: LEF reader

**Files:**
- Create: `src/chip_planner/formats/lef.py`
- Create: `tests/data/macros/adc_sar/final/lef/adc_sar_top.lef` (fixture, see Step 1)
- Test: `tests/test_floorplan.py` (new, class `LefTests`)

**Interfaces:**
- Produces (in `model/floorplan.py`, created here with only these dataclasses):
  - `MacroPin(name: str, direction: str, use: str, x: float, y: float)` — direction upper case as in LEF (`"INPUT"`, `"OUTPUT"`, `"OUTPUT TRISTATE"`, `"INOUT"`, `""`), use upper case (`"SIGNAL"` default, `"POWER"`, `"GROUND"`, `"ANALOG"`, `"CLOCK"`), x/y unrotated macro coordinates, origin top-left, y down.
  - `MacroDef(name: str, w: float, h: float, pins: List[MacroPin])`.
- Produces in `formats/lef.py`: `parse_lef(text: str) -> List[MacroDef]`, `read_lef(path) -> List[MacroDef]` (raises `OSError`, `ValueError` on no `MACRO`).

- [ ] **Step 1: Write the fixture and the failing tests**

Fixture `adc_sar_top.lef`: `VERSION 5.8`, `UNITS DATABASE MICRONS 1000`, one `MACRO adc_sar_top` with `SIZE 420 BY 310`, pins:
`VIN_P` (INPUT, USE ANALOG, `RECT 0 220 2 240` on Metal3), `VIN_N` (INPUT, USE ANALOG, `RECT 0 100 2 120`), `CLK` (INPUT, USE CLOCK, `RECT 418 250 420 270`), `DOUT[0]` (OUTPUT, `RECT 418 50 420 52`), `EN` (OUTPUT TRISTATE, `POLYGON 100 0 110 0 110 2 100 2`), `VDD` (INOUT, USE POWER, `RECT 0 0 420 4`), `NOGEO` (INPUT, PORT with only a `LAYER` line). Include a `PROPERTY` line, an `OBS` block and comments (`#`) to check they are skipped.

```python
class LefTests(unittest.TestCase):
    def test_size_and_pins(self):
        (m,) = read_lef(FIXTURE)
        self.assertEqual((m.name, m.w, m.h), ("adc_sar_top", 420.0, 310.0))
        pins = {p.name: p for p in m.pins}
        self.assertEqual((pins["VIN_P"].x, pins["VIN_P"].y), (1.0, 80.0))   # y flipped: 310 - 230
        self.assertEqual(pins["VIN_P"].use, "ANALOG")
        self.assertEqual(pins["EN"].direction, "OUTPUT TRISTATE")
        self.assertEqual((pins["EN"].x, pins["EN"].y), (105.0, 309.0))
        self.assertEqual(pins["VDD"].use, "POWER")
        self.assertEqual((pins["NOGEO"].x, pins["NOGEO"].y), (210.0, 155.0))  # no shape: centre
        self.assertIn("DOUT[0]", pins)

    def test_picks_top_macro(self):
        text = "MACRO helper\n SIZE 1 BY 1 ;\nEND helper\n" + FIXTURE.read_text()
        self.assertEqual(pick_macro(parse_lef(text), "adc_sar").name, "adc_sar_top")
        self.assertEqual(pick_macro(parse_lef("MACRO x\n SIZE 1 BY 2 ;\nEND x\n"), "adc_sar").name, "x")

    def test_no_macro_raises(self):
        with self.assertRaises(ValueError):
            parse_lef("VERSION 5.8 ;\n")
```

- [ ] **Step 2: Run, expect FAIL** — `python3 -m unittest tests.test_floorplan -v` → ImportError.

- [ ] **Step 3: Implement** `parse_lef`, `read_lef`, and `pick_macro(macros: List[MacroDef], dirname: str) -> MacroDef` (in `formats/lef.py`): token-based reader over `;`-terminated statements; pin position = centre of the bounding box of the first `RECT`/`POLYGON` of the first `PORT`; skip `OBS … END`, `PROPERTY`, `MASK n` prefixes; honour `ORIGIN` by shifting shapes.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** `git commit -m "Add LEF reader for macro size and pins"`

---

### Task 2: Fixed core size mode (settings, layout, JSON)

**Files:**
- Modify: `src/chip_planner/model/project.py` (Settings, to_dict, from_dict, normalize_state, sanitized)
- Modify: `src/chip_planner/model/layout.py:153-170` (die sizing), `Layout` dataclass
- Modify: `docs/superpowers/specs/2026-11-02-floorplan-design.md` (replace `die_mode` text with the storage decision above)
- Test: `tests/test_model.py`

**Interfaces:**
- Produces: `Settings.fixed_core: bool = False`, `Settings.core_width: float = 1500.0`, `Settings.core_height: float = 1200.0`, `Settings.grid: float = 10.0`; JSON `fixed_core`, `core_w`, `core_h`, `grid`.
- Produces: `Layout.core_limited: bool` (True when fixed core mode is active), `Layout.core_margin: float` (PDK `core_margin`, else 0.0).

- [ ] **Step 1: Failing tests**

```python
def test_fixed_core_is_minimum(self):
    p = cp.Project(sides={"L": ["A"]})
    p.settings.fixed_core, p.settings.square = True, False
    p.settings.core_width, p.settings.core_height = 1500.0, 1200.0
    lay = p.layout()
    H = lay.ring_depth
    self.assertEqual((lay.die_width, lay.die_height), (1500 + 2 * H, 1200 + 2 * H))
    self.assertTrue(lay.core_limited)
    p.sides["T"] = ["X"] * 40                       # pads need more than the core
    self.assertGreater(p.layout().die_width, 1500 + 2 * H)
    self.assertFalse(any("do not fit" in w for w in p.layout().warnings))

def test_fixed_core_with_pdk_adds_core_margin(self):
    p = cp.Project(sides={"L": ["A [in]"]})
    p.settings.pdk, p.settings.fixed_core, p.settings.square = "ihp-sg13g2", True, False
    lay = p.layout()
    m = lay.ring_depth + lay.core_margin
    self.assertGreaterEqual(lay.die_width, 1500 + 2 * m)
    self.assertEqual(lay.die_width % cp.get_pdk("ihp-sg13g2").site, 0)

def test_fixed_die_wins_over_fixed_core(self): ...   # both True → die_width == settings.die_width

def test_new_settings_round_trip_and_old_files(self):
    p = cp.Project.example(); p.settings.fixed_core = True; p.settings.grid = 5.0
    self.assertEqual(cp.Project.from_dict(p.to_dict()), p)
    old = cp.Project.from_dict({"sides": {}})
    self.assertEqual((old.settings.fixed_core, old.settings.core_width, old.settings.grid), (False, 1500.0, 10.0))
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Sizing in `build_layout` when `cfg.fixed_core and not cfg.fixed_die`: compute the pad-limited `e_tb`/`e_lr` as today (incl. `square`), then `m = H + margin`; `min_w = core_width + 2m`, `min_h = core_height + 2m`, rounded **up** to `pdk.site` with a PDK; `e_tb = max(e_tb, min_w - 2H)`, `e_lr = max(e_lr, min_h - 2H)`; with `square` both get the larger value. Invalid numbers sanitize to the defaults above (grid minimum 0.001).
- [ ] **Step 4: Run all tests, expect PASS** (baseline unchanged).
- [ ] **Step 5: Commit** `"Add fixed core size mode (core size as minimum)"`

---

### Task 3: Floorplan model and geometry

**Files:**
- Modify: `src/chip_planner/model/floorplan.py`
- Modify: `src/chip_planner/model/project.py` (field `floorplan`, JSON key `floorplan`, normalize)
- Modify: `src/chip_planner/model/__init__.py` (export `Floorplan`, `Macro`)
- Test: `tests/test_floorplan.py` (class `FloorplanTests`)

**Interfaces:**
- Consumes: `MacroDef`, `MacroPin` (Task 1); `Layout.ring_depth`, `Layout.core_margin` (Task 2).
- Produces:
  - `Macro(name: str, macro: str = "", path: str = "", x: float = 0.0, y: float = 0.0, rot: int = 0, io: List[str] = [], cache: Optional[MacroDef] = None)`; `path == ""` means placeholder (cache holds the typed size, no pins).
  - `Macro.size() -> Tuple[float, float]` (rotated), `Macro.pin_xy(pin: MacroPin) -> Tuple[float, float]` (core coordinates; rotation 90° clockwise with y down maps `(x, y)` to `(h - y, x)`, applied `rot // 90` times), `Macro.io_pins() -> List[MacroPin]` (signal pins whose name is in `io`).
  - `Floorplan(macros: List[Macro] = [])` with `to_dict() -> dict`, `from_dict(d) -> Floorplan`, `instance_name(macro: str) -> str` (first free `<macro>0`, `<macro>1`, …).
  - `core_origin(layout, settings) -> Tuple[float, float]` (die coordinates of the core rectangle's top-left, centred in CORE_AREA).
  - `nearest_side(x: float, y: float, die_w: float, die_h: float) -> str` (ties T, R, B, L).
  - `floorplan_warnings(project) -> List[str]` (overlaps "Macros A and B overlap", "Macro A outside the core", missing LEF warnings come from Task 4).
  - `utilization(project) -> float` (macro area / core area).
  - `Project.floorplan: Floorplan` (dataclass field, default empty); JSON key `floorplan` written only when it has macros.
  - Pin JSON: `{"name", "dir", "use", "x", "y"}`; cache JSON `{"name", "w", "h", "pins"}`.

- [ ] **Step 1: Failing tests** — rotation (`rot=90` of a 420×310 macro: size `(310, 420)`, pin `(1, 80)` → `(230, 1)`), `rot=270` round trip, `nearest_side` incl. a tie, overlap warning, `test_outside_core_warning` (core 300×300, macro 420×310 → warning naming the instance), utilisation value, JSON round trip of a project with two instances of one macro and a placeholder, old file without `floorplan` → empty.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** as dataclasses (equality must work: `Project.__eq__` is used in tests and the GUI).
- [ ] **Step 4: Run all tests, expect PASS.**
- [ ] **Step 5: Commit** `"Add floorplan model with macro instances"`

---

### Task 4: LEF lookup, reload, project file paths, scripting API

**Files:**
- Modify: `src/chip_planner/model/floorplan.py`, `src/chip_planner/formats/project_file.py`, `src/chip_planner/__init__.py`
- Test: `tests/test_floorplan.py` (class `ReloadTests`), copy the fixture dir per test into a temp dir.

**Interfaces:**
- Produces:
  - `find_lef(path: str) -> Optional[Path]`: `<path>/final/lef/<basename>_top.lef`, else the only `*.lef` in `final/lef/`, else `None`.
  - `Floorplan.reload() -> List[str]`: re-reads every non-placeholder macro (one read per directory, instances share the `MacroDef`), updates `cache`, returns warnings: `"No LEF found for adc0 (macros/adc_sar), using last known values"`, `"Pin X of adc0 no longer in the LEF"` for stale `io` names (kept in `io`).
  - `Macro.from_dir(path: str, name: str) -> Macro` reads the LEF (raises `ValueError` if none).
  - `formats.project_file.load(path)` resolves relative macro paths against `Path(path).parent` and calls `floorplan.reload()`; the warnings are stored on `Project.load_warnings` (not serialized). `save(project, path)` writes macro paths relative to `Path(path).parent` (absolute when `relpath` raises `ValueError`).
  - `cp.Macro`, `cp.Floorplan`, `cp.read_lef`, `cp.generate_pads` (Task 5) exported in `__init__.py` and `__all__`.

- [ ] **Step 1: Failing tests** — `find_lef` both lookups and `None`; `from_dir` on the fixture; `test_reload_drops_missing_pin` (edit the copied LEF to remove `VIN_N`, reload → warning, `io` still contains it); missing dir → warning, cache kept; `test_paths_relative_to_project_file` (save into `tmp/a/p.json` and `tmp/b/sub/p.json`, JSON holds relative paths, `load` gives absolute paths that exist).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all tests, expect PASS.**
- [ ] **Step 5: Commit** `"Read macro LEFs from LibreLane run directories"`

---

### Task 5: Generate padframe

**Files:**
- Modify: `src/chip_planner/model/floorplan.py`
- Test: `tests/test_floorplan.py` (class `GenerateTests`)

**Interfaces:**
- Consumes: Tasks 2–4, `parse.parse_line`, `parse.format_entry`, `Project.physical_lines`/`set_physical_lines`.
- Produces: `io_signals(project) -> List[dict]` with keys `instance, pin, name, side, pos, function` (pos = coordinate along the side in physical order, from the pin's die position; `function` from the LEF: `USE ANALOG`→`"analog"`, `INPUT`→`"in"`, `OUTPUT`→`"out"`, `OUTPUT TRISTATE`→`"tri"`, `INOUT`→`"inout"`, else `None`); `generate_pads(project) -> List[str]` mutates `project`, returns the added pad names, sets `settings.fixed_core = True` and `fixed_die = False`.
- Names: pin name, or `<instance>_<pin>` when the same pin name is marked in more than one instance.
- Placement: side empty → new lines sorted by `pos`; side not empty → appended at the physical end in `pos` order. Skip names already present as a pad name on any side (`parse_line(l)["name"]`).

- [ ] **Step 1: Failing tests** — fixture macro placed at the left of the core with `VIN_P`, `VIN_N` marked → `project.physical_lines("L") == ["VIN_P [analog]", "VIN_N [analog]"]` (VIN_P sits at y 80, VIN_N at y 200, so top → bottom); two instances both marking `CLK` → `adc0_CLK`, `adc1_CLK`; non-empty side gets appended lines; `test_generate_is_idempotent`; stale io pin skipped; settings switched to fixed core.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all tests, expect PASS.**
- [ ] **Step 5: Commit** `"Generate padframe lines from floorplan IO pins"`

---

### Task 6: GUI settings and tab rename

**Files:**
- Modify: `src/chip_planner/gui/main_window.py` (`_build_settings`, `get_project`, `set_project`, `_update_die_widgets`, `render` stat caption, menu texts "Export Preview…" → "Export Padframe…")
- Test: `tests/test_gui.py`

**Interfaces:**
- Produces widgets: `self.cb_die` (QComboBox, data `"pads"`, `"die"`, `"core"`, labels "Pad-limited", "Fixed die size", "Fixed core size (minimum)") replacing `chk_fixed`; `self.sp_core_w`, `self.sp_core_h`, `self.sp_grid` (`spin(...)`, grid minimum 0.1). Die W/H enabled only for `"die"`, core W/H only for `"core"`, `Keep square` disabled only for `"die"`. Switching to `"die"` keeps today's behaviour (start from current size). Stat caption `DIE (MIN. CORE)` when `core_limited`.
- Tab text `Preview` → `Padframe`.

- [ ] **Step 1: Failing tests** — `test_layout_of_window` expects `["Padframe", "Pin List", "Settings", "LibreLane"]` (Task 7 adds Floorplan in front); `cb_die` set to `"core"` → `get_project().settings.fixed_core` and `die_width >= core + 2×ring`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all tests; manual check `PYTHONPATH=src python3 -m chip_planner`.**
- [ ] **Step 5: Commit** `"Add die size mode selector and core size settings"`

---

### Task 7: Floorplan tab

**Files:**
- Create: `src/chip_planner/gui/floorplan_view.py` (`FloorplanView(QGraphicsView)`, `MacroItem(QGraphicsRectItem)`)
- Create: `src/chip_planner/gui/macro_panel.py` (`MacroPanel(QWidget)`)
- Modify: `src/chip_planner/gui/main_window.py` (tab, left `QStackedWidget`, toolbar, stats, menu action `Reload Macros`, project state)
- Modify: `README.md` (section "Floorplan"), `CLAUDE.md` (structure: `formats/lef.py`, `model/floorplan.py`; fixed core mode no longer "planned")
- Test: `tests/test_gui.py`

**Interfaces:**
- Consumes: everything above. Drawing reuses `fill_scene(scene, layout, pal)` for the die and IO ring, then adds the core rectangle (`core` style), grid (`free` style colour, every n-th line when lines are closer than 6 px on screen), macros, pin markers and flylines.
- `MainWindow.floorplan: Floorplan` is the source of truth; `get_project()` puts a copy into the returned project; `set_project()` takes it over.
- `MacroItem`: movable, snaps to `settings.grid` in `itemChange(ItemPositionChange)`, keeps inside the core; on move it updates its macro's `x/y` and its own flylines; on release calls `changed()`. Double-click rotates 90° (keeps top-left, clamps). Overlapping macros drawn with `warn` colour outline. Placeholder outline dashed.
- Pins: small squares on the macro outline, filled with the type outline colour when marked IO (type from `parse.classify`/function, palette `types`), hollow when internal. Flyline from each IO pin to `nearest_side` die edge, dashed, plus the pin name next to the edge.
- `MacroPanel`: one `QGroupBox` per instance (title = instance name, editable via a `QLineEdit` in the box; path or "placeholder, no LEF"; size; buttons Rotate, Duplicate, Remove); signal pins as `QCheckBox` `"NAME  → IO"` / internal; power pins in a muted label "Power: VDD, VSS". Bottom buttons `Add Macro…` (QFileDialog directory → `Macro.from_dir`, error box on `ValueError`), `Add Placeholder…` (name, W, H), `Reload`.
- Toolbar: type legend as on Padframe, `Core` W × H spins (same values as Settings), `Grid` spin, `Show grid` checkbox, `Generate Padframe →` (confirmation box when the project is not in fixed core mode or sides are not empty; afterwards switch to the Padframe tab and show "Added N pads"), zoom `− Fit +`.
- Stats: CORE (mm), MACROS (instance count), UTILIZATION (%), IO SIGNALS (T/R/B/L). Warnings label below as on Padframe (floorplan warnings + reload warnings).
- Left panel: `QStackedWidget` with the side editors page and the `MacroPanel`; switches with the tab (macro panel only on Floorplan). Start tab: Padframe.

- [ ] **Step 1: Failing GUI tests** — tab list `["Floorplan", "Padframe", "Pin List", "Settings", "LibreLane"]`; selecting the Floorplan tab shows the macro panel; adding the fixture macro via `win.add_macro_dir(path)` (method used by the dialog) creates `adc_sar0`; checking `VIN_P` and `win.generate_padframe(confirm=False)` puts `VIN_P [analog]` into an editor; moving a `MacroItem` with `setPos` snaps to the grid; project round trip via `get_project`/`set_project` keeps the floorplan.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all tests; manual check with `PYTHONPATH=src python3 -m chip_planner`: add the fixture macro twice, drag, rotate, mark pins, generate, save, reopen.**
- [ ] **Step 5: Commit** `"Add Floorplan tab with draggable macros"`
