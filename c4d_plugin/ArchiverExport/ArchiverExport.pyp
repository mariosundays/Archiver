"""
ArchiverExport -- write each scene's asset list where Archiver can read it.

WHY THIS EXISTS

Modern .c4d is a proprietary compressed container: no asset path survives in
plaintext, so Archiver cannot tell from outside what a scene loads. On a real
project that meant 38 of 63 scenes were unreadable and every cache in the
job had to be reported as "unverified" -- including a 3 GB .abc that a scene
almost certainly needed.

Cinema 4D knows the answer. This dumps it: one JSON sidecar per scene, next to
the scene, which Archiver reads instead of scraping.

    shot_010.c4d
    shot_010.c4d.assets.json

Extensions -> Archiver Asset Export, then pick a scope:
    - This scene only
    - Every scene in this scene's folder
    - Every scene in the project (recursive)

SHAPE OF THIS FILE

Deliberately a thin shell. The logic that decides anything lives in Archiver's
core/c4d_assets.py and core/sidecar.py, which are plain modules with tests --
because a bug in here costs a C4D restart to find, and a bug in there does
not. Those two files are shipped ALONGSIDE this plugin and exec'd, since C4D's
interpreter cannot import Archiver's package.

C4D 2026 LOADER REQUIREMENTS (learned the hard way on this install, see the
Iris bridge): install into the application's own plugins folder, keep the
res/ folder with c4d_symbols.h or the plugin is silently skipped, and keep the
file CRLF -- an LF-only .pyp is ignored. sync_to_c4d.ps1 handles all three.
"""

import os
import sys
import traceback

import c4d
from c4d import plugins, storage


PLUGIN_ID = 1065219        # Archiver asset export
PLUGIN_NAME = "Archiver Asset Export"

SCOPE_SCENE = 0
SCOPE_FOLDER = 1
SCOPE_PROJECT = 2

_HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# The shared modules, exec'd rather than imported
# ---------------------------------------------------------------------------

def _load_shared():
    """
    Load sidecar.py and c4d_assets.py out of the plugins folder.

    C4D's interpreter has no idea where Archiver is installed, so importing
    core.sidecar is not an option. The sync script copies both modules next to
    this plugin and they are exec'd into throwaway namespaces here -- the same
    trick IrisLaunch uses for iris_boot.py.
    """
    modules = {}
    for name in ("sidecar", "c4d_assets"):
        path = os.path.join(os.path.dirname(_HERE), "archiver_" + name + ".py")
        if not os.path.isfile(path):
            path = os.path.join(_HERE, "archiver_" + name + ".py")
        if not os.path.isfile(path):
            raise IOError("Archiver module not found: archiver_%s.py" % name)

        namespace = {"__name__": "archiver_" + name, "__file__": path}
        with open(path, "r", encoding="utf-8") as handle:
            exec(compile(handle.read(), path, "exec"), namespace)
        modules[name] = namespace
    return modules


# ---------------------------------------------------------------------------
# One scene
# ---------------------------------------------------------------------------

def _assets_of(doc, shared, scene_path):
    """Every asset the document references, as plain path strings."""
    assets = []

    # GetAllAssetsNew is what the Project Asset Inspector itself uses. The
    # signature has moved between versions, so try the modern form first and
    # fall back rather than failing outright on an older build.
    try:
        result = c4d.documents.GetAllAssetsNew(
            doc, False, "", c4d.ASSETDATA_FLAG_WITHCACHES)
    except (AttributeError, TypeError):
        try:
            result = c4d.documents.GetAllAssetsNew(doc, False, "")
        except (AttributeError, TypeError):
            result = None

    if isinstance(result, tuple):
        # (returncode, assets) in current versions.
        for part in result:
            if isinstance(part, list):
                assets = part
                break
    elif isinstance(result, list):
        assets = result

    return shared["c4d_assets"]["asset_paths"](assets, scene_path)


def _export_document(doc, shared, scene_path=None):
    """
    Write one document's sidecar. Returns the number of assets recorded.

    Raises on anything that stops a sidecar being written, so the batch loop
    can record which scene failed instead of reporting a clean run.
    """
    if scene_path is None:
        folder = doc.GetDocumentPath()
        name = doc.GetDocumentName()
        if not folder or not name:
            raise IOError("the scene has never been saved")
        scene_path = os.path.join(folder, name)

    paths = _assets_of(doc, shared, scene_path)
    version = ""
    try:
        version = str(c4d.GetC4DVersion())
    except Exception:
        pass

    shared["sidecar"]["write"](scene_path, paths,
                               app="Cinema 4D", app_version=version)
    return len(paths)


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

def _export_batch(scenes, shared):
    """
    Open each scene, export it, close it. Returns rows for summarize().

    Scenes are loaded WITHOUT dialogs and closed straight after, so a missing
    texture or an old file version cannot stall an unattended run of sixty
    scenes behind a modal box.

    The user's own open document is never touched: LoadDocument brings the
    scene in as a separate document and KillDocument disposes of it.
    """
    results = []

    for index, scene in enumerate(scenes):
        c4d.StatusSetText("Archiver: %d/%d  %s"
                          % (index + 1, len(scenes), os.path.basename(scene)))
        c4d.StatusSetBar(int(100.0 * index / max(1, len(scenes))))

        doc = None
        try:
            doc = c4d.documents.LoadDocument(
                scene, c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS)
            if doc is None:
                results.append((scene, 0, "could not open"))
                continue
            count = _export_document(doc, shared, scene)
            results.append((scene, count, None))
        except Exception as exc:
            results.append((scene, 0, str(exc) or exc.__class__.__name__))
        finally:
            if doc is not None:
                c4d.documents.KillDocument(doc)

    c4d.StatusClear()
    return results


class ScopeDialog(c4d.gui.GeDialog):
    """Three buttons, because the scope changes how long the run takes."""

    ID_SCENE = 1001
    ID_FOLDER = 1002
    ID_PROJECT = 1003
    ID_CANCEL = 1004

    def __init__(self):
        super(ScopeDialog, self).__init__()
        self.choice = None

    def CreateLayout(self):
        self.SetTitle("Archiver Asset Export")
        self.GroupBegin(0, c4d.BFH_SCALEFIT, 1, 0, "")
        self.GroupBorderSpace(12, 12, 12, 8)
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0,
                           "Write each scene's asset list for Archiver.")
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "")
        self.AddButton(self.ID_SCENE, c4d.BFH_SCALEFIT, 0, 0,
                       "This scene only")
        self.AddButton(self.ID_FOLDER, c4d.BFH_SCALEFIT, 0, 0,
                       "Every scene in this folder")
        self.AddButton(self.ID_PROJECT, c4d.BFH_SCALEFIT, 0, 0,
                       "Every scene in the project (choose folder)...")
        self.AddStaticText(0, c4d.BFH_SCALEFIT, 0, 0, "")
        self.AddButton(self.ID_CANCEL, c4d.BFH_SCALEFIT, 0, 0, "Cancel")
        self.GroupEnd()
        return True

    def Command(self, cid, msg):
        mapping = {self.ID_SCENE: SCOPE_SCENE,
                   self.ID_FOLDER: SCOPE_FOLDER,
                   self.ID_PROJECT: SCOPE_PROJECT}
        if cid in mapping:
            self.choice = mapping[cid]
            self.Close()
            return True
        if cid == self.ID_CANCEL:
            self.choice = None
            self.Close()
            return True
        return True


class ArchiverExportCommand(plugins.CommandData):

    def Execute(self, doc):
        try:
            return self._run(doc)
        except Exception:
            c4d.StatusClear()
            c4d.gui.MessageDialog("Archiver Asset Export failed:\n\n"
                                  + traceback.format_exc())
            return False

    def _run(self, doc):
        shared = _load_shared()
        find_scenes = shared["c4d_assets"]["find_scenes"]
        summarize = shared["c4d_assets"]["summarize"]

        dialog = ScopeDialog()
        dialog.Open(c4d.DLG_TYPE_MODAL, PLUGIN_ID, defaultw=320)
        scope = dialog.choice
        if scope is None:
            return True

        if scope == SCOPE_SCENE:
            if not doc.GetDocumentPath():
                c4d.gui.MessageDialog(
                    "Save the scene first -- a sidecar is written beside the "
                    "scene file, so the scene needs a home on disk.")
                return False
            count = _export_document(doc, shared)
            c4d.gui.MessageDialog(
                "Exported %s\n\n%d asset%s recorded."
                % (doc.GetDocumentName(), count, "" if count == 1 else "s"))
            return True

        if scope == SCOPE_FOLDER:
            folder = doc.GetDocumentPath()
            if not folder:
                c4d.gui.MessageDialog("Save the scene first, or use the "
                                      "project option and pick a folder.")
                return False
            scenes = find_scenes(folder, recursive=False)
        else:
            start = doc.GetDocumentPath() or ""
            folder = storage.LoadDialog(
                title="Project folder to export", flags=c4d.FILESELECT_DIRECTORY,
                def_path=start)
            if not folder:
                return True
            scenes = find_scenes(folder, recursive=True)

        if not scenes:
            c4d.gui.MessageDialog("No scenes found in:\n" + folder)
            return True

        # Opening scenes is slow and this is the unattended path, so say how
        # much work was asked for before starting it.
        if len(scenes) > 1 and not c4d.gui.QuestionDialog(
                "Export asset lists for %d scenes?\n\n"
                "Each is opened and closed in turn, which can take a while."
                % len(scenes)):
            return True

        results = _export_batch(scenes, shared)
        c4d.gui.MessageDialog(summarize(results))
        return True


def _icon():
    for name in ("icon.png", "ArchiverExport.png"):
        path = os.path.join(_HERE, "res", name)
        if os.path.isfile(path):
            bitmap = c4d.bitmaps.BaseBitmap()
            if bitmap.InitWith(path)[0] == c4d.IMAGERESULT_OK:
                return bitmap
    return None


if __name__ == "__main__":
    sys.stdout.write("[ArchiverExport] module load\n")
    sys.stdout.flush()
    plugins.RegisterCommandPlugin(
        id=PLUGIN_ID,
        str=PLUGIN_NAME,
        info=0,
        help="Write each scene's asset list where Archiver can read it",
        dat=ArchiverExportCommand(),
        icon=_icon(),
    )
