"""
The c4d-free half of the Cinema 4D export.

This exists because the plugin itself cannot be run here: testing a change in
the .pyp costs a C4D restart and a report back from Mario. So every decision
worth getting wrong lives in core/c4d_assets.py and is pinned down here.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import c4d_assets


class TestAssetPaths(unittest.TestCase):
    """Turning whatever GetAllAssetsNew returned into a list of paths."""

    def test_the_documented_dict_shape(self):
        assets = [{"filename": r"C:\job\tex\wood.png", "assetname": "wood",
                   "owner": None, "exists": True}]
        self.assertEqual(c4d_assets.asset_paths(assets),
                         [r"C:\job\tex\wood.png"])

    def test_a_missing_asset_is_still_recorded(self):
        # "The scene wants a file that is not there" is worth knowing. Silently
        # dropping it turns a broken reference into no reference.
        assets = [{"filename": r"C:\job\tex\gone.png", "exists": False}]
        self.assertEqual(c4d_assets.asset_paths(assets),
                         [r"C:\job\tex\gone.png"])

    def test_plain_strings_are_accepted(self):
        self.assertEqual(c4d_assets.asset_paths([r"C:\job\tex\wood.png"]),
                         [r"C:\job\tex\wood.png"])

    def test_an_object_with_attributes_is_accepted(self):
        class Entry(object):
            filename = r"C:\job\tex\wood.png"
        self.assertEqual(c4d_assets.asset_paths([Entry()]),
                         [r"C:\job\tex\wood.png"])

    def test_assetname_is_the_fallback(self):
        self.assertEqual(
            c4d_assets.asset_paths([{"assetname": r"C:\job\tex\a.png"}]),
            [r"C:\job\tex\a.png"])

    def test_unusable_entries_are_skipped_not_guessed(self):
        assets = [{"owner": "x"}, None, 42, {"filename": "  "},
                  {"filename": r"C:\job\tex\good.png"}]
        self.assertEqual(c4d_assets.asset_paths(assets),
                         [r"C:\job\tex\good.png"])

    def test_empty_input_gives_an_empty_list_not_a_crash(self):
        self.assertEqual(c4d_assets.asset_paths(None), [])
        self.assertEqual(c4d_assets.asset_paths([]), [])

    def test_duplicates_collapse_case_insensitively(self):
        assets = [{"filename": r"C:\job\tex\wood.png"},
                  {"filename": r"c:\JOB\tex\Wood.png"}]
        self.assertEqual(len(c4d_assets.asset_paths(assets)), 1)

    def test_the_scene_is_not_its_own_asset(self):
        scene = r"C:\job\scenes\shot.c4d"
        assets = [{"filename": scene}, {"filename": r"C:\job\tex\a.png"}]
        self.assertEqual(c4d_assets.asset_paths(assets, scene),
                         [r"C:\job\tex\a.png"])

    def test_the_scene_is_matched_regardless_of_separator_or_case(self):
        assets = [{"filename": "C:/JOB/scenes/Shot.c4d"}]
        self.assertEqual(
            c4d_assets.asset_paths(assets, r"C:\job\scenes\shot.c4d"), [])

    def test_an_xref_scene_is_left_to_the_scanner(self):
        # A referenced .c4d is found and read as a scene in its own right, so
        # recording it here would only double-count it.
        assets = [{"filename": r"C:\job\scenes\prop.c4d"},
                  {"filename": r"C:\job\lib\kit.lib4d"},
                  {"filename": r"C:\job\tex\a.png"}]
        self.assertEqual(c4d_assets.asset_paths(assets),
                         [r"C:\job\tex\a.png"])

    def test_order_is_preserved(self):
        assets = [{"filename": r"C:\b.png"}, {"filename": r"C:\a.png"}]
        self.assertEqual(c4d_assets.asset_paths(assets),
                         [r"C:\b.png", r"C:\a.png"])


class TestFindScenes(unittest.TestCase):
    """Which scenes a batch run should open, which is the slow part."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_find_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, relative):
        path = os.path.join(self.root, relative.replace("/", os.sep))
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        open(path, "wb").close()
        return path

    def names(self, **kwargs):
        return sorted(os.path.basename(p)
                      for p in c4d_assets.find_scenes(self.root, **kwargs))

    def test_finds_scenes_at_every_depth(self):
        self.make("shot_a.c4d")
        self.make("scenes/shot_b.c4d")
        self.make("scenes/shots/shot_c.c4d")
        self.assertEqual(self.names(),
                         ["shot_a.c4d", "shot_b.c4d", "shot_c.c4d"])

    def test_non_recursive_stays_in_the_folder(self):
        self.make("shot_a.c4d")
        self.make("scenes/shot_b.c4d")
        self.assertEqual(self.names(recursive=False), ["shot_a.c4d"])

    def test_other_files_are_ignored(self):
        self.make("shot.c4d")
        self.make("tex/wood.png")
        self.make("lib/kit.lib4d")
        self.assertEqual(self.names(), ["shot.c4d"])

    def test_backups_are_not_opened(self):
        # Opening a scene is the expensive step and a backup's asset list is
        # never acted on -- backups drop by category, not by reference.
        self.make("shot.c4d")
        self.make("shot_bak.c4d")
        self.make("shot.bak.c4d")
        self.make("backup/shot.c4d")
        self.assertEqual(self.names(), ["shot.c4d"])

    def test_the_staging_folder_is_skipped(self):
        # _toDelete holds things already decided against; re-reading them
        # would resurrect their assets as "referenced".
        self.make("shot.c4d")
        self.make("_toDelete/scenes/old.c4d")
        self.assertEqual(self.names(), ["shot.c4d"])

    def test_results_are_sorted_so_a_run_is_reproducible(self):
        self.make("z.c4d")
        self.make("a.c4d")
        found = c4d_assets.find_scenes(self.root)
        self.assertEqual(found, sorted(found))

    def test_an_empty_folder_is_not_an_error(self):
        self.assertEqual(c4d_assets.find_scenes(self.root), [])


class TestSummary(unittest.TestCase):
    """The message Mario reads after a batch run."""

    def test_counts_scenes_and_assets(self):
        text = c4d_assets.summarize([
            (r"C:\job\a.c4d", 3, None),
            (r"C:\job\b.c4d", 5, None)])
        self.assertIn("Exported 2 scenes, 8 assets", text)
        self.assertNotIn("FAILED", text)

    def test_failures_are_reported_not_hidden(self):
        text = c4d_assets.summarize([
            (r"C:\job\a.c4d", 3, None),
            (r"C:\job\b.c4d", 0, "could not load")])
        self.assertIn("1 FAILED", text)
        self.assertIn("could not load", text)
        self.assertIn("Exported 1 scene,", text)

    def test_every_scene_is_listed(self):
        text = c4d_assets.summarize([
            (r"C:\job\a.c4d", 1, None), (r"C:\job\b.c4d", 2, None)])
        self.assertIn("a.c4d", text)
        self.assertIn("b.c4d", text)

    def test_singulars_read_correctly(self):
        text = c4d_assets.summarize([(r"C:\job\a.c4d", 1, None)])
        self.assertIn("Exported 1 scene, 1 asset", text)

    def test_nothing_to_do_is_not_a_crash(self):
        self.assertIn("Exported 0 scenes", c4d_assets.summarize([]))


if __name__ == "__main__":
    unittest.main()
