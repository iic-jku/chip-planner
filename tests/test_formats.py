# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tests import ROOT

import prep_ic as prep
from prep_ic.formats import pinlist


def child_env():
    # inherit the environment: Windows Python 3.10 and older cannot start without SYSTEMROOT
    return {**os.environ, "PYTHONPATH": str(ROOT / "src")}


class Exports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.project = prep.Project.example()

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load(self):
        path = self.dir / "sub" / "p.json"
        prep.save(self.project, path)
        self.assertEqual(prep.load(path), self.project)

    def test_load_rejects_other_json(self):
        path = self.dir / "x.json"
        path.write_text("[1, 2]")
        with self.assertRaises(ValueError):
            prep.load(path)

    def test_csv(self):
        path = self.dir / "pins.csv"
        prep.export_csv(self.project, path)
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(tuple(rows[0]), pinlist.HEADER)
        self.assertEqual(len(rows) - 1, len(self.project.layout().pins))
        self.assertEqual(rows[1][:4], ["1", "Left", "VDDIO", "Power"])

    def test_svg(self):
        path = self.dir / "ring.svg"
        prep.export_svg(self.project, path)
        root = ET.parse(path).getroot()
        ns = {"s": "http://www.w3.org/2000/svg"}
        texts = [t.text for t in root.iterfind(".//s:text", ns)]
        self.assertIn("VDDIO", texts)
        self.assertIn("31", texts)


class CommandLine(unittest.TestCase):
    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-m", "prep_ic", *args], capture_output=True, text=True,
                              cwd=ROOT, env={**child_env(), **env})

    def test_export(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("export", "examples/padring.json", "--csv", f"{d}/p.csv", "--svg", f"{d}/p.svg")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(Path(d, "p.csv").exists() and Path(d, "p.svg").exists())

    def test_export_missing_file(self):
        r = self.run_cli("export", "does-not-exist.json", "--csv", "x.csv")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error:", r.stderr)

    def test_export_prints_findings_and_exits_0(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_cli("export", "examples/chip_demo.json", "--csv", f"{d}/p.csv")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(Path(d, "p.csv").exists())
        self.assertIn("warning: 1 flyline crossing: VIN_P/VIN_N", r.stderr)
        self.assertIn("warning: 1 checked pins without pad: CLK", r.stderr)

    def test_check_clean(self):
        for project in ("examples/padring.json", "examples/ihp_sg13g2_domains.json"):
            r = self.run_cli("check", project)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "no findings"), r.stderr)

    def test_check_findings(self):
        r = self.run_cli("check", "examples/chip_demo.json")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["1 flyline crossing: VIN_P/VIN_N", "1 checked pins without pad: CLK"])

    def test_check_reports_a_lost_lef(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(ROOT / "examples" / "chip_demo.json", d)  # its macro paths no longer resolve
            r = self.run_cli("check", str(Path(d, "chip_demo.json")))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("No LEF found for adc_sar0", r.stdout)

    def test_check_that_did_not_run_is_no_finding(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (("text.json", "not json"), ("list.json", "[]"), ("sides.json", '{"sides": 3}')):
                Path(d, name).write_text(text, encoding="utf-8")
                r = self.run_cli("check", str(Path(d, name)))
                self.assertEqual(r.returncode, 2, name)
                self.assertIn("error:", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.run_cli("check", "does-not-exist.json").returncode, 2)
        self.assertEqual(self.run_cli("check").returncode, 2)  # no project given

    def test_check_name_outside_the_output_encoding(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "chip.json")
            prep.save(prep.Project(sides={"L": ["Ä [foo]"], "T": [], "R": [], "B": []}), path)
            r = self.run_cli("check", str(path), PYTHONIOENCODING="ascii")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("Unknown tag in pad name: \\xc4 [foo]", r.stdout)


class NoQtOutsideGui(unittest.TestCase):
    """Model, formats, API and CLI export must work without loading Qt."""

    def test_no_qt_loaded(self):
        code = (
            "import sys, tempfile, os\n"
            "import prep_ic as prep, prep_ic.cli as cli\n"
            "import prep_ic.model, prep_ic.formats.svg, prep_ic.formats.pinlist\n"
            "d = tempfile.mkdtemp()\n"
            "assert cli.main(['export', 'examples/padring.json', '--csv', os.path.join(d, 'a.csv'),"
            " '--svg', os.path.join(d, 'a.svg')]) == 0\n"
            "assert cli.main(['check', 'examples/padring.json']) == 0\n"
            "bad = [m for m in sys.modules if m.split('.')[0] in ('PySide6', 'PyQt6', 'shiboken6')"
            " or m.startswith('prep_ic.gui.')]\n"
            "assert not bad, bad\n"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_gui_start_without_qt_is_a_clean_error(self):
        code = (
            "import sys\n"
            "sys.modules.update({'PySide6': None, 'PyQt6': None})\n"  # blocks them where Qt is installed
            "import prep_ic.cli as cli\n"
            "sys.exit(cli.main([]))\n"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT,
                           env=child_env())
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("error: Qt is missing", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_no_qt_import_in_source(self):
        src = ROOT / "src" / "prep_ic"
        for path in src.rglob("*.py"):
            if "gui" in path.relative_to(src).parts:
                continue
            text = path.read_text(encoding="utf-8")
            for qt in ("PySide6", "PyQt6", ".gui."):
                self.assertNotIn(qt, text.replace("from .gui import run", ""), f"{path} mentions {qt}")


if __name__ == "__main__":
    unittest.main()
