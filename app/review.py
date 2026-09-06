# Archiver -- step 4: confirm what is about to happen.
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
The review screen: the last thing between a selection and acting on it.

Its job is not to summarise flatteringly. It exists to give the user a fair
chance to notice a mistake, so it leads with the things most likely to BE a
mistake -- folders the scan judged worth keeping, and anything selected in a
project whose scenes could not be read.
"""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from core import rules
from core.scanner import human

from .bars import StackedBar, VERDICT_FILL
from .explorer import add_reveal_menu


def _short_path(relative, keep=2):
    """The identifying tail of a path; the full one lives in the tooltip."""
    parts = [p for p in (relative or "").split("/") if p]
    if len(parts) <= keep:
        return relative or "."
    return ".../" + "/".join(parts[-keep:])


class ReviewDialog(QtWidgets.QDialog):
    """Shows the selection, then offers to stage it."""

    def __init__(self, selection, result, parent=None):
        super().__init__(parent)
        self.selection = selection
        self.result = result
        self.approved = False

        self.setWindowTitle("Review selection")
        self.resize(860, 620)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

        self._build()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        headline = QtWidgets.QLabel(
            "%s in %d folders, %s files"
            % (human(self.selection.total_bytes()),
               len(self.selection.nodes()),
               "{:,}".format(self.selection.total_files())))
        headline.setStyleSheet("font-size: 17px;")
        layout.addWidget(headline)

        bar = StackedBar(14)
        totals = self.selection.by_verdict()
        bar.set_segments([(rules.VERDICT_LABEL[v], totals.get(v, 0),
                           VERDICT_FILL[v])
                          for v in (rules.KEEP, rules.REVIEW, rules.DROP)])
        layout.addWidget(bar)

        for warning in self._warnings():
            label = QtWidgets.QLabel(warning)
            label.setObjectName("warn")
            label.setWordWrap(True)
            layout.addWidget(label)

        layout.addWidget(self._build_table(), 1)

        note = QtWidgets.QLabel(
            "Approving MOVES these into a _toDelete folder inside the "
            "project. Nothing is deleted, and you can move it back.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addLayout(self._build_buttons())

    def _warnings(self):
        """The things worth stopping for, most serious first."""
        warnings = []

        overrides = self.selection.overrides()
        if overrides:
            names = ", ".join(node.name for node in overrides[:4])
            if len(overrides) > 4:
                names += ", and %d more" % (len(overrides) - 4)
            warnings.append(
                "%d selected folder%s the scan judged worth keeping: %s. "
                "These hold source material the scan could not tie to "
                "anything regenerable."
                % (len(overrides), "" if len(overrides) == 1 else "s", names))

        if self.result is not None and self.result.opaque_scenes:
            stale = len(getattr(self.result, "stale_sidecars", []))
            unread = len(self.result.opaque_scenes) - stale

            if unread:
                warnings.append(
                    "%d scene%s in this project could not be read, so nothing "
                    "was verified against them. A cache or geometry file they "
                    "use looks unreferenced here. Run Archiver Asset Export "
                    "inside Cinema 4D to fix this."
                    % (unread, "" if unread == 1 else "s"))

            # Stale evidence still protects what it names, so this is a
            # weaker warning than the one above -- but it has to be said,
            # or a cache added since the export looks unreferenced.
            if stale:
                warnings.append(
                    "%d scene%s been saved since its asset list was exported. "
                    "What that list names is still protected, but anything "
                    "added to the scene since is not. Re-run Archiver Asset "
                    "Export in Cinema 4D."
                    % (stale, " has" if stale == 1 else "s have"))

        return warnings

    def _build_table(self):
        table = QtWidgets.QTreeWidget()
        table.setHeaderLabels(["Folder", "Size", "Files", "Verdict", "Why"])
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        root = self.result.root if self.result else ""
        # Worst first: a folder the scan wanted kept is the one most worth a
        # second look, so it should not be buried at the bottom.
        order = {rules.KEEP: 0, rules.REVIEW: 1, rules.DROP: 2}
        nodes = sorted(self.selection.nodes(),
                       key=lambda n: (order.get(n.verdict, 1),
                                      -n.total_size))

        for node in nodes:
            item = QtWidgets.QTreeWidgetItem(table)
            relative = node.path[len(root):].lstrip("/") or node.name
            item.setText(0, _short_path(relative))
            item.setToolTip(0, node.path)
            item.setData(0, Qt.UserRole, node.path)
            item.setText(1, node.human_size)
            item.setText(2, "{:,}".format(node.total_files))
            item.setText(3, rules.VERDICT_LABEL.get(node.verdict, ""))
            item.setText(4, node.report.reason if node.report else "")
            if node.verdict:
                item.setForeground(3, QtGui.QBrush(
                    VERDICT_FILL[node.verdict].lighter(150)))

        add_reveal_menu(table)

        header = table.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        table.setColumnWidth(0, 320)
        return table

    def _build_buttons(self):
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)

        back = QtWidgets.QPushButton("Back")
        back.clicked.connect(self.reject)

        self.approve = QtWidgets.QPushButton("Approve — move to _toDelete")
        self.approve.setObjectName("primary")
        self.approve.clicked.connect(self._accept)

        row.addWidget(back)
        row.addWidget(self.approve)
        return row

    def _accept(self):
        """
        Last confirmation before anything moves.

        The dialog above already lists what was chosen, so this does not
        repeat it -- it states the one fact the list does not: this is the
        step that touches the disk.
        """
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Approve")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("Move %s into _toDelete?"
                    % human(self.selection.total_bytes()))
        box.setInformativeText(
            "Files are MOVED, not deleted, and the folder structure is kept "
            "so anything can be put back.\n\n"
            "Check the project still opens, then delete _toDelete yourself "
            "when you are satisfied.")
        box.setStandardButtons(QtWidgets.QMessageBox.Cancel |
                               QtWidgets.QMessageBox.Yes)
        box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        if box.exec() != QtWidgets.QMessageBox.Yes:
            return

        self.approved = True
        self.accept()
