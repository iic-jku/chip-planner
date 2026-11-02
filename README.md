# Pad-Ring-Planer

A lightweight tool for planning IC pad ring pinouts: type the pads of each side,
the die grows with them (pad-limited). RF/GSG pad groups, pin list and exports.
For analog/mixed-signal and RFIC designers doing early floorplanning.

## Install and start

```sh
pip install .                 # or: pip install -e .  for development
pad-ring-planer               # start the GUI
pad-ring-planer chip.json     # open a project
```

Without installing: `PYTHONPATH=src python3 -m pad_ring_planer`.

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
pad-ring-planer export examples/ihp_sg13g2_domains.json --librelane flow/padring
```

## Scripting

The package works without Qt:

```python
import pad_ring_planer as prp

project = prp.load("chip.json")
project.sides["L"].append("VDDA [p]")
project.settings.std.pitch = 90
layout = project.layout()
print(layout.die_width, layout.die_height, layout.warnings)
for pin in layout.pins:
    print(pin.no, pin.name, pin.x, pin.y)
prp.export_csv(project, "pins.csv")
prp.export_svg(project, "ring.svg")
prp.save(project, "chip.json")
```

`project.sides` holds each side in numbering order; `project.physical_lines(side)` and
`project.set_physical_lines(side, lines)` use the order as seen on the die, like the GUI.

See [examples/script_example.py](examples/script_example.py). Command line export:

```sh
pad-ring-planer export chip.json --csv pins.csv --svg ring.svg
```

## Development

```sh
python3 -m unittest discover -s tests -t .
```
