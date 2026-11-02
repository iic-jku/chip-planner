"""Floorplan: LEF reading, macro placement and padframe generation."""

import unittest

from tests import ROOT

from chip_planner.formats.lef import parse_lef, pick_macro, read_lef

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


if __name__ == "__main__":
    unittest.main()
