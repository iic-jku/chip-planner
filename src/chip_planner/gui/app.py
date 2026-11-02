import sys

from .. import APP_NAME
from .main_window import MainWindow, apply_theme, load_view_settings
from .qt import QApplication, QLocale


def run(path=None):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    # English UI throughout, including number formatting (decimal point)
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    theme = load_view_settings().get("theme", "system")  # View → Theme
    win = MainWindow(apply_theme(theme), path, theme)
    win.show()
    return app.exec()
