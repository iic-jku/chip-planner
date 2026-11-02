"""Chip view model: analysis and edits of pads and macros together."""

import unittest

from tests import ROOT

import chip_planner as cp
from chip_planner.formats.lef import read_lef
from chip_planner.model.chip import analyse, diff_partner, drop_index
from chip_planner.model.floorplan import Macro, MacroDef

MACRO_DIR = ROOT / "tests" / "data" / "macros" / "adc_sar"
FIXTURE = MACRO_DIR / "final" / "lef" / "adc_sar_top.lef"


def adc(name="a0", x=400.0, y=0.0, rot=0, io=("VIN_P", "VIN_N"), cls="normal"):
    (m,) = read_lef(FIXTURE)
    return Macro(name, m.name, str(MACRO_DIR), x, y, rot, list(io), m, cls)


def box(name, x, y, w=100.0, h=100.0, cls="normal"):
    return Macro(name, cache=MacroDef(name, w, h), x=x, y=y, cls=cls)


def chip(sides=None, macros=()):
    """No PDK, fixed core 1500 × 1200: die 1740 × 1440, core area from (120, 120)."""
    p = cp.Project(sides={s: list(v) for s, v in (sides or {}).items()})
    p.settings.fixed_core, p.settings.square = True, False
    p.floorplan.macros = list(macros)
    return p


def set_lines(p, side, lines):
    p.set_physical_lines(side, list(lines))
    return p


class AnalyseTests(unittest.TestCase):
    def test_flylines(self):
        p = set_lines(chip(macros=[adc()]), "L", ["VIN_P", "VIN_N"])
        lay = p.layout()
        c = analyse(p, lay)
        fl = {f.pin: f for f in c.flylines}
        self.assertEqual(set(fl), {"VIN_P", "VIN_N"})
        vin_p = next(q for q in lay.pins if q.name == "VIN_P")
        self.assertEqual(fl["VIN_P"].p, (521.0, 200.0))
        self.assertEqual(fl["VIN_P"].q, (120.0, 120.0 + (vin_p.a + vin_p.b) / 2))
        self.assertAlmostEqual(fl["VIN_P"].length, ((521 - 120) ** 2 + (fl["VIN_P"].q[1] - 200) ** 2) ** 0.5)
        self.assertEqual((fl["VIN_P"].side, fl["VIN_P"].pad), ("L", "VIN_P"))
        self.assertEqual(c.missing, [])

    def test_crossings(self):
        p = set_lines(chip(macros=[adc()]), "L", ["VIN_N", "VIN_P"])
        c = analyse(p)
        self.assertEqual(c.crossings, 1)
        self.assertTrue(all(f.crossing for f in c.flylines))
        set_lines(p, "L", ["VIN_P", "VIN_N"])
        self.assertEqual(analyse(p).crossings, 0)

    def test_missing_pin(self):
        p = set_lines(chip(macros=[adc(x=0.0)]), "L", ["VIN_P"])
        c = analyse(p)
        (m,) = c.missing
        self.assertEqual((m.instance, m.pin, m.name, m.side, m.function), ("a0", "VIN_N", "VIN_N", "L", "analog"))
        self.assertEqual(m.q, (120.0, 320.0))
        self.assertIn("1 checked pins without pad: VIN_N", c.warnings)

    def test_diff_partner(self):
        self.assertEqual(diff_partner("VIN_P"), "VIN_N")
        self.assertEqual(diff_partner("INN"), "INP")
        self.assertIsNone(diff_partner("CLK"))

    def test_diff_pair_warning(self):
        p = set_lines(chip(), "L", ["VIN_N", "X", "VIN_P"])
        self.assertIn("Differential pair VIN_P/VIN_N not adjacent", analyse(p).warnings)
        set_lines(p, "L", ["VIN_N", "VIN_P", "X"])
        self.assertFalse(any("Differential" in w for w in analyse(p).warnings))

    def test_sensitive_next_to_noisy(self):
        p = set_lines(chip(), "L", ["VREF", "TEST_CLK"])
        self.assertIn("Sensitive pad next to noisy pad: VREF – TEST_CLK", analyse(p).warnings)
        # a connected pad takes the class of its macro: RFIN [in] would be digital by type
        p = set_lines(chip(macros=[adc(io=["VIN_P"], cls="sensitive")]), "L", ["VIN_P [in]", "TEST_CLK"])
        self.assertIn("Sensitive pad next to noisy pad: VIN_P – TEST_CLK", analyse(p).warnings)
        p.floorplan.macros[0].cls = "normal"  # falls through to the type: digital next to clock
        self.assertFalse(any("Sensitive pad" in w for w in analyse(p).warnings))

    def test_spacer_breaks_adjacency(self):
        p = set_lines(chip(), "L", ["VREF", "", "TEST_CLK"])
        self.assertFalse(any("Sensitive pad" in w for w in analyse(p).warnings))
        set_lines(p, "L", ["VREF", "RFIN [gsg]", "TEST_CLK"])  # a shielded group breaks it too
        self.assertFalse(any("VREF – " in w for w in analyse(p).warnings))

    def test_halo_and_spacing(self):
        p = chip(macros=[box("a", 0.0, 0.0, cls="sensitive"), box("b", 130.0, 0.0, cls="noisy")])
        w = analyse(p).warnings
        self.assertIn("Halos of a and b overlap", w)
        self.assertIn("a (sensitive) closer than 100 µm to b (noisy)", w)
        p.floorplan.macros[1].x = 300.0
        w = analyse(p).warnings
        self.assertFalse(any("Halos" in x or "closer" in x for x in w))
        p.floorplan.macros[0].halo = 200.0  # per-macro halo overrides the default
        self.assertIn("Halos of a and b overlap", analyse(p).warnings)

    def test_flyline_too_long(self):
        p = set_lines(chip(macros=[adc(cls="sensitive")]), "L", ["VIN_P", "VIN_N"])
        p.settings.max_flyline = 100.0
        c = analyse(p)
        n = round(next(f.length for f in c.flylines if f.pin == "VIN_P"))
        self.assertIn(f"Flyline VIN_P {n} µm (limit 100 µm)", c.warnings)
        self.assertIn(c.longest.pin, ("VIN_P", "VIN_N"))
        p.floorplan.macros[0].cls = "normal"  # VIN_P is digital by type: no length limit
        self.assertFalse(any(w.startswith("Flyline") for w in analyse(p).warnings))

    def test_supply_by_function_and_domain(self):
        p = chip(sides={"L": ["VDDIO", "VSSIO"]}, macros=[adc(x=0.0, io=())])
        w = analyse(p).warnings
        self.assertIn("a0: no VDD pad of domain ring within 1000 µm", w)  # IO supplies do not count
        self.assertIn("a0: no VSS pad of domain ring within 1000 µm", w)
        set_lines(p, "L", ["VDDIO", "VDD", "VSS", "VSSIO"])
        self.assertFalse(any("pad of domain" in x for x in analyse(p).warnings))

    def test_supply_domains(self):
        p = chip(sides={"L": ["=== ANA", "VDD", "VSS"], "R": ["=== DIG", "VDD", "VSS"]}, macros=[adc(x=0.0, io=())])
        lay = p.layout()
        left = next(q for q in lay.pins if q.side == "L" and q.name == "VDD").domain
        right = next(q for q in lay.pins if q.side == "R" and q.name == "VDD").domain
        self.assertNotEqual(left, right)
        p.floorplan.macros[0].domain = left
        self.assertFalse(any("pad of domain" in x for x in analyse(p).warnings))
        p.floorplan.macros[0].domain = right  # its supplies are far away on the right
        self.assertIn(f"a0: no VDD pad of domain {right} within 1000 µm", analyse(p).warnings)

    def test_supply_without_splits(self):
        p = chip(sides={"T": ["VDD", "VSS"]}, macros=[box("d", 0.0, 0.0)])
        self.assertFalse(any("pad of domain" in x for x in analyse(p).warnings))

    def test_supply_suggestions(self):
        p = chip(sides={"R": ["VDDIO"]}, macros=[adc(x=0.0, io=())])
        s = analyse(p).supplies
        self.assertEqual([(x.name, x.function) for x in s], [("VDD", "vdd"), ("VSS", "vss")])  # LEF: VDD only
        p = chip(sides={"L": ["=== ANA", "X"], "R": ["=== DIG", "Y"]}, macros=[box("d", 0.0, 0.0)])
        dom = next(q for q in p.layout().pins if q.name == "X").domain
        p.floorplan.macros[0].domain = dom
        s = analyse(p).supplies
        self.assertEqual([x.name for x in s], [f"VDD_{dom}", f"VSS_{dom}"])
        self.assertEqual({x.side for x in s}, {"L"})  # next to the domain's pad X

    def test_no_macros(self):
        c = analyse(cp.Project.example())
        self.assertEqual((c.flylines, c.missing, c.crossings, c.longest, c.supplies), ([], [], 0, None, []))

    def test_drop_index(self):
        p = set_lines(chip(), "L", ["A", "", "B"])
        lay = p.layout()
        a = next(q for q in lay.pins if q.name == "A")
        b = next(q for q in lay.pins if q.name == "B")
        self.assertEqual(drop_index(lay, p, "L", 0.0), 0)
        self.assertEqual(drop_index(lay, p, "L", 120 + (a.a + a.b) / 2 + 1), 1)
        self.assertEqual(drop_index(lay, p, "L", 120 + (b.a + b.b) / 2 + 1), 3)
        self.assertEqual(drop_index(lay, p, "T", 500.0), 0)


if __name__ == "__main__":
    unittest.main()
