"""
What must NOT survive a rescan.

A new scan replaces the tree, the strips, the findings and the summary, so
anything that keeps the OLD project's data reads as part of the NEW one. The
drill-down panel was exactly that: it is only ever filled by a double-click,
so no refill path touched it and it sat under the new tree still listing the
previous project's files, with their real paths.

Needs Qt, so it skips cleanly where PySide6 is absent.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PySide6 import QtWidgets
    _app = (QtWidgets.QApplication.instance()
            or QtWidgets.QApplication([]))
    from app.window import MainWindow
    from core import rules, scanner
    HAVE_QT = True
except ImportError:                                  # no PySide6 installed
    HAVE_QT = False


def _project(root, name, payload):
    """A minimal project: one render folder with a superseded version."""
    base = os.path.join(root, name)
    for version, size in (("v001", 400), ("v002", 400)):
        folder = os.path.join(base, "renders", version)
        os.makedirs(folder)
        for frame in range(3):
            path = os.path.join(folder, "%s_%s.%04d.exr"
                                % (payload, version, frame))
            with open(path, "wb") as handle:
                handle.write(b"\0" * size)
    return base


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestRescanClearsPanel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="archiver_window_")
        self.first = _project(self.tmp, "job_alpha", "ALPHA")
        self.second = _project(self.tmp, "job_beta", "BETA")
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scan(self, root):
        """Drive _on_finished directly -- the worker is a thread we do not
        need; what is under test is what the handler rebuilds."""
        self.window._on_finished(scanner.scan(root))

    def panel_rows(self):
        table = self.window.file_panel.table
        return [table.topLevelItem(i).text(0)
                for i in range(table.topLevelItemCount())]

    def test_panel_does_not_show_the_previous_project(self):
        self.scan(self.first)
        self.window._show_verdict_files(rules.DROP)
        rows = self.panel_rows()
        self.assertTrue(rows, "the first project should have Drop rows")
        self.assertTrue(any("ALPHA" in row for row in rows))

        self.scan(self.second)
        # The bar filter is dropped -- the segment that opened it may not
        # exist in the new scan -- and selecting the new root then shows the
        # new project's files. What must never survive is the OLD project.
        rows = self.panel_rows()
        self.assertFalse([r for r in rows if "ALPHA" in r],
                         "the previous project's files must not survive")
        self.assertNotIn("ALPHA", self.window.file_panel.title.text())

    def test_panel_still_opens_after_a_rescan(self):
        # Clearing it must not leave it unusable: the same double-click has
        # to fill it from the new result.
        self.scan(self.first)
        self.window._show_verdict_files(rules.DROP)
        self.scan(self.second)

        self.window._show_verdict_files(rules.DROP)
        rows = self.panel_rows()
        self.assertTrue(rows)
        self.assertTrue(any("BETA" in row for row in rows))
        self.assertFalse(any("ALPHA" in row for row in rows))

    def test_panel_root_is_the_new_project(self):
        # The panel shortens paths against the root it was handed. A stale
        # root makes the Folder column nonsense even once the rows are right.
        self.scan(self.first)
        self.window._show_verdict_files(rules.DROP)
        self.scan(self.second)

        self.window._show_verdict_files(rules.DROP)
        self.assertEqual(os.path.normcase(self.window.file_panel._root),
                         os.path.normcase(self.window.result.root))


if __name__ == "__main__":
    unittest.main()
