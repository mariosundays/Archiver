# Archiver -- what a file or folder IS, and whether it needs to survive.
# Copyright (C) 2026 Mario Domingos
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.

"""
The rules layer: categories, verdicts, and the heuristics that assign them.

AssetCleaner asks a per-file question -- "does anything reference this?".
Archiving asks a different one, per CATEGORY: "what is this, and does it need
to survive?". A render nothing references is not an orphan, it is the point of
the project. A sim cache everything references is still the first thing to
drop, because it regenerates.

So reference-counting informs the verdict but never decides it alone. What
decides it is what the file IS.

Qt-free and DCC-free by design, so the whole thing is testable without a UI
and without Houdini. Nothing here touches the filesystem except through the
paths handed to it.
"""

import os
import re

from . import scene_parser
from .scene_parser import clean, file_ext, key

# ---------------------------------------------------------------------------
# Verdicts
#
# Three, deliberately. Two is not enough -- it forces a guess on everything
# ambiguous -- and four means nothing gets looked at.
# ---------------------------------------------------------------------------

KEEP = "keep"        # the project is not the project without this
REVIEW = "review"    # only you know; the tool refuses to guess
DROP = "drop"        # regenerable, superseded, or disposable

VERDICT_ORDER = {KEEP: 0, REVIEW: 1, DROP: 2}

VERDICT_LABEL = {
    KEEP: "Keep",
    REVIEW: "Review",
    DROP: "Drop",
}

# Shown in the UI so a verdict is never a bare assertion.
VERDICT_HELP = {
    KEEP: "Source material and scene files. Cannot be regenerated -- "
          "archive these.",
    REVIEW: "Could go either way. Renders you may still need, caches whose "
            "scene is gone. Decide per project.",
    DROP: "Regenerable from the scene, superseded by a newer version, or "
          "disposable by nature.",
}

# ---------------------------------------------------------------------------
# Categories
#
# What a thing IS, independent of whether it should survive. The verdict is a
# separate axis: a category maps to a DEFAULT verdict, which evidence can then
# move. Keeping the two apart is what lets "sim cache whose scene still
# exists" and "sim cache whose scene is gone" share a category and differ in
# verdict.
# ---------------------------------------------------------------------------

CAT_SCENE = "scene"
CAT_SOURCE = "source"        # textures, HDRIs, reference, plates
CAT_GEO_IN = "geo_in"        # imported geometry: abc, fbx, obj
CAT_CACHE = "cache"          # simulation and geometry caches
CAT_RENDER = "render"        # rendered frames
CAT_COMP = "comp"            # comp output, flipbooks, playblasts
CAT_BACKUP = "backup"        # autosaves, .bak, backup/ folders
CAT_TEMP = "temp"            # tmp, proxies, thumbnail caches
CAT_DOC = "doc"              # notes, briefs, spreadsheets, PDFs
CAT_DELIVERY = "delivery"    # final output for the client
CAT_OTHER = "other"          # unclassified

CATEGORY_LABEL = {
    CAT_SCENE: "Scene files",
    CAT_SOURCE: "Source / textures",
    CAT_GEO_IN: "Imported geometry",
    CAT_CACHE: "Caches",
    CAT_RENDER: "Renders",
    CAT_COMP: "Comp / flipbooks",
    CAT_BACKUP: "Backups",
    CAT_TEMP: "Temp / proxies",
    CAT_DOC: "Documents",
    CAT_DELIVERY: "Deliveries",
    CAT_OTHER: "Other",
}

# The default verdict for each category, before any evidence is applied.
CATEGORY_VERDICT = {
    CAT_SCENE: KEEP,
    CAT_SOURCE: KEEP,
    CAT_GEO_IN: KEEP,
    CAT_DELIVERY: KEEP,
    CAT_DOC: KEEP,
    CAT_CACHE: DROP,
    CAT_RENDER: REVIEW,
    CAT_COMP: REVIEW,
    CAT_BACKUP: DROP,
    CAT_TEMP: DROP,
    CAT_OTHER: REVIEW,
}

# Why each category defaults where it does. Surfaced in the report, because a
# verdict the user cannot interrogate is a verdict they will not trust.
CATEGORY_WHY = {
    CAT_SCENE: "The project itself. Never archivable.",
    CAT_SOURCE: "Cannot be regenerated -- shot, bought, or authored.",
    CAT_GEO_IN: "Imported from elsewhere; the original may be gone.",
    CAT_DELIVERY: "The finished work. The reason the project exists.",
    CAT_DOC: "Small, and the context you will want in two years.",
    CAT_CACHE: "Regenerable by re-cooking the scene.",
    CAT_RENDER: "Re-renderable, but expensive. Your call.",
    CAT_COMP: "Usually re-exportable from the comp.",
    CAT_BACKUP: "Superseded by the scene file itself.",
    CAT_TEMP: "Disposable by nature.",
    CAT_OTHER: "Unrecognised -- look before deciding.",
}

# ---------------------------------------------------------------------------
# Extension groups
# ---------------------------------------------------------------------------

IMAGE_EXTS = {
    ".exr", ".hdr", ".hdri", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
    ".tga", ".bmp", ".dpx", ".cin", ".psd", ".pic", ".iff", ".sgi", ".webp",
}

# Textures pre-converted for a renderer. Regenerable from the source image.
TEXTURE_CACHE_EXTS = {".rat", ".tx", ".tex", ".rstexbin"}

CACHE_EXTS = {
    ".bgeo", ".bgeo.sc", ".geo", ".geo.gz", ".bgeo.gz", ".vdb", ".vdb.sc",
    ".sim", ".bclip", ".bphysics", ".rs", ".ass", ".ifd", ".usdc_cache",
}

# Interchange geometry. Deliberately does NOT include .blend, .ma, .mb or
# .max: those are scene formats, and listing them here shadowed
# scene_parser.SCENE_EXTS so a project's scenes stopped being detected at all.
GEO_EXTS = {".abc", ".obj", ".fbx", ".ply", ".stl", ".usd", ".usda",
            ".usdc", ".usdz", ".gltf", ".glb", ".3ds", ".dae", ".lwo",
            ".step", ".stp", ".iges", ".igs", ".sldprt", ".x3d", ".3mf"}

# Interchange formats a DCC also EXPORTS in bulk. Only these become caches
# when they sit in a cache or render folder.
#
# The distinction is about what the format is used for in practice, not what
# it can technically hold. An .abc in alembic/ is nearly always a sim or
# animation cache someone wrote out; a .usd likewise. But .obj, .fbx and .mtl
# are how models ARRIVE -- bought, scanned, or sent by a client -- and a
# folder name should never be enough to call one regenerable, because if the
# original is gone it cannot be re-exported from anything.
CACHEABLE_GEO_EXTS = {".abc", ".usd", ".usda", ".usdc", ".usdz"}

# Sidecars that travel with an imported model. Losing one silently strips a
# model of its materials, so they follow their owner rather than a folder.
MODEL_SIDECAR_EXTS = {".mtl"}

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mxf", ".r3d", ".braw", ".mkv",
              ".prores", ".webm"}

AUDIO_EXTS = {".wav", ".aif", ".aiff", ".mp3", ".flac"}

DOC_EXTS = {".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
            ".csv", ".rtf", ".odt", ".pur", ".json", ".xml"}

TEMP_EXTS = {".tmp", ".temp", ".log", ".lock", ".swp", ".ds_store",
             ".thumbs", ".part", ".crdownload"}

# Backup files by extension or suffix.
BACKUP_EXTS = {".bak", ".autosave", ".backup", ".orig", ".old"}

# ---------------------------------------------------------------------------
# Folder-name conventions
#
# The heart of the generic heuristics. Matched on a whole path SEGMENT, so
# "render" matches but "rendering_notes" does not, and a leading order prefix
# ("05_render", "3_comp") is stripped first because that convention is
# near-universal.
# ---------------------------------------------------------------------------

FOLDER_CATEGORIES = {
    CAT_RENDER: {
        "render", "renders", "rendered", "rendering", "beauty", "aov", "aovs",
        "passes", "frames", "img", "images_out",
    },
    CAT_COMP: {
        "comp", "comps", "compositing", "flipbook", "flipbooks", "playblast",
        "playblasts", "preview", "previews", "review", "dailies",
    },
    CAT_CACHE: {
        "cache", "caches", "geo", "geometry", "sim", "sims", "simulation",
        "flip", "pyro", "vellum", "rbd", "particles", "alembic_cache",
        "ass", "ifd", "rs_proxy", "proxies_geo",
        # A folder named for an interchange format holds exports, not source:
        # "alembic/" is where caches were written to, "models/" is where
        # bought geometry lives.
        "alembic", "vdb", "bgeo", "xparticles", "xp_cache", "sc",
    },
    CAT_SOURCE: {
        "tex", "texture", "textures", "maps", "materials", "hdri", "hdris",
        "reference", "references", "ref", "refs", "plates", "footage",
        "source", "sources", "src", "assets", "photos", "scans", "audio",
        "sound", "music",
    },
    CAT_GEO_IN: {
        "abc", "obj", "fbx", "usd", "models", "meshes", "import", "imports",
        "geo_in", "incoming",
    },
    CAT_SCENE: {
        "scenes", "hip", "hips", "shots", "project_files", "working",
    },
    CAT_BACKUP: {
        "backup", "backups", "autosave", "autosaves", "bak", "old",
        "archive_old", "versions_old",
    },
    CAT_TEMP: {
        "tmp", "temp", "cache_tmp", "thumbnails", "thumbs", "proxy",
        "proxies", "trash", "scratch",
    },
    CAT_DOC: {
        "docs", "doc", "notes", "brief", "briefs", "admin", "invoice",
        "invoices", "contract", "contracts", "email", "emails",
    },
    CAT_DELIVERY: {
        "delivery", "deliveries", "deliverable", "deliverables", "final",
        "finals", "output_final", "master", "masters", "publish", "published",
        "export", "exports", "to_client", "client",
    },
}

# Inverted once at import: segment name -> category.
_FOLDER_LOOKUP = {}
for _cat, _names in FOLDER_CATEGORIES.items():
    for _name in _names:
        _FOLDER_LOOKUP[_name] = _cat

# A leading order prefix is common: 05_render, 3_comp, 010_output.
_ORDER_PREFIX = re.compile(r"^\d{1,3}[_\-. ]")

# Trailing version or number on a folder: render_v03, comp2, output_01.
_TRAILING_VERSION = re.compile(r"[_\-]?v?\d{1,4}$")

# A version token anywhere in a name: shot_v012, cache.v3, name-V02.
VERSION_RE = re.compile(r"[._\-]v(\d{1,4})\b", re.IGNORECASE)

# Names that mark a file as disposable whatever else is true.
BACKUP_HINTS = ("_bak", ".bak", "_backup", "_old", "_tmp", "_temp",
                "_copy", " copy", "_autosave", "-old",
                "_previous", "_wip_old")

# Names matched at the END only, so a marker cannot fire from the middle of a
# word. "_prev" as a plain substring matched "_preview", which is an ordinary
# part of a texture name -- that one hint turned a live GSG material preview
# into a backup.
_BACKUP_TAILS = ("_prev", "-bak", "-backup", "-copy", "_v0_old")

# A name hint is only trusted for SCENE files.
#
# A scene called shot_old.hip really is an old scene, and Houdini and C4D both
# write autosaves by mangling the name. A TEXTURE called leather_old.jpg is
# just a texture with "old" in its name -- artists name assets that way
# constantly, and reading the name as evidence offered live source material
# for deletion. For everything else the FOLDER decides: a backup lives in a
# folder called backup.

# Houdini writes autosaves as scene.hip.bak, scene.hip.1, scene.hip.2 ...
_HIP_AUTOSAVE = re.compile(r"\.hip(?:lc|nc)?\.(?:bak|\d+)$", re.IGNORECASE)

# Cinema 4D writes scene_bak.c4d and scene.c4d.bak
_C4D_BACKUP = re.compile(r"(?:_bak\.c4d|\.c4d\.bak)$", re.IGNORECASE)


def normalise_segment(name):
    """
    Reduce a folder name to the bare word its convention is built on.

    Strips an order prefix, a trailing version, and unifies separators, so
    "05_render_v02", "render-2" and "Renders" all reduce to something the
    lookup can match.
    """
    name = (name or "").strip().lower()
    name = _ORDER_PREFIX.sub("", name)
    name = name.replace("-", "_").strip("_")
    if not name:
        return ""
    if name in _FOLDER_LOOKUP:
        return name
    stripped = _TRAILING_VERSION.sub("", name).strip("_")
    return stripped or name


# Words that mean something on their own but nothing as a compound's tail.
# "cache_old" is an old cache, not a backup folder; "render_notes" is notes
# ABOUT renders. Matching these as the noun reads the name backwards.
_AMBIGUOUS_TAIL = {
    "old", "notes", "ref", "refs", "review", "client", "final", "master",
    "source", "src", "working", "out", "export",
}


def _lookup(word):
    """One word against the table, tolerating a plural either way."""
    if word in _FOLDER_LOOKUP:
        return _FOLDER_LOOKUP[word]
    if word.endswith("s") and word[:-1] in _FOLDER_LOOKUP:
        return _FOLDER_LOOKUP[word[:-1]]
    if (word + "s") in _FOLDER_LOOKUP:
        return _FOLDER_LOOKUP[word + "s"]
    return None


def category_for_segment(name):
    """The category a single folder name implies, or None."""
    normal = normalise_segment(name)
    if not normal:
        return None

    found = _lookup(normal)
    if found:
        return found

    # Compound names are the norm in these trees: flip_sim, pyro_cache,
    # rbd_sim, tex_source. Only the LAST word is consulted, because it is the
    # noun and everything before it qualifies -- "flip_sim" is a sim.
    #
    # Scanning all the words instead is tempting and wrong: it turns
    # "rendering_notes" into docs and "shot_01_anim" into scenes, matching on
    # a word that was never the subject. One word, the last one, or nothing.
    words = [w for w in normal.split("_") if w]
    if len(words) > 1 and words[-1] not in _AMBIGUOUS_TAIL:
        return _lookup(words[-1])

    return None


def category_from_path(path, root):
    """
    The category implied by the folders a file sits in.

    Reads the path from the DEEPEST segment outward, because the nearest
    folder is the most specific statement about the file: in
    "render/v02/tex_ref" the file is reference, not a render.

    Only segments BELOW the project root are considered -- a project living in
    "D:/renders/shot01" must not have its every file called a render.
    """
    path_key = key(path)
    root_key = key(root)
    inside = path_key[len(root_key):] if path_key.startswith(root_key) \
        else path_key

    parts = [p for p in os.path.dirname(inside).split("/") if p]
    for segment in reversed(parts):
        found = category_for_segment(segment)
        if found:
            return found
    return None


def category_from_ext(path):
    """The category implied by a file's extension alone."""
    ext = file_ext(path)

    if ext in scene_parser.SCENE_EXTS:
        return CAT_SCENE
    if ext in BACKUP_EXTS:
        return CAT_BACKUP
    if ext in TEMP_EXTS:
        return CAT_TEMP
    if ext in CACHE_EXTS or ext in TEXTURE_CACHE_EXTS:
        return CAT_CACHE
    if ext in GEO_EXTS or ext in MODEL_SIDECAR_EXTS:
        # A .mtl is nothing without its .obj and vice versa, so it travels
        # with the model rather than being judged on the folder it sits in.
        return CAT_GEO_IN
    if ext in DOC_EXTS:
        return CAT_DOC
    if ext in AUDIO_EXTS:
        return CAT_SOURCE
    if ext in VIDEO_EXTS:
        # A video is source footage or a delivery depending on where it sits;
        # the folder decides. Unqualified, it is worth a look.
        return None
    if ext in IMAGE_EXTS:
        # Likewise: an .exr is a texture, a render, or a plate by location.
        return None
    return None


def is_backup_name(path):
    """
    True when a filename marks itself as a backup or autosave.

    Applies the name hints only to SCENE files. On assets the hints produced
    real false positives on a live project: "leather (32) copy.jpg" and
    "..._KnittedCheckerFabricWhiteandNavy_preview.jpg" were both flagged --
    the second because "_prev" matched inside "_preview". Neither is a backup;
    they are how artists name textures.

    An autosave pattern still fires whatever the extension, because those are
    written by the application and unambiguous.
    """
    name = os.path.basename(key(path))

    # Application-written autosaves: shot.hip.bak, shot.hip.3, shot_bak.c4d.
    if _HIP_AUTOSAVE.search(name) or _C4D_BACKUP.search(name):
        return True

    if file_ext(name) not in scene_parser.SCENE_EXTS:
        return False

    stem = os.path.splitext(name)[0]
    if any(hint in stem for hint in BACKUP_HINTS):
        return True
    # Tail-only hints, so a marker cannot fire from mid-word.
    return stem.endswith(_BACKUP_TAILS)


def version_of(path):
    """The version number in a filename, or None."""
    match = VERSION_RE.search(os.path.basename(key(path)))
    return int(match.group(1)) if match else None


def version_stem(path):
    """A filename with its version token removed, for grouping versions."""
    name = os.path.basename(key(path))
    return VERSION_RE.sub("", name, count=1)


def classify(path, root, is_dir=False):
    """
    The category of one path. Never returns None -- CAT_OTHER is the floor.

    Extension and folder are both evidence and neither always wins. The
    ordering below is what experience with these folder trees says is right:

      - A self-declared backup name beats everything: a _bak.c4d in scenes/
        is a backup, not a scene.
      - So does a backup or temp FOLDER. A scene inside backup/ is a backup
        copy of a scene -- that is what the folder is for -- and treating it
        as a live scene made the folder Keep and left it out of "tick all
        Drop" entirely.
      - Otherwise a scene file is a scene wherever it sits.
      - The FOLDER wins for ambiguous media, because an .exr means nothing on
        its own -- render/, tex/ and plates/ are what tell you.
      - Extension wins for unambiguous types: a .vdb in tex/ is still a cache.
    """
    if is_dir:
        return category_for_segment(os.path.basename(clean(path))) or CAT_OTHER

    ext = file_ext(path)

    if is_backup_name(path):
        return CAT_BACKUP

    by_folder = category_from_path(path, root)
    if by_folder in (CAT_BACKUP, CAT_TEMP):
        return by_folder

    if ext in scene_parser.SCENE_EXTS:
        return CAT_SCENE

    by_ext = category_from_ext(path)

    # Ambiguous media -- images and video -- take the folder's word.
    if by_ext is None:
        if by_folder:
            return by_folder
        if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
            # Unplaced media, sitting loose. Source is the safe reading: it
            # errs toward KEEP.
            return CAT_SOURCE
        return CAT_OTHER

    # An unambiguous extension normally wins, with one exception: a backup or
    # temp FOLDER swallows whatever is in it. A .vdb under backup/ is a
    # backup, however much it looks like a cache.
    if by_folder in (CAT_BACKUP, CAT_TEMP):
        return by_folder

    # Some interchange geometry genuinely does not say what it is by
    # extension. An .abc is imported source in models/ and a generated cache
    # in cache/ or alembic/, and the difference is the whole verdict: one is
    # irreplaceable, the other re-cooks.
    #
    # Found the hard way: a 3 GB xpTrail.abc in an "R&D/alembic" folder was
    # 88% of a real project and got called irreplaceable source.
    #
    # But this applies ONLY to the formats a DCC writes out in bulk. .obj,
    # .fbx and .mtl are how models ARRIVE -- bought, scanned, or sent by a
    # client -- and calling one a cache because of the folder it sits in
    # offers an irreplaceable model up for deletion. A folder name is not
    # evidence enough for that.
    if by_ext == CAT_GEO_IN and by_folder in (CAT_CACHE, CAT_RENDER,
                                              CAT_COMP) \
            and ext in CACHEABLE_GEO_EXTS:
        return CAT_CACHE

    return by_ext


def verdict_for(category, referenced=None, superseded=False,
                scene_missing=False, trust_references=True):
    """
    Turn a category plus evidence into a verdict, with a reason.

    Returns (verdict, reason). The evidence flags are all optional because the
    scan applies what it has -- a folder-level verdict has no reference data,
    a file-level one does.

    Every rule here moves in one direction only, and never past REVIEW toward
    DROP on reference evidence alone. Nothing gets promoted to DROP by not
    being referenced; that is exactly the mistake that makes a cleaning tool
    dangerous.
    """
    base = CATEGORY_VERDICT.get(category, REVIEW)
    reason = CATEGORY_WHY.get(category, "")

    # A superseded version is the strongest signal there is. It applies to
    # every category, including the ones that otherwise never drop.
    if superseded:
        return DROP, "A newer version of this exists alongside it."

    # A cache is only safely regenerable while the scene that cooks it still
    # exists. Without it, the cache IS the asset.
    if category == CAT_CACHE and scene_missing:
        return REVIEW, ("Regenerable in principle, but no scene here "
                        "references it -- re-cooking may not be possible.")

    # With a scene we could not read, "regenerable" is an assumption rather
    # than a finding: the cache may be driven by that scene, and we would
    # never see the link. Cinema 4D projects hit this every time.
    #
    # Only applies to a cache nothing was found to reference. One we DID find
    # a reference for is confirmed live, and that evidence stands whatever
    # else in the project was unreadable.
    if category == CAT_CACHE and not trust_references and not referenced:
        return REVIEW, ("Probably regenerable, but a scene in this project "
                        "could not be read -- verify before dropping.")

    # A referenced render is one the project still actively uses, likely as a
    # comp input. Not a drop candidate.
    if category in (CAT_RENDER, CAT_COMP) and referenced:
        return KEEP, "Referenced by a scene in this project -- still in use."

    return base, reason


def sort_key(verdict, size_bytes):
    """
    Order for the report: worst verdict first, then biggest.

    Sorting by size alone buries a 40 GB drop under a 400 GB keep; sorting by
    verdict alone gives no sense of what is worth acting on.
    """
    return (VERDICT_ORDER.get(verdict, 1), -size_bytes)
