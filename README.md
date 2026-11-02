# chip-planner

A lightweight tool for planning IC pad ring pinouts: type the pads of each side,
the die grows with them (pad-limited). RF/GSG pad groups, pin list and exports.
For analog/mixed-signal and RFIC designers doing early floorplanning.

## Install and start

```sh
pip install .                 # or: pip install -e .  for development
chip-planner               # start the GUI
chip-planner chip.json     # open a project
```

Without installing: `PYTHONPATH=src python3 -m chip_planner`.

## Entry syntax

One line per entry. In the GUI each side lists its pads as seen on the die:
top and bottom from left to right, left and right from top to bottom.
Empty lines at the end of a side are spacers as well (files of older versions ignored them).

| Entry | Meaning |
|---|---|
| `VDDA` | pad, type guessed from the name |
| *(empty line)* | spacer slot of one standard pitch |
| `NC` | pad without connection |
| `NAME [p\|g\|a\|rf\|d\|c\|nc]` | force type: power, ground, analog, RF, digital, clock, NC |
| `NAME {80x60}` | custom bond pad size W × H in µm (W along the edge) |
| `NAME @120` | custom pitch in µm |
| `RFIN [gsg]`, `[gs]`, `[sg]` | RF group, e.g. GND, RFIN, GND |
| `LO [gsgsg]` | differential: GND, LO_P, GND, LO_N, GND |
| `NAME [in\|out\|tri\|io\|analog\|vdd\|vss\|iovdd\|iovss\|none]` | IO function, selects the IO cell (default guessed from name and type) |
| `NAME [16mA]` | drive strength of output, tristate and bidirectional cells |
| `=== NAME` | power split: cuts the IO ring here and starts power domain `NAME` |

Options combine: `RFOUT [gsg] {70x70} @125`, `DOUT[3] [out] [4mA]`.

## PDK, LibreLane and package

In *Settings → Technology* choose a PDK (IHP SG13G2 and SG13CMOS5L, IO library
`sg13g2_io` / `sg13cmos5l_io`) and optionally a package from the EUROPRACTICE library.

- **With a PDK** the preview shows the real ring: 140 µm seal ring spacing, 80 × 180 µm IO cells,
  corner cells and 70 × 70 µm bondpads. Function and drive of each pad can be set in the
  *Pin List* (or with tags in the editor). The rows in the *Pin List* also show the IO cell,
  the power domain and the package pin.
- **Power splits**: an `=== NAME` line leaves a 10 µm gap in the IO ring. Every ring segment gets
  its own rails (`VDD_NAME`, `VSS_NAME`, `IOVDD_NAME`, `IOVSS_NAME`); without splits they are
  `VDD`, `VSS`, `IOVDD`, `IOVSS`. The planner warns if a domain has no supply pad of a kind.
- **LibreLane tab / File → Export LibreLane Files…** writes:
  - `padring_config.yaml`: `DIE_AREA`, `CORE_AREA`, `PAD_CFG` and the `PAD_SOUTH/EAST/NORTH/WEST`
    lists, to copy into the LibreLane `config.yaml` (flow `Chip`),
  - `pad_cfg.tcl`: places the IO cells exactly as planned (LibreLane's default script spreads
    them evenly) and keeps the split gaps free,
  - `chip_top.sv`: the IO cell instances with the same names, top-level `*_PAD` ports and the
    `chip_core` instance; `chip_core_template.sv`: the matching core ports,
  - `bondplan_pinout.yaml` (with a package): `PACKAGE_NAME` and `PINOUT` for the bondplan config.
- The design must still provide the bondpad cell (`PAD_BONDPAD_NAME`, e.g.
  `sg13g2_ip__bondpad_70x70` with `EXTRA_LEFS`/`EXTRA_GDS`), as in any IHP chip.

See [examples/ihp_sg13g2_domains.json](examples/ihp_sg13g2_domains.json). From the command line:

```sh
chip-planner export examples/ihp_sg13g2_domains.json --librelane flow/padring
```

## Chip view

The *Chip* tab shows the whole chip: the IO ring with the pads, the core area inside it, the
macros and a flyline from every checked macro pin to the pad with the same name. The left panel has
two tabs: *Pads* (the side editors) and *Macros* (the macro list).

**Macros**
- **Add Macro…** takes a LibreLane run directory, e.g. `macros/adc_sar/`. Size and pins come from
  `final/lef/adc_sar_top.lef` (or the only `*.lef` in `final/lef/`). The project stores the path;
  the LEF is read again when the project opens and with *File → Reload Macros* (F5). One macro can be
  placed several times (`adc_sar0`, `adc_sar1`, …). **Add Placeholder…** adds a box without a LEF.
- Drag a macro to move it: it snaps to the grid (default 10 µm) and to the edges of other macros
  (a dashed guide shows it). Double-click or *Rotate* turns it by 90°, *Auto-rotate* picks the
  rotation with the shortest flylines. Shift-click selects macros for *Align Left* / *Align Top*.
- Per macro: the pins that go off-chip, the class (`normal`, `sensitive` for analog/RF, `noisy` for
  digital or clocks), the power domain and the halo.

**Pads**
- Drag a pad (or a `=== NAME` split marker) along the ring to move it, also to another side; the
  side editors follow. Dropped on another pad it is sorted in; dropped on an empty part of a side
  (or on a spacer) it stays exactly there and no other pad moves: empty lines fill the distance. Alt-click locks a pad (tag `[lock]`): it can no longer be dragged and
  *Optimize Pad Order* leaves it in place.
- *Add Missing Pads* adds a pad for every checked pin without one, where its dashed line points.
  *Suggest Supply Pads* adds VDD/VSS pads (named after the macro's LEF power pins) next to the
  macros that have none of their domain within reach.
- *Optimize Pad Order* sorts the connected pads of each side by the positions of their macro pins,
  so the flylines no longer cross. Differential pairs (`VIN_P`/`VIN_N`) stay together.

**Checks** (thresholds in *Settings → Checks*)
- Crossing flylines (orange, counted in the stat tiles) and the longest analog/RF flyline.
- Differential pairs that are not adjacent; a sensitive pad next to a noisy one (a connected pad
  takes the class of its macro, others their type).
- Overlapping macros, macros outside the core, overlapping halos, sensitive and noisy macros closer
  than the minimum distance.
- A macro without a VDD and a VSS pad of its domain within the distance (IO supplies don't count).

*Layers* hides the grid, pads, macros, halos, flylines, power domains or pad names; *Measure* shows
distances. *Edit → Undo/Redo* (Ctrl+Z, Ctrl+Shift+Z) covers all chip view and macro list actions;
typing in a side editor keeps its own undo while it has the focus.

The die follows the core size in *Fixed core size (minimum)* mode (set when the first macro is
added): the die is at least core + IO ring (+ the PDK core margin) and grows with the pads.

**Demo**: [examples/chip_demo.json](examples/chip_demo.json) uses the demo macros in
[examples/macros/](examples/macros/) (abstract LEFs of an ADC, a PLL, an LNA and a digital core, in
the LibreLane run layout `final/lef/<name>_top.lef`). It starts with one crossing and one missing pad:
try *Optimize Pad Order* and *Add Missing Pads*.

**LibreLane**: with macros, the LibreLane export also writes `macros.yaml` (`MACROS` with LEF/GDS and
the instance locations, `i_chip_core.<instance>`), and `chip_core_template.sv` lists the instances
to create in the core. *Export MACROS…* shows it.

## Scripting

The package works without Qt:

```python
import chip_planner as cp

project = cp.load("chip.json")
project.sides["L"].append("VDDA [p]")
project.settings.std.pitch = 90
layout = project.layout()
print(layout.die_width, layout.die_height, layout.warnings)
for pin in layout.pins:
    print(pin.no, pin.name, pin.x, pin.y)
cp.export_csv(project, "pins.csv")
cp.export_svg(project, "ring.svg")
cp.save(project, "chip.json")

macro = cp.Macro.from_dir("macros/adc_sar", "adc0")  # reads final/lef/adc_sar_top.lef
macro.io = ["VIN_P", "VIN_N"]
project.floorplan.macros.append(macro)
cp.add_missing_pads(project)                         # adds VIN_P/VIN_N pads, fixed core mode
print(cp.analyse(project).warnings)                  # crossings, pairs, analog and power checks
```

`project.sides` holds each side in numbering order; `project.physical_lines(side)` and
`project.set_physical_lines(side, lines)` use the order as seen on the die, like the GUI.

See [examples/script_example.py](examples/script_example.py). Command line export:

```sh
chip-planner export chip.json --csv pins.csv --svg ring.svg
```

## Development

```sh
python3 -m unittest discover -s tests -t .
```
