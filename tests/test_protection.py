"""
"Never delete this."

A verdict is what the scan worked out; a protection is what the user KNOWS,
and it outranks the scan permanently. Two independent refusals guard it --
the selection will not tick a protected thing, and staging refuses it again
on its own -- so both are tested here, and so is the leak between them.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import actions, protection, scanner, selection, tree


def write(path, payload=b"x" * 1024):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)


class TestMarks(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_prot_").replace(
            "\\", "/")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_folder_protects_everything_under_it(self):
        marks = protection.Protected(self.root)
        marks.add(self.root + "/B_SOURCE")
        self.assertTrue(marks.is_protected(self.root + "/B_SOURCE"))
        self.assertTrue(marks.is_protected(self.root + "/B_SOURCE/tex/a.png"))

    def test_a_file_protects_only_itself(self):
        # The case folder-only marks cannot express: one irreplaceable file
        # inside an otherwise disposable folder.
        marks = protection.Protected(self.root)
        marks.add(self.root + "/OUT/hero.exr")
        self.assertTrue(marks.is_protected(self.root + "/OUT/hero.exr"))
        self.assertFalse(marks.is_protected(self.root + "/OUT/other.exr"))
        self.assertFalse(marks.is_protected(self.root + "/OUT"))

    def test_a_sibling_sharing_the_prefix_is_not_protected(self):
        # "B_SOURCE" must not cover "B_SOURCE_OLD". Silent failure: things
        # the user never protected quietly become unstageable.
        marks = protection.Protected(self.root)
        marks.add(self.root + "/B_SOURCE")
        self.assertFalse(marks.is_protected(self.root + "/B_SOURCE_OLD/a.png"))

    def test_anything_outside_the_project_is_refused(self):
        marks = protection.Protected(self.root)
        self.assertFalse(marks.add("D:/somewhere/else"))
        self.assertFalse(marks.is_protected("D:/somewhere/else"))

    def test_marking_a_parent_absorbs_its_children(self):
        # Otherwise unprotecting the parent later leaves orphan marks nobody
        # remembers setting.
        marks = protection.Protected(self.root)
        marks.add(self.root + "/A/B")
        marks.add(self.root + "/A")
        self.assertEqual(marks.relatives(), ["A"])

    def test_protected_by_names_the_mark_that_did_it(self):
        marks = protection.Protected(self.root)
        marks.add(self.root + "/B_SOURCE")
        self.assertEqual(marks.protected_by(self.root + "/B_SOURCE/tex/a.png"),
                         "B_SOURCE")

    def test_removing_only_works_on_the_exact_mark(self):
        # Removing a child's protection by deleting the PARENT mark would
        # unprotect the parent's other children too.
        marks = protection.Protected(self.root)
        marks.add(self.root + "/B_SOURCE")
        self.assertFalse(marks.remove(self.root + "/B_SOURCE/tex"))
        self.assertTrue(marks.is_protected(self.root + "/B_SOURCE/tex"))


class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_persist_").replace(
            "\\", "/")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_marks_survive_a_round_trip(self):
        marks = protection.Protected(self.root)
        marks.add(self.root + "/B_SOURCE")
        marks.add(self.root + "/OUT/hero.exr")
        _path, error = protection.save(self.root, marks, dry_run=False)
        self.assertIsNone(error)

        again, error = protection.load(self.root)
        self.assertIsNone(error)
        self.assertTrue(again.is_protected(self.root + "/B_SOURCE/x.png"))
        self.assertTrue(again.is_protected(self.root + "/OUT/hero.exr"))

    def test_marks_are_stored_relative_so_the_project_can_move(self):
        marks = protection.Protected(self.root)
        marks.add(self.root + "/B_SOURCE")
        protection.save(self.root, marks, dry_run=False)

        moved = self.root + "_moved"
        shutil.move(self.root, moved)
        try:
            again, error = protection.load(moved)
            self.assertIsNone(error)
            # Same mark, new location: Mario moves projects around.
            self.assertTrue(again.is_protected(moved + "/B_SOURCE/x.png"))
        finally:
            shutil.move(moved, self.root)

    def test_no_marks_leaves_no_file_behind(self):
        marks = protection.Protected(self.root)
        marks.add(self.root + "/A")
        protection.save(self.root, marks, dry_run=False)
        self.assertTrue(os.path.isfile(protection.marks_path(self.root)))

        marks.remove(self.root + "/A")
        protection.save(self.root, marks, dry_run=False)
        self.assertFalse(os.path.isfile(protection.marks_path(self.root)))

    def test_a_corrupt_file_protects_nothing_but_says_so(self):
        # Failing open would let something be deleted, so the caller is told
        # rather than left to assume nothing was ever marked.
        with open(protection.marks_path(self.root), "w") as handle:
            handle.write("{ not json")
        marks, error = protection.load(self.root)
        self.assertIsNotNone(error)
        self.assertEqual(len(marks), 0)

    def test_a_path_escaping_the_root_is_dropped_on_read(self):
        # The file is hand-editable, so this is not paranoia about our writer.
        with open(protection.marks_path(self.root), "w") as handle:
            json.dump({"format": 1, "paths": ["../../etc", "GOOD"]}, handle)
        marks, error = protection.load(self.root)
        self.assertIsNone(error)
        self.assertEqual(marks.relatives(), ["GOOD"])


class TestSelectionRefuses(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_selprot_").replace(
            "\\", "/")
        write(self.root + "/OUT/renders/a.exr")
        write(self.root + "/OUT/other/b.exr")
        write(self.root + "/OUT/third/c.exr")
        self.result = scanner.scan(self.root)
        self.tree = tree.build(self.result)
        self.marks = protection.Protected(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def node(self, name):
        for node in self.tree.descendants():
            if node.name == name:
                return node
        self.fail("no node %r" % name)

    def test_a_protected_node_cannot_be_ticked(self):
        self.marks.add(self.root + "/OUT/renders")
        chosen = selection.Selection(self.tree, self.marks)
        chosen.set(self.node("renders"), True)
        self.assertFalse(chosen.is_selected(self.node("renders")))

    def test_ticking_a_parent_does_not_swallow_a_protected_child(self):
        # The one place protection could leak: the subtree rule means one key
        # covers everything below it, so a mark deep down could be staged by
        # a tick far above it.
        self.marks.add(self.root + "/OUT/renders")
        chosen = selection.Selection(self.tree, self.marks)
        chosen.set(self.node("OUT"), True)

        self.assertFalse(chosen.is_selected(self.node("renders")))
        self.assertTrue(chosen.is_selected(self.node("other")))
        self.assertTrue(chosen.is_selected(self.node("third")))

    def test_select_verdict_never_overrides_a_mark(self):
        self.marks.add(self.root + "/OUT/renders")
        chosen = selection.Selection(self.tree, self.marks)
        for verdict in ("keep", "review", "drop"):
            chosen.select_verdict(verdict)
        self.assertFalse(chosen.is_selected(self.node("renders")))

    def test_deselecting_a_protected_node_is_always_allowed(self):
        # Refusing that would be refusing to make something safer.
        chosen = selection.Selection(self.tree, self.marks)
        chosen.set(self.node("renders"), True)
        self.marks.add(self.root + "/OUT/renders")
        chosen.set(self.node("renders"), False)
        self.assertFalse(chosen.is_selected(self.node("renders")))


class TestStagingRefuses(unittest.TestCase):
    """The second, independent refusal -- it reads the marks itself."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_stgprot_").replace(
            "\\", "/")
        write(self.root + "/OUT/renders/a.exr")
        write(self.root + "/OUT/other/b.exr")
        write(self.root + "/KEEP/hero.exr")
        marks = protection.Protected(self.root)
        marks.add(self.root + "/OUT/renders")
        marks.add(self.root + "/KEEP/hero.exr")
        protection.save(self.root, marks, dry_run=False)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_staging_refuses_a_protected_folder(self):
        _moved, failed = actions.stage(
            self.root, [self.root + "/OUT/renders"], dry_run=False)
        self.assertEqual(len(failed), 1)
        self.assertIn("never delete", failed[0][1])
        self.assertTrue(os.path.isdir(self.root + "/OUT/renders"))

    def test_staging_refuses_a_protected_file(self):
        _moved, failed = actions.stage(
            self.root, [self.root + "/KEEP/hero.exr"], dry_run=False)
        self.assertEqual(len(failed), 1)
        self.assertTrue(os.path.isfile(self.root + "/KEEP/hero.exr"))

    def test_staging_refuses_something_inside_a_protected_folder(self):
        _moved, failed = actions.stage(
            self.root, [self.root + "/OUT/renders/a.exr"], dry_run=False)
        self.assertEqual(len(failed), 1)
        # The reason names the mark, or the user hunts for one they cannot see.
        self.assertIn("OUT/renders", failed[0][1])

    def test_staging_a_folder_holding_a_protected_file_is_refused(self):
        # THE dangerous case: a folder is moved WHOLE, so a protected file
        # inside it would travel with it and the protection would be bypassed
        # silently. Checking only the path handed in is not enough.
        _moved, failed = actions.stage(
            self.root, [self.root + "/KEEP"], dry_run=False)
        self.assertEqual(len(failed), 1)
        self.assertIn("never delete", failed[0][1])
        self.assertTrue(os.path.isfile(self.root + "/KEEP/hero.exr"))

    def test_a_refused_folder_does_not_block_its_siblings(self):
        moved, failed = actions.stage(
            self.root, [self.root + "/KEEP", self.root + "/OUT/other"],
            dry_run=False)
        self.assertEqual(len(failed), 1)
        self.assertEqual(len(moved), 1)
        self.assertFalse(os.path.isdir(self.root + "/OUT/other"))

    def test_unprotected_paths_still_stage(self):
        moved, failed = actions.stage(
            self.root, [self.root + "/OUT/other"], dry_run=False)
        self.assertEqual(failed, [])
        self.assertEqual(len(moved), 1)
        self.assertFalse(os.path.isdir(self.root + "/OUT/other"))


if __name__ == "__main__":
    unittest.main()
