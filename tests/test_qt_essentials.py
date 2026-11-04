"""Guard the PySide6-Essentials-only dependency, as snp2le does.

An import from PySide6-Addons (QtCharts, QtWebEngine, ...) still runs where the full PySide6 is installed
and only fails on an Essentials-only install such as the IIC-OSIC-TOOLS image. A source scan, no Qt needed.
"""

import ast
import unittest

from tests import ROOT

# modules in the PySide6-Essentials wheel (6.6 to 6.11), the PyQt6 fallback must stay within them too
ESSENTIALS = {
    "QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtConcurrent", "QtDBus", "QtDesigner", "QtHelp", "QtOpenGL",
    "QtOpenGLWidgets", "QtPrintSupport", "QtQml", "QtQuick", "QtQuickControls2", "QtQuickTest", "QtQuickWidgets",
    "QtSql", "QtSvg", "QtSvgWidgets", "QtTest", "QtUiTools", "QtXml",
}
BINDINGS = ("PySide6", "PyQt6")


def qt_modules(path):
    """Every Qt submodule that `path` imports, at any nesting depth."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), str(path))):
        if isinstance(node, ast.ImportFrom) and node.module:
            top, _, sub = node.module.partition(".")
            if top in BINDINGS:
                found.update([sub.split(".")[0]] if sub else (a.name for a in node.names))
        elif isinstance(node, ast.Import):
            for a in node.names:
                top, _, sub = a.name.partition(".")
                if top in BINDINGS and sub:
                    found.add(sub.split(".")[0])
    return found


class QtEssentials(unittest.TestCase):
    def test_no_addons_imports(self):
        offenders = {}
        for py in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
            extra = qt_modules(py) - ESSENTIALS
            if extra:
                offenders[str(py.relative_to(ROOT))] = sorted(extra)
        self.assertEqual(offenders, {})

    def test_dependency_is_essentials(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        deps = text.split("dependencies = [", 1)[1].split("]", 1)[0]
        qt = [d.strip(' "\n') for d in deps.split(",") if "PySide6" in d]
        self.assertTrue(qt, "no PySide6 dependency in pyproject.toml")
        self.assertTrue(all(d.startswith("PySide6-Essentials") for d in qt), qt)


if __name__ == "__main__":
    unittest.main()
