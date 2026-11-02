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
Empty lines at the end of a side are ignored.

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

## Floorplan

The *Floorplan* tab places hard macros in the core before the pad ring exists:

- **Add Macro…** takes a LibreLane run directory, e.g. `macros/adc_sar/`. Size and pins come from
  `final/lef/adc_sar_top.lef` (or the only `*.lef` in `final/lef/`). The project stores only the
  path; the LEF is read again when the project opens and with *File → Reload Macros* (F5).
  The same macro can be placed several times (`adc_sar0`, `adc_sar1`, …).
- **Add Placeholder…** adds a box with name and size for a block that has no LEF yet.
- Drag a macro to move it (it snaps to the grid, default 10 µm), double-click or *Rotate* turns it
  by 90°. Overlapping macros and macros outside the core are marked and listed as warnings.
- Check the pins that go off-chip. Each one gets a flyline to the nearest die edge.
- **Generate Padframe →** adds a pad line for every checked pin that is not a pad yet, on the side
  the flyline points to (function from the LEF direction, e.g. `VIN_P [analog]`, `DOUT[0] [out]`).
  Existing lines are kept. Then add the supply pads in the side editors as usual.

The core size and the grid are set in *Settings → Die* or in the floorplan toolbar. The floorplan
uses the die size mode *Fixed core size (minimum)*: the die is at least core + IO ring (+ the core
margin of the PDK) and grows when the pads need more room. The core is centred in the LibreLane
`CORE_AREA`.

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
cp.generate_pads(project)                            # adds VIN_P/VIN_N pads, fixed core mode
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
