# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Help → About: logo, version, authors, license and links."""

from pathlib import Path

from .. import APP_NAME, __version__
from .qt import QDialog, QDialogButtonBox, QHBoxLayout, QIcon, QLabel, Qt, QVBoxLayout

LOGO = Path(__file__).parent / "assets" / "prep_ic_logo.svg"
REPO_URL = "https://github.com/iic-jku/prep-ic"
PYPI_URL = "https://pypi.org/project/prep-ic/"


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.logo = QLabel()
        self.logo.setPixmap(QIcon(str(LOGO)).pixmap(96, 96))
        self.logo.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.text = QLabel(
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>Pinout, Ring and Early floorplan Planner for ICs</p>"
            "<p>© 2026 Maximilian Golser and Simon Dorrer</p>"
            "<p>Institute for Integrated Circuits and Quantum Computing (IICQC)<br>"
            "Johannes Kepler University (JKU), Linz, Austria</p>"
            "<p>Licensed under the Apache License 2.0.</p>"
            f'<p><a href="{REPO_URL}">GitHub</a> · <a href="{PYPI_URL}">PyPI</a></p>')
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.text.setOpenExternalLinks(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self.logo)
        row.addWidget(self.text, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(buttons)
