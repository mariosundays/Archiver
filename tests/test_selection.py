"""
The selection model. Plain data, so all of this is testable without Qt.

The awkward case throughout is deselecting something inside an already
selected parent: the parent has to break up into its other children, or the
thing you just unticked is still covered.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules, scanner, selection, tree
from core.selection import CHECKED, PARTIAL, UNCHECKED
from test_scanner import fake_hip, write


class SelectionCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_sel_").replace("\\", "/")
        fake_hip(self.root + "/scenes/shot.hip", ["$HIP/tex/a.exr"])
        write(self.root + "/tex/a.exr", b"x" * 4096)
        write(self.root + "/render/v01/f.exr", b"x" * 2048)
        write(self.root + "/render/v02/f.exr", b"x" * 2048)
        write(self.root + "/cache/sim.bgeo", b"x" * 8192)
        write(self.root + "/tmp/junk.tmp", b"x" * 1024)

        self.result = scanner.scan(self.root)
        self.tree = tree.build(self.result)
        self.sel = selection.Selection(self.tree)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def node(self, relative):
        want = (self.root + "/" + relative).lower()
        for node in self.tree.descendants():
            if node.path.lower() == want:
                return node
        self.fail("no node %r" % relative)


class TestDefaults(SelectionCase):

    def test_nothing_selected_initially(self):
        # The user opts in. An accidental approve must do nothing.
        self.assertTrue(self.sel.is_empty())
        self.assertEqual(self.sel.total_bytes(), 0)
        self.assertEqual(self.sel.state(self.tree), UNCHECKED)


class TestSelecting(SelectionCase):

    def test_select_a_folder(self):
        self.sel.set(self.node("tmp"), True)
        self.assertTrue(self.sel.is_selected(self.node("tmp")))
        self.assertEqual(self.sel.total_bytes(), 1024)

    def test_selection_covers_descendants(self):
        self.sel.set(self.node("render"), True)
        self.assertTrue(self.sel.is_selected(self.node("render/v01")))
        self.assertTrue(self.sel.is_selected(self.node("render/v02")))

    def test_total_does_not_double_count(self):
        # render is selected AND its children are covered; counting both
        # would report twice the space freed.
        self.sel.set(self.node("render"), True)
        self.assertEqual(self.sel.total_bytes(), 4096)

    def test_selecting_a_child_of_a_selected_parent_is_a_no_op(self):
        self.sel.set(self.node("render"), True)
        self.sel.set(self.node("render/v01"), True)
        self.assertEqual(self.sel.total_bytes(), 4096)
        self.assertEqual(len(self.sel.nodes()), 1)

    def test_selecting_a_parent_absorbs_its_children(self):
        self.sel.set(self.node("render/v01"), True)
        self.sel.set(self.node("render/v02"), True)
        self.sel.set(self.node("render"), True)
        # The set must collapse to the one node, not keep three.
        self.assertEqual(len(self.sel.nodes()), 1)
        self.assertEqual(self.sel.total_bytes(), 4096)


class TestDeselecting(SelectionCase):

    def test_deselect(self):
        self.sel.set(self.node("tmp"), True)
        self.sel.set(self.node("tmp"), False)
        self.assertTrue(self.sel.is_empty())

    def test_deselect_a_child_breaks_up_the_parent(self):
        # The awkward case. Unticking v01 inside a selected render/ must
        # actually uncover v01, leaving v02 selected.
        self.sel.set(self.node("render"), True)
        self.sel.set(self.node("render/v01"), False)

        self.assertFalse(self.sel.is_selected(self.node("render/v01")))
        self.assertTrue(self.sel.is_selected(self.node("render/v02")))
        self.assertFalse(self.sel.is_selected(self.node("render")))
        self.assertEqual(self.sel.total_bytes(), 2048)

    def test_deselect_a_deep_child_breaks_up_every_level(self):
        self.sel.set(self.tree, True)
        self.sel.set(self.node("render/v01"), False)

        self.assertFalse(self.sel.is_selected(self.node("render/v01")))
        self.assertTrue(self.sel.is_selected(self.node("tex")))
        self.assertTrue(self.sel.is_selected(self.node("render/v02")))

    def test_deep_deselect_keeps_the_sibling_branch(self):
        # The regression: breaking up only the top level dropped "render"
        # entirely and never selected "render/v02", so the selection silently
        # became smaller than what the user had asked for.
        self.sel.set(self.tree, True)
        before = self.sel.total_bytes()
        self.sel.set(self.node("render/v01"), False)

        self.assertTrue(self.sel.is_selected(self.node("render/v02")),
                        "the untouched sibling was dropped from the "
                        "selection")
        self.assertEqual(self.sel.total_bytes(), before - 2048)

    def test_deselecting_everything_empties_the_selection(self):
        self.sel.set(self.node("render"), True)
        self.sel.set(self.node("render/v01"), False)
        self.sel.set(self.node("render/v02"), False)
        self.assertTrue(self.sel.is_empty())

    def test_clear(self):
        self.sel.set(self.tree, True)
        self.sel.clear()
        self.assertTrue(self.sel.is_empty())


class TestTriState(SelectionCase):

    def test_checked(self):
        self.sel.set(self.node("render"), True)
        self.assertEqual(self.sel.state(self.node("render")), CHECKED)

    def test_partial_parent(self):
        self.sel.set(self.node("render/v01"), True)
        self.assertEqual(self.sel.state(self.node("render")), PARTIAL)
        self.assertEqual(self.sel.state(self.tree), PARTIAL)

    def test_unchecked_siblings_stay_unchecked(self):
        self.sel.set(self.node("render/v01"), True)
        self.assertEqual(self.sel.state(self.node("render/v02")), UNCHECKED)
        self.assertEqual(self.sel.state(self.node("tex")), UNCHECKED)

    def test_full_children_still_read_as_checked_below(self):
        self.sel.set(self.node("render"), True)
        self.assertEqual(self.sel.state(self.node("render/v01")), CHECKED)


class TestSelectVerdict(SelectionCase):

    def test_select_all_drop(self):
        self.sel.select_verdict(rules.DROP)
        self.assertFalse(self.sel.is_empty())
        for node in self.sel.nodes():
            self.assertEqual(node.verdict, rules.DROP)

    def test_keeps_are_not_touched(self):
        self.sel.select_verdict(rules.DROP)
        self.assertFalse(self.sel.is_selected(self.node("tex")))


class TestReviewData(SelectionCase):

    def test_by_verdict(self):
        self.sel.set(self.node("tmp"), True)
        totals = self.sel.by_verdict()
        self.assertEqual(totals.get(rules.DROP), 1024)

    def test_overrides_reports_selected_keeps(self):
        # Selecting something the tool wanted kept is the one case where the
        # user and the tool disagree, and review must say so.
        self.sel.set(self.node("tex"), True)
        overrides = self.sel.overrides()
        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides[0].name, "tex")

    def test_no_overrides_when_only_drops_chosen(self):
        self.sel.select_verdict(rules.DROP)
        self.assertEqual(self.sel.overrides(), [])

    def test_file_count(self):
        self.sel.set(self.node("render"), True)
        self.assertEqual(self.sel.total_files(), 2)


if __name__ == "__main__":
    unittest.main()
