"""
The asset sidecar: its shape, and above all its freshness rule.

Freshness is the safety boundary. A sidecar that wrongly reads as fresh lets
the scanner promote a cache to DROP on stale evidence, which is how this tool
would delete a live 3 GB file. Every ambiguous case here must land on stale.
"""

import json
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import sidecar


class SidecarTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_sidecar_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def scene(self, name="shot.c4d", mtime=None):
        path = os.path.join(self.root, name)
        with open(path, "wb") as handle:
            handle.write(b"QC4DC4D6" + b"\x00" * 256)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def touch(self, path, when):
        os.utime(path, (when, when))


class TestPathing(SidecarTestCase):
    def test_sidecar_sits_beside_the_scene_keeping_the_extension(self):
        self.assertTrue(
            sidecar.sidecar_path(r"C:\job\shot.c4d").endswith(
                r"shot.c4d.assets.json"))

    def test_two_scenes_sharing_a_stem_do_not_share_a_sidecar(self):
        # shot.c4d and shot.hip in one folder is ordinary. Naming the sidecar
        # off the stem alone would give them one file between them.
        self.assertNotEqual(sidecar.sidecar_path(r"C:\job\shot.c4d"),
                            sidecar.sidecar_path(r"C:\job\shot.hip"))

    def test_a_sidecar_is_recognised_as_one(self):
        self.assertTrue(sidecar.is_sidecar(r"C:\job\shot.c4d.assets.json"))
        self.assertTrue(sidecar.is_sidecar(r"C:\job\SHOT.C4D.ASSETS.JSON"))
        self.assertFalse(sidecar.is_sidecar(r"C:\job\shot.c4d"))


class TestBuild(SidecarTestCase):
    def test_duplicates_collapse_case_insensitively(self):
        payload = sidecar.build(
            self.scene(),
            [r"C:\tex\wood.png", r"c:\TEX\Wood.png", r"C:\tex\metal.png"])
        self.assertEqual(len(payload["assets"]), 2)

    def test_blanks_are_dropped(self):
        payload = sidecar.build(self.scene(), ["", "   ", None, r"C:\a.png"])
        self.assertEqual(payload["assets"], [r"C:\a.png"])

    def test_separators_normalize_to_windows(self):
        payload = sidecar.build(self.scene(), ["C:/tex/wood.png"])
        self.assertEqual(payload["assets"], [r"C:\tex\wood.png"])

    def test_a_percent_sign_in_a_filename_survives(self):
        # Iris hit this: round-tripping through a URL form mangles real
        # filenames. The sidecar stores what the app said, verbatim.
        payload = sidecar.build(self.scene(), [r"C:\tex\100%_rough.png"])
        self.assertEqual(payload["assets"], [r"C:\tex\100%_rough.png"])

    def test_records_the_scene_mtime_it_saw(self):
        scene = self.scene(mtime=1_000_000)
        payload = sidecar.build(scene, [])
        self.assertAlmostEqual(payload["scene_mtime"], 1_000_000, places=1)


class TestRoundTrip(SidecarTestCase):
    def test_written_assets_read_back(self):
        scene = self.scene()
        sidecar.write(scene, [r"C:\tex\wood.png", r"C:\cache\sim.abc"],
                      app="Cinema 4D", app_version="2026.1")
        assets, fresh = sidecar.read(scene)
        self.assertEqual(assets, [r"C:\tex\wood.png", r"C:\cache\sim.abc"])
        self.assertTrue(fresh)

    def test_no_sidecar_reads_as_absent_not_empty(self):
        # None and [] mean opposite things: "no evidence" versus "nothing is
        # referenced". Confusing them is how a live file looks unused.
        assets, fresh = sidecar.read(self.scene())
        self.assertIsNone(assets)
        self.assertFalse(fresh)

    def test_a_scene_with_genuinely_no_assets_reads_as_empty_not_absent(self):
        scene = self.scene()
        sidecar.write(scene, [])
        assets, fresh = sidecar.read(scene)
        self.assertEqual(assets, [])
        self.assertIsNotNone(assets)

    def test_no_temp_file_is_left_behind(self):
        scene = self.scene()
        sidecar.write(scene, [r"C:\a.png"])
        leftovers = [n for n in os.listdir(self.root) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class TestMalformed(SidecarTestCase):
    def write_raw(self, scene, text):
        with open(sidecar.sidecar_path(scene), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_truncated_json_reads_as_absent(self):
        scene = self.scene()
        self.write_raw(scene, '{"format": 1, "assets": ["C:\\\\a.png"')
        self.assertEqual(sidecar.read(scene), (None, False))

    def test_a_newer_format_is_refused_rather_than_guessed(self):
        scene = self.scene()
        self.write_raw(scene, json.dumps(
            {"format": sidecar.FORMAT_VERSION + 1, "assets": ["C:\\a.png"]}))
        self.assertEqual(sidecar.read(scene), (None, False))

    def test_assets_of_the_wrong_type_read_as_absent(self):
        scene = self.scene()
        self.write_raw(scene, json.dumps({"format": 1, "assets": "nope"}))
        self.assertEqual(sidecar.read(scene), (None, False))

    def test_a_bare_list_is_not_a_sidecar(self):
        scene = self.scene()
        self.write_raw(scene, json.dumps(["C:\\a.png"]))
        self.assertEqual(sidecar.read(scene), (None, False))


class TestFreshness(SidecarTestCase):
    """The rule that decides whether a scene stays opaque."""

    def test_exported_now_is_fresh(self):
        scene = self.scene()
        sidecar.write(scene, [r"C:\a.png"])
        self.assertTrue(sidecar.read(scene)[1])

    def test_a_scene_saved_after_the_export_is_stale(self):
        scene = self.scene(mtime=1_000_000)
        sidecar.write(scene, [r"C:\a.png"])
        self.touch(sidecar.sidecar_path(scene), 1_000_000)
        self.touch(scene, 1_000_500)          # saved again, sidecar not redone
        self.assertFalse(sidecar.read(scene)[1])

    def test_a_scene_rolled_back_to_an_older_version_is_stale(self):
        # The case a file-time comparison alone gets WRONG: restore an older
        # scene and it is older than the sidecar, so mtimes say "fresh" -- but
        # it is not the scene that was exported.
        scene = self.scene(mtime=1_000_000)
        sidecar.write(scene, [r"C:\a.png"])
        self.touch(sidecar.sidecar_path(scene), 1_000_000)
        self.touch(scene, 900_000)
        self.assertFalse(sidecar.read(scene)[1])

    def test_a_sidecar_copied_from_another_machine_is_stale(self):
        # Recorded mtime matches, but the sidecar file itself predates the
        # scene on this disk.
        scene = self.scene(mtime=1_000_000)
        sidecar.write(scene, [r"C:\a.png"])
        self.touch(sidecar.sidecar_path(scene), 900_000)
        self.touch(scene, 1_000_000)
        self.assertFalse(sidecar.read(scene)[1])

    def test_a_save_within_tolerance_stays_fresh(self):
        # Writing the sidecar happens a moment after the scene's mtime is
        # read; a strict comparison would call every export stale on arrival.
        scene = self.scene(mtime=1_000_000)
        sidecar.write(scene, [r"C:\a.png"])
        self.touch(sidecar.sidecar_path(scene), 1_000_001)
        self.touch(scene, 1_000_000)
        self.assertTrue(sidecar.read(scene)[1])

    def test_stale_still_returns_its_assets(self):
        # Stale is not worthless. The paths still count toward KEEP; it is
        # only the promotion to DROP that they may not support.
        scene = self.scene(mtime=1_000_000)
        sidecar.write(scene, [r"C:\cache\sim.abc"])
        self.touch(sidecar.sidecar_path(scene), 1_000_000)
        self.touch(scene, 2_000_000)
        assets, fresh = sidecar.read(scene)
        self.assertEqual(assets, [r"C:\cache\sim.abc"])
        self.assertFalse(fresh)

    def test_a_vanished_scene_is_never_fresh(self):
        scene = self.scene()
        sidecar.write(scene, [r"C:\a.png"])
        os.remove(scene)
        self.assertFalse(sidecar.read(scene)[1])


if __name__ == "__main__":
    unittest.main()
