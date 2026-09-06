"""
Staging and restore -- step 5.

This is the most destructive code in the project: it moves real folders. The
tests are correspondingly paranoid, and most of them are about what must NOT
happen rather than what should.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import actions
from test_scanner import write


class StagingCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_stage_").replace(
            "\\", "/")
        write(self.root + "/tex/keep.exr", b"k" * 2048)
        write(self.root + "/render/v01/f.0001.exr", b"a" * 1024)
        write(self.root + "/render/v01/f.0002.exr", b"b" * 1024)
        write(self.root + "/tmp/junk.tmp", b"j" * 512)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def staged(self, *parts):
        return "/".join([actions.staging_dir(self.root)] + list(parts))

    def exists(self, relative):
        return os.path.exists(self.root + "/" + relative)


class TestDryRun(StagingCase):

    def test_dry_run_moves_nothing(self):
        moved, failed = actions.stage(self.root, [self.root + "/tmp"])
        self.assertEqual(len(moved), 1)
        self.assertEqual(failed, [])
        self.assertTrue(self.exists("tmp/junk.tmp"))
        self.assertFalse(os.path.isdir(actions.staging_dir(self.root)))

    def test_dry_run_is_the_default(self):
        actions.stage(self.root, [self.root + "/tmp"])
        self.assertTrue(self.exists("tmp/junk.tmp"),
                        "stage must not move anything unless asked")


class TestStage(StagingCase):

    def test_moves_the_folder(self):
        moved, failed = actions.stage(self.root, [self.root + "/tmp"],
                                      dry_run=False)
        self.assertEqual(failed, [])
        self.assertEqual(len(moved), 1)
        self.assertFalse(self.exists("tmp"))
        self.assertTrue(os.path.isfile(self.staged("tmp", "junk.tmp")))

    def test_relative_layout_is_preserved(self):
        # render/v01 must land at _toDelete/render/v01, not _toDelete/v01 --
        # otherwise two folders called v01 collide and a restore cannot tell
        # them apart.
        actions.stage(self.root, [self.root + "/render/v01"], dry_run=False)
        self.assertTrue(os.path.isfile(
            self.staged("render", "v01", "f.0001.exr")))

    def test_nothing_else_is_touched(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        self.assertTrue(self.exists("tex/keep.exr"))
        self.assertTrue(self.exists("render/v01/f.0001.exr"))

    def test_manifest_records_the_move(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        entries = actions.read_manifest(self.root)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]["from"].endswith("/tmp"))
        self.assertIn(actions.STAGING, entries[0]["to"])

    def test_second_run_appends_to_the_manifest(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        actions.stage(self.root, [self.root + "/render/v01"], dry_run=False)
        self.assertEqual(len(actions.read_manifest(self.root)), 2)


class TestRefusals(StagingCase):
    """Every one of these is a way to lose work."""

    def test_refuses_the_project_root(self):
        moved, failed = actions.stage(self.root, [self.root], dry_run=False)
        self.assertEqual(moved, [])
        self.assertEqual(len(failed), 1)
        self.assertTrue(self.exists("tex/keep.exr"))

    def test_refuses_a_path_outside_the_project(self):
        outside = tempfile.mkdtemp(prefix="archiver_outside_").replace(
            "\\", "/")
        try:
            write(outside + "/precious.exr")
            moved, failed = actions.stage(self.root, [outside],
                                          dry_run=False)
            self.assertEqual(moved, [])
            self.assertIn("outside", failed[0][1])
            self.assertTrue(os.path.isfile(outside + "/precious.exr"))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_refuses_a_sibling_with_a_shared_prefix(self):
        # "<root>_backup" starts with the root string but is a different
        # folder. A plain startswith without the separator would stage it.
        sibling = self.root + "_backup"
        os.makedirs(sibling)
        try:
            write(sibling + "/other.exr")
            moved, failed = actions.stage(self.root, [sibling],
                                          dry_run=False)
            self.assertEqual(moved, [])
            self.assertTrue(os.path.isfile(sibling + "/other.exr"))
        finally:
            shutil.rmtree(sibling, ignore_errors=True)

    def test_refuses_the_staging_folder_itself(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        moved, failed = actions.stage(
            self.root, [actions.staging_dir(self.root)], dry_run=False)
        self.assertEqual(moved, [])
        self.assertIn("already staged", failed[0][1])

    def test_refuses_something_already_staged(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        moved, failed = actions.stage(self.root, [self.staged("tmp")],
                                      dry_run=False)
        self.assertEqual(moved, [])

    def test_missing_path_is_reported_not_raised(self):
        moved, failed = actions.stage(self.root, [self.root + "/gone"],
                                      dry_run=False)
        self.assertEqual(moved, [])
        self.assertIn("no longer", failed[0][1])

    def test_a_failure_does_not_stop_the_rest(self):
        moved, failed = actions.stage(
            self.root, [self.root + "/gone", self.root + "/tmp"],
            dry_run=False)
        self.assertEqual(len(moved), 1)
        self.assertEqual(len(failed), 1)
        self.assertTrue(os.path.isfile(self.staged("tmp", "junk.tmp")))


class TestCollisions(StagingCase):

    def test_staging_the_same_name_twice_does_not_overwrite(self):
        # Stage tmp/, recreate it, stage again. The first one must survive.
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        write(self.root + "/tmp/second.tmp", b"2" * 64)
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)

        self.assertTrue(os.path.isfile(self.staged("tmp", "junk.tmp")))
        self.assertTrue(os.path.isfile(self.staged("tmp__1", "second.tmp")))


class TestRestore(StagingCase):

    def test_restores_to_the_original_place(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        restored, failed = actions.restore(self.root, dry_run=False)

        self.assertEqual(failed, [])
        self.assertEqual(len(restored), 1)
        self.assertTrue(self.exists("tmp/junk.tmp"))

    def test_dry_run_restores_nothing(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        actions.restore(self.root)
        self.assertFalse(self.exists("tmp"))

    def test_restore_works_from_the_manifest_alone(self):
        # No scan, no app state -- just the folder on disk. This is what
        # makes a restore possible tomorrow rather than only in this session.
        actions.stage(self.root, [self.root + "/render/v01"], dry_run=False)
        entries = actions.read_manifest(self.root)
        self.assertEqual(len(entries), 1)

        actions.restore(self.root, dry_run=False)
        self.assertTrue(self.exists("render/v01/f.0001.exr"))

    def test_refuses_when_the_destination_exists_again(self):
        # Something was recreated there since staging. Merging two versions
        # of a folder silently is exactly the damage to avoid.
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        write(self.root + "/tmp/new.tmp", b"n" * 32)

        restored, failed = actions.restore(self.root, dry_run=False)
        self.assertEqual(restored, [])
        self.assertEqual(len(failed), 1)
        self.assertTrue(os.path.isfile(self.staged("tmp", "junk.tmp")),
                        "the staged copy was destroyed by a refused restore")
        self.assertTrue(self.exists("tmp/new.tmp"))

    def test_manifest_is_emptied_after_a_full_restore(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        actions.restore(self.root, dry_run=False)
        self.assertEqual(actions.read_manifest(self.root), [])

    def test_a_refused_entry_stays_in_the_manifest(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        write(self.root + "/tmp/new.tmp")
        actions.restore(self.root, dry_run=False)
        self.assertEqual(len(actions.read_manifest(self.root)), 1)

    def test_staging_folder_disappears_when_emptied(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        actions.restore(self.root, dry_run=False)
        self.assertFalse(os.path.isdir(actions.staging_dir(self.root)),
                         "empty staging scaffolding was left behind")

    def test_scaffolding_is_pruned_but_occupied_folders_survive(self):
        actions.stage(self.root, [self.root + "/render/v01"], dry_run=False)
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)

        entries = [e for e in actions.read_manifest(self.root)
                   if e["from"].endswith("v01")]
        actions.restore(self.root, entries, dry_run=False)

        self.assertTrue(self.exists("render/v01/f.0001.exr"))
        self.assertTrue(os.path.isfile(self.staged("tmp", "junk.tmp")))


class TestManifestRobustness(StagingCase):

    def test_missing_manifest_reads_as_empty(self):
        self.assertEqual(actions.read_manifest(self.root), [])

    def test_corrupt_manifest_does_not_raise(self):
        os.makedirs(actions.staging_dir(self.root))
        with open(actions.manifest_path(self.root), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json at all")
        self.assertEqual(actions.read_manifest(self.root), [])

    def test_malformed_entry_is_reported(self):
        os.makedirs(actions.staging_dir(self.root))
        with open(actions.manifest_path(self.root), "w",
                  encoding="utf-8") as handle:
            json.dump({"moved": [{"to": "", "from": ""}]}, handle)
        restored, failed = actions.restore(self.root, dry_run=False)
        self.assertEqual(restored, [])
        self.assertEqual(len(failed), 1)


class TestStagedSize(StagingCase):

    def test_reports_what_is_staged(self):
        actions.stage(self.root, [self.root + "/render/v01"], dry_run=False)
        self.assertEqual(actions.staged_size(self.root), 2048)

    def test_manifest_is_not_counted(self):
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        self.assertEqual(actions.staged_size(self.root), 512)

    def test_zero_when_nothing_staged(self):
        self.assertEqual(actions.staged_size(self.root), 0)


if __name__ == "__main__":
    unittest.main()
