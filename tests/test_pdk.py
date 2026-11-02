import re
import unittest

from tests import ROOT  # noqa: F401  (sets the import path)

import chip_planner as cp
from chip_planner.formats.librelane import (bondplan_yaml, chip_top_sv, config_yaml, librelane_files,
                                               pad_cfg_tcl)
from chip_planner.model.parse import format_entry, infer_function, parse_line


def compac_like(split=False, package=""):
    """8 pads per side on a 1600 µm IHP die, as in a real tapeout (checked with LibreLane)."""
    p = cp.Project()
    st = p.settings
    st.pdk, st.package = "ihp-sg13g2", package
    st.fixed_die, st.die_width, st.die_height, st.std.pitch = True, 1600, 1600, 115
    p.sides["L"] = ["clk [in]", "rst_n [in]", "enable", "IOVDD", "IOVSS", "VDD", "VSS", "out[8] [out]"]
    p.sides["B"] = [f"out[{i}] [out]" for i in range(8)]
    p.sides["R"] = ["ain[0] [analog]", "", "ain[1] [analog]", "IOVDD", "IOVSS", "VDD", "VSS"]
    if split:
        p.sides["R"] = ["=== ANA", "ain[0] [analog]", "ain[1] [analog]", "AVDD [vdd]", "AVSS [vss]",
                        "AIOVDD [iovdd]", "AIOVSS [iovss]", "=== MAIN"]
    p.sides["T"] = [f"bidir[{i}] [io] [4mA]" for i in range(4)]
    return p


class Syntax(unittest.TestCase):
    def test_function_drive_split(self):
        e = parse_line("DOUT[3] [out] [16mA] @120")
        self.assertEqual((e["name"], e["function"], e["drive"], e["pitch"]), ("DOUT[3]", "out", 16, 120.0))
        self.assertEqual(parse_line("=== ANA"), {"split": True, "domain": "ANA"})
        self.assertEqual(parse_line("---")["name"], "---")  # old NC notation still a pad

    def test_format_round_trip(self):
        for line in ("DOUT [out] [16mA]", "RF [gsg] [analog] {60x60} @110", "X [d] [io]", "=== ANA"):
            self.assertEqual(format_entry(parse_line(line)), line)

    def test_infer_function(self):
        cases = {("VDDIO", "pwr"): "iovdd", ("VSSD", "gnd"): "vss", ("CLK_IN", "clk"): "in",
                 ("SDO", "dig"): "out", ("RST_N", "dig"): "in", ("GPIO3", "dig"): "inout",
                 ("VREF", "ana"): "analog", ("NC", "nc"): "none"}
        for (name, typ), fn in cases.items():
            self.assertEqual(infer_function(name, typ), fn, name)

    def test_function_sets_type(self):
        lay = cp.Project(sides={"L": ["AVDD [vdd]", "VDD_SENSE [analog]", "X [none]"],
                                 "T": [], "R": [], "B": []}).layout()
        self.assertEqual([p.type for p in lay.pins], ["pwr", "ana", "nc"])


class PdkGeometry(unittest.TestCase):
    def test_ring_and_cells(self):
        lay = compac_like().layout()
        self.assertEqual((lay.die_width, lay.ring_depth, lay.warnings), (1600, 320, []))
        out0 = next(p for p in lay.pins if p.name == "out[0]")
        self.assertEqual((out0.x - 40, out0.y), (357, 105))  # IO cell edge and bondpad centre
        self.assertEqual(out0.cell, "sg13g2_IOPadOut30mA")
        bidir = next(p for p in lay.pins if p.name == "bidir[0]")
        self.assertEqual(bidir.cell, "sg13g2_IOPadInOut4mA")
        for p in lay.pins:
            self.assertEqual((p.x - 40) % 1 if p.side in "TB" else (p.y - 40) % 1, 0, p.name)

    def test_pitch_too_small(self):
        p = compac_like()
        p.settings.std.pitch = 70
        self.assertTrue(any(w.startswith("Pitch smaller than the IO cell") for w in p.layout().warnings))

    def test_missing_supply(self):
        p = compac_like()
        p.sides["R"] = ["ain[0] [analog]"]
        p.sides["L"] = ["clk [in]", "VDD", "VSS"]
        self.assertIn("The IO ring has no IOVDD/IOVSS pad", p.layout().warnings)


class PowerDomains(unittest.TestCase):
    def test_domains_wrap_around(self):
        lay = compac_like(split=True).layout()
        self.assertEqual(lay.domains, ["ANA", "MAIN"])
        dom = {p.name: p.domain for p in lay.pins}
        self.assertEqual((dom["ain[0]"], dom["AVDD"], dom["clk"], dom["out[0]"], dom["bidir[3]"]),
                         ("ANA", "ANA", "MAIN", "MAIN", "MAIN"))
        self.assertEqual(lay.warnings, [])

    def test_domain_without_supply(self):
        p = compac_like(split=True)
        p.sides["R"] = ["=== ANA", "ain[0] [analog]", "=== MAIN"]
        self.assertIn("Power domain ANA has no VDD/VSS/IOVDD/IOVSS pad", p.layout().warnings)

    def test_single_split_warns(self):
        p = compac_like()
        p.sides["R"].append("=== X")
        self.assertTrue(any(w.startswith("Only one power split") for w in p.layout().warnings))


class Packaging(unittest.TestCase):
    def test_qfn_one_to_one(self):
        p = compac_like(package="OP_QFN32_A4_FIT")
        p.sides["R"] = ["IOVDD", "IOVSS", "VDD", "VSS", "a", "b", "c", "d"]
        p.sides["T"] += ["e", "f", "g", "h"]
        lay = p.layout()
        self.assertEqual([x.package_pin for x in lay.pins], [x.no for x in lay.pins])
        self.assertEqual(lay.unbonded_leads, [])

    def test_fewer_pads_are_centred(self):
        lay = compac_like(package="OP_QFN32_A4_FIT").layout()
        top = sorted(lay.pins_on("T"), key=lambda x: -x.x)  # counter-clockwise: right to left
        self.assertEqual([x.package_pin for x in top], [27, 28, 29, 30])
        self.assertIn(25, lay.unbonded_leads)

    def test_lcc_pin1_top_centre(self):
        leads = cp.get_package("JLCC44_A4").leads()
        self.assertEqual(leads["T"], [40, 41, 42, 43, 44, 1, 2, 3, 4, 5, 6])
        self.assertEqual(leads["L"][0], 7)


class LibreLaneOutput(unittest.TestCase):
    def test_needs_pdk(self):
        with self.assertRaises(ValueError):
            librelane_files(cp.Project.example())

    def test_names_match_between_files(self):
        lay = compac_like(split=True).layout()
        cfg, sv, tcl = config_yaml(lay), chip_top_sv(lay), pad_cfg_tcl(lay)
        listed = re.findall(r'"(pad_\w+)"', cfg)
        self.assertEqual(len(listed), sum(1 for p in lay.pins if p.cell))
        instances = re.findall(r"^\s+sg13g2_\w+ (pad_\w+) \($", sv, re.M)
        self.assertEqual(sorted(listed), sorted(instances))
        placed = re.findall(r"\{IO_\w+ (pad_\w+) [\d.]+\}", tcl)
        self.assertEqual(sorted(placed), sorted(listed))
        self.assertIn("{IO_EAST", tcl.split("set prp_gaps {")[1].split("}")[0] + "}")

    def test_config_values(self):
        cfg = config_yaml(compac_like().layout())
        self.assertIn("DIE_AREA: [0, 0, 1600, 1600]", cfg)
        self.assertIn("CORE_AREA: [365, 365, 1235, 1235]", cfg)
        self.assertIn("PAD_CFG: dir::pad_cfg.tcl", cfg)
        west = cfg.split("PAD_WEST: [")[1].split("\n]")[0]
        self.assertLess(west.index("pad_out_8"), west.index("pad_clk"))  # bottom to top

    def test_chip_top_ports(self):
        sv = chip_top_sv(compac_like(split=True).layout())
        for decl in ("inout wire [8:0] out_PAD", "inout wire [1:0] ain_PAD", "inout wire VDD_ANA",
                     ".bidir_oe(bidir_c2p_en)", ".padres(ain_padres[1])"):
            self.assertIn(decl, sv)

    def test_bondplan(self):
        text = bondplan_yaml(compac_like(package="OP_QFN32_A4_FIT").layout())
        self.assertIn("PACKAGE_NAME: OP_QFN32_A4_FIT", text)
        self.assertRegex(text, r'\n  1:\s+"clk_PAD"')
        self.assertRegex(text, r'\n  4:\s+"IOVDD"')
        self.assertRegex(text, r'\n  25:\s+"~"')


class MacroExport(unittest.TestCase):
    def project(self):
        import os
        from chip_planner.formats.lef import read_lef
        from chip_planner.model.floorplan import Macro, MacroDef
        d = ROOT / "tests" / "data" / "macros" / "adc_sar"
        (m,) = read_lef(d / "final" / "lef" / "adc_sar_top.lef")
        p = compac_like()
        p.floorplan.macros = [Macro("adc0", m.name, str(d), 40.0, 20.0, 90, [], m),
                              Macro("dig", cache=MacroDef("dig", 100.0, 100.0))]
        return p

    def test_macros_yaml(self):
        from chip_planner.formats.librelane import macros_yaml
        from chip_planner.model.floorplan import core_area
        p = self.project()
        lay = p.layout()
        x0, y0, _, _ = core_area(lay)
        text = macros_yaml(p, lay, out_dir=ROOT / "flow")
        self.assertIn("MACROS:\n  adc_sar_top:\n", text)
        self.assertIn("    gds: [dir::../tests/data/macros/adc_sar/final/gds/adc_sar_top.gds]\n", text)
        self.assertIn("    lef: [dir::../tests/data/macros/adc_sar/final/lef/adc_sar_top.lef]\n", text)
        self.assertIn(f"      i_chip_core.adc0:\n        location: [{x0 + 40:g}, {lay.die_height - (y0 + 20 + 420):g}]\n"
                      "        orientation: E\n", text)
        self.assertIn("# placeholder dig (no LEF) not exported", text)

    def test_macros_yaml_keeps_three_decimals(self):
        from chip_planner.formats.librelane import _num
        self.assertEqual((_num(1790.565), _num(160.0), _num(0.1 + 0.2)), ("1790.565", "160", "0.3"))

    def test_macros_yaml_only_with_macros(self):
        self.assertNotIn("macros.yaml", librelane_files(compac_like()))
        files = librelane_files(self.project())
        self.assertIn("macros.yaml", files)
        self.assertIn("//   adc_sar_top i_chip_core.adc0", files["chip_core_template.sv"])
        self.assertNotIn("Macros", librelane_files(compac_like())["chip_core_template.sv"])


if __name__ == "__main__":
    unittest.main()
