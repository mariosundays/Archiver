# Archiver -- GUI entry point.
# Copyright (C) 2026 Mario Domingos
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.

"""Archiver -- scan a project and see what can be archived."""

import os
import sys

from PySide6 import QtGui, QtWidgets

from app.window import MainWindow

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "app", "resources")


def app_icon():
    """The window and taskbar icon (Lucide "archive", ISC licensed)."""
    path = os.path.join(RESOURCES, "icon.ico")
    return QtGui.QIcon(path) if os.path.isfile(path) else QtGui.QIcon()


def _claim_taskbar_identity():
    """Windows groups taskbar icons by AppUserModelID; without our own we
    inherit python.exe's, and the taskbar shows the Python logo."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "mariodomingos.archiver")
    except Exception:
        pass    # cosmetic only - never block startup over it


def apply_style(app):
    """
    The look, applied to an existing QApplication.

    Split out of main() so anything that builds a window WITHOUT going
    through main() -- a test harness, a screenshot rig -- gets the same
    style. When this lived inline, a rig that skipped it rendered the
    Windows accent over the size bars and looked like a live regression.
    """
    # Fusion, not the platform style. The Windows 11 style paints its own
    # accent-coloured highlight over the current tree row (#a94dc1 by default),
    # which lands on top of the size bars and reads as an error outline -- and
    # it ignores both `outline: 0` and a cleared State_HasFocus, because it is
    # not a focus rectangle at all. Fusion honours the stylesheet, so the dark
    # theme comes out the same on every machine whatever accent the user has.
    app.setStyle("Fusion")

    # Pin the highlight colour. It otherwise comes from the user's Windows
    # accent (a purple #a94dc1 on this machine), and the size-bar delegate
    # paints palette.highlight() behind a selected row -- so the accent lands
    # on top of the bars and reads as an error outline. Everything else in the
    # app is themed by stylesheet; the palette is the one thing a stylesheet
    # cannot reach from inside a QStyledItemDelegate.
    palette = app.palette()
    for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive):
        palette.setColor(group, QtGui.QPalette.Highlight,
                         QtGui.QColor("#35566e"))
        palette.setColor(group, QtGui.QPalette.HighlightedText,
                         QtGui.QColor("#e8e8e8"))
    app.setPalette(palette)


def main():
    _claim_taskbar_identity()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Archiver")
    apply_style(app)

    app.setWindowIcon(app_icon())

    window = MainWindow()
    if len(sys.argv) > 1:
        window.path_edit.setText(sys.argv[1])
        window.show()
        window.start_scan()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
