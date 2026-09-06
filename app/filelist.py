# Archiver -- the drill-down panel under the tree.
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
"Show me what is actually in that segment."

Double-clicking a piece of a summary bar opens this underneath the tree. The
bars answer how much and what kind; this answers which files, which is the
question you ask right before deciding anything.

Sequences are collapsed to one row -- a 3000-frame render is one decision, not
three thousand -- and expand on demand. Without that a cache segment on a real
project is fifty thousand rows and unreadable.
"""

import os

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from core.scanner import age_label, human

from .explorer import add_reveal_menu


class FileListPanel(QtWidgets.QWidget):
    """A closable pane listing the files behind one bar segment."""

    closed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = ""
        self._build()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(4)

        header = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel("")
        self.title.setStyleSheet("font-size: 13px;")
        close = QtWidgets.QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setToolTip("Close this panel")
        close.clicked.connect(self.closed.emit)
        header.addWidget(self.title, 1)
        header.addWidget(close)
        layout.addLayout(header)

        self.table = QtWidgets.QTreeWidget()
        self.table.setHeaderLabels(["File", "Size", "Folder", "Age"])
        self.table.setAlternatingRowColors(True)
        self.table.setRootIsDecorated(True)
        self.table.setUniformRowHeights(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header_view = self.table.header()
        header_view.setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        header_view.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.setColumnWidth(0, 340)
        self.table.setColumnWidth(1, 90)

        add_reveal_menu(self.table)
        layout.addWidget(self.table, 1)

    def show_sequences(self, title, sequences, root):
        """
        Fill the panel. sequences comes from scanner.group_sequences().

        Only the first few hundred rows are built: past that the list is not
        something anyone reads, and building tens of thousands of widgets
        stalls the window for seconds.
        """
        self._root = root or ""
        self.table.clear()

        total = sum(sequence.size for sequence in sequences)
        count = sum(sequence.count for sequence in sequences)
        self.title.setText("%s — %s in %s files"
                           % (title, human(total), "{:,}".format(count)))

        shown = sequences[:400]
        for sequence in shown:
            self._add_sequence(sequence)

        if len(sequences) > len(shown):
            note = QtWidgets.QTreeWidgetItem(self.table)
            note.setText(0, "... and %d more, smaller"
                         % (len(sequences) - len(shown)))
            note.setForeground(0, QtGui.QBrush(QtGui.QColor("#9aa0a6")))

    def _add_sequence(self, sequence):
        item = QtWidgets.QTreeWidgetItem(self.table)
        item.setText(0, sequence.name)
        item.setText(1, human(sequence.size))
        item.setText(2, self._relative(os.path.dirname(sequence.entries[0].path)
                                       if sequence.entries else ""))
        item.setText(3, age_label(sequence.mtime))

        first = sequence.entries[0] if sequence.entries else None
        if first is not None:
            item.setData(0, Qt.UserRole, first.path)
            item.setToolTip(0, first.path)

        # Individual frames only when there is more than one; a single file
        # dressed as an expandable group is just noise.
        if sequence.count > 1:
            for entry in sequence.entries[:2000]:
                child = QtWidgets.QTreeWidgetItem(item)
                child.setText(0, os.path.basename(entry.path))
                child.setText(1, human(entry.size))
                child.setText(3, age_label(entry.mtime))
                child.setData(0, Qt.UserRole, entry.path)

    def _relative(self, path):
        if self._root and path.lower().startswith(self._root.lower()):
            return path[len(self._root):].lstrip("/") or "."
        return path
