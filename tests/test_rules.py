"""Category and verdict rules -- the judgement calls, tested directly."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules


ROOT = "D:/Projects/shot01"


class TestSegments(unittest.TestCase):

    def test_plain_names(self):
        self.assertEqual(rules.category_for_segment("render"),
                         rules.CAT_RENDER)
        self.assertEqual(rules.category_for_segment("tex"), rules.CAT_SOURCE)
        self.assertEqual(rules.category_for_segment("geo"), rules.CAT_CACHE)

    def test_order_prefix_stripped(self):
        # "05_render", "3_comp", "010_output" are the same convention.
        self.assertEqual(rules.category_for_segment("05_render"),
                         rules.CAT_RENDER)
        self.assertEqual(rules.category_for_segment("3_comp"), rules.CAT_COMP)

    def test_trailing_version_stripped(self):
        self.assertEqual(rules.category_for_segment("render_v02"),
                         rules.CAT_RENDER)
        self.assertEqual(rules.category_for_segment("comp2"), rules.CAT_COMP)

    def test_case_and_separators(self):
        self.assertEqual(rules.category_for_segment("Renders"),
                         rules.CAT_RENDER)
        self.assertEqual(rules.category_for_segment("FLIP-SIM"),
                         rules.CAT_CACHE)

    def test_near_miss_is_not_a_match(self):
        # The bug this guards: substring matching would call these outputs.
        self.assertIsNone(rules.category_for_segment("rendering_notes"))
        self.assertIsNone(rules.category_for_segment("reference_board"))

    def test_unknown_is_none(self):
        self.assertIsNone(rules.category_for_segment("shot_01_anim"))

    def test_compound_takes_the_last_word(self):
        # The last word is the noun; the rest qualify it.
        self.assertEqual(rules.category_for_segment("flip_sim"),
                         rules.CAT_CACHE)
        self.assertEqual(rules.category_for_segment("pyro_cache"),
                         rules.CAT_CACHE)
        self.assertEqual(rules.category_for_segment("rbd_sim"),
                         rules.CAT_CACHE)

    def test_compound_does_not_match_an_inner_word(self):
        # Scanning every word turns "rendering_notes" into docs and
        # "shot_01_anim" into scenes, matching on a word that was never the
        # subject. This is the regression that guards it.
        self.assertIsNone(rules.category_for_segment("rendering_notes"))
        self.assertIsNone(rules.category_for_segment("shot_01_anim"))
        self.assertIsNone(rules.category_for_segment("tex_wip_anim"))

    def test_ambiguous_tail_is_refused(self):
        # "cache_old" is an old cache, not a backup folder -- reading the
        # tail as the noun gets the meaning backwards.
        self.assertIsNone(rules.category_for_segment("cache_old"))
        self.assertIsNone(rules.category_for_segment("render_notes"))


class TestPathCategory(unittest.TestCase):

    def test_deepest_segment_wins(self):
        # The nearest folder is the most specific statement about the file.
        path = ROOT + "/render/v02/tex/wood.exr"
        self.assertEqual(rules.category_from_path(path, ROOT),
                         rules.CAT_SOURCE)

    def test_root_segments_ignored(self):
        # A project living under D:/renders must not call everything a render.
        root = "D:/renders/shot01"
        path = root + "/tex/wood.exr"
        self.assertEqual(rules.category_from_path(path, root),
                         rules.CAT_SOURCE)


class TestClassify(unittest.TestCase):

    def test_scene_anywhere(self):
        self.assertEqual(rules.classify(ROOT + "/tex/weird.hip", ROOT),
                         rules.CAT_SCENE)
        self.assertEqual(rules.classify(ROOT + "/scene.c4d", ROOT),
                         rules.CAT_SCENE)

    def test_backup_name_beats_folder(self):
        # A _bak.c4d in scenes/ is a backup, not a scene.
        self.assertEqual(rules.classify(ROOT + "/scenes/shot_bak.c4d", ROOT),
                         rules.CAT_BACKUP)
        self.assertEqual(rules.classify(ROOT + "/scenes/shot.hip.bak", ROOT),
                         rules.CAT_BACKUP)
        self.assertEqual(rules.classify(ROOT + "/scenes/shot.hip.3", ROOT),
                         rules.CAT_BACKUP)

    def test_folder_decides_ambiguous_media(self):
        # An .exr means nothing on its own; location is the whole signal.
        self.assertEqual(rules.classify(ROOT + "/render/beauty.0001.exr",
                                        ROOT), rules.CAT_RENDER)
        self.assertEqual(rules.classify(ROOT + "/tex/wood.exr", ROOT),
                         rules.CAT_SOURCE)

    def test_extension_wins_for_unambiguous(self):
        # A .vdb in tex/ is still a cache.
        self.assertEqual(rules.classify(ROOT + "/tex/smoke.vdb", ROOT),
                         rules.CAT_CACHE)

    def test_asset_names_are_not_read_as_backups(self):
        # Real false positives from a live project. Artists name textures
        # this way constantly, and treating the name as evidence offered
        # source material for deletion.
        for name in ("leather (32) copy.jpg",
                     "GSG_A007_KnittedFabricWhiteandNavy_preview.jpg",
                     "wood_old.jpg", "metal_bak.exr", "plate_temp.tif"):
            self.assertEqual(
                rules.classify(ROOT + "/tex/" + name, ROOT),
                rules.CAT_SOURCE,
                "%r was read as a backup on its name alone" % name)

    def test_preview_does_not_match_the_prev_hint(self):
        # "_prev" as a plain substring fired inside "_preview".
        self.assertFalse(rules.is_backup_name(ROOT + "/tex/x_preview.jpg"))
        self.assertFalse(rules.is_backup_name(ROOT + "/tex/previews.png"))

    def test_scene_names_still_count(self):
        # A scene called shot_old.hip really is an old scene, and the
        # applications write autosaves by mangling the name.
        for name in ("shot_old.hip", "shot_copy.c4d", "shot.hip.bak",
                     "shot.hip.3", "shot_bak.c4d"):
            self.assertTrue(rules.is_backup_name(ROOT + "/scenes/" + name),
                            "%r should read as a backup" % name)

    def test_a_backup_folder_still_decides(self):
        # Mario's rule: backups live in a folder called backup.
        self.assertEqual(rules.classify(ROOT + "/backup/leather.jpg", ROOT),
                         rules.CAT_BACKUP)
        self.assertEqual(rules.classify(ROOT + "/tmp/plate.exr", ROOT),
                         rules.CAT_TEMP)

    def test_scene_inside_a_backup_folder_is_a_backup(self):
        # A .hip in backup/ is a backup copy of a scene -- that is what the
        # folder is for. Treating it as a live scene made the whole backup
        # folder Keep, so "tick all Drop" silently skipped it.
        self.assertEqual(rules.classify(ROOT + "/backup/old.hip", ROOT),
                         rules.CAT_BACKUP)
        self.assertEqual(rules.classify(ROOT + "/tmp/scratch.hip", ROOT),
                         rules.CAT_TEMP)

    def test_scene_outside_those_folders_is_still_a_scene(self):
        self.assertEqual(rules.classify(ROOT + "/scenes/shot.hip", ROOT),
                         rules.CAT_SCENE)
        self.assertEqual(rules.classify(ROOT + "/shot.c4d", ROOT),
                         rules.CAT_SCENE)

    def test_backup_folder_swallows_contents(self):
        # ...but a backup folder outranks even that.
        self.assertEqual(rules.classify(ROOT + "/backup/smoke.vdb", ROOT),
                         rules.CAT_CACHE if False else rules.CAT_BACKUP)

    def test_loose_media_reads_as_source(self):
        # Unplaced media errs toward KEEP.
        self.assertEqual(rules.classify(ROOT + "/random.exr", ROOT),
                         rules.CAT_SOURCE)

    def test_texture_cache_is_a_cache(self):
        self.assertEqual(rules.classify(ROOT + "/tex/wood.rat", ROOT),
                         rules.CAT_CACHE)


class TestVersions(unittest.TestCase):

    def test_version_parsed(self):
        self.assertEqual(rules.version_of("cache_v003.bgeo"), 3)
        self.assertEqual(rules.version_of("shot.v12.exr"), 12)
        self.assertIsNone(rules.version_of("cache.bgeo"))

    def test_version_stem_groups(self):
        self.assertEqual(rules.version_stem("cache_v003.bgeo"),
                         rules.version_stem("cache_v007.bgeo"))

    def test_frame_number_is_not_a_version(self):
        self.assertIsNone(rules.version_of("render.0004.exr"))


class TestVerdicts(unittest.TestCase):

    def test_defaults(self):
        self.assertEqual(rules.verdict_for(rules.CAT_SOURCE)[0], rules.KEEP)
        self.assertEqual(rules.verdict_for(rules.CAT_CACHE)[0], rules.DROP)
        self.assertEqual(rules.verdict_for(rules.CAT_RENDER)[0], rules.REVIEW)

    def test_superseded_always_drops(self):
        # Even a category that otherwise never drops.
        verdict, _ = rules.verdict_for(rules.CAT_SOURCE, superseded=True)
        self.assertEqual(verdict, rules.DROP)

    def test_orphan_cache_is_not_droppable(self):
        # A cache is only regenerable while its scene exists.
        verdict, _ = rules.verdict_for(rules.CAT_CACHE, referenced=False,
                                       scene_missing=True)
        self.assertEqual(verdict, rules.REVIEW)

    def test_referenced_render_is_kept(self):
        verdict, _ = rules.verdict_for(rules.CAT_RENDER, referenced=True)
        self.assertEqual(verdict, rules.KEEP)

    def test_unreferenced_never_promotes_to_drop(self):
        # The dangerous mistake: deleting things merely for being unreferenced.
        for category in (rules.CAT_SOURCE, rules.CAT_GEO_IN,
                         rules.CAT_DELIVERY, rules.CAT_DOC):
            verdict, _ = rules.verdict_for(category, referenced=False)
            self.assertEqual(verdict, rules.KEEP,
                             "%s dropped on reference evidence" % category)


if __name__ == "__main__":
    unittest.main()


class TestCacheEvidence(unittest.TestCase):
    """
    A cache splits three ways and the difference is the whole decision:
    proven by a readable scene, orphaned with every scene readable, or
    unverified because a scene could not be read at all.

    Collapsing the last two is what makes a tool untrustworthy on a mixed
    Houdini/C4D project: a 40-minute sim whose C4D scene cannot be read would
    otherwise read exactly like genuine junk.
    """

    def test_proven_cache_drops_and_says_so(self):
        verdict, why = rules.verdict_for(rules.CAT_CACHE, referenced=True)
        self.assertEqual(verdict, rules.DROP)
        self.assertIn("a scene here reads it", why)

    def test_orphaned_cache_reviews_and_says_the_maker_is_gone(self):
        verdict, why = rules.verdict_for(rules.CAT_CACHE, referenced=False,
                                         scene_missing=True)
        self.assertEqual(verdict, rules.REVIEW)
        self.assertIn("may NOT be re-cookable", why)

    def test_unverified_cache_reviews_and_names_the_reason(self):
        verdict, why = rules.verdict_for(rules.CAT_CACHE, referenced=False,
                                         trust_references=False)
        self.assertEqual(verdict, rules.REVIEW)
        self.assertIn("UNVERIFIED", why)
        self.assertIn("Cinema 4D", why)

    def test_the_three_reasons_are_distinguishable(self):
        proven = rules.verdict_for(rules.CAT_CACHE, referenced=True)[1]
        orphan = rules.verdict_for(rules.CAT_CACHE, scene_missing=True)[1]
        unknown = rules.verdict_for(rules.CAT_CACHE,
                                    trust_references=False)[1]
        self.assertEqual(len({proven, orphan, unknown}), 3)

    def test_a_proven_cache_drops_even_with_unreadable_scenes_around(self):
        # Evidence found stands whatever else could not be read.
        verdict, _why = rules.verdict_for(rules.CAT_CACHE, referenced=True,
                                          trust_references=False)
        self.assertEqual(verdict, rules.DROP)


class TestExpensiveSim(unittest.TestCase):
    """Regenerable is not the same as cheap."""

    def test_sim_folders_are_flagged(self):
        for path in ("D:/p/cache/flip/x.bgeo",
                     "D:/p/pyro_sim/smoke.vdb",
                     "D:/p/SHOT_v002.RBD_SIM/v1/x.bgeo.sc",
                     "D:/p/vellum/cloth.sim"):
            self.assertTrue(rules.is_expensive_sim(path), path)

    def test_ordinary_caches_are_not(self):
        for path in ("D:/p/geo/x.bgeo", "D:/p/tex/wood.exr",
                     "D:/p/simple_things/x.bgeo", "D:/p/abc/model.abc"):
            self.assertFalse(rules.is_expensive_sim(path), path)
