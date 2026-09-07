"""
The file panel as a filter over one set of rows.

The bars ask WHAT (a category or a verdict), the tree asks WHERE (a folder),
and the scope toggle decides whether the two compose. They are views of the
same scan, so the answers have to agree with each other.

The core half needs no Qt; the wiring half skips when PySide6 is absent.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules, scanner

try:
    from PySide6 import QtWidgets
    _app = (QtWidgets.QApplication.instance()
            or QtWidgets.QApplication([]))
    from app.window import MainWindow
    HAVE_QT = True
except ImportError:                                  # no PySide6 installed
    HAVE_QT = False


def write(path, payload=b"x" * 1024):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)


def build(root):
    """Two output trees plus a decoy whose name shares a prefix."""
    for version in ("v001", "v002"):
        for frame in range(3):
            write("%s/E_OUTPUT/renders/%s/beauty.%04d.exr"
                  % (root, version, frame))
    # The trap: "E_OUTPUT" must not match "E_OUTPUT_OLD".
    write(root + "/E_OUTPUT_OLD/renders/v001/old.0001.exr")
    write(root + "/B_SOURCE/tex/wood.png")
    write(root + "/B_SOURCE/tex/metal.png")
    return root


def count(sequences):
    return sum(sequence.count for sequence in sequences)


class TestScopedFilters(unittest.TestCase):
    """core: the same question, asked of the project and of one folder."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_scope_").replace(
            "\\", "/")
        build(self.root)
        self.result = scanner.scan(self.root)
        self.output = self.root + "/E_OUTPUT"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_no_scope_answers_for_the_whole_project(self):
        everything = self.result.files_in_category(rules.CAT_RENDER)
        self.assertEqual(count(everything), 7)      # 6 + the decoy's 1

    def test_scope_limits_to_the_subtree(self):
        scoped = self.result.files_in_category(rules.CAT_RENDER,
                                               under=self.output)
        self.assertEqual(count(scoped), 6)

    def test_a_sibling_sharing_the_prefix_is_not_included(self):
        # "E_OUTPUT" must not swallow "E_OUTPUT_OLD". Comparing raw prefixes
        # without the separator is the easy way to get this wrong, and the
        # damage is silent: too many files listed under a folder.
        scoped = self.result.files_in_category(rules.CAT_RENDER,
                                               under=self.output)
        for sequence in scoped:
            for entry in sequence.entries:
                self.assertNotIn("E_OUTPUT_OLD", entry.path)

    def test_scope_applies_to_verdicts_too(self):
        globally = self.result.files_with_verdict(rules.DROP)
        scoped = self.result.files_with_verdict(rules.DROP,
                                                under=self.output)
        self.assertGreaterEqual(count(globally), count(scoped))
        for sequence in scoped:
            for entry in sequence.entries:
                self.assertTrue(entry.path.startswith(self.output))

    def test_files_under_ignores_category_and_verdict(self):
        # Selecting a folder asks "what is in here", not "what kind".
        source = self.result.files_under(self.root + "/B_SOURCE")
        self.assertEqual(count(source), 2)

    def test_scoping_to_the_root_is_the_same_as_no_scope(self):
        self.assertEqual(
            count(self.result.files_in_category(rules.CAT_RENDER)),
            count(self.result.files_in_category(rules.CAT_RENDER,
                                                under=self.root)))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TestPanelWiring(unittest.TestCase):
    """the window: what the tree, the bars and the toggle do together."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_wire_").replace(
            "\\", "/")
        build(self.root)
        self.window = MainWindow()
        self.window._on_finished(scanner.scan(self.root))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        shutil.rmtree(self.root, ignore_errors=True)

    def rows(self):
        table = self.window.file_panel.table
        return [table.topLevelItem(i).text(0)
                for i in range(table.topLevelItemCount())]

    def select(self, relative):
        """Put the tree cursor on a folder, as clicking it would."""
        node = self.window._node_for_path(self.root + "/" + relative)
        self.assertIsNotNone(node, "no node for %r" % relative)
        self.window.current_node = node
        return node

    def test_selecting_a_folder_lists_its_files(self):
        self.select("B_SOURCE/tex")
        self.window._show_folder_files()
        # isHidden(), not isVisible(): a child of an unshown window is never
        # "visible" headlessly, but it does record whether it was hidden.
        self.assertFalse(self.window.file_panel.isHidden())
        self.assertTrue(any("wood" in r or "metal" in r for r in self.rows()))

    def test_a_bar_segment_answers_for_the_whole_project_by_default(self):
        self.select("B_SOURCE/tex")
        self.window._show_category_files(rules.CAT_RENDER)
        # Scope is off, so the selected source folder does not narrow it and
        # the decoy tree's render is included.
        joined = " ".join(self.rows())
        self.assertIn("beauty", joined)
        self.assertIn("old", joined)

    def test_the_toggle_narrows_it_to_the_selected_folder(self):
        self.select("E_OUTPUT")
        self.window._show_category_files(rules.CAT_RENDER)
        self.window.file_panel.scope_box.setChecked(True)
        joined = " ".join(self.rows())
        self.assertIn("beauty", joined)
        self.assertNotIn("old", joined)      # E_OUTPUT_OLD is a sibling

    def test_turning_the_toggle_off_widens_it_again(self):
        self.select("E_OUTPUT")
        self.window._show_category_files(rules.CAT_RENDER)
        self.window.file_panel.scope_box.setChecked(True)
        self.window.file_panel.scope_box.setChecked(False)
        self.assertIn("old", " ".join(self.rows()))

    def test_moving_the_selection_re_scopes_a_standing_filter(self):
        # The whole point: the bar filter stays, the folder changes under it.
        self.select("E_OUTPUT")
        self.window._show_category_files(rules.CAT_RENDER)
        self.window.file_panel.scope_box.setChecked(True)
        self.assertIn("beauty", " ".join(self.rows()))

        self.select("B_SOURCE")
        self.window._refresh_file_panel(open_it=False)
        # No renders live under B_SOURCE, so the panel says so rather than
        # showing a bare empty table.
        self.assertNotIn("beauty", " ".join(self.rows()))
        self.assertTrue(self.rows(), "an empty result still needs a message")

    def test_scoping_to_the_root_node_does_not_limit_anything(self):
        self.window.current_node = self.window.tree_root
        self.window._show_category_files(rules.CAT_RENDER)
        self.window.file_panel.scope_box.setChecked(True)
        self.assertIn("old", " ".join(self.rows()))

    def test_closing_the_panel_forgets_the_question(self):
        # Otherwise the next folder click silently re-opens it on a filter
        # the user just dismissed.
        self.window._show_category_files(rules.CAT_RENDER)
        self.window._close_file_panel()
        self.assertEqual(self.window._request, (None, None))


if __name__ == "__main__":
    unittest.main()
