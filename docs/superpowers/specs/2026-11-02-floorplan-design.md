# Floorplan: macro placement and padframe generation

Status: design, 2026-11-02. Covers steps 1 and 2 of the planned workflow. Step 3 (bonding) is
brainstormed separately later.

## Intent

Today chiptile starts from the pads: the designer types the pad ring and the die grows around it.
In practice the designer first has hard macros (ADC, PLL, LNA, digital core, …) and decides where
they sit on the chip. That placement decides where the signal pads should go. Until now this was
done by hand.

The new workflow:

1. **Floorplan**: place the macros inside a core rectangle until they fit well. Mark which macro
   pins go off-chip. Each marked pin shows the nearest die edge, so the rough position of its pad
   is visible.
2. **Generate padframe**: the marked pins become pads in the existing side editors, on the side
   and in the order the floorplan suggests. The designer then adds VDD, VSS, IOVDD, IOVSS and
   all other pads in the normal pad ring editor.
3. **Bonding** (later, separate design): padframe plus macros, then the bond assignment to the
   package.

Success: a designer loads the LibreLane outputs of their macros, arranges them in minutes and gets
a first padframe whose signal pads already sit on the right sides.

## Goals

- Add macros by choosing a macro directory. Size and pins are always read from the LEF in that
  directory; the user never types them.
- Drag macros in a core rectangle, rotate them, snap to an adjustable grid.
- Mark macro pins as off-chip IO and see a flyline to the nearest die edge.
- Generate pads in the side editors from the marked pins.
- Save the floorplan in the project file.

## Non-goals

- No permanent link between floorplan and padframe. Generating is a one-time proposal; after that
  the padframe is edited freely and the floorplan does not follow (or overwrite) it.
- No routing, no power planning, no placement optimisation.
- No GDS reading (LEF only).
- No export of the macro placement to LibreLane yet (natural follow-up, see "Later").
- No bonding (step 3).

## Anti-goals

- Typing macro sizes or pin lists by hand for macros that have a LEF.
- Losing an existing padframe: generating must never delete lines the user wrote.
- Qt code in `model/` or `formats/` (project rule).

## Decisions by the user

- Macro source: the user selects a macro directory, e.g. `macros/adc_sar/`. chiptile reads
  `final/lef/<dirname>_top.lef` inside it (LibreLane run output). Size from `SIZE`, pins from `PIN`
  (direction, use, port geometry).
- Values are always looked up automatically: the project stores the path, and the LEF is read again
  when the project opens and on a `Reload` action.
- Core rectangle with a default size, adjustable in Settings.
- Adjustable grid, default 10 µm; macros snap to it.
- Macros can be moved freely with the mouse (drag) in the view.
- **Core size is a minimum**: in fixed core size mode the die is at least core + 2 × ring depth on
  each axis, and grows like a pad-limited die when the pads need more room. No corner overflow.
- **Several instances of one macro**: the same macro directory can be placed more than once. Each
  instance has its own instance name (default `<macro>0`, `<macro>1`, …, editable), position,
  rotation and IO checkboxes.
- **Placeholders stay plain boxes** (name and size, no pins): blocks like the digital core also come
  with a LEF, so placeholders are only for blocks that have no LEF yet.
- UI in English, in the style of the existing application (palette from `style.py`, same widgets,
  same stat tiles). The approved mockup is
  `.superpowers/brainstorm/*/content/floorplan-v3.html` (local, not committed); its structure:
  tabs `Floorplan · Padframe · Pin List · Settings · LibreLane` (Bonding tab later), left panel
  with one box per macro and a checkbox per pin (`→ IO` / `internal`), toolbar with legend,
  grid field, `Show grid`, `Generate padframe →`, zoom buttons; stat tiles CORE, MACROS,
  UTILIZATION, IO SIGNALS (T/R/B/L).

## Decisions made by Claude (open for correction)

- **Missing LEF**: if `<dir>/final/lef/<dirname>_top.lef` does not exist, use the only `*.lef` in
  `final/lef/`; if there is none or more than one, the macro stays with its last known values
  (cached in the project file) and a warning is shown.
- **Placeholder macros**: a macro without a directory, with only name and size typed in. This is the
  only case where sizes are typed.
- **Power pins** (`USE POWER` / `USE GROUND`) are listed apart and are not offered as pad
  candidates. Signal pins default to `internal`.
- **Pin position**: the centre of the pin's first port shape, in macro coordinates. Bus bits are
  separate LEF pins and appear separately.
- **Rotation** in 90° steps (double-click or a button), no mirroring.
- **Overlaps** are allowed but highlighted (warning colour) and listed as warnings.
- **Nearest edge**: measured from the pin position (with the macro's placement and rotation) to the
  four die edges; ties go T, R, B, L.
- **Generate padframe**: for every marked pin not already present as a pad name, insert a line on its
  side, ordered by the pin position along that edge in physical order (top/bottom left → right,
  left/right top → bottom). Existing lines are kept; new lines are placed among them by position
  only when the side is empty, otherwise appended at the physical end. Function tag from the LEF:
  `USE ANALOG` → `[analog]`, `DIRECTION INPUT/OUTPUT/INOUT` → `[in]`/`[out]`/`[io]`, output
  tristate → `[tri]`; `parse.infer_function` only when the LEF gives no direction. Name clash between two
  instances: pad name `<instance>_<pin>`.
- **Which core**: the floorplan core is the LibreLane `CORE_AREA` (layout core minus the PDK
  `core_margin`; without a PDK the margin is 0), so macros never sit in the core power-ring margin
  and the later `MACROS` export is a plain offset. Macro origin is the top-left corner of that area.
- **Core size storage**: `Settings.core_width`/`core_height` (JSON `core_w`/`core_h` at top level,
  next to `die_w`/`die_h`), edited in the Settings tab and the floorplan toolbar. Grid default in
  `Settings.grid` (JSON `grid`). The `floorplan` key holds only the macros.
- **Core and die**: the floorplan core size sets the die via the planned *fixed core size* mode,
  a third die-size mode next to pad-limited and fixed die (JSON `die_mode`: `"pads"`, `"die"`,
  `"core"`; older files map `fixed_die` true/false to `"die"`/`"pads"`; `square` still applies).
  Generating the padframe switches the project to this mode after a confirmation. The floorplan view draws the ring depth from the current settings, so the
  flylines point to real die edges.
- **Paths** in the project file are stored relative to the project file when possible.
- **Units**: µm everywhere, LEF `SIZE` and `RECT` are already in µm.
- Tab `Preview` is renamed to `Padframe`.

## Data model (project file)

New optional key `floorplan`; files without it load with an empty floorplan (`normalize_state` must
keep reading older files):

```json
"floorplan": {
  "macros": [
    {"name": "adc0", "macro": "adc_sar", "path": "macros/adc_sar", "x": 60.0, "y": 80.0, "rot": 0,
     "io": ["VIN_P", "VIN_N"],
     "cache": {"w": 420.0, "h": 310.0,
               "pins": [{"name": "VIN_P", "dir": "INPUT", "use": "SIGNAL", "x": 0.0, "y": 80.0}]}}
  ]
}
```

`x`/`y`: top-left corner of the placed (rotated) macro box, in µm, origin top-left of the core,
y points down (model convention). LEF coordinates (origin lower-left, y up) are converted
when read. `name` is the instance name (unique), `macro` the LEF macro name. `cache` holds the last
values read from the LEF (or the typed values of a placeholder, which has `path` empty); instances of
the same directory are read once and share the values.

## Where it goes

- `formats/lef.py`: minimal stdlib LEF reader (MACRO, SIZE, PIN, DIRECTION, USE, PORT/LAYER/RECT
  and POLYGON). No new dependency.
- `model/floorplan.py`: `Floorplan`, `Macro`, `MacroPin`, geometry (rotation, nearest edge,
  overlaps, utilisation), `generate_pads(project)`.
- `model/project.py`: `Project.floorplan`, JSON round trip, settings for default core size and grid.
- `model/layout.py`: fixed core size mode.
- `gui/`: Floorplan tab with a scene (drag, rotate, snap, flylines), left macro panel, settings
  fields. Qt only here.
- `__init__.py`: scripting API, e.g. `ct.read_lef(path)` and access via `project.floorplan`.
- Tests (stdlib unittest): LEF parsing with a small fixture LEF, rotation/edge geometry, generation
  order, JSON round trip incl. old files, GUI smoke test (offscreen).

## Left to the builder

- Exact widget layout within the existing style, keyboard shortcuts, zoom behaviour.
- How the left panel switches between side editors (Padframe) and macro list (Floorplan).
- Default core size (suggestion 1500 × 1200 µm).
- Internal API naming.

## Later

- Export of macro placement to LibreLane (`MACROS` with `instances`/locations in `config.yaml`).
- Bonding tab (step 3).
- Separate power rings / power domains (open todo from the user).
