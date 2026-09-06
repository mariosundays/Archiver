"""
The writing paths. This is the only part of the tool that destroys anything,
so these tests carry more weight than the rest of the suite.
"""

import json
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


class TestScanReport(unittest.TestCase):
    """
    The report is written at the project root after a scan -- but by an
    explicit call, never by the scan itself. That separation is what keeps
    "scanning costs you nothing" true and testable.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_rep_").replace("\\", "/")
        write(self.root + "/tex/a.exr", b"k" * 1024)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_scanning_alone_writes_nothing(self):
        scanner.scan(self.root)
        self.assertFalse(os.path.exists(actions.report_path(self.root)),
                         "the scan wrote a report by itself")

    def test_dry_run_writes_nothing(self):
        actions.write_report(self.root, {"a": 1})
        self.assertFalse(os.path.exists(actions.report_path(self.root)))

    def test_writes_at_the_project_root(self):
        path, error = actions.write_report(self.root, {"a": 1},
                                           dry_run=False)
        self.assertIsNone(error)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.dirname(path), self.root)
        self.assertTrue(os.path.basename(path).startswith("."))

    def test_content_round_trips(self):
        data = {"root": self.root, "folders": [{"path": "tex"}]}
        actions.write_report(self.root, data, dry_run=False)
        with open(actions.report_path(self.root), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), data)

    def test_rewriting_replaces_cleanly(self):
        actions.write_report(self.root, {"n": 1}, dry_run=False)
        actions.write_report(self.root, {"n": 2}, dry_run=False)
        with open(actions.report_path(self.root), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["n"], 2)
        # No temporary left behind.
        self.assertFalse(os.path.exists(
            actions.report_path(self.root) + ".tmp"))

    def test_a_missing_project_is_reported_not_raised(self):
        _path, error = actions.write_report(self.root + "/gone", {"a": 1},
                                            dry_run=False)
        self.assertIsNotNone(error)

    def test_unserialisable_data_leaves_no_wreckage(self):
        actions.write_report(self.root, {"n": 1}, dry_run=False)
        _path, error = actions.write_report(self.root, {"bad": object()},
                                            dry_run=False)
        self.assertIsNotNone(error)
        # The good report survives, and no .tmp is orphaned.
        with open(actions.report_path(self.root), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["n"], 1)
        self.assertFalse(os.path.exists(
            actions.report_path(self.root) + ".tmp"))

    def test_the_report_is_not_scanned_as_project_content(self):
        actions.write_report(self.root, {"a": 1}, dry_run=False)
        result = scanner.scan(self.root)
        for folder in result.folders:
            for entry in folder.entries:
                self.assertNotIn(actions.REPORT, entry.path)

    def test_the_report_does_not_grow_the_file_count(self):
        before = scanner.scan(self.root).total_files
        actions.write_report(self.root, {"a": 1}, dry_run=False)
        self.assertEqual(scanner.scan(self.root).total_files, before)


if __name__ == "__main__":
    unittest.main()
