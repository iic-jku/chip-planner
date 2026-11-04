"""Command line entry point. Without a subcommand the GUI starts.

    prep-ic [PROJECT]
    prep-ic export PROJECT [--csv FILE] [--svg FILE] [--librelane DIR]
"""

import argparse
import sys

from . import APP_NAME, __version__, export_csv, export_librelane, export_svg, load


def _export(argv):
    ap = argparse.ArgumentParser(prog="prep-ic export", description="Export a project without the GUI.")
    ap.add_argument("project", help="project file (.json)")
    ap.add_argument("--csv", metavar="FILE", help="write the pin list as CSV")
    ap.add_argument("--svg", metavar="FILE", help="write the drawing as SVG")
    ap.add_argument("--librelane", metavar="DIR",
                    help="write the LibreLane pad ring files (needs a PDK in the project)")
    args = ap.parse_args(argv)
    if not (args.csv or args.svg or args.librelane):
        ap.error("nothing to export, give --csv, --svg and/or --librelane")
    try:
        project = load(args.project)
        if args.csv:
            export_csv(project, args.csv)
        if args.svg:
            export_svg(project, args.svg)
        if args.librelane:
            for path in export_librelane(project, args.librelane, source=args.project):
                print(f"wrote {path}")
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for w in project.layout().warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "export":
        return _export(argv[1:])
    ap = argparse.ArgumentParser(prog="prep-ic", description=f"{APP_NAME}: plan IC pad ring pinouts.",
                                 epilog="Subcommand: 'prep-ic export -h' for exports without the GUI.")
    ap.add_argument("project", nargs="?", help="project file (.json) to open")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args = ap.parse_args(argv)
    try:
        from .gui import run
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return run(args.project)


if __name__ == "__main__":
    sys.exit(main())
