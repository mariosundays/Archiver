# Archiver -- open a path in the system file manager.
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

"""
Right-click, show it in Explorer.

A verdict is an opinion about a folder; sooner or later you want to look at the
thing itself. This is that escape hatch, and it is deliberately the only place
in the app that hands a path to the shell.

Read-only: it opens a window, it never modifies anything.
"""

import os
import subprocess
import sys

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt


def reveal(path):
    """
    Open the system file manager with `path` selected.

    Selecting the item is the useful behaviour -- opening its parent and
    leaving you to find it is not -- so Windows gets /select, and the fallback
    opens the containing folder.

    Returns an error string, or None on success.
    """
    path = os.path.normpath(str(path))
    if not os.path.exists(path):
        return "No longer on disk:\n\n%s" % path

    try:
        if sys.platform == "win32":
            # explorer.exe returns a non-zero exit code even when it works,
            # so its result is deliberately not checked. The quoting matters:
            # /select, needs the comma and an unquoted-by-list argument.
            subprocess.Popen(["explorer", "/select,", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.Popen(["xdg-open", folder])
    except (OSError, ValueError) as exc:
        return "Could not open the file manager:\n\n%s" % exc
    return None


def copy_path(path):
    QtWidgets.QApplication.clipboard().setText(str(path))


def add_reveal_menu(tree, path_for_item=None, protection_for=None,
                    on_protect=None):
    """
    Give a QTreeWidget a right-click menu with Show in Explorer.

    path_for_item(item) -> path lets a caller map its own rows; by default the
    path is read from Qt.UserRole on column 0, which is where every tree in
    this app already stores it.

    Pass protection_for(path) -> (is_protected, owning_mark) and
    on_protect(path, wanted) to add the "Never delete" entry. Both live here
    rather than in each tree so the three places you can right-click offer
    the same thing worded the same way.
    """
    if path_for_item is None:
        def path_for_item(item):
            return item.data(0, Qt.UserRole)

    def show_menu(point):
        item = tree.itemAt(point)
        if item is None:
            return
        path = path_for_item(item)
        if not path:
            return
        path = str(path)

        menu = QtWidgets.QMenu(tree)

        if protection_for is not None and on_protect is not None:
            protected, owner = protection_for(path)
            if protected and owner is not None and not owner[1]:
                # Protected by an ANCESTOR. Offering "unprotect" here would
                # have to remove the parent's mark, which would unprotect its
                # siblings too -- so say where the mark is instead of doing
                # something surprising.
                entry = menu.addAction("Protected by %s" % owner[0])
                entry.setEnabled(False)
            elif protected:
                entry = menu.addAction("Never delete")
                entry.setCheckable(True)
                entry.setChecked(True)
                entry.triggered.connect(
                    lambda _c=False, p=path: on_protect(p, False))
            else:
                entry = menu.addAction("Never delete")
                entry.setCheckable(True)
                entry.setChecked(False)
                entry.triggered.connect(
                    lambda _c=False, p=path: on_protect(p, True))
            menu.addSeparator()

        label = ("Show folder in Explorer" if os.path.isdir(path)
                 else "Show file in Explorer")

        action = menu.addAction(label)
        action.triggered.connect(lambda: _reveal_or_warn(tree, path))

        copy = menu.addAction("Copy path")
        copy.triggered.connect(lambda: copy_path(path))

        menu.exec(tree.viewport().mapToGlobal(point))

    tree.setContextMenuPolicy(Qt.CustomContextMenu)
    tree.customContextMenuRequested.connect(show_menu)


def _reveal_or_warn(parent, path):
    error = reveal(path)
    if error:
        QtWidgets.QMessageBox.warning(parent, "Archiver", error)
