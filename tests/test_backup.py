"""
Step 6: copying the project out.

Less dangerous than staging -- this only ever copies, so the original survives
whatever happens -- but the refusals still matter, because copying a folder
into itself fills a disk and a truncated archive is worse than none.
"""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import actions, backup
from test_scanner import write


class BackupCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_bk_").replace("\\", "/")
        self.dest = tempfile.mkdtemp(prefix="archiver_dest_").replace(
            "\\", "/")
        write(self.root + "/tex/wood.exr", b"w" * 4096)
        write(self.root + "/tex/metal.exr", b"m" * 2048)
        write(self.root + "/scenes/shot.hip", b"h" * 1024)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.dest, ignore_errors=True)

    def out(self, *parts):
        name = os.path.basename(self.root)
        return "/".join([self.dest, name] + list(parts))


class TestPlan(BackupCase):

    def test_lists_every_file(self):
        p = backup.plan(self.root, self.dest)
        self.assertEqual(p.count, 3)
        self.assertEqual(p.total_bytes, 4096 + 2048 + 1024)
        self.assertEqual(p.problems, [])

    def test_relative_paths_are_kept(self):
        p = backup.plan(self.root, self.dest)
        relatives = sorted(rel for _full, rel in p.files)
        self.assertEqual(relatives,
                         ["scenes/shot.hip", "tex/metal.exr", "tex/wood.exr"])

    def test_staging_is_excluded_and_measured(self):
        # _toDelete holds what you already decided against. It must not be
        # archived, and the UI needs its size to say what is being left.
        write(self.root + "/tmp/junk.tmp", b"j" * 512)
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)

        p = backup.plan(self.root, self.dest)
        self.assertEqual(p.count, 3)
        self.assertTrue(all("_toDelete" not in rel for _f, rel in p.files))

        # Exactly the staged file, and not the manifest sitting beside it.
        # Pruning the walk at the top of _toDelete counted only the manifest,
        # so the "leaving behind" figure was wrong by whatever was staged.
        self.assertEqual(p.skipped_bytes, 512)
        self.assertEqual(p.skipped_files, 1)

    def test_junk_files_are_skipped(self):
        write(self.root + "/Thumbs.db", b"x" * 64)
        write(self.root + "/tex/.DS_Store", b"x" * 64)
        p = backup.plan(self.root, self.dest)
        self.assertEqual(p.count, 3)

    def test_vcs_folders_are_skipped(self):
        write(self.root + "/.git/config", b"x" * 64)
        self.assertEqual(backup.plan(self.root, self.dest).count, 3)


class TestRefusals(BackupCase):
    """Each of these would otherwise fill a disk or lose the project."""

    def test_destination_inside_the_project(self):
        p = backup.plan(self.root, self.root + "/archive")
        self.assertTrue(p.problems)
        self.assertIn("inside the project", p.problems[0])

    def test_destination_is_the_project(self):
        p = backup.plan(self.root, self.root)
        self.assertTrue(p.problems)

    def test_missing_source(self):
        p = backup.plan(self.root + "/nope", self.dest)
        self.assertTrue(p.problems)

    def test_empty_project(self):
        empty = tempfile.mkdtemp(prefix="archiver_empty_")
        try:
            p = backup.plan(empty, self.dest)
            self.assertTrue(p.problems)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_run_refuses_a_plan_with_problems(self):
        p = backup.plan(self.root, self.root + "/inside")
        copied, failed = backup.run(p)
        self.assertEqual(copied, [])
        self.assertTrue(failed)

    def test_sibling_with_a_shared_prefix_is_allowed(self):
        # "<root>_archive" is a different folder, not inside the project. A
        # naive prefix test would refuse a perfectly good destination.
        sibling = self.root + "_archive"
        os.makedirs(sibling)
        try:
            p = backup.plan(self.root, sibling)
            self.assertEqual(p.problems, [])
        finally:
            shutil.rmtree(sibling, ignore_errors=True)


class TestCopy(BackupCase):

    def test_copies_under_a_folder_named_for_the_project(self):
        # Copying the contents bare would scatter the project across whatever
        # else is at the destination.
        p = backup.plan(self.root, self.dest)
        backup.run(p)
        self.assertTrue(os.path.isfile(self.out("tex", "wood.exr")))

    def test_content_survives_intact(self):
        p = backup.plan(self.root, self.dest)
        backup.run(p)
        with open(self.out("tex", "wood.exr"), "rb") as handle:
            self.assertEqual(handle.read(), b"w" * 4096)

    def test_original_is_untouched(self):
        p = backup.plan(self.root, self.dest)
        backup.run(p)
        self.assertTrue(os.path.isfile(self.root + "/tex/wood.exr"))
        self.assertTrue(os.path.isfile(self.root + "/scenes/shot.hip"))

    def test_mtimes_are_preserved(self):
        # An archive should still look like the project, not like the day it
        # was archived.
        source = self.root + "/tex/wood.exr"
        os.utime(source, (100000, 100000))
        p = backup.plan(self.root, self.dest)
        backup.run(p)
        self.assertAlmostEqual(os.path.getmtime(self.out("tex", "wood.exr")),
                               100000, delta=2)

    def test_reports_what_was_copied(self):
        copied, failed = backup.run(backup.plan(self.root, self.dest))
        self.assertEqual(len(copied), 3)
        self.assertEqual(failed, [])

    def test_progress_can_cancel(self):
        seen = []

        def stop_after_one(index, total, relative):
            seen.append(relative)
            return len(seen) < 1

        copied, _failed = backup.run(backup.plan(self.root, self.dest),
                                     stop_after_one)
        self.assertEqual(copied, [])


class TestZip(BackupCase):

    def test_creates_a_zip(self):
        p = backup.plan(self.root, self.dest, as_zip=True)
        copied, failed = backup.run(p)
        self.assertEqual(failed, [])
        self.assertTrue(os.path.isfile(backup.zip_path(p)))

    def test_zip_holds_every_file_under_the_project_name(self):
        p = backup.plan(self.root, self.dest, as_zip=True)
        backup.run(p)
        with zipfile.ZipFile(backup.zip_path(p)) as archive:
            names = archive.namelist()
        self.assertEqual(len(names), 3)
        self.assertTrue(all(n.startswith(p.name + "/") for n in names))

    def test_zip_content_is_correct(self):
        p = backup.plan(self.root, self.dest, as_zip=True)
        backup.run(p)
        with zipfile.ZipFile(backup.zip_path(p)) as archive:
            data = archive.read(p.name + "/tex/wood.exr")
        self.assertEqual(data, b"w" * 4096)

    def test_zip_excludes_staging(self):
        write(self.root + "/tmp/junk.tmp", b"j" * 512)
        actions.stage(self.root, [self.root + "/tmp"], dry_run=False)
        p = backup.plan(self.root, self.dest, as_zip=True)
        backup.run(p)
        with zipfile.ZipFile(backup.zip_path(p)) as archive:
            self.assertTrue(all("_toDelete" not in n
                                for n in archive.namelist()))


class TestVerify(BackupCase):

    def test_clean_copy_verifies(self):
        p = backup.plan(self.root, self.dest)
        backup.run(p)
        self.assertEqual(backup.verify(p), [])

    def test_missing_file_is_caught(self):
        p = backup.plan(self.root, self.dest)
        backup.run(p)
        os.remove(self.out("tex", "wood.exr"))
        problems = backup.verify(p)
        self.assertEqual(len(problems), 1)
        self.assertIn("missing", problems[0][1])

    def test_truncated_file_is_caught(self):
        # The failure a size check exists for: a copy that died part way.
        p = backup.plan(self.root, self.dest)
        backup.run(p)
        with open(self.out("tex", "wood.exr"), "wb") as handle:
            handle.write(b"w" * 10)
        problems = backup.verify(p)
        self.assertEqual(len(problems), 1)
        self.assertIn("size", problems[0][1])

    def test_zip_verifies(self):
        p = backup.plan(self.root, self.dest, as_zip=True)
        backup.run(p)
        self.assertEqual(backup.verify(p), [])


class TestFreeSpace(BackupCase):

    def test_reads_the_volume_of_a_path_that_does_not_exist_yet(self):
        # The destination is usually a folder about to be created.
        free = backup.free_space(self.dest + "/not/there/yet")
        self.assertIsNotNone(free)
        self.assertGreater(free, 0)


if __name__ == "__main__":
    unittest.main()
