"""
The writing paths. This is the only part of the tool that destroys anything,
so these tests carry more weight than the rest of the suite.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import actions, scanner
from test_scanner import write


class PruneCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_prune_").replace("\\", "/")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def scan(self):
        return scanner.scan(self.root)


class TestDryRun(PruneCase):

    def test_dry_run_removes_nothing(self):
        os.makedirs(self.root + "/empty_a")
        os.makedirs(self.root + "/empty_b")
        write(self.root + "/tex/a.exr")

        removed, failed = actions.prune_empty_folders(self.scan())

        self.assertEqual(len(removed), 2)
        self.assertEqual(failed, [])
        # Still there -- that is the whole point of a dry run.
        self.assertTrue(os.path.isdir(self.root + "/empty_a"))
        self.assertTrue(os.path.isdir(self.root + "/empty_b"))

    def test_dry_run_is_the_default(self):
        os.makedirs(self.root + "/gone")
        actions.prune_empty_folders(self.scan())
        self.assertTrue(os.path.isdir(self.root + "/gone"),
                        "prune must not delete unless asked")


class TestPrune(PruneCase):

    def test_removes_empty_folders(self):
        os.makedirs(self.root + "/empty_a")
        write(self.root + "/tex/a.exr")

        removed, failed = actions.prune_empty_folders(self.scan(),
                                                      dry_run=False)

        self.assertEqual(failed, [])
        self.assertFalse(os.path.isdir(self.root + "/empty_a"))
        self.assertTrue(os.path.isfile(self.root + "/tex/a.exr"))

    def test_nested_chain_collapses_fully(self):
        # A/B/C all empty: removing C is what makes B removable, and so on.
        os.makedirs(self.root + "/A/B/C")
        write(self.root + "/tex/a.exr")

        removed, failed = actions.prune_empty_folders(self.scan(),
                                                      dry_run=False)

        self.assertEqual(failed, [])
        self.assertFalse(os.path.isdir(self.root + "/A"))

    def test_folder_with_content_survives(self):
        os.makedirs(self.root + "/keep_me")
        write(self.root + "/keep_me/file.exr")
        actions.prune_empty_folders(self.scan(), dry_run=False)
        self.assertTrue(os.path.isfile(self.root + "/keep_me/file.exr"))

    def test_parent_of_a_full_folder_survives(self):
        # DOCS holds no files itself but NDA under it does.
        write(self.root + "/DOCS/NDA/contract.pdf")
        actions.prune_empty_folders(self.scan(), dry_run=False)
        self.assertTrue(os.path.isfile(self.root + "/DOCS/NDA/contract.pdf"))

    def test_project_root_is_never_removed(self):
        # An empty project would otherwise delete the folder out from under
        # the user.
        result = scanner.scan(self.root)
        result.empty_folders.append(self.root)
        actions.prune_empty_folders(result, dry_run=False)
        self.assertTrue(os.path.isdir(self.root))


class TestSafety(PruneCase):
    """What happens when the scan is stale."""

    def test_a_folder_filled_since_the_scan_is_refused(self):
        # The safety net: rmdir refuses a non-empty directory, so a file that
        # appeared after the scan survives and the failure is reported.
        os.makedirs(self.root + "/was_empty")
        write(self.root + "/tex/a.exr")
        result = self.scan()

        write(self.root + "/was_empty/appeared.exr")

        removed, failed = actions.prune_empty_folders(result, dry_run=False)

        self.assertTrue(os.path.isfile(self.root + "/was_empty/appeared.exr"),
                        "a file that appeared after the scan was destroyed")
        self.assertEqual(len(failed), 1)
        self.assertNotIn(self.root + "/was_empty", removed)

    def test_already_gone_is_reported_not_raised(self):
        os.makedirs(self.root + "/vanishing")
        result = self.scan()
        os.rmdir(self.root + "/vanishing")

        removed, failed = actions.prune_empty_folders(result, dry_run=False)
        self.assertEqual(len(failed), 1)

    def test_progress_can_cancel(self):
        for name in ("a", "b", "c", "d"):
            os.makedirs(self.root + "/" + name)
        result = self.scan()

        seen = []

        def stop_after_two(index, total, path):
            seen.append(path)
            return len(seen) < 2

        actions.prune_empty_folders(result, dry_run=False,
                                    progress=stop_after_two)
        remaining = [n for n in ("a", "b", "c", "d")
                     if os.path.isdir(self.root + "/" + n)]
        self.assertEqual(len(remaining), 3, "cancel did not stop the prune")


if __name__ == "__main__":
    unittest.main()
