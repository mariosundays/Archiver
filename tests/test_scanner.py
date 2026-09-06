"""The scan end to end, against a real project tree built in a temp folder."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import rules, scanner


def write(path, content=b"x" * 512):
    """Create a file and everything above it."""
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def fake_hip(path, references):
    """
    A file shaped enough like a .hip for the parser to read it.

    The parser scrapes printable byte runs out of a binary, so a plausible
    scene is just those paths surrounded by noise.
    """
    blob = b"\x00\x01Houdini\x00" + b"\x00".join(
        ref.encode("utf-8") for ref in references) + b"\x00\xff"
    return write(path, blob)


class ProjectCase(unittest.TestCase):
    """A realistic project tree, built once per test."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_test_").replace("\\", "/")

        # Scene, referencing a texture and a cache folder.
        fake_hip(self.root + "/scenes/shot01.hip", [
            "$HIP/tex/wood_diffuse.exr",
            "$HIP/geo",
            self.root + "/tex/metal.exr",
        ])
        # An autosave beside it.
        write(self.root + "/scenes/shot01.hip.bak")

        # Source textures.
        write(self.root + "/tex/wood_diffuse.exr")
        write(self.root + "/tex/metal.exr")
        write(self.root + "/tex/unused_but_precious.exr")

        # A cache the scene references by folder.
        for frame in range(1, 6):
            write(self.root + "/geo/smoke.%04d.bgeo.sc" % frame)

        # A cache nothing references at all.
        write(self.root + "/cache_old/orphan.vdb")

        # Renders, two versions of the same thing.
        for frame in range(1, 4):
            write(self.root + "/render/v01/beauty.%04d.exr" % frame)
            write(self.root + "/render/v02/beauty.%04d.exr" % frame)

        # Superseded versions sitting side by side in one folder.
        write(self.root + "/cache/sim_v001.bgeo")
        write(self.root + "/cache/sim_v002.bgeo")

        # Disposables and documents.
        write(self.root + "/backup/shot01_old.hip")
        write(self.root + "/tmp/scratch.tmp")
        write(self.root + "/docs/brief.pdf")
        write(self.root + "/delivery/final_master.mov")

        self.result = scanner.scan(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def folder(self, relative):
        for folder in self.result.folders:
            if folder.relative == relative:
                return folder
        self.fail("no folder %r in %s"
                  % (relative, [f.relative for f in self.result.folders]))

    def verdict(self, relative):
        return self.folder(relative).verdict


class TestScanShape(ProjectCase):

    def test_finds_the_scene(self):
        names = [os.path.basename(s.path) for s in self.result.scenes]
        self.assertIn("shot01.hip", names)

    def test_autosave_is_not_a_scene(self):
        names = [os.path.basename(s.path) for s in self.result.scenes]
        self.assertNotIn("shot01.hip.bak", names)

    def test_totals_add_up(self):
        # Folder sizes must not overlap, or every total is wrong.
        summed = sum(f.size for f in self.result.folders)
        self.assertEqual(summed, self.result.total_size)

    def test_no_errors(self):
        self.assertEqual(self.result.errors, [])


class TestVerdicts(ProjectCase):

    def test_textures_kept(self):
        self.assertEqual(self.verdict("tex"), rules.KEEP)

    def test_unreferenced_texture_still_kept(self):
        # The whole point: nothing irreplaceable drops for being unreferenced.
        entry = [e for e in self.folder("tex").entries
                 if "precious" in e.path][0]
        self.assertFalse(entry.referenced)
        self.assertEqual(self.verdict("tex"), rules.KEEP)

    def test_backup_dropped(self):
        self.assertEqual(self.verdict("backup"), rules.DROP)

    def test_temp_dropped(self):
        self.assertEqual(self.verdict("tmp"), rules.DROP)

    def test_docs_kept(self):
        self.assertEqual(self.verdict("docs"), rules.KEEP)

    def test_delivery_kept(self):
        self.assertEqual(self.verdict("delivery"), rules.KEEP)

    def test_referenced_cache_drops(self):
        # Referenced by folder, so re-cookable -- the safe kind of drop.
        self.assertEqual(self.verdict("geo"), rules.DROP)

    def test_orphan_cache_reviews(self):
        # Nothing references it, so re-cooking may be impossible.
        self.assertEqual(self.verdict("cache_old"), rules.REVIEW)

    def test_renders_review(self):
        self.assertIn(self.verdict("render/v02"),
                      (rules.REVIEW, rules.KEEP))


class TestReferences(ProjectCase):

    def test_direct_reference_found(self):
        entry = [e for e in self.folder("tex").entries
                 if "wood_diffuse" in e.path][0]
        self.assertTrue(entry.referenced)

    def test_absolute_reference_found(self):
        entry = [e for e in self.folder("tex").entries
                 if "metal" in e.path][0]
        self.assertTrue(entry.referenced)

    def test_folder_reference_covers_contents(self):
        # $HIP/geo protects every frame in it, though none is named.
        for entry in self.folder("geo").entries:
            self.assertTrue(entry.referenced, entry.path)

    def test_unreferenced_stays_unreferenced(self):
        entry = [e for e in self.folder("tex").entries
                 if "precious" in e.path][0]
        self.assertFalse(entry.referenced)


class TestSupersede(ProjectCase):

    def test_older_version_flagged(self):
        entries = {os.path.basename(e.path): e
                   for e in self.folder("cache").entries}
        self.assertTrue(entries["sim_v001.bgeo"].superseded)
        self.assertFalse(entries["sim_v002.bgeo"].superseded)


class TestFolderSupersede(ProjectCase):
    """Old render versions -- usually the biggest reclaimable thing there is."""

    def test_older_version_folder_drops(self):
        self.assertEqual(self.verdict("render/v01"), rules.DROP)

    def test_newest_version_folder_survives(self):
        self.assertNotEqual(self.verdict("render/v02"), rules.DROP)

    def test_reason_explains_itself(self):
        self.assertIn("uperseded", self.folder("render/v01").reason)


class TestSupersedeLimits(unittest.TestCase):
    """The folder rule must not eat source material."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_ver_").replace("\\", "/")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def verdict_of(self, relative):
        result = scanner.scan(self.root)
        for folder in result.folders:
            if folder.relative == relative:
                return folder.verdict
        self.fail("no folder %r" % relative)

    def test_texture_versions_are_never_superseded(self):
        # tex/v01 may hold maps tex/v02 does not, and losing them is
        # unrecoverable. Renders regenerate; source does not.
        write(self.root + "/tex/v01/wood.exr")
        write(self.root + "/tex/v02/wood.exr")
        self.assertEqual(self.verdict_of("tex/v01"), rules.KEEP)

    def test_scene_versions_are_never_superseded(self):
        write(self.root + "/scenes/v01/shot.hip")
        write(self.root + "/scenes/v02/shot.hip")
        self.assertNotEqual(self.verdict_of("scenes/v01"), rules.DROP)

    def test_non_version_siblings_are_left_alone(self):
        # "render/final" is not a version of "render/v01".
        write(self.root + "/render/v01/a.exr")
        write(self.root + "/render/final/a.exr")
        self.assertNotEqual(self.verdict_of("render/v01"), rules.DROP)

    def test_single_version_folder_is_not_superseded(self):
        write(self.root + "/render/v01/a.exr")
        self.assertNotEqual(self.verdict_of("render/v01"), rules.DROP)


class TestOpaqueScenes(unittest.TestCase):
    """
    A scene we cannot read makes every reference verdict unsafe.

    Modern Cinema 4D files are compressed, so a C4D project yields no
    references at all. Treating that as "nothing is referenced" would archive
    away the caches and geometry those scenes load -- which on a real project
    was a single 3 GB .abc.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_c4d_").replace("\\", "/")
        # The R20+ container magic, which is what is_opaque keys on.
        write(self.root + "/scenes/shot.c4d", b"QC4DC4D6" + b"\xd7" * 4096)
        write(self.root + "/cache/sim.abc", b"x" * 8192)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def scan(self):
        return scanner.scan(self.root)

    def test_opaque_scene_detected(self):
        result = self.scan()
        self.assertEqual(len(result.opaque_scenes), 1)
        self.assertFalse(result.references_trustworthy)

    def test_cache_is_not_dropped_when_scenes_unreadable(self):
        # The whole point. Without this the .abc gets a confident Drop.
        result = self.scan()
        folder = [f for f in result.folders if f.relative == "cache"][0]
        self.assertEqual(folder.verdict, rules.REVIEW)
        self.assertIn("could not be read", folder.reason)

    def test_readable_project_gives_the_orphan_reason(self):
        # The gate must not make the tool useless on a Houdini project. An
        # unreferenced cache there is genuinely orphaned, so it still reviews
        # -- but for the confident reason, not the "could not read" one.
        root = tempfile.mkdtemp(prefix="archiver_hip_").replace("\\", "/")
        try:
            fake_hip(root + "/scenes/shot.hip", ["$HIP/tex/a.exr"])
            write(root + "/cache/sim.bgeo")
            result = scanner.scan(root)
            self.assertTrue(result.references_trustworthy)
            folder = [f for f in result.folders if f.relative == "cache"][0]
            self.assertNotIn("could not be read", folder.reason)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_referenced_cache_still_drops_despite_opaque_scenes(self):
        # Evidence we DID find stands, whatever else was unreadable.
        write(self.root + "/geo/sim.bgeo")
        fake_hip(self.root + "/scenes/other.hip",
                 [self.root + "/geo/sim.bgeo"])
        result = scanner.scan(self.root)
        self.assertFalse(result.references_trustworthy)
        folder = [f for f in result.folders if f.relative == "geo"][0]
        self.assertEqual(folder.verdict, rules.DROP)


class TestEmptyFolders(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_mt_").replace("\\", "/")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_empty_folder_flagged(self):
        os.makedirs(self.root + "/DOCS/NDA")
        write(self.root + "/tex/a.exr")
        result = scanner.scan(self.root)

        empty = [f for f in result.folders if f.is_empty]
        names = sorted(f.relative for f in empty)
        self.assertIn("DOCS/NDA", names)
        for folder in empty:
            self.assertEqual(folder.verdict, rules.DROP)

    def test_parent_of_a_used_folder_is_not_empty(self):
        # DOCS holds no files itself, but NDA under it does -- that is
        # structure, not clutter.
        os.makedirs(self.root + "/DOCS/NDA")
        write(self.root + "/DOCS/NDA/contract.pdf")
        result = scanner.scan(self.root)

        docs = [f for f in result.folders if f.relative == "DOCS"][0]
        self.assertFalse(docs.is_empty)
        self.assertNotEqual(docs.verdict, rules.DROP)

    def test_empty_folders_listed_on_the_result(self):
        os.makedirs(self.root + "/a")
        os.makedirs(self.root + "/b")
        write(self.root + "/tex/x.exr")
        self.assertEqual(len(scanner.scan(self.root).empty_folders), 2)


class TestGeneratedGeometry(unittest.TestCase):
    """An .abc is source in models/ and a cache in alembic/."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_abc_").replace("\\", "/")
        fake_hip(self.root + "/scenes/shot.hip", ["$HIP/tex/a.exr"])

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def folder_of(self, relative):
        for folder in scanner.scan(self.root).folders:
            if folder.relative == relative:
                return folder
        self.fail("no folder %r" % relative)

    def verdict_of(self, relative):
        return self.folder_of(relative).verdict

    def test_alembic_folder_is_a_cache_not_source(self):
        # The real bug: a 3 GB xpTrail.abc in R&D/alembic was called
        # irreplaceable source and kept. Cache means it is at least offered.
        write(self.root + "/alembic/xpTrail.abc", b"x" * 4096)
        folder = self.folder_of("alembic")
        self.assertEqual(folder.category, rules.CAT_CACHE)
        self.assertNotEqual(folder.verdict, rules.KEEP)

    def test_models_folder_is_source(self):
        write(self.root + "/models/building.abc", b"x" * 4096)
        folder = self.folder_of("models")
        self.assertEqual(folder.category, rules.CAT_GEO_IN)
        self.assertEqual(folder.verdict, rules.KEEP)

    def test_cache_folder_geometry_is_a_cache(self):
        write(self.root + "/cache/sim.abc", b"x" * 4096)
        self.assertEqual(self.folder_of("cache").category, rules.CAT_CACHE)

    def test_referenced_alembic_drops(self):
        write(self.root + "/alembic/xpTrail.abc", b"x" * 4096)
        fake_hip(self.root + "/scenes/uses.hip",
                 [self.root + "/alembic/xpTrail.abc"])
        self.assertEqual(self.verdict_of("alembic"), rules.DROP)


class TestSequences(ProjectCase):

    def test_frames_collapse(self):
        sequences = self.folder("geo").sequences
        self.assertEqual(len(sequences), 1)
        self.assertEqual(sequences[0].count, 5)

    def test_sequence_size_is_the_sum(self):
        sequence = self.folder("geo").sequences[0]
        self.assertEqual(sequence.size,
                         sum(e.size for e in self.folder("geo").entries))


class TestReadOnly(unittest.TestCase):
    """A scan must never change the folder it looks at."""

    def test_nothing_written(self):
        root = tempfile.mkdtemp(prefix="archiver_ro_").replace("\\", "/")
        try:
            write(root + "/tex/a.exr")
            fake_hip(root + "/scene.hip", ["$HIP/tex/a.exr"])

            before = _snapshot(root)
            scanner.scan(root)
            self.assertEqual(_snapshot(root), before)
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _snapshot(root):
    """Every path under root with its size -- byte-identical or it failed."""
    out = {}
    for folder, _dirs, names in os.walk(root):
        for name in names:
            full = os.path.join(folder, name)
            out[full] = os.path.getsize(full)
    return out


class TestEdges(unittest.TestCase):

    def test_missing_root(self):
        result = scanner.scan("Z:/nope/not/here")
        self.assertTrue(result.errors)
        self.assertEqual(result.folders, [])

    def test_empty_project(self):
        root = tempfile.mkdtemp(prefix="archiver_empty_")
        try:
            result = scanner.scan(root)
            self.assertEqual(result.total_files, 0)
            self.assertEqual(result.total_size, 0)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


class TestEveryVerdictExplainsItself(unittest.TestCase):
    """
    A Drop row with no reason is the one most in need of one.

    _folder_verdict started at DROP with an empty reason and only recorded one
    when a SAFER verdict won, so a folder where everything genuinely dropped
    came out unexplained.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_why_").replace("\\", "/")
        fake_hip(self.root + "/scenes/shot.hip", ["$HIP/tex/a.exr"])
        write(self.root + "/tex/a.exr")
        write(self.root + "/tmp/junk.tmp")
        write(self.root + "/backup/old.hip")
        write(self.root + "/cache_old/orphan.vdb")
        os.makedirs(self.root + "/hollow")
        self.result = scanner.scan(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_every_folder_has_a_reason(self):
        for folder in self.result.folders:
            if not folder.count and not folder.is_empty:
                continue        # pure container
            self.assertTrue(folder.reason,
                            "%s (%s) has no reason"
                            % (folder.relative, folder.verdict))

    def test_drop_rows_name_the_category(self):
        drops = [f for f in self.result.folders
                 if f.verdict == rules.DROP and f.count]
        self.assertTrue(drops)
        for folder in drops:
            self.assertIn("—", folder.reason,
                          "%s does not say what it is" % folder.relative)

    def test_empty_folder_reason_is_kept(self):
        empty = [f for f in self.result.folders if f.is_empty]
        self.assertTrue(empty)
        self.assertIn("Empty folder", empty[0].reason)
