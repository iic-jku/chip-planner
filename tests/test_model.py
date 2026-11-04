import dataclasses
import json
import unittest

from tests import ROOT

import prep_ic as prep
from prep_ic.model import parse_line
from prep_ic.model.parse import format_entry

BASELINE = json.loads((ROOT / "tests" / "data" / "layout_baseline.json").read_text(encoding="utf-8"))
PIN_FIELDS = ("no", "name", "type", "side", "line", "w", "h", "pitch", "a", "b", "cx", "cy", "grouped")


def project_for(inp):
    if inp == "example":
        return prep.Project.example()
    if isinstance(inp, str):
        return prep.load(ROOT / inp)
    return prep.Project.from_dict(inp)


class LayoutBaseline(unittest.TestCase):
    """Geometry must match the output of the original single-file version."""

    def test_cases(self):
        for name, exp in BASELINE.items():
            with self.subTest(name):
                lay = project_for(exp["input"]).layout("L:2")
                self.assertEqual(lay.die_width, exp["W"])
                self.assertEqual(lay.die_height, exp["Hh"])
                self.assertEqual(lay.margin, exp["margin"])
                pins = [{f: getattr(p, f) for f in PIN_FIELDS} for p in lay.pins]
                self.assertEqual(pins, exp["pins"])
                self.assertEqual(json.loads(json.dumps(lay.prims)), exp["prims"])
                self.assertEqual(lay.counts, exp["counts"])
                self.assertEqual(lay.gutter, exp["gutter"])
                self.assertEqual(lay.pins_per_side, exp["per_side"])
                self.assertEqual(lay.side_length, exp["S"])
                self.assertEqual(len(lay.warnings), exp["n_warnings"])

    def test_warnings_text(self):
        lay = project_for(BASELINE["warn"]["input"]).layout()
        self.assertEqual(lay.warnings, ["Signal assigned more than once: SIG",
                                        "Pad wider than pitch (overlaps) at pin 4",
                                        "Pad deeper than IO cell at pin 5"])

    def test_pin_list_coordinates(self):
        lay = prep.Project.example().layout()
        for p in lay.pins:
            self.assertEqual((p.x, p.y), (p.cx, lay.die_height - p.cy))


class Parsing(unittest.TestCase):
    def test_options(self):
        e = parse_line("RFOUT [gsg] {70x70} @125")
        self.assertEqual((e["name"], e["group"], e["size"], e["pitch"]), ("RFOUT", "gsg", (70.0, 70.0), 125.0))

    def test_bus_name_kept(self):
        self.assertEqual(parse_line("D[3]")["name"], "D[3]")

    def test_spacer(self):
        self.assertIsNone(parse_line("   "))


class ProjectApi(unittest.TestCase):
    def test_build_from_script(self):
        p = prep.Project()
        p.sides["L"] += ["VDDA", "", "RFIN [gsg]"]
        p.settings.std.pitch = 90
        lay = p.layout()
        self.assertEqual([x.name for x in lay.pins], ["VDDA", "GND", "RFIN", "GND"])
        self.assertEqual(lay.counts["gnd"], 2)
        self.assertEqual(lay.side_length["L"], 90 + 90 + 3 * 100)

    def test_dict_round_trip(self):
        data = json.loads((ROOT / "examples" / "padring.json").read_text(encoding="utf-8"))
        p = prep.Project.from_dict(data)
        self.assertEqual(prep.Project.from_dict(p.to_dict()), p)
        # older versions ignored empty lines at the end of a side
        self.assertEqual(p.side_text("T"), data["sides"]["T"].rstrip("\n"))

    def test_trailing_spacers_kept_in_new_files(self):
        p = prep.Project()
        p.sides["L"] = ["A", "", ""]
        d = p.to_dict()
        self.assertEqual(d["format"], 2)
        self.assertEqual(prep.Project.from_dict(d).sides["L"], ["A", "", ""])
        del d["format"]  # older files: empty lines at the end were ignored
        self.assertEqual(prep.Project.from_dict(d).sides["L"], ["A"])

    def test_trailing_spacer_counts_in_api(self):
        p = prep.Project()
        p.sides["L"] = ["A"]
        n = p.layout().side_length["L"]
        p.sides["L"].append("")
        self.assertEqual(p.layout().side_length["L"], n + p.settings.std.pitch)

    def test_physical_order(self):
        p = prep.Project.example()  # ccw: top and right are numbered against the geometry
        lay = p.layout()
        for side in "TRBL":
            nos = p.to_physical(side, [x.no for x in lay.pins_on(side)])
            key = (lambda n: lay.pins[n - 1].cx) if side in "TB" else (lambda n: lay.pins[n - 1].cy)
            self.assertEqual(nos, sorted(nos, key=key), side)
        self.assertEqual(p.physical_lines("T"), p.sides["T"][::-1])
        self.assertEqual(p.physical_lines("L"), p.sides["L"])
        self.assertEqual(p.physical_line_index("T", 0), len(p.sides["T"]) - 1)

    def test_set_physical_lines_keeps_position_across_modes(self):
        lines = ["A", "", "B [gsg]", "C"]
        pos = {}
        for mode in ("ccw", "cw"):
            p = prep.Project()
            p.settings.mode = mode
            for side in "TRBL":
                p.set_physical_lines(side, [f"{side}{x}" if x else x for x in lines])
            pos[mode] = sorted((x.name, x.cx, x.cy) for x in p.layout().pins)
        self.assertEqual(pos["ccw"], pos["cw"])

    def test_fixed_die(self):
        p = prep.Project.example()
        auto = p.layout()
        p.settings.fixed_die = True
        p.settings.die_width, p.settings.die_height = 1500, 1200
        lay = p.layout()
        self.assertEqual((lay.die_width, lay.die_height), (1500, 1200))
        self.assertTrue(lay.fixed_die)
        self.assertEqual(lay.side_space["T"], 1500 - 2 * 120)
        self.assertEqual(lay.warnings, [])
        # centered pads keep their spacing, only the ring around them grows
        dx = (1500 - auto.die_width) / 2
        self.assertAlmostEqual(lay.pins[0].cy - auto.pins[0].cy, (1200 - auto.die_height) / 2)
        self.assertAlmostEqual(lay.pins_on("T")[0].cx - auto.pins_on("T")[0].cx, dx)

    def test_fixed_die_too_small(self):
        p = prep.Project.example()
        p.settings.fixed_die = True
        p.settings.die_width, p.settings.die_height = 700, 100
        lay = p.layout()
        self.assertEqual((lay.die_width, lay.die_height), (700, 120 * 2 + 80))
        self.assertTrue(lay.warnings[0].startswith("Fixed die size too small"))
        self.assertIn("Pads do not fit on the left side: 720 µm needed, 80 µm available", lay.warnings)
        self.assertIn("Pads do not fit on the top side: 740 µm needed, 460 µm available", lay.warnings)

    def test_fixed_core_is_minimum(self):
        p = prep.Project(sides={"L": ["A"]})
        p.settings.fixed_core, p.settings.square = True, False
        p.settings.core_width, p.settings.core_height = 1500.0, 1200.0
        lay = p.layout()
        H = lay.ring_depth
        self.assertEqual((lay.die_width, lay.die_height), (1500 + 2 * H, 1200 + 2 * H))
        self.assertTrue(lay.core_limited)
        self.assertFalse(lay.fixed_die)
        p.sides["T"] = ["X"] * 40  # the pads need more than the core: the die grows
        lay = p.layout()
        self.assertGreater(lay.die_width, 1500 + 2 * H)
        self.assertEqual(lay.die_height, 1200 + 2 * H)
        self.assertFalse(any("do not fit" in w for w in lay.warnings))

    def test_fixed_core_square(self):
        p = prep.Project(sides={"L": ["A"]})
        p.settings.fixed_core = True
        lay = p.layout()
        self.assertEqual(lay.die_width, lay.die_height)
        self.assertEqual(lay.die_width, 1500 + 2 * lay.ring_depth)

    def test_fixed_core_with_pdk_adds_core_margin(self):
        p = prep.Project(sides={"L": ["A [in]"]})
        p.settings.pdk, p.settings.fixed_core, p.settings.square = "ihp-sg13g2", True, False
        p.settings.core_width = 1501.0
        lay = p.layout()
        pdk = prep.get_pdk("ihp-sg13g2")
        m = lay.ring_depth + lay.core_margin
        self.assertEqual(lay.core_margin, pdk.core_margin)
        self.assertGreaterEqual(lay.die_width, 1501 + 2 * m)
        self.assertGreaterEqual(lay.die_height, 1200 + 2 * m)
        self.assertEqual(lay.die_width % pdk.site, 0)
        self.assertLess(lay.die_width, 1501 + 2 * m + pdk.site)

    def test_fixed_die_wins_over_fixed_core(self):
        p = prep.Project(sides={"L": ["A"]})
        p.settings.fixed_die = p.settings.fixed_core = True
        p.settings.die_width, p.settings.die_height = 900, 800
        lay = p.layout()
        self.assertEqual((lay.die_width, lay.die_height), (900, 800))
        self.assertFalse(lay.core_limited)

    def test_new_settings_round_trip_and_old_files(self):
        p = prep.Project.example()
        p.settings.fixed_core, p.settings.grid = True, 5.0
        p.settings.core_width, p.settings.core_height = 800.0, 600.0
        d = p.to_dict()
        self.assertEqual((d["fixed_core"], d["core_w"], d["core_h"], d["grid"]), (True, 800.0, 600.0, 5.0))
        self.assertEqual(prep.Project.from_dict(d), p)
        old = prep.Project.from_dict({"sides": {}}).settings
        self.assertEqual((old.fixed_core, old.core_width, old.core_height, old.grid), (False, 1500.0, 1200.0, 10.0))
        bad = prep.Project.from_dict({"sides": {}, "core_w": "x", "grid": -1}).settings.sanitized()
        self.assertEqual((bad.core_width, bad.grid), (1500.0, 10.0))

    def test_lock_tag(self):
        e = parse_line("VDDIO [lock]")
        self.assertEqual((e["name"], e["lock"]), ("VDDIO", True))
        self.assertFalse(parse_line("VDDIO")["lock"])
        e = parse_line("D[3] [lock] [out]")
        self.assertEqual((e["name"], e["function"], e["lock"]), ("D[3]", "out", True))
        self.assertEqual(format_entry(e), "D[3] [out] [lock]")

    def test_check_settings_round_trip(self):
        p = prep.Project()
        st = p.settings
        self.assertEqual((st.halo, st.spacing, st.max_flyline, st.max_supply_dist), (20.0, 100.0, 900.0, 1000.0))
        st.halo, st.spacing, st.max_flyline, st.max_supply_dist = 0.0, 50.0, 700.0, 1200.0
        d = p.to_dict()
        self.assertEqual((d["halo"], d["spacing"], d["max_flyline"], d["max_supply_dist"]), (0.0, 50.0, 700.0, 1200.0))
        self.assertEqual(prep.Project.from_dict(d), p)
        self.assertEqual(prep.Project.from_dict({"sides": {}, "halo": -3}).settings.sanitized().halo, 20.0)

    def test_fixed_die_round_trip(self):
        p = prep.Project.example()
        p.settings.fixed_die = True
        p.settings.die_width = 3000
        d = p.to_dict()
        self.assertEqual((d["fixed_die"], d["die_w"], d["die_h"]), (True, 3000, 2000.0))
        self.assertEqual(prep.Project.from_dict(d), p)
        self.assertFalse(prep.Project.from_dict({"sides": {}}).settings.fixed_die)

    def test_legacy_flat_pitch(self):
        p = prep.Project.from_dict({"pitch": 100, "sides": {"T": "A"}})
        self.assertEqual(dataclasses.astuple(p.settings.std), (100.0, 75.0, 75.0))
        self.assertEqual(p.sides["R"], [])

    def test_invalid_values_fall_back(self):
        p = prep.Project.from_dict({"mode": "zigzag", "cellh": "abc", "std": {"pitch": -5}, "sides": {}})
        self.assertEqual((p.settings.mode, p.settings.cell_height, p.settings.std.pitch), ("ccw", 120.0, 80.0))
        p.settings.std.w = 0
        self.assertEqual(p.layout().pins, [])


if __name__ == "__main__":
    unittest.main()
