# SPDX-FileCopyrightText: 2026 Maximilian Golser and Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""Qt GUI. Uses only the public model/formats API; nothing outside this package imports Qt."""


def run(path=None):
    """Start the GUI, optionally opening ``path``. Returns the exit code."""
    from .app import run as _run
    return _run(path)
