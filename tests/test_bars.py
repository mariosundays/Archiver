"""
The stacked bar's geometry.

Needs Qt, so it skips cleanly where PySide6 is absent -- the rest of the suite
stays dependency-free.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6 import QtWidgets
    _app = (QtWidgets.QApplication.instance()
            or QtWidgets.QApplication([]))
    from app.bars import MIN_SEGMENT_PX, StackedBar
    HAVE_QT = True
except ImportError:                                  # no PySide6 installed
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestSegmentWidths(unittest.TestCase):

    def bar(self, values, width=1000):
        from PySide6 import QtGui
        bar = StackedBar(16)
        bar.resize(width, 16)
        bar.set_segments([(str(i), v, QtGui.QColor("#888888"))
                          for i, v in enumerate(values)])
        return bar

    def test_proportional_when_all_are_large(self):
        bar = self.bar([500, 300, 200])
        widths = [w for _o, w, _c in bar._laid_out(1000)]
        self.assertAlmostEqual(widths[0], 500, delta=1)
        self.assertAlmostEqual(widths[1], 300, delta=1)
        self.assertAlmostEqual(widths[2], 200, delta=1)

    def test_tiny_segment_is_still_visible(self):
        # The real case: 2 MB of backups inside 3.4 GB is 0.06% -- a third of
        # a pixel -- so the Drop segment was simply not drawn.
        bar = self.bar([176881664, 3435973836, 2097152], 1150)
        widths = [w for _o, w, _c in bar._laid_out(1150)]
        self.assertGreaterEqual(widths[2], MIN_SEGMENT_PX)

    def test_widths_still_fill_the_bar(self):
        bar = self.bar([176881664, 3435973836, 2097152], 1150)
        total = sum(w for _o, w, _c in bar._laid_out(1150))
        self.assertAlmostEqual(total, 1150, delta=1.0)

    def test_large_segments_stay_close_to_true(self):
        # The floor is paid for pro-rata by the big ones; they must not move
        # more than a few pixels or the bar stops being a measurement.
        bar = self.bar([176881664, 3435973836, 2097152], 1150)
        widths = [w for _o, w, _c in bar._laid_out(1150)]
        true_review = 1150 * (3435973836 / float(176881664 + 3435973836
                                                 + 2097152))
        self.assertAlmostEqual(widths[1], true_review, delta=8.0)

    def test_hit_test_finds_the_tiny_segment(self):
        # A segment you can see but cannot hover is only half fixed.
        bar = self.bar([176881664, 3435973836, 2097152], 1150)
        self.assertEqual(bar._segment_at(1147)[0], "2")

    def test_hit_test_matches_the_drawing(self):
        bar = self.bar([500, 300, 200])
        for index, (offset, width, _colour) in enumerate(bar._laid_out(1000)):
            middle = offset + width / 2
            self.assertEqual(bar._segment_at(middle)[0], str(index))

    def test_all_tiny_keeps_proportions(self):
        # When nothing is big enough to donate, proportions are left alone
        # rather than scaled into nonsense.
        bar = self.bar([1, 1, 1], 12)
        widths = [w for _o, w, _c in bar._laid_out(12)]
        self.assertAlmostEqual(widths[0], widths[1], delta=0.5)

    def test_zero_segments_are_dropped(self):
        bar = self.bar([100, 0, 50])
        self.assertEqual(len(bar._laid_out(1000)), 2)

    def test_empty_bar(self):
        bar = self.bar([])
        self.assertEqual(bar._laid_out(1000), [])
        self.assertIsNone(bar._segment_at(10))


if __name__ == "__main__":
    unittest.main()
