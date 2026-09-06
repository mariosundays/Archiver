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
