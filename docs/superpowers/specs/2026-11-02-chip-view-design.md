# Chip view: padframe and floorplan in one view

Status: design, 2026-11-02. Follows `2026-11-02-floorplan-design.md` (implemented) and replaces its
separate Floorplan tab. Approved mockup: `.superpowers/brainstorm/*/content/combined-v3.html`
(local, not committed).

## Intent

The Floorplan tab drew its own core rectangle next to the real padframe, so the designer saw two
pictures that did not agree. The designer wants one picture of the chip: the IO ring with the real
pads, the real core inside it, the macros in that core, and a line from every off-chip macro pin to
its pad. In that picture they arrange macros and pads together, and the tool helps with the things
an analog/RF designer checks by hand today: crossing connections, differential pairs, noisy pads
next to sensitive ones, distances to supply pads, power domains.

Success: one view in which a padframe and a floorplan are planned together, and in which the
common pinout mistakes show up as warnings before tapeout.

## Goals (all five idea groups the user approved)

1. **One Chip view**: tab `Chip` replaces `Floorplan` and `Padframe`. Pads, IO ring, core, macros,
   flylines, grid. Pads can be dragged along the ring (also to another side); macros can be dragged
   in the core. Left panel with two tabs: `Pads` (the side editors) and `Macros` (the macro list).
2. **Pad order**: flylines that cross are drawn in the warning colour and counted; `Optimize pad
   order`; differential pairs are checked, move together and stay together; pads can be locked.
3. **Analog/RF rules**: macro class (`normal`, `sensitive`, `noisy`) and halo; warnings for a
   sensitive pad next to a noisy pad, overlapping halos, a sensitive macro too close to a noisy one,
   and analog/RF flylines that are too long.
4. **Power**: each macro belongs to a power domain (from the `=== NAME` split lines); a warning when
   a macro has no VDD or VSS pad of its domain within a distance; `Suggest supply pads` adds them
   inside the domain; split markers can be dragged on the ring like pads.
5. **Placement and workflow**: `Auto-rotate` per macro, snapping to the edges of other macros with
   a guide line, `Align left`/`Align top` for selected macros, a measure tool, undo/redo for all view
   actions, `Export MACROS` for LibreLane, hover cross-highlighting (pad, pin, flyline, editor line,
   length), a `Layers` menu (Grid, Pads, Macros, Halos, Flylines, Power domains, Pad names).

## Non-goals

- Bonding and the package in this view (later, step 3).
- Macro-to-macro connections from a netlist.
- Free pad positions with automatic spacers: dragging a pad changes the order of its side only.
- Routing, congestion, power grid.
- Macros in the SVG/PNG export (they stay padframe exports for now).

## Anti-goals

- Two different cores in one picture (the reason for this change).
- Changing editor text without the user doing it: the side editors change only through a drag,
  `Optimize`, `Add missing pads`, `Suggest supply pads` or typing, and each is one undo step.
- Qt code outside `gui/`; all checks and edits live in the model and are scriptable.

## Decisions by the user

- Merge floorplan and padframe into one view; flylines go from checked macro pins to the pads with
  the same name; pads can be moved along the padframe.
- Grid in this view (field and `Show grid`, default 10 µm as before).
- Build all of groups 1–5 as shown in the mockup.

## Decisions made by Claude (open for correction)

- **Core**: the core shown is the layout core area (LibreLane `CORE_AREA` = die − 2 × (ring depth +
  PDK core margin)). The separate centred core rectangle is gone. Settings keep the core size as the
  minimum for the *Fixed core size* mode. Macro `x`/`y` are relative to the top-left of `CORE_AREA`.
  Projects saved with the previous Floorplan tab (only today, local) are read as they are (their
  macros shift by the old centring offset); no migration.
- **Flyline target**: the inner edge centre of the pad's IO cell slot. A checked pin whose name is no
  pad yet gets a dashed line to the nearest die edge and a `+ NAME` marker; `Add missing pads`
  (the former `Generate Padframe`) inserts it at that position of the side instead of appending.
  If the same name is checked in several instances, the pad name is `<instance>_<pin>` as before.
- **Pad drag**: drop position decides side and index (by slot centres). A grouped line (`[gsg]`)
  moves as one line. Split lines (`=== NAME`) are dragged the same way. Locked pads cannot be
  dragged and are not moved by `Optimize`.
- **Lock** is a line tag `[lock]` (editor syntax, saved with the line, shown with a lock symbol);
  alt-click on a pad toggles it. It means: not draggable and not moved by `Optimize`. Other edits on
  the same side (dropping or inserting another line before it) may still shift it by one slot.
- **Differential pairs**: names that differ only in a final `P`/`N` (`VIN_P`/`VIN_N`, `INP`/`INN`,
  `LO_P`/`LO_N`) on the same side. Warning when not adjacent. Dragging one moves the partner next to
  it (P before N in physical order). `Optimize` keeps pairs together.
- **Optimize pad order**, per side: the unlocked pads that have a flyline keep the set of slots they
  occupy and are sorted in it by the position of their macro pin along that side. Pairs are joined
  only by swapping within those slots (P before N); a pair that would need a fixed line to move stays
  split and keeps its warning. Supplies, splits, locked and unconnected pads stay where they are.
- **Crossings**: two flylines cross when their straight segments intersect (shared end points do not
  count).
- **Pad classes for the adjacency and length rules**: a pad connected by a flyline takes the class of
  its macro (`sensitive` or `noisy`; a `normal` macro falls through to the type). Otherwise: type
  analog or RF = sensitive, clock or digital = noisy, supplies and NC = neither. Reason: `pad_type`
  makes every pad with a signal function (`[in]`, `[out]`, `[io]`) digital, so an LNA's `RFIN [in]`
  would count as noisy; `pad_type` itself stays unchanged. Neighbours are adjacent pads on one side;
  a spacer line or a split between them breaks the adjacency. The length limit applies to flylines
  of sensitive pads.
- **Macro class and halo**: stored per instance (`class`, `halo` in JSON; defaults `normal` and the
  settings default). Halo overlap and sensitive–noisy spacing use the macro rectangles.
- **Thresholds in Settings** (new group *Checks*): default halo 20 µm, sensitive–noisy spacing
  100 µm, max analog/RF flyline length 900 µm, max distance to a supply pad 1000 µm. JSON keys
  `halo`, `spacing`, `max_flyline`, `max_supply_dist`.
- **Macro domain**: per instance (`domain` in JSON); the list offers the domains of the split lines;
  empty = the domain of the whole ring when there are no splits. The supply names to suggest come
  from the macro's LEF power pins (`USE POWER` → VDD name, `USE GROUND` → VSS name); a placeholder
  or a macro without power pins uses `VDD`/`VSS` (or `VDD_<DOMAIN>`/`VSS_<DOMAIN>` with splits).
  Distance = from the macro centre to the inner edge centre of the pad. A supply pad is matched by
  function, not by name: any pad with function `vdd` (or `vss`) in the macro's domain counts; IO
  supplies (`iovdd`/`iovss`) do not. A macro needs one of each. Suggested pads get an explicit
  `[vdd]`/`[vss]` tag (a LEF name like `VPWR` would otherwise classify as digital); with several
  power pins of one kind, the first one names the pad.
- **Suggest supply pads**: one pad at a time, next to the pad of the macro's domain that is closest
  to the macro, on the macro's side of it; repeat until no macro misses a supply (a new pad can serve
  several macros).
- **Auto-rotate**: tries 0/90/180/270°, keeps the macro inside the core, takes the rotation with the
  shortest total flyline length to existing pads (ties: keep the current one).
- **Edge snapping**: while dragging, a macro edge within 15 µm (screen-independent) of an edge of
  another macro snaps to it; a dashed guide line shows it. Grid snapping first, then edge snapping.
- **Selection**: shift-click toggles; `Align left`/`Align top` need two or more selected macros.
- **Measure**: toggle button; drag draws a line with Δx, Δy and distance in µm; Esc ends.
- **Undo/redo**: a project snapshot stack in the window (Edit menu, Ctrl+Z / Ctrl+Shift+Z /
  Ctrl+Y). Steps: every Chip view action (drags, rotate, lock, align, optimize, add missing pads,
  suggest supplies, auto-rotate) and every macro panel edit (checkboxes, class, halo, domain, rename,
  add, duplicate, remove, reload). Settings changes are not undo steps. Typing in a side editor is
  one step per editing session (snapshot when the editor loses focus with changed text); while an
  editor has focus, Ctrl+Z is the editor's own undo.
- **Export MACROS**: new LibreLane file `macros.yaml` with `MACROS:` → per macro `gds`, `lef`
  (`dir::` paths relative to the export directory, `final/gds/<name>.gds`, `final/lef/<name>.lef`)
  and `instances` with `location` (lower-left, die coordinates, origin lower-left) and `orientation`
  (0/90/180/270° clockwise → `N`/`E`/`S`/`W`). The macros sit inside the core, which `chip_top.sv`
  instantiates as `i_chip_core`, so instance names are `i_chip_core.<instance>`, and
  `chip_core_template.sv` gets a comment block listing the macro instances to create with those
  names. Shown in the LibreLane tab and written with the other files when the project has macros;
  placeholders are left out with a comment. To be verified in the IIC-OSIC-TOOLS container
  (`librelane` macro placement), like the pad ring.
- **Hover**: highlight only (no re-layout); shows the flyline length next to the line.
- **Layers** menu as a tool button with checkable actions; the state is a view preference, not saved.
- Stat tiles: PADS, DIE, CROSSINGS, LONGEST ANALOG/RF FLYLINE, MACROS · UTILIZATION.

## Data model changes

- Line syntax: tag `[lock]`.
- `Macro`: `cls` (`"normal" | "sensitive" | "noisy"`), `halo: Optional[float]` (None = settings
  default), `domain: str`. JSON `class`, `halo`, `domain`; older files load with defaults.
- `Settings`: `halo`, `spacing`, `max_flyline`, `max_supply_dist`.
- All checks as model functions returning data (flylines with crossing flags and lengths, warnings,
  supply suggestions), all edits (`move_line`, `optimize_pad_order`, `add_missing_pads`,
  `suggest_supply_pads`, `auto_rotate`) as model functions on a `Project`, so the GUI and scripts use
  the same code.

## Left to the builder

- Widget layout within the existing style, icons, shortcut details beyond those named.
- How the scene is updated during drags (full redraw on release is fine).
- Internal function names beyond the public API listed above.
