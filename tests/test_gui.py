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
        self.assertEqual(tabs, ["Padframe", "Pin List", "Settings", "LibreLane"])
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
