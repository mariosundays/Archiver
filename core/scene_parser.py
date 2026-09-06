# Archiver -- scene reference extraction, no DCC required.
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
Read what a scene file references without opening the application.

Every DCC scene format this cares about is a binary container with the asset
paths sitting in it as plain byte runs. That is enough: scrape the printable
runs, pull the path-shaped tokens out, expand whatever variables the format
uses. It is approximate by nature, and that is fine -- the error is one-sided.
A path we find but that is dead costs nothing. A path we MISS could get a live
file archived away, so every ambiguous case resolves toward "referenced".

This is the Houdini-free descendant of AssetCleaner's paths_in_hip(),
generalised past .hip to the other formats a project folder actually contains.

No imports beyond the standard library. Never imports hou, c4d, or Qt.
"""

import os
import re

# ---------------------------------------------------------------------------
# Scene formats we can read
# ---------------------------------------------------------------------------

# Houdini. .hip is the scene; the .bak variants are its autosaves.
HIP_EXTS = (".hip", ".hiplc", ".hipnc")

# Cinema 4D. .c4d is the scene, .lib4d an asset library.
C4D_EXTS = (".c4d", ".lib4d")

# Blender, Maya, Nuke, After Effects, Fusion, Substance.
OTHER_SCENE_EXTS = (
    ".blend",
    ".ma", ".mb",
    ".nk", ".nknc",
    ".aep", ".aepx",
    ".comp",
    ".spp", ".sbs",
)

SCENE_EXTS = HIP_EXTS + C4D_EXTS + OTHER_SCENE_EXTS

# Text-based scene formats. These we can read far more precisely than a binary
# scrape, because the whole file is paths and markup.
TEXT_SCENE_EXTS = (".ma", ".nk", ".nknc", ".usda", ".sbs")

# Scene files can be huge -- a .c4d with baked geometry runs to gigabytes, and
# reading one whole to find a dozen texture paths is a waste. Paths live in the
# scene's tables, which sit near the ends, so read a window at each end.
_HEAD_BYTES = 48 * 1024 * 1024
_TAIL_BYTES = 16 * 1024 * 1024

# Printable runs inside a binary. A path never spans one of these.
_PRINTABLE = re.compile(rb"[ -~]{6,400}")

# Asset extensions worth recognising inside a scene. Kept as one alternation
# so the path regex stays a single pass.
_ASSET_EXT_PATTERN = (
    rb"exr|hdr|hdri|png|jpe?g|tiff?|tga|bmp|dpx|cin|rat|tx|psd|pic|iff|sgi"
    rb"|bgeo\.sc|bgeo|geo|vdb|obj|fbx|ply|stl|usd[acz]?|sim|bclip|abc|rs"
    rb"|c4d|lib4d|mov|mp4|avi|mxf|r3d|braw|wav|aif|aiff|mp3"
)

# A path-looking token ending in an extension we care about.
#
# Deliberately broad on the leading form: a drive letter, a UNC share, or one
# of the variables the DCCs use for "the project folder". The trailing class
# excludes the characters that reliably terminate a path in these files --
# quotes, brackets, whitespace, separators.
_PATH_TOKEN = re.compile(
    rb"(?:[A-Za-z]:[/\\]"
    rb"|\$HIP[/\\]|\$JOB[/\\]"          # Houdini
    rb"|\$\{?PROJECT\}?[/\\]"           # generic / Nuke-ish
    rb"|//)"
    rb"[^\s\"'<>|*\?,;=\)\(\]\[]{2,180}"
    rb"\.(?:" + _ASSET_EXT_PATTERN + rb")\b",
    re.IGNORECASE)

# Cinema 4D stores texture paths RELATIVE to the scene's tex/ folder, with no
# drive letter and no variable -- a bare "wood_diffuse.png" or "sub/x.png".
# A bare-name regex over a binary would match enormous amounts of noise, so
# this is applied only to .c4d files and only for image extensions.
_C4D_RELATIVE = re.compile(
    rb"[A-Za-z0-9_\-][A-Za-z0-9_\-. /\\]{0,120}"
    rb"\.(?:exr|hdr|hdri|png|jpe?g|tiff?|tga|bmp|psd|rs|abc|mov|mp4)\b",
    re.IGNORECASE)

# A path-looking token with NO extension: a folder.
#
# This exists for procedural paths. A Houdini File Cache builds its path at
# cook time from other parameters, so reading a closed scene as text recovers
# the expression, never a usable path. The pieces are still there though --
# a "basedir" holding a literal "$HIP/geo" -- and that is enough to protect the
# folder without pretending to evaluate anything.
_FOLDER_TOKEN = re.compile(
    rb"(?:[A-Za-z]:[/\\]|\$HIP[/\\]|\$JOB[/\\]|\$\{?PROJECT\}?[/\\]|//)"
    rb"[A-Za-z0-9_.\-/\\ ]{1,180}",
    re.IGNORECASE)

# Folders too broad to protect. $HIP itself would cover the whole project and
# make the tool useless.
_TOO_BROAD = {"", ".", "/"}

# Any variable we could not expand ourselves.
VARIABLE_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")

# A frame-number placeholder in any of the forms the DCCs write.
SEQ_PATTERNS = [
    re.compile(r"\$F\d*", re.IGNORECASE),      # Houdini  $F4
    re.compile(r"#+"),                          # Nuke/C4D ####
    re.compile(r"%0?\d*d"),                     # printf   %04d
    re.compile(r"<UDIM>", re.IGNORECASE),       # UDIM tiles
    re.compile(r"<udim>"),
]

COMPOUND_EXTS = (".bgeo.sc", ".bgeo.gz", ".geo.gz", ".vdb.sc")


def clean(path):
    """Normalise a path for comparison: forward slashes, no trailing slash."""
    if not path:
        return ""
    path = str(path).replace("\\", "/").strip()
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def key(path):
    """Lower-cased normalised path -- the form every set and dict uses."""
    return clean(path).lower()


def file_ext(filepath):
    """Extension including the dot, lower case, compound-aware."""
    lowered = key(filepath)
    for compound in COMPOUND_EXTS:
        if lowered.endswith(compound):
            return compound
    return os.path.splitext(lowered)[1]


def is_scene(path):
    """True when a path names a scene file of any supported DCC."""
    return key(path).endswith(SCENE_EXTS)


def is_sequence(path):
    """True when a path holds a frame or UDIM placeholder."""
    return any(pattern.search(path) for pattern in SEQ_PATTERNS)


def sequence_glob(path):
    """Turn every placeholder in a path into a glob wildcard."""
    out = path
    for pattern in SEQ_PATTERNS:
        out = pattern.sub("*", out)
    return out


def expand_glob(path):
    """
    Resolve a path holding placeholders or unknown variables to real files.

    A path we cannot resolve exactly must still match the files it might name,
    or a cache that IS in use looks unused.
    """
    import glob

    pattern = sequence_glob(path)
    pattern = VARIABLE_RE.sub("*", pattern)
    # Collapse runs of wildcards; "*/*" would walk into subfolders we never
    # meant to include.
    pattern = re.sub(r"\*{2,}", "*", pattern)
    if "*" not in pattern:
        return []
    try:
        return [clean(match) for match in glob.iglob(pattern)]
    except (OSError, ValueError):
        return []


def _read_windows(path):
    """
    Read the head and tail of a file, skipping the middle of a huge one.

    Returns the bytes to scan. A scene small enough is read whole.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size <= _HEAD_BYTES + _TAIL_BYTES:
                return handle.read()
            head = handle.read(_HEAD_BYTES)
            handle.seek(-_TAIL_BYTES, os.SEEK_END)
            return head + b"\n" + handle.read()
    except (OSError, IOError, ValueError):
        return b""


def _expand_vars(text, scene_dir, project):
    """
    Expand the project variables we can resolve ourselves.

    Returns a LIST of candidates, because $HIP is genuinely ambiguous here.

    In Houdini $HIP is the scene's own folder. But a project is normally laid
    out with the scenes in a subfolder --

        shot01/scenes/shot01.hip
        shot01/tex/wood.exr

    -- and that scene, opened from a launcher or with $JOB set to the project,
    writes "$HIP/tex/wood.exr" meaning shot01/tex, not shot01/scenes/tex.
    Both readings are real and which one is right depends on how the artist
    had their environment set when they saved.

    So resolve against both and let the disk decide: a candidate that exists
    is a reference, one that does not costs nothing. Erring toward finding too
    many references is the safe direction -- a false reference keeps a file,
    a missed one archives a live asset away.

    Returns [] when the path starts with a variable we cannot resolve, since a
    half-expanded path is worse than none -- it would look relative and
    resolve against the wrong folder entirely.
    """
    lowered = text.lower()

    if lowered.startswith("$hip/"):
        rest = text[5:]
        candidates = [scene_dir + "/" + rest]
        if project and key(project) != key(scene_dir):
            candidates.append(project + "/" + rest)
        return candidates
    if lowered.startswith("$job/"):
        return [project + "/" + text[5:]]
    if lowered.startswith("${project}/"):
        return [project + "/" + text[11:]]
    if lowered.startswith("$project/"):
        return [project + "/" + text[9:]]
    if lowered in ("$hip", "$job", "$project", "${project}"):
        return []
    if text.startswith("$"):
        return []
    return [text]


def paths_in_scene(scene_path, project=None):
    """
    Every asset path a scene file appears to reference, without opening it.

    Returns a set of lower-case absolute paths. Sequence and UDIM patterns are
    expanded against the disk, and the unresolved form is kept too so the
    scene's own reference list still reflects what it asks for.

    Reports what the scene SAYS it uses, including references that no longer
    resolve -- the right side to err on for a tool that recommends deletion.
    """
    scene_dir = clean(os.path.dirname(scene_path))
    project = clean(project or scene_dir)
    data = _read_windows(scene_path)
    if not data:
        return set()

    found = set()
    for run in _PRINTABLE.findall(data):
        for match in _PATH_TOKEN.findall(run):
            raw = match.decode("utf-8", "replace").replace("\\", "/")

            for text in _expand_vars(raw, scene_dir, project):
                if is_sequence(text) or VARIABLE_RE.search(text):
                    for frame in expand_glob(text):
                        found.add(key(frame))
                    found.add(key(text))
                else:
                    found.add(key(text))

    if key(scene_path).endswith(C4D_EXTS):
        found |= _c4d_relative_paths(data, scene_dir)

    return found


def is_opaque(scene_path):
    """
    True when a scene's format hides its paths from a byte scrape.

    Modern Cinema 4D (R20+, certainly 25.x) writes a proprietary compressed
    container: magic "QC4DC4D6", entropy around 7.2 bits/byte, and no zlib
    streams to walk. Verified against real R25 project files -- not one asset
    path survives as plaintext, in ASCII or UTF-16.

    This matters more than it looks. A scene we cannot read contributes no
    references, so every file it uses looks unreferenced. Silently treating
    that as "nothing is referenced" is how a tool archives away a live
    texture, so the scan has to KNOW the difference between "read it, found
    nothing" and "could not read it at all" -- and say so.

    .lib4d is the same container. Older pre-R20 .c4d files are often
    scrapeable, so this checks the magic rather than the extension.
    """
    if not key(scene_path).endswith(C4D_EXTS):
        return False
    try:
        with open(scene_path, "rb") as handle:
            magic = handle.read(8)
    except (OSError, IOError):
        return True
    # "QC4DC4D6" is the R20+ compressed container. Anything else is old
    # enough to be worth scraping.
    return magic[:4] == b"QC4D"


def _c4d_relative_paths(data, scene_dir):
    """
    Resolve Cinema 4D's relative texture references.

    C4D writes texture paths relative to the scene, normally into a sibling
    tex/ folder. A bare name in a binary is far too weak a signal to trust on
    its own, so nothing is returned unless the file is actually THERE -- the
    disk check is what separates a real reference from random bytes.

    Only reaches anything on pre-R20 scenes; see is_opaque().
    """
    found = set()
    roots = [scene_dir, scene_dir + "/tex", scene_dir + "/images"]

    seen = set()
    for run in _PRINTABLE.findall(data):
        for match in _C4D_RELATIVE.findall(run):
            name = match.decode("utf-8", "replace").replace("\\", "/").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            if len(name) < 5:
                continue
            for base in roots:
                candidate = clean(base + "/" + name)
                if os.path.isfile(candidate):
                    found.add(key(candidate))
                    break
    return found


def folders_in_scene(scene_path, project=None, root=None):
    """
    Directories a scene appears to write to or read from.

    Complements paths_in_scene(): that finds literal paths, this finds the
    folder a procedural path is assembled inside. Returns lower-case absolute
    directories that exist on disk.

    Erring toward protecting too much is right here: a wrong guess costs one
    folder left alone, against a re-sim if we guess the other way.
    """
    scene_dir = clean(os.path.dirname(scene_path))
    project = clean(project or scene_dir)
    root = clean(root or project)

    data = _read_windows(scene_path)
    if not data:
        return set()

    # Collect and filter candidates first, then hit the filesystem once per
    # distinct folder. A scene names the same path hundreds of times, and on a
    # network or Dropbox share every isdir() is a round trip.
    candidates = set()
    for run in _PRINTABLE.findall(data):
        for match in _FOLDER_TOKEN.findall(run):
            text = match.decode("utf-8", "replace").replace("\\", "/").strip()

            # A token with an extension is a file; paths_in_scene has it.
            if file_ext(text):
                continue

            for expanded in _expand_vars(text, scene_dir, project):
                expanded = clean(expanded)
                if not expanded or expanded.lower() in _TOO_BROAD:
                    continue
                # The project root itself is far too broad.
                if key(expanded) in (key(scene_dir), key(project), key(root)):
                    continue
                if len(expanded.rstrip("/").split("/")) < 2:
                    continue
                candidates.add(key(expanded))

    if root:
        candidates = {c for c in candidates if is_inside(c, root)}

    return {c for c in candidates if os.path.isdir(c)}


def is_inside(filepath, root):
    """True when a path lives under root. Segment-aware, so a sibling folder
    sharing a name prefix does not count as inside."""
    if not filepath or not root:
        return False
    path_key = key(filepath)
    root_key = key(root)
    return path_key == root_key or path_key.startswith(root_key + "/")
