# Archiver -- the detail strip under a table.
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
Everything about the row you are on, in full.

The "Why" column is a summary and always will be -- the reasons are whole
sentences and no column wide enough to hold one leaves room for the table.
Rather than truncate and hope, the column gives the gist and this gives the
complete answer for whichever row has focus.

It is deliberately a fixed strip rather than a popup: a verdict you have to
hover to read is a verdict that gets acted on unread.
"""

import os

from PySide6 import QtCore, QtGui, QtWidgets

from core import rules
from core.scanner import human

from .bars import VERDICT_FILL, verdict_icon

# Selecting the text matters: these are paths people paste into a file dialog
# or a shell.
Qt_SELECTABLE = (QtCore.Qt.TextSelectableByMouse
                 | QtCore.Qt.TextSelectableByKeyboard)


class DetailPanel(QtWidgets.QFrame):
    """A three-line summary of the selected folder: what, why, and where."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setObjectName("detail")
        self.setStyleSheet(
            "QFrame#detail { background: #242424; border: 1px solid #303030;"
            " border-radius: 3px; }")
        self._build()
        self.clear()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)

        self.badge = QtWidgets.QLabel()
        self.badge.setFixedSize(14, 14)
        top.addWidget(self.badge)

        self.headline = QtWidgets.QLabel("")
        self.headline.setStyleSheet("font-size: 13px;")
        self.headline.setTextInteractionFlags(Qt_SELECTABLE)
        top.addWidget(self.headline, 1)

        self.facts = QtWidgets.QLabel("")
        self.facts.setObjectName("hint")
        top.addWidget(self.facts)
        layout.addLayout(top)

        # The whole reason, wrapped. This is the point of the panel.
        self.why = QtWidgets.QLabel("")
        self.why.setWordWrap(True)
        self.why.setTextInteractionFlags(Qt_SELECTABLE)
        layout.addWidget(self.why)

        # Which scenes read this. The reason line used to say "check the Used
        # by column", but that column only exists in the file panel on tab 1 --
        # it pointed at something that was not on the screen. Naming the
        # scenes here answers the question where it is actually asked.
        self.users = QtWidgets.QLabel("")
        self.users.setWordWrap(True)
        self.users.setTextInteractionFlags(Qt_SELECTABLE)
        layout.addWidget(self.users)

        self.path = QtWidgets.QLabel("")
        self.path.setObjectName("hint")
        self.path.setWordWrap(True)
        self.path.setTextInteractionFlags(Qt_SELECTABLE)
        layout.addWidget(self.path)

    def clear(self):
        self.badge.clear()
        self.headline.setText("Select a row to see why.")
        self.facts.setText("")
        self.why.setText("")
        self.users.setText("")
        self.users.hide()
        self.path.setText("")

    def show_folder(self, folder, root=""):
        """Fill from a scanner.FolderReport."""
        if folder is None:
            self.clear()
            return

        verdict = folder.verdict
        self.badge.setPixmap(verdict_icon(verdict, 14).pixmap(14, 14))

        label = rules.CATEGORY_LABEL.get(folder.category, "")
        self.headline.setText("%s   <b>%s</b>" % (label, folder.name))

        parts = [rules.VERDICT_LABEL.get(verdict, ""), folder.human_size,
                 "%s files" % "{:,}".format(folder.count)]
        if folder.age:
            parts.append(folder.age)
        if folder.referenced_count:
            parts.append("%d referenced" % folder.referenced_count)
        self.facts.setText("   ".join(p for p in parts if p))

        colour = VERDICT_FILL.get(verdict, VERDICT_FILL[None]).lighter(150)

        # The reason, then the evidence behind it. Naming the signals is the
        # point: each is a claim the user can go and check, which is what a
        # percentage would have replaced with a number nobody can verify.
        text = folder.reason or ""
        if getattr(folder, "signals", None):
            text += ("   %s — %d signal%s agree: %s."
                     % (rules.CONFIDENCE_LABEL[folder.confidence],
                        len(folder.signals),
                        "" if len(folder.signals) == 1 else "s",
                        "; ".join(folder.signals)))
        self.why.setText(text)
        self.why.setStyleSheet("color: %s;" % colour.name())

        self._show_users(folder)
        self.path.setText(folder.path)

    def _show_users(self, folder):
        """Name the scenes that read anything in this folder."""
        scenes = []
        for entry in folder.entries:
            for scene in getattr(entry, "used_by", ()) or ():
                name = os.path.basename(scene)
                if name not in scenes:
                    scenes.append(name)

        if not scenes:
            self.users.hide()
            return

        shown = "  ".join(scenes[:6])
        if len(scenes) > 6:
            shown += "   +%d more" % (len(scenes) - 6)
        self.users.setText("Read by:  " + shown)
        self.users.setStyleSheet("color: #7fb48f;")
        self.users.setToolTip("\n".join(scenes))
        self.users.show()
