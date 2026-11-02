"""GUI smoke test, runs offscreen. Skipped without Qt."""

import os
import tempfile
import unittest
from pathlib import Path

from tests import ROOT

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from chip_planner.gui import main_window
    from chip_planner.gui.qt import QApplication
    from chip_planner.style import PALETTES
except ImportError:
    main_window = None


@unittest.skipIf(main_window is None, "Qt not installed")
class GuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        main_window.LAST_STATE = Path(self.tmp.name) / "last.json"
        self.win = main_window.MainWindow(PALETTES["light"], ROOT / "examples" / "padring.json")

    def tearDown(self):
        self.win.setWindowModified(False)
        self.win.close()
        self.tmp.cleanup()

    def test_loads_and_renders(self):
        import chip_planner as cp
        expected = cp.load(ROOT / "examples" / "padring.json")
        self.assertEqual(self.win.get_project(), expected)
        self.assertEqual(self.win.table.rowCount(), len(expected.layout().pins))
        self.assertEqual(self.win.editors["T"].text(), "\n".join(expected.physical_lines("T")))

    def test_editors_show_physical_order(self):
        # ccw: left 1–14 top → bottom, top numbered right → left, so its editor starts at 40
        self.assertEqual(self.win.editors["L"].edit.labels[:3], ["1", "2", "3"])
        self.assertEqual(self.win.editors["T"].edit.labels[:3], ["40", "39", "38"])
        self.assertEqual(self.win.editors["R"].edit.labels[0], "24")
        self.assertEqual(self.win.editors["B"].edit.labels[0], "15")
        import chip_planner as cp
        self.win.set_project(cp.Project.example())
        self.assertEqual(self.win.editors["T"].edit.labels, ["31", "30", "29–25", "24"])

    def test_mode_switch_keeps_editor_text(self):
        before = {s: e.text() for s, e in self.win.editors.items()}
        self.win.cb_mode.setCurrentIndex(self.win.cb_mode.findData("cw"))
        self.win.render()
        self.assertEqual({s: e.text() for s, e in self.win.editors.items()}, before)
        self.assertEqual(self.win.editors["T"].edit.labels[0], "1")

    def test_click_selects_editor_line(self):
        self.win.pad_clicked("T:0")  # first line in numbering order = rightmost pad = last editor line
        ed = self.win.editors["T"].edit
        self.assertEqual(ed.textCursor().blockNumber(), ed.blockCount() - 1)
        self.assertEqual(ed.textCursor().selectedText(), "VSSA_MIX")

    def test_fixed_die_setting(self):
        w = self.win
        self.assertFalse(w.sp_die_w.isEnabled())
        w.cb_die.setCurrentIndex(w.cb_die.findData("die"))  # starts from the current pad-limited size
        self.assertEqual((w.sp_die_w.value(), w.sp_die_h.value()), (1780.0, 1700.0))
        self.assertTrue(w.sp_die_w.isEnabled() and not w.chk_square.isEnabled())
        w.sp_die_w.setValue(2500)
        w.render()
        self.assertEqual(w.layout_data.die_width, 2500)
        self.assertEqual(w.stat_cap["die"].text(), "DIE (FIXED)")
        self.assertTrue(w.get_project().settings.fixed_die)
        w.cb_die.setCurrentIndex(w.cb_die.findData("pads"))
        w.render()
        self.assertEqual(w.layout_data.die_width, 1780)

    def test_fixed_core_setting(self):
        w = self.win
        self.assertFalse(w.sp_core_w.isEnabled())
        w.cb_die.setCurrentIndex(w.cb_die.findData("core"))
        self.assertTrue(w.sp_core_w.isEnabled() and w.chk_square.isEnabled() and not w.sp_die_w.isEnabled())
        w.chk_square.setChecked(False)
        w.sp_core_w.setValue(3000)
        w.sp_core_h.setValue(2500)
        w.sp_grid.setValue(5)
        w.render()
        st = w.get_project().settings
        self.assertEqual((st.fixed_core, st.fixed_die, st.core_width, st.core_height, st.grid),
                         (True, False, 3000.0, 2500.0, 5.0))
        self.assertEqual(w.layout_data.die_width, 3000 + 2 * w.layout_data.ring_depth)
        self.assertEqual(w.stat_cap["die"].text(), "DIE (MIN. CORE)")
        w.set_project(w.get_project())
        self.assertEqual(w.cb_die.currentData(), "core")

    def test_pdk_and_librelane_tab(self):
        w = self.win
        w.cb_pdk.setCurrentIndex(w.cb_pdk.findData("ihp-sg13g2"))
        self.assertFalse(w.sp[("std", "w")].isEnabled() or w.sp_cellh.isEnabled())
        self.assertGreaterEqual(w.sp[("std", "pitch")].value(), 80)
        w.render()
        self.assertEqual(w.layout_data.ring_depth, 320)
        self.assertTrue(all(p.cell for p in w.layout_data.pins))
        w.tabs.setCurrentWidget(w.ll_page)
        self.assertEqual(list(w.ll_texts), ["padring_config.yaml", "pad_cfg.tcl", "chip_top.sv",
                                            "chip_core_template.sv"])
        w.cb_pkg.setCurrentIndex(w.cb_pkg.findData("OP_QFN64_9x9mm_A4_FIT"))
        w.render()
        self.assertIn("PACKAGE_NAME: OP_QFN64_9x9mm_A4_FIT", w.ll_texts["bondplan_pinout.yaml"].toPlainText())
        self.assertEqual(w.get_project().settings.pdk, "ihp-sg13g2")

    def test_function_combo_rewrites_line(self):
        w = self.win
        w.cb_pdk.setCurrentIndex(w.cb_pdk.findData("ihp-sg13g2"))
        w.render()
        from chip_planner.gui.main_window import COL
        row = next(r for r, p in enumerate(w.layout_data.pins) if p.name == "RST_N")
        cb = w.table.cellWidget(row, COL["Function"])
        cb.setCurrentIndex(cb.findData("inout"))
        self.assertIn("RST_N [io]", w.editors["L"].text())
        w.render()
        row = next(r for r, p in enumerate(w.layout_data.pins) if p.name == "RST_N")
        drive = w.table.cellWidget(row, COL["Drive"])
        drive.setCurrentIndex(drive.findData(16))
        self.assertIn("RST_N [io] [16mA]", w.editors["L"].text())
        w.render()
        self.assertEqual(next(p.cell for p in w.layout_data.pins if p.name == "RST_N"), "sg13g2_IOPadInOut16mA")

    def test_layout_of_window(self):
        tabs = [self.win.tabs.tabText(i) for i in range(self.win.tabs.count())]
        self.assertEqual(tabs, ["Floorplan", "Padframe", "Pin List", "Settings", "LibreLane"])
        for mode in ("ccw", "cw"):
            self.win.cb_mode.setCurrentIndex(self.win.cb_mode.findData(mode))
            self.win.render()
            order = [self.win.ed_box.itemAt(i).widget().side for i in range(self.win.ed_box.count())]
            self.assertEqual(order, ["T", "R", "B", "L"])

    def test_select_pad(self):
        self.win.pad_clicked("L:2")
        self.assertEqual(self.win.table.currentRow(), 2)

    def test_mode_switch_keeps_physical_order(self):
        before = [(p.name, p.cx, p.cy) for p in self.win.get_project().layout().pins]
        self.win.cb_mode.setCurrentIndex(self.win.cb_mode.findData("cw"))
        after = [(p.name, p.cx, p.cy) for p in self.win.get_project().layout().pins]
        self.assertEqual(sorted(before), sorted(after))

    def test_png(self):
        path = Path(self.tmp.name) / "ring.png"
        self.assertTrue(self.win.render_png(path, size=400))
        self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()

MACRO_DIR = ROOT / "tests" / "data" / "macros" / "adc_sar"


@unittest.skipIf(main_window is None, "Qt not installed")
class FloorplanGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import chip_planner as cp
        self.tmp = tempfile.TemporaryDirectory()
        main_window.LAST_STATE = Path(self.tmp.name) / "last.json"
        self.win = main_window.MainWindow(PALETTES["light"])
        self.win.set_project(cp.Project())

    def tearDown(self):
        self.win.setWindowModified(False)
        self.win.close()
        self.tmp.cleanup()

    def test_starts_on_padframe_and_switches_left_panel(self):
        w = self.win
        self.assertEqual(w.tabs.tabText(w.tabs.currentIndex()), "Padframe")
        self.assertIs(w.left_stack.currentWidget(), w.editor_page)
        w.tabs.setCurrentWidget(w.fp_page)
        self.assertIs(w.left_stack.currentWidget(), w.macro_panel)
        w.tabs.setCurrentWidget(w.ll_page)
        self.assertIs(w.left_stack.currentWidget(), w.editor_page)

    def test_add_macro_mark_pin_and_generate(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.add_macro_dir(str(MACRO_DIR))
        self.assertEqual([m.name for m in w.floorplan.macros], ["adc_sar0", "adc_sar1"])
        w.render()
        self.assertEqual(len(w.macro_items), 2)
        self.assertEqual(len(w.macro_panel.boxes), 2)
        w.floorplan.macros[1].x = 800.0
        w.floorplan.macros[0].io.append("VIN_P")
        w.render()
        self.assertEqual(w.fp_stat["io"].text(), "0/0/0/1")
        self.assertEqual(w.generate_padframe(confirm=False), ["VIN_P"])
        self.assertIn("VIN_P [analog]", w.editors["L"].text().split("\n"))
        self.assertTrue(w.get_project().settings.fixed_core)
        self.assertEqual(w.cb_die.currentData(), "core")
        self.assertEqual(w.tabs.tabText(w.tabs.currentIndex()), "Padframe")

    def test_drag_snaps_to_grid_and_stays_in_core(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.sp_grid.setValue(10)
        w.render()
        item = w.macro_items[0]
        x0, y0 = item.ctx["origin"]
        item.setPos(x0 + 123.4, y0 + 56.7)
        m = w.floorplan.macros[0]
        self.assertEqual((m.x, m.y), (120.0, 60.0))
        item.setPos(x0 + 5000, y0 - 50)
        self.assertEqual((m.x, m.y), (1500.0 - 420.0, 0.0))

    def test_rotate_duplicate_remove(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        m = w.floorplan.macros[0]
        w.rotate_macro(m)
        self.assertEqual((m.rot, m.size()), (90, (310.0, 420.0)))
        w.duplicate_macro(m)
        self.assertEqual([x.name for x in w.floorplan.macros], ["adc_sar0", "adc_sar1"])
        self.assertEqual(w.floorplan.macros[1].rot, 90)
        w.remove_macro(m)
        self.assertEqual([x.name for x in w.floorplan.macros], ["adc_sar1"])

    def test_floorplan_round_trip_through_project(self):
        w = self.win
        w.add_macro_dir(str(MACRO_DIR))
        w.floorplan.macros[0].io.append("CLK")
        p = w.get_project()
        self.assertEqual(p.floorplan.macros[0].io, ["CLK"])
        p.floorplan.macros[0].io.append("VIN_N")  # the window keeps its own copy
        self.assertEqual(w.floorplan.macros[0].io, ["CLK"])
        w.set_project(p)
        self.assertEqual(w.get_project().floorplan, p.floorplan)

    def test_placeholder(self):
        w = self.win
        w.add_placeholder("digital", 600.0, 400.0)
        self.assertTrue(w.floorplan.macros[0].placeholder)
        self.assertEqual(w.floorplan.macros[0].size(), (600.0, 400.0))
