"""Pad-Ring-Planer: plan IC pad ring pinouts.

Scripting API (no Qt needed)::

    import pad_ring_planer as prp

    project = prp.load("chip.json")
    project.sides["L"].append("VDDA [p]")
    project.settings.std.pitch = 90
    layout = project.layout()
    print(layout.die_width, layout.die_height, layout.warnings)
    prp.export_csv(project, "pins.csv")
    prp.export_svg(project, "ring.svg")
    prp.save(project, "chip.json")

    project.settings.pdk = "ihp-sg13g2"          # see prp.pdk_names()
    project.settings.package = "OP_QFN32_A4_FIT"  # see prp.package_names()
    prp.export_librelane(project, "flow/padring")  # config part, pad_cfg.tcl, chip_top.sv, …
"""

# defined before the imports: submodules import them
__version__ = "0.1.0"
APP_NAME = "Pad-Ring-Planer"

from .formats.librelane import export_librelane, librelane_files
from .formats.pinlist import export_csv
from .formats.project_file import load, save
from .formats.svg import export_svg, to_svg
from .model import (SIDE_NAMES, SIDES, TYPE_NAMES, TYPES, Layout, PadSettings, Pin, Project,
                    Settings, build_layout)
from .model.pdk import get_package, get_pdk, package_names, pdk_names

__all__ = ["APP_NAME", "SIDES", "SIDE_NAMES", "TYPES", "TYPE_NAMES", "Layout", "PadSettings", "Pin",
           "Project", "Settings", "build_layout", "export_csv", "export_librelane", "export_svg",
           "get_package", "get_pdk", "librelane_files", "load", "package_names", "pdk_names", "save", "to_svg"]
