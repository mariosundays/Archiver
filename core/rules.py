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

# Why each category defaults where it does.
#
# TWO forms, because a table column and an explanation want different things.
# The short one is what the Why column shows: a few words, no sentence, and
# nothing the Verdict, Confidence or Folder columns already say. The long one
# is the full argument, and lives in the detail strip and the tooltip where
# there is room for it.
#
# The old single form ran to 70 characters -- "Comp / flipbooks - Superseded
# -- a higher version of this folder exists alongside it." -- of which the
# first half repeated the category and the rest was truncated away.
CATEGORY_WHY_SHORT = {
    CAT_SCENE: "the project itself",
    CAT_SOURCE: "cannot be remade",
    CAT_GEO_IN: "imported, original may be gone",
    CAT_DELIVERY: "the finished work",
    CAT_DOC: "small, worth the context",
    CAT_CACHE: "re-cookable",
    CAT_RENDER: "re-renderable, costly",
    CAT_COMP: "re-exportable from the comp",
    CAT_BACKUP: "the scene supersedes it",
    CAT_TEMP: "disposable",
    CAT_OTHER: "unrecognised — look first",
}

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

# Folder names for simulations that are slow to re-cook. "Regenerable" is
# true of these and still beside the point: re-running a FLIP or pyro sim is
# an afternoon, not a button press, so the report should say so rather than
# imply the cache is free to lose.
EXPENSIVE_SIM_WORDS = {
    "flip", "pyro", "smoke", "fire", "vellum", "cloth", "rbd", "crowd",
    "whitewater", "spray", "foam", "bubbles", "particles", "sim", "sims",
    "simulation",
}


def is_expensive_sim(path):
    """
    True when a path sits under a folder named for a slow simulation.

    Matches ANY word in a segment, not just the whole name, because real
    folders are called "pyro_sim", "RBD_SIM" and
    "AMA_DESIGN_AD_Swipe_v002.RBD_SIM". The compound-tail rule used for
    categories is deliberately strict to avoid false categories; here a false
    positive only adds a warning, so the looser match is the right trade.
    """
    for segment in clean(path).lower().split("/"):
        segment = _ORDER_PREFIX.sub("", segment)
        for word in re.split(r"[^a-z0-9]+", segment):
            if word in EXPENSIVE_SIM_WORDS:
                return True
    return False


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
        "ass", "ifd", "rs_proxy", "proxies_geo", "whitewater", "spray",
        "foam", "bubbles", "smoke", "fire", "cloth", "crowd",
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

# A version token anywhere in a name: shot_v012, cache.v3, name-V02, and
# crucially SHOT_v002_SH060 -- a version with more name after it.
#
# The old pattern ended in \b, which does not match between "2" and "_"
# because underscore is a word character. So every folder named
# "..._v002_SH060" -- a whole project's worth of dailies -- had no detectable
# version at all, and none of them were ever seen as superseded.
#
# The trailing group instead requires the digits to END the name or be
# followed by a separator, which is what "the version token stops here"
# actually means.
VERSION_RE = re.compile(r"[._\-]v(\d{1,4})(?=[._\-]|$)", re.IGNORECASE)

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
    reason = (CATEGORY_WHY.get(category, ""),
              CATEGORY_WHY_SHORT.get(category, ""))

    # A superseded version is the strongest signal there is. It applies to
    # every category, including the ones that otherwise never drop.
    if superseded:
        return DROP, ("A newer version of this exists alongside it.",
                      "a newer version exists")

    # A cache is only safely regenerable while the scene that cooks it still
    # exists. Without it, the cache IS the asset.
    # A cache splits three ways, and the difference is the whole decision.
    #
    #   PROVEN     a readable scene names it. You know what re-cooks it, and
    #              you know what breaks if it goes.
    #   ORPHANED   every scene was readable and none of them named it. The
    #              thing that made it is gone, so "regenerable" may be false.
    #   UNKNOWN    a scene could not be read, so nothing was checked against
    #              it. On a Cinema 4D project that is every scene.
    #
    # Collapsing the last two into one "unreferenced" verdict is what makes a
    # tool untrustworthy on mixed projects: a 40-minute sim whose C4D scene
    # cannot be read reads identically to genuine junk.
    if category == CAT_CACHE and referenced:
        return DROP, ("Regenerable -- a scene in this project reads it, so "
                      "it can be re-cooked.", "a scene here reads it")

    if category == CAT_CACHE and scene_missing:
        return REVIEW, ("No scene in this project references it. Whatever "
                        "made it is gone, so it may NOT be re-cookable.",
                        "orphaned — no scene reads it")

    if category == CAT_CACHE and not trust_references:
        return REVIEW, ("UNVERIFIED -- a scene here could not be read "
                        "(Cinema 4D), so this may be driven by it. Nothing "
                        "was checked against those scenes.",
                        "unverified — a C4D scene is unreadable")

    # A referenced render is one the project still actively uses, likely as a
    # comp input. Not a drop candidate.
    if category in (CAT_RENDER, CAT_COMP) and referenced:
        return KEEP, ("Referenced by a scene in this project -- still in "
                      "use.", "a scene here uses it")

    return base, reason


def sort_key(verdict, size_bytes):
    """
    Order for the report: worst verdict first, then biggest.

    Sorting by size alone buries a 40 GB drop under a 400 GB keep; sorting by
    verdict alone gives no sense of what is worth acting on.
    """
    return (VERDICT_ORDER.get(verdict, 1), -size_bytes)


# ---------------------------------------------------------------------------
# Confidence
#
# Deliberately words, not a percentage. A number like "87% likely unused"
# would be invented -- there is no calibration data behind it -- and false
# precision on a tool that deletes things invites acting without checking.
#
# What IS real is how many independent signals agree, and each one is a claim
# you can go and verify. So the report says how much evidence there is and
# names it, rather than compressing it into a figure.
# ---------------------------------------------------------------------------

STRONG = "strong"
MODERATE = "moderate"
WEAK = "weak"

CONFIDENCE_LABEL = {
    STRONG: "STRONG",
    MODERATE: "MODERATE",
    WEAK: "WEAK",
}


def confidence(signals):
    """
    Turn a list of agreeing signals into a confidence word.

    Two or more independent signals is strong: each one alone can mislead,
    but they fail in different ways, so agreement means something.
    """
    count = len(signals)
    if count >= 2:
        return STRONG
    if count == 1:
        return MODERATE
    return WEAK


def drop_signals(category, superseded=False, referenced=None,
                 trust_references=True, expensive=False):
    """
    The independent reasons to believe something is safe to drop.

    Each is phrased as a fact the user can check, because the point is to let
    them verify the verdict rather than take it on trust.
    """
    signals = []

    if superseded:
        signals.append("a newer version sits alongside it")

    if category in (CAT_RENDER, CAT_COMP) and not expensive:
        signals.append("it is output, re-makeable from the scene")

    if category == CAT_CACHE and referenced and trust_references:
        signals.append("a readable scene names it, so it re-cooks")

    if category in (CAT_BACKUP, CAT_TEMP):
        signals.append("its folder marks it as disposable")

    return signals
