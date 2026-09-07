"""
Shift-range and drag-to-paint on the checkbox trees.

Driven with real QMouseEvents rather than by calling the handlers, because
the part most likely to be wrong is the geometry: deciding whether a press
landed on the checkbox or merely on the row.

Needs Qt, so it skips cleanly where PySide6 is absent.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
    _app = (QtWidgets.QApplication.instance()
            or QtWidgets.QApplication([]))
    from app.bulkcheck import BulkCheckTree
    HAVE_QT = True
except ImportError:                                  # no PySide6 installed
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestGestures(unittest.TestCase):

    def setUp(self):
        self.tree = BulkCheckTree()
        self.tree.setColumnCount(1)
        self.tree.setRootIsDecorated(False)
        self.applied = []

        for index in range(8):
            item = QtWidgets.QTreeWidgetItem(self.tree)
            item.setText(0, "row %d" % index)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)

        # Route ticks through a recorder, the way the window routes them
        # through the Selection model.
        def set_checked(item, checked):
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
            self.applied.append((item.text(0), checked))

        self.tree._bulk_init(set_checked)
        self.tree.resize(400, 300)
        self.tree.show()
        _app.processEvents()

    def tearDown(self):
        self.tree.close()
        self.tree.deleteLater()

    def row(self, index):
        return self.tree.topLevelItem(index)

    def checkbox_point(self, index):
        """A point inside row `index`'s checkbox indicator."""
        rect = self.tree.visualItemRect(self.row(index))
        return QtCore.QPointF(rect.left() + 8, rect.center().y())

    def label_point(self, index):
        """A point on the row's TEXT, well clear of the checkbox."""
        rect = self.tree.visualItemRect(self.row(index))
        return QtCore.QPointF(rect.right() - 20, rect.center().y())

    def press(self, point, modifiers=Qt.NoModifier):
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress, point,
            self.tree.viewport().mapToGlobal(point.toPoint()),
            Qt.LeftButton, Qt.LeftButton, modifiers)
        self.tree.mousePressEvent(event)

    def move(self, point):
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseMove, point,
            self.tree.viewport().mapToGlobal(point.toPoint()),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        self.tree.mouseMoveEvent(event)

    def release(self, point):
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease, point,
            self.tree.viewport().mapToGlobal(point.toPoint()),
            Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        self.tree.mouseReleaseEvent(event)

    def states(self):
        return [self.row(i).checkState(0) == Qt.Checked for i in range(8)]

    # -- the gestures -------------------------------------------------------

    def test_a_plain_click_ticks_one_row(self):
        self.press(self.checkbox_point(2))
        self.release(self.checkbox_point(2))
        self.assertEqual(self.states(),
                         [False, False, True, False, False, False, False,
                          False])

    def test_shift_click_fills_the_range(self):
        self.press(self.checkbox_point(1))
        self.release(self.checkbox_point(1))
        self.press(self.checkbox_point(5), Qt.ShiftModifier)
        self.assertEqual(self.states(),
                         [False, True, True, True, True, True, False, False])

    def test_shift_click_works_upwards_too(self):
        self.press(self.checkbox_point(5))
        self.release(self.checkbox_point(5))
        self.press(self.checkbox_point(2), Qt.ShiftModifier)
        for index in (2, 3, 4, 5):
            self.assertTrue(self.states()[index], "row %d" % index)

    def test_dragging_paints_the_first_box_state(self):
        self.press(self.checkbox_point(0))
        self.move(self.checkbox_point(1))
        self.move(self.checkbox_point(2))
        self.move(self.checkbox_point(3))
        self.release(self.checkbox_point(3))
        self.assertEqual(self.states()[:4], [True, True, True, True])

    def test_dragging_from_a_ticked_box_unticks(self):
        # The state comes from the FIRST box, so a drag is one decision --
        # not a toggle per row, which would undo itself on the way back.
        for index in range(4):
            self.row(index).setCheckState(0, Qt.Checked)
        self.press(self.checkbox_point(0))
        self.move(self.checkbox_point(1))
        self.move(self.checkbox_point(2))
        self.release(self.checkbox_point(2))
        self.assertEqual(self.states()[:3], [False, False, False])

    def test_dragging_back_over_a_row_does_not_flip_it_again(self):
        self.press(self.checkbox_point(0))
        self.move(self.checkbox_point(1))
        self.move(self.checkbox_point(2))
        self.move(self.checkbox_point(1))    # back over one already painted
        self.release(self.checkbox_point(1))
        self.assertEqual(self.states()[:3], [True, True, True])

    def test_clicking_the_row_label_does_not_tick_it(self):
        # Otherwise clicking a row to read it would start a paint drag.
        self.press(self.label_point(3))
        self.release(self.label_point(3))
        self.assertFalse(self.states()[3])

    def test_a_veto_keeps_rows_untouched(self):
        # What protection uses: some rows simply cannot be painted.
        blocked = self.row(2)

        def can_check(item):
            return item is not blocked

        def set_checked(item, checked):
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

        self.tree._bulk_init(set_checked, can_check)
        self.press(self.checkbox_point(0))
        self.release(self.checkbox_point(0))
        self.press(self.checkbox_point(4), Qt.ShiftModifier)
        states = self.states()
        self.assertTrue(states[1])
        self.assertFalse(states[2], "the vetoed row must stay unticked")
        self.assertTrue(states[3])


if __name__ == "__main__":
    unittest.main()
