"""
The Cinema 4D plugin, run against a stand-in for Cinema 4D.

Claude cannot drive C4D, so without this the .pyp would ship having never
executed once -- and every mistake in it would cost Mario a restart to find.
A fake c4d module is enough to prove the parts that are ordinary Python: that
the file executes, that the shared modules load the way the sync script
arranges them, that a document's assets reach a sidecar on disk, and that a
batch run reports a failure instead of swallowing it.

What this can NOT prove is the C4D API surface itself -- whether
GetAllAssetsNew takes those flags on this build, whether the dialog lays out
sensibly. Those need Mario and a restart. Everything else is pinned here.
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

PYP = os.path.join(ROOT, "c4d_plugin", "ArchiverExport", "ArchiverExport.pyp")


# ---------------------------------------------------------------------------
# The stand-in for Cinema 4D
# ---------------------------------------------------------------------------

class FakeDocument(object):
    def __init__(self, folder="", name="", assets=None):
        self._folder = folder
        self._name = name
        self.assets = assets or []
        self.killed = False

    def GetDocumentPath(self):
        return self._folder

    def GetDocumentName(self):
        return self._name


def build_fake_c4d(load_map=None, assets_result=None):
    """
    A c4d module with just the surface the plugin touches.

    load_map maps a scene path to the FakeDocument LoadDocument returns, or to
    an exception to raise.
    """
    c4d = types.ModuleType("c4d")
    c4d.ASSETDATA_FLAG_WITHCACHES = 1
    c4d.SCENEFILTER_OBJECTS = 1
    c4d.SCENEFILTER_MATERIALS = 2
    c4d.DLG_TYPE_MODAL = 1
    c4d.FILESELECT_DIRECTORY = 1
    c4d.IMAGERESULT_OK = 0
    c4d.BFH_SCALEFIT = 1

    c4d.GetC4DVersion = lambda: 2026100
    c4d.StatusSetText = lambda *a: None
    c4d.StatusSetBar = lambda *a: None
    c4d.StatusClear = lambda *a: None

    documents = types.ModuleType("c4d.documents")
    c4d.killed = []

    def get_all_assets_new(doc, dialogs, path, flags=None):
        if assets_result is not None:
            return assets_result
        return (0, list(doc.assets))

    def load_document(path, flags=0):
        entry = (load_map or {}).get(path)
        if isinstance(entry, Exception):
            raise entry
        return entry

    def kill_document(doc):
        doc.killed = True
        c4d.killed.append(doc)

    documents.GetAllAssetsNew = get_all_assets_new
    documents.LoadDocument = load_document
    documents.KillDocument = kill_document
    documents.GetActiveDocument = lambda: None
    c4d.documents = documents

    gui = types.ModuleType("c4d.gui")
    c4d.messages = []
    gui.MessageDialog = lambda text, *a, **k: c4d.messages.append(text)
    gui.QuestionDialog = lambda text, *a, **k: True

    class GeDialog(object):
        def SetTitle(self, *a): pass
        def GroupBegin(self, *a, **k): return True
        def GroupEnd(self, *a): pass
        def GroupBorderSpace(self, *a): pass
        def AddStaticText(self, *a, **k): pass
        def AddButton(self, *a, **k): pass
        def Open(self, *a, **k): return True
        def Close(self, *a): pass

    gui.GeDialog = GeDialog
    c4d.gui = gui

    bitmaps = types.ModuleType("c4d.bitmaps")

    class BaseBitmap(object):
        def InitWith(self, path):
            return (0, None)

    bitmaps.BaseBitmap = BaseBitmap
    c4d.bitmaps = bitmaps

    plugins_mod = types.ModuleType("c4d.plugins")

    class CommandData(object):
        pass

    plugins_mod.CommandData = CommandData
    plugins_mod.RegisterCommandPlugin = lambda **k: True
    c4d.plugins = plugins_mod

    storage = types.ModuleType("c4d.storage")
    storage.LoadDialog = lambda **k: ""
    c4d.storage = storage

    return c4d


def load_plugin(fake_c4d, plugin_dir):
    """
    Execute the .pyp the way C4D would, with the fake module in its place.

    plugin_dir stands in for the installed location, so _load_shared() is
    exercised against a real folder laid out as the sync script leaves it.
    """
    saved = {name: sys.modules.get(name) for name in
             ("c4d", "c4d.documents", "c4d.gui", "c4d.bitmaps",
              "c4d.plugins", "c4d.storage")}
    sys.modules["c4d"] = fake_c4d
    sys.modules["c4d.documents"] = fake_c4d.documents
    sys.modules["c4d.gui"] = fake_c4d.gui
    sys.modules["c4d.bitmaps"] = fake_c4d.bitmaps
    sys.modules["c4d.plugins"] = fake_c4d.plugins
    sys.modules["c4d.storage"] = fake_c4d.storage
    try:
        with open(PYP, "r", encoding="utf-8") as handle:
            source = handle.read()
        namespace = {
            "__name__": "archiver_export_test",
            "__file__": os.path.join(plugin_dir, "ArchiverExport.pyp"),
        }
        exec(compile(source, PYP, "exec"), namespace)
        return namespace
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class PluginCase(unittest.TestCase):
    """A plugins folder laid out the way sync_to_c4d.ps1 leaves it."""

    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="archiver_pyp_")
        self.plugins_dir = os.path.join(self.temp, "plugins")
        self.plugin_dir = os.path.join(self.plugins_dir, "ArchiverExport")
        os.makedirs(self.plugin_dir)

        # The two shared modules, copied beside the plugin folder exactly as
        # the sync script places them.
        for name in ("sidecar", "c4d_assets"):
            shutil.copy(os.path.join(ROOT, "core", name + ".py"),
                        os.path.join(self.plugins_dir, "archiver_%s.py" % name))

        self.project = os.path.join(self.temp, "job")
        os.makedirs(os.path.join(self.project, "scenes"))

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def scene(self, name="shot.c4d"):
        path = os.path.join(self.project, "scenes", name)
        with open(path, "wb") as handle:
            handle.write(b"QC4DC4D6" + b"\x00" * 128)
        return path

    def plugin(self, **kwargs):
        fake = build_fake_c4d(**kwargs)
        return load_plugin(fake, self.plugin_dir), fake


class TestPluginLoads(PluginCase):

    def test_the_plugin_executes(self):
        namespace, _ = self.plugin()
        self.assertIn("ArchiverExportCommand", namespace)

    def test_the_shared_modules_load_from_the_plugins_folder(self):
        namespace, _ = self.plugin()
        shared = namespace["_load_shared"]()
        self.assertIn("write", shared["sidecar"])
        self.assertIn("find_scenes", shared["c4d_assets"])

    def test_a_missing_shared_module_says_so_plainly(self):
        os.remove(os.path.join(self.plugins_dir, "archiver_sidecar.py"))
        namespace, _ = self.plugin()
        with self.assertRaises(IOError) as caught:
            namespace["_load_shared"]()
        self.assertIn("archiver_sidecar.py", str(caught.exception))


class TestExportDocument(PluginCase):

    def test_writes_a_sidecar_beside_the_scene(self):
        scene = self.scene()
        namespace, _ = self.plugin()
        shared = namespace["_load_shared"]()
        doc = FakeDocument(os.path.dirname(scene), "shot.c4d",
                           [{"filename": r"C:\job\tex\wood.png"}])

        count = namespace["_export_document"](doc, shared)

        self.assertEqual(count, 1)
        written = scene + ".assets.json"
        self.assertTrue(os.path.isfile(written))
        with open(written) as handle:
            payload = json.load(handle)
        self.assertEqual(payload["assets"], [r"C:\job\tex\wood.png"])
        self.assertEqual(payload["app"], "Cinema 4D")

    def test_an_unsaved_scene_is_refused_not_written_somewhere_odd(self):
        namespace, _ = self.plugin()
        shared = namespace["_load_shared"]()
        with self.assertRaises(IOError):
            namespace["_export_document"](FakeDocument("", ""), shared)

    def test_a_list_return_from_the_api_is_handled(self):
        # Older signatures hand back a bare list rather than (code, assets).
        scene = self.scene()
        namespace, _ = self.plugin(
            assets_result=[{"filename": r"C:\job\tex\a.png"}])
        shared = namespace["_load_shared"]()
        doc = FakeDocument(os.path.dirname(scene), "shot.c4d")
        self.assertEqual(namespace["_export_document"](doc, shared), 1)

    def test_a_scene_with_no_assets_still_writes_a_sidecar(self):
        # An empty export is a real answer -- it is what tells Archiver the
        # scene loads nothing, and lets the project become trustworthy.
        scene = self.scene()
        namespace, _ = self.plugin()
        shared = namespace["_load_shared"]()
        doc = FakeDocument(os.path.dirname(scene), "shot.c4d", [])
        self.assertEqual(namespace["_export_document"](doc, shared), 0)
        self.assertTrue(os.path.isfile(scene + ".assets.json"))


class TestBatch(PluginCase):

    def test_every_scene_is_exported_and_closed(self):
        first = self.scene("a.c4d")
        second = self.scene("b.c4d")
        docs = {
            first: FakeDocument(os.path.dirname(first), "a.c4d",
                                [{"filename": r"C:\tex\a.png"}]),
            second: FakeDocument(os.path.dirname(second), "b.c4d",
                                 [{"filename": r"C:\tex\b.png"}]),
        }
        namespace, fake = self.plugin(load_map=docs)
        shared = namespace["_load_shared"]()

        results = namespace["_export_batch"]([first, second], shared)

        self.assertEqual([r[2] for r in results], [None, None])
        self.assertTrue(os.path.isfile(first + ".assets.json"))
        self.assertTrue(os.path.isfile(second + ".assets.json"))
        # Leaking documents through a 63-scene run would exhaust memory.
        self.assertEqual(len(fake.killed), 2)

    def test_a_scene_that_will_not_open_is_reported_not_swallowed(self):
        good = self.scene("a.c4d")
        bad = self.scene("b.c4d")
        docs = {good: FakeDocument(os.path.dirname(good), "a.c4d"),
                bad: None}
        namespace, _ = self.plugin(load_map=docs)
        shared = namespace["_load_shared"]()

        results = namespace["_export_batch"]([good, bad], shared)

        self.assertIsNone(results[0][2])
        self.assertEqual(results[1][2], "could not open")

    def test_a_scene_that_raises_does_not_stop_the_run(self):
        # One bad scene in sixty must not cost the other fifty-nine.
        first = self.scene("a.c4d")
        boom = self.scene("b.c4d")
        third = self.scene("c.c4d")
        docs = {
            first: FakeDocument(os.path.dirname(first), "a.c4d"),
            boom: RuntimeError("corrupt file"),
            third: FakeDocument(os.path.dirname(third), "c.c4d"),
        }
        namespace, _ = self.plugin(load_map=docs)
        shared = namespace["_load_shared"]()

        results = namespace["_export_batch"]([first, boom, third], shared)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[1][2], "corrupt file")
        self.assertIsNone(results[2][2])
        self.assertTrue(os.path.isfile(third + ".assets.json"))

    def test_a_failed_scene_is_still_closed(self):
        scene = self.scene("a.c4d")
        doc = FakeDocument(os.path.dirname(scene), "")   # unsaved -> raises
        namespace, fake = self.plugin(load_map={scene: doc})
        shared = namespace["_load_shared"]()

        namespace["_export_batch"]([scene], shared)

        self.assertTrue(doc.killed)


class TestSidecarIsReadBack(PluginCase):
    """The round trip the whole feature rests on."""

    def test_what_the_plugin_writes_is_what_the_scanner_reads(self):
        from core import scanner

        scene = self.scene()
        cache_dir = os.path.join(self.project, "cache")
        os.makedirs(cache_dir)
        cache = os.path.join(cache_dir, "sim.abc")
        with open(cache, "wb") as handle:
            handle.write(b"x" * 4096)

        namespace, _ = self.plugin()
        shared = namespace["_load_shared"]()
        doc = FakeDocument(os.path.dirname(scene), "shot.c4d",
                           [{"filename": cache}])
        namespace["_export_document"](doc, shared)

        result = scanner.scan(self.project)

        self.assertEqual(result.opaque_scenes, [])
        self.assertTrue(result.references_trustworthy)
        entry = [e for f in result.folders for e in f.entries
                 if e.name == "sim.abc"][0]
        self.assertTrue(entry.referenced)


if __name__ == "__main__":
    unittest.main()
