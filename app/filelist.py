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

from core import rules
from core.scanner import age_label, human

from .bars import VERDICT_FILL, verdict_icon
from .explorer import add_reveal_menu

_CONFIDENCE_COLOUR = {
    rules.STRONG: QtGui.QColor("#7fb48f"),
    rules.MODERATE: QtGui.QColor("#c2a34a"),
    rules.WEAK: QtGui.QColor("#9aa0a6"),
}


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
        # The same columns the findings tab shows, because this answers the
        # same question. A bar segment and the findings table describing the
        # same folders differently is how a tool stops being trusted.
        self.table.setHeaderLabels(
            ["File", "Size", "Verdict", "Confidence", "Why", "Used by",
             "Folder", "Age"])
        self.table.setAlternatingRowColors(True)
        self.table.setRootIsDecorated(True)
        self.table.setUniformRowHeights(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header_view = self.table.header()
        header_view.setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        header_view.setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(5, 150)
        self.table.setSortingEnabled(True)

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
        self._set_verdict(item, sequence.folder)
        item.setText(6, self._relative(os.path.dirname(sequence.entries[0].path)
                                       if sequence.entries else ""))
        item.setText(7, age_label(sequence.mtime))

        first = sequence.entries[0] if sequence.entries else None
        if first is not None:
            item.setData(0, Qt.UserRole, first.path)
            item.setToolTip(0, first.path)
            self._set_users(item, first)

        # Individual frames only when there is more than one; a single file
        # dressed as an expandable group is just noise.
        if sequence.count > 1:
            for entry in sequence.entries[:2000]:
                child = QtWidgets.QTreeWidgetItem(item)
                child.setText(0, os.path.basename(entry.path))
                child.setText(1, human(entry.size))
                child.setText(7, age_label(entry.mtime))
                child.setData(0, Qt.UserRole, entry.path)
                self._set_users(child, entry)

    def _set_verdict(self, item, folder):
        """Carry the folder's verdict, confidence and reason onto the row."""
        if folder is None:
            return

        verdict = folder.verdict
        item.setText(2, rules.VERDICT_LABEL.get(verdict, ""))
        item.setIcon(2, verdict_icon(verdict))
        item.setForeground(2, QtGui.QBrush(
            VERDICT_FILL.get(verdict, VERDICT_FILL[None]).lighter(160)))

        if getattr(folder, "confidence", None):
            item.setText(3, rules.CONFIDENCE_LABEL[folder.confidence])
            item.setForeground(3, QtGui.QBrush(
                _CONFIDENCE_COLOUR.get(folder.confidence,
                                       QtGui.QColor("#9aa0a6"))))
            if folder.signals:
                item.setToolTip(3, "%d signal%s agree:\n  %s"
                                % (len(folder.signals),
                                   "" if len(folder.signals) == 1 else "s",
                                   "\n  ".join(folder.signals)))

        item.setText(4, folder.reason or "")
        item.setToolTip(4, folder.reason or "")

    def _set_users(self, item, entry):
        """
        Which scenes name this file.

        The question you actually ask before deleting a cache is not "is this
        referenced?" but "what breaks if it goes?". An empty cell is honest
        ambiguity, not a verdict: it means no READABLE scene named it, and on
        a Cinema 4D project no scene is readable at all.
        """
        users = getattr(entry, "used_by", None)
        if not users:
            return

        names = [os.path.splitext(os.path.basename(u))[0] for u in users]
        unique = list(dict.fromkeys(names))
        text = unique[0] if len(unique) == 1 else "%s +%d" % (unique[0],
                                                             len(unique) - 1)
        item.setText(2, text)
        item.setForeground(2, QtGui.QBrush(QtGui.QColor("#7fb48f")))
        item.setToolTip(2, "Referenced by:\n  " + "\n  ".join(
            os.path.basename(u) for u in users[:20]))

    def _relative(self, path):
        if self._root and path.lower().startswith(self._root.lower()):
            return path[len(self._root):].lstrip("/") or "."
        return path
