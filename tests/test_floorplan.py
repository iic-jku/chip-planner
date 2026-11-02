"""Floorplan: LEF reading, macro placement and padframe generation."""

import unittest

from tests import ROOT

import chip_planner as cp
from chip_planner.formats.lef import parse_lef, pick_macro, read_lef
from chip_planner.model.floorplan import (Floorplan, Macro, MacroDef, MacroPin, core_origin, floorplan_warnings,
                                          nearest_side, utilization)

MACRO_DIR = ROOT / "tests" / "data" / "macros" / "adc_sar"
FIXTURE = MACRO_DIR / "final" / "lef" / "adc_sar_top.lef"


class LefTests(unittest.TestCase):
    def test_size_and_pins(self):
        (m,) = read_lef(FIXTURE)
        self.assertEqual((m.name, m.w, m.h), ("adc_sar_top", 420.0, 310.0))
        pins = {p.name: p for p in m.pins}
        self.assertEqual((pins["VIN_P"].x, pins["VIN_P"].y), (1.0, 80.0))  # y flipped: 310 - 230
        self.assertEqual(pins["VIN_P"].use, "ANALOG")
        self.assertEqual(pins["VIN_P"].direction, "INPUT")
        self.assertEqual(pins["CLK"].use, "CLOCK")
        self.assertEqual(pins["EN"].direction, "OUTPUT TRISTATE")
        self.assertEqual(pins["EN"].use, "SIGNAL")
        self.assertEqual((pins["EN"].x, pins["EN"].y), (105.0, 309.0))
        self.assertEqual(pins["VDD"].use, "POWER")
        self.assertEqual((pins["NOGEO"].x, pins["NOGEO"].y), (210.0, 155.0))  # no shape: centre
        self.assertIn("DOUT[0]", pins)
        self.assertEqual(len(m.pins), 7)

    def test_origin_shifts_shapes(self):
        (m,) = parse_lef("MACRO o\n ORIGIN 10 20 ;\n SIZE 100 BY 50 ;\n PIN A\n  PORT\n   LAYER M1 ;\n"
                         "    RECT -10 -20 -8 -10 ;\n  END\n END A\nEND o\n")
        self.assertEqual((m.pins[0].x, m.pins[0].y), (1.0, 45.0))

    def test_picks_top_macro(self):
        text = "MACRO helper\n SIZE 1 BY 1 ;\nEND helper\n" + FIXTURE.read_text()
        self.assertEqual(pick_macro(parse_lef(text), "adc_sar").name, "adc_sar_top")
        self.assertEqual(pick_macro(parse_lef("MACRO x\n SIZE 1 BY 2 ;\nEND x\n"), "adc_sar").name, "x")

    def test_no_macro_raises(self):
        with self.assertRaises(ValueError):
            parse_lef("VERSION 5.8 ;\n")


def adc(name="adc_sar0", x=0.0, y=0.0, rot=0, io=()):
    (m,) = read_lef(FIXTURE)
    return Macro(name, m.name, str(MACRO_DIR), x, y, rot, list(io), m)


class FloorplanTests(unittest.TestCase):
    def test_rotation(self):
        m = adc(rot=90)
        self.assertEqual(m.size(), (310.0, 420.0))
        vin_p = next(p for p in m.cache.pins if p.name == "VIN_P")
        self.assertEqual(m.pin_xy(vin_p), (230.0, 1.0))
        m.rot = 180
        self.assertEqual(m.size(), (420.0, 310.0))
        self.assertEqual(m.pin_xy(vin_p), (419.0, 230.0))
        m.rot, m.x, m.y = 270, 100.0, 50.0
        self.assertEqual(m.pin_xy(vin_p), (100.0 + 80.0, 50.0 + 419.0))

    def test_io_pins_only_marked_signals(self):
        m = adc(io=["VIN_P", "VDD", "GONE"])
        self.assertEqual([p.name for p in m.io_pins()], ["VIN_P"])

    def test_placeholder(self):
        m = Macro("digital", cache=MacroDef("digital", 600.0, 400.0))
        self.assertTrue(m.placeholder)
        self.assertEqual(m.size(), (600.0, 400.0))
        self.assertEqual(m.io_pins(), [])

    def test_nearest_side(self):
        self.assertEqual(nearest_side(10, 500, 2000, 1000), "L")
        self.assertEqual(nearest_side(1990, 500, 2000, 1000), "R")
        self.assertEqual(nearest_side(1000, 990, 2000, 1000), "B")
        self.assertEqual(nearest_side(1000, 5, 2000, 1000), "T")
        self.assertEqual(nearest_side(500, 500, 1000, 1000), "T")  # tie: T, R, B, L

    def test_core_origin_centred_in_core_area(self):
        p = cp.Project(sides={"L": ["A"]})
        p.settings.fixed_core, p.settings.square = True, False
        p.settings.core_width, p.settings.core_height = 1000.0, 800.0
        lay = p.layout()
        self.assertEqual(core_origin(lay, p.settings), (lay.ring_depth, lay.ring_depth))
        p.settings.fixed_core = False  # pad-limited, die larger than the core: centred
        p.sides["T"] = ["X"] * 20
        lay = p.layout()
        x0, _ = core_origin(lay, p.settings)
        self.assertAlmostEqual(x0, lay.ring_depth + (lay.die_width - 2 * lay.ring_depth - 1000.0) / 2)

    def test_overlap_and_outside_core_warning(self):
        p = cp.Project()
        p.settings.core_width, p.settings.core_height = 300.0, 300.0
        p.floorplan.macros = [adc("a0"), adc("a1", x=100.0)]
        w = floorplan_warnings(p)
        self.assertIn("Macros a0 and a1 overlap", w)
        self.assertIn("Macro a0 outside the core", w)
        p.settings.core_width, p.settings.core_height = 2000.0, 2000.0
        p.floorplan.macros[1].x = 500.0
        self.assertEqual(floorplan_warnings(p), [])

    def test_utilization(self):
        p = cp.Project()
        p.settings.core_width, p.settings.core_height = 1000.0, 1000.0
        p.floorplan.macros = [adc(), Macro("d", cache=MacroDef("d", 100.0, 100.0))]
        self.assertAlmostEqual(utilization(p), (420 * 310 + 100 * 100) / 1e6)

    def test_instance_names(self):
        fp = Floorplan([adc("adc_sar0")])
        self.assertEqual(fp.instance_name("adc_sar"), "adc_sar1")
        self.assertEqual(Floorplan().instance_name("pll"), "pll0")

    def test_json_round_trip(self):
        p = cp.Project.example()
        p.floorplan.macros = [adc("adc0", 10.0, 20.0, 90, ["VIN_P"]), adc("adc1", 500.0, 20.0),
                              Macro("digital", cache=MacroDef("digital", 600.0, 400.0))]
        d = p.to_dict()
        self.assertEqual(d["floorplan"]["macros"][0]["io"], ["VIN_P"])
        self.assertEqual(cp.Project.from_dict(d), p)
        self.assertNotIn("floorplan", cp.Project.example().to_dict())
        self.assertEqual(cp.Project.from_dict({"sides": {}}).floorplan, Floorplan())
        self.assertEqual(cp.Project.from_dict({"sides": {}, "floorplan": {"macros": [{"bad": 1}, 3]}}).floorplan,
                         Floorplan())


if __name__ == "__main__":
    unittest.main()
