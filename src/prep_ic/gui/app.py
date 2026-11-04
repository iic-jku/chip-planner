import sys
from pathlib import Path

from .. import APP_NAME
from .main_window import MainWindow, apply_theme, load_view_settings
from .qt import QApplication, QIcon, QLocale

LOGO = Path(__file__).parent / "assets" / "prep_ic_logo.svg"


def _set_windows_app_id():
    # without its own AppUserModelID the taskbar shows the icon of python.exe
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JKU.IICQC.prep-ic")
        except (AttributeError, OSError):
            pass


def run(path=None):
    _set_windows_app_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(LOGO)))
    # English UI throughout, including number formatting (decimal point)
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    theme = load_view_settings().get("theme", "system")  # View → Theme
    win = MainWindow(apply_theme(theme), path, theme)
    win.show()
    return app.exec()
