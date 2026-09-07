# Archiver -- Shift-range and drag-to-paint on checkbox trees.
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
Ticking fifty rows one at a time is not a decision, it is typing.

Two gestures, both the ones people already expect from a file manager:

  SHIFT-CLICK a checkbox  -- everything from the last one you touched to this
                             one takes the state you just set.
  CLICK AND DRAG          -- the box you pressed decides the state, and every
                             box you drag across is set to match.

Both work on the VISIBLE order -- what the eye sees between the two rows, with
collapsed branches left alone. Anything else surprises: a Shift-range that
silently ticked things hidden inside a folded branch would be a selection
nobody could check before approving it.

Drag paints ONE state, taken from the first box. Toggling each row you cross
would mean dragging back over your own path undid half of it.
"""

from PySide6 import QtWidgets
from PySide6.QtCore import Qt


class BulkCheckMixin(object):
    """
    Adds Shift-range and drag-paint to a QTreeWidget with checkboxes.

    The host must call _bulk_init() once, and supply set_checked(item, state)
    if ticking a row means more than setCheckState -- which it does here,
    since a tick has to go through the Selection model to keep the tri-state
    parents honest.
    """

    def _bulk_init(self, set_checked=None, can_check=None):
        self._bulk_anchor = None        # last row whose box was clicked
        self._bulk_painting = False
        self._bulk_paint_state = None
        self._bulk_set = set_checked
        self._bulk_can = can_check

    # -- the two gestures ---------------------------------------------------

    def _bulk_rows(self):
        """Every visible row, top to bottom, as the eye reads them."""
        rows = []
        iterator = QtWidgets.QTreeWidgetItemIterator(
            self, QtWidgets.QTreeWidgetItemIterator.NotHidden)
        while iterator.value():
            rows.append(iterator.value())
            iterator += 1
        return rows

    def _bulk_apply(self, item, checked):
        if self._bulk_can is not None and not self._bulk_can(item):
            return
        if self._bulk_set is not None:
            self._bulk_set(item, checked)
        else:
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

    def _bulk_range(self, item, checked):
        """Apply `checked` to every visible row between the anchor and item."""
        rows = self._bulk_rows()
        try:
            start = rows.index(self._bulk_anchor)
            end = rows.index(item)
        except ValueError:
            # The anchor was collapsed away or the tree was refilled. Treat
            # this as a plain click rather than guessing at a range.
            self._bulk_apply(item, checked)
            return
        if start > end:
            start, end = end, start
        for row in rows[start:end + 1]:
            self._bulk_apply(row, checked)

    def _bulk_hit_checkbox(self, event):
        """
        Is the press on the checkbox itself, rather than the row?

        Asks the STYLE where it drew the indicator rather than computing an
        indent. A hand-rolled guess got this wrong in both directions --
        indentation, rootIsDecorated and the item's depth all move the box,
        and the style's own padding is not knowable from here. Being too
        permissive is the worse failure: it would start a paint drag every
        time someone clicked a row simply to read it.
        """
        point = event.position().toPoint()
        item = self.itemAt(point)
        if item is None:
            return None
        if not (item.flags() & Qt.ItemIsUserCheckable):
            return None

        index = self.indexFromItem(item, 0)
        option = QtWidgets.QStyleOptionViewItem()
        option.initFrom(self)
        option.rect = self.visualRect(index)
        option.features |= QtWidgets.QStyleOptionViewItem.HasCheckIndicator
        box = self.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            option, self)
        # A few pixels of slack: the indicator is 14px and clicking its very
        # edge should still count, as it does everywhere else in Windows.
        box = box.adjusted(-2, -2, 2, 2)
        return item if box.contains(point) else None

    # -- events -------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self._bulk_hit_checkbox(event)
            if item is not None:
                wanted = item.checkState(0) != Qt.Checked

                if (event.modifiers() & Qt.ShiftModifier) \
                        and self._bulk_anchor is not None:
                    self._bulk_range(item, wanted)
                    self._bulk_anchor = item
                    event.accept()
                    return

                # Plain press on a box: start painting. The first row sets
                # the state every row crossed will take.
                self._bulk_painting = True
                self._bulk_paint_state = wanted
                self._bulk_apply(item, wanted)
                self._bulk_anchor = item
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._bulk_painting and (event.buttons() & Qt.LeftButton):
            item = self.itemAt(event.position().toPoint())
            if item is not None and (item.flags() & Qt.ItemIsUserCheckable):
                current = item.checkState(0) == Qt.Checked
                if current != self._bulk_paint_state:
                    self._bulk_apply(item, self._bulk_paint_state)
                    self._bulk_anchor = item
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._bulk_painting:
            self._bulk_painting = False
            self._bulk_paint_state = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class BulkCheckTree(BulkCheckMixin, QtWidgets.QTreeWidget):
    """A QTreeWidget with both gestures wired up."""

    def __init__(self, parent=None):
        QtWidgets.QTreeWidget.__init__(self, parent)
        self._bulk_init()
