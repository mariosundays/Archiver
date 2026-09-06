# Archiver -- walk a project, classify everything, report what it found.
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
The scan: one walk of the project, then a verdict on everything in it.

Report-only. Nothing in this module writes, moves, or deletes anything -- the
only filesystem calls are walk, stat, and the isdir/isfile checks the parser
needs to confirm a reference. That is a property worth keeping: as long as it
holds, a scan can never cost you anything.

Structure of a scan:

  1. Walk the tree once, collecting every file with its size and mtime.
  2. Find the scene files among them and read what each one references.
  3. Classify every file into a category.
  4. Group files into sequences, then sequences into folders.
  5. Apply verdicts, using references and version evidence.

The unit the report talks in is a FOLDER, not a file. A project has hundreds
of thousands of files and about forty folders that matter, and a per-file list
is unreadable and unactionable. Files are still tracked underneath, so a
folder can always be opened up.
"""

import os
import time
from collections import defaultdict

from . import rules, scene_parser
from .scene_parser import clean, file_ext, key

# Never walked into. Version control, OS clutter, and our own output.
SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "$recycle.bin",
    "system volume information", ".dropbox.cache", ".archiver",
    "node_modules", ".venv", "venv",
}

# Frame padding in a filename: the trailing digits of "render.0042.exr".
import re
_FRAME_RE = re.compile(r"^(?P<stem>.*?)(?P<frame>\d{3,8})$")

# A UDIM tile is a 4-digit number in the 1001+ range.
_UDIM_RE = re.compile(r"^(?P<stem>.*?)(?P<udim>1\d{3})$")


def human(size):
    """Byte count as a short human string."""
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return "%d B" % size
            return "%.1f %s" % (size, unit)
        size /= 1024
    return "%.1f TB" % size


def age_days(mtime):
    """Days since a timestamp, or None."""
    if not mtime:
        return None
    return max(0, int((time.time() - mtime) / 86400))


def age_label(mtime):
    """Human age: '3 days', '5 months', '2 years'."""
    days = age_days(mtime)
    if days is None:
        return ""
    if days < 1:
        return "today"
    if days == 1:
        return "1 day"
    if days < 60:
        return "%d days" % days
    months = days // 30
    if months < 24:
        return "%d months" % months
    return "%d years" % (days // 365)


def split_frame(path):
    """
    Split a path into (stem, frame) when it ends in a frame number.

    Returns (None, None) when it does not. UDIM tiles are deliberately treated
    the same way -- a UDIM set is a sequence for our purposes.
    """
    directory = os.path.dirname(path)
    name = os.path.basename(path)
    ext = file_ext(name)
    base = name[:-len(ext)] if ext else name

    match = _FRAME_RE.match(base)
    if not match:
        return None, None
    stem = match.group("stem")
    # A name that is ALL digits has no stem to group on.
    if not stem:
        return None, None
    return clean(directory + "/" + stem + "*" + ext), match.group("frame")


class FileEntry(object):
    """One file on disk, with what we worked out about it."""

    __slots__ = ("path", "size", "mtime", "category", "referenced",
                 "superseded", "used_by")

    def __init__(self, path, size, mtime):
        self.path = path
        self.size = size
        self.mtime = mtime
        self.category = rules.CAT_OTHER
        self.referenced = False
        self.superseded = False
        self.used_by = []       # scenes naming this file, when readable

    @property
    def name(self):
        return os.path.basename(self.path)


class Sequence(object):
    """
    A run of numbered frames collapsed into one row.

    A 3000-frame render is one thing to decide about, not 3000. Collapsing
    them is what makes the report readable at all.
    """

    def __init__(self, pattern, entries):
        self.pattern = pattern
        self.entries = entries

    @property
    def count(self):
        return len(self.entries)

    @property
    def size(self):
        return sum(entry.size for entry in self.entries)

    @property
    def mtime(self):
        return max((entry.mtime for entry in self.entries), default=0)

    @property
    def name(self):
        base = os.path.basename(self.pattern)
        if self.count > 1:
            return "%s  (%d frames)" % (base, self.count)
        return base

    @property
    def category(self):
        return self.entries[0].category if self.entries else rules.CAT_OTHER

    @property
    def referenced(self):
        return any(entry.referenced for entry in self.entries)

    @property
    def superseded(self):
        return all(entry.superseded for entry in self.entries)


class FolderReport(object):
    """
    One folder's worth of findings -- the unit the report is built from.

    A folder holds the files directly in it, not its subfolders' files; each
    subfolder is its own row. That keeps sizes non-overlapping, so the totals
    add up.
    """

    def __init__(self, path, root):
        self.path = path
        self.root = root
        self.entries = []
        self.sequences = []
        self.verdict = rules.REVIEW
        self.reason = ""
        self.category = rules.CAT_OTHER
        self.is_empty = False

    @property
    def relative(self):
        rel = clean(self.path)[len(clean(self.root)):].lstrip("/")
        return rel or "."

    @property
    def name(self):
        return os.path.basename(clean(self.path)) or clean(self.path)

    @property
    def size(self):
        return sum(entry.size for entry in self.entries)

    @property
    def count(self):
        return len(self.entries)

    @property
    def mtime(self):
        return max((entry.mtime for entry in self.entries), default=0)

    @property
    def age(self):
        return age_label(self.mtime)

    @property
    def human_size(self):
        return human(self.size)

    @property
    def referenced_count(self):
        return sum(1 for entry in self.entries if entry.referenced)


class ScanResult(object):
    """Everything one scan found."""

    def __init__(self, root):
        self.root = root
        self.folders = []
        self.scenes = []
        self.errors = []
        self.opaque_scenes = []     # scenes whose format we cannot read
        self.empty_folders = []
        self.duration = 0.0

    @property
    def references_trustworthy(self):
        """
        False when some scene could not be read.

        With an unreadable scene in the project, "nothing references this" is
        not a fact -- it is an absence of evidence. Every verdict that leans
        on reference data has to be held back, or a .abc loaded by an opaque
        .c4d gets archived away.
        """
        return not self.opaque_scenes

    @property
    def total_size(self):
        return sum(folder.size for folder in self.folders)

    @property
    def total_files(self):
        return sum(folder.count for folder in self.folders)

    def by_verdict(self, verdict):
        return [f for f in self.folders if f.verdict == verdict]

    def size_of(self, verdict):
        return sum(f.size for f in self.by_verdict(verdict))

    def totals(self):
        """(verdict -> (size, folder count, file count)) for the summary."""
        out = {}
        for verdict in (rules.KEEP, rules.REVIEW, rules.DROP):
            folders = self.by_verdict(verdict)
            out[verdict] = (
                sum(f.size for f in folders),
                len(folders),
                sum(f.count for f in folders),
            )
        return out

    def by_category(self):
        """(category -> total size) across every folder, biggest first."""
        sizes = defaultdict(int)
        for folder in self.folders:
            for entry in folder.entries:
                sizes[entry.category] += entry.size
        return sorted(sizes.items(), key=lambda kv: -kv[1])

    def reclaimable(self):
        """Bytes in DROP folders -- what a clean would actually free."""
        return self.size_of(rules.DROP)

    def files_in_category(self, category):
        """Every file of one category, as sequences, biggest first."""
        return group_sequences(
            [entry for folder in self.folders for entry in folder.entries
             if entry.category == category])

    def files_with_verdict(self, verdict):
        """
        Every file in folders carrying one verdict, as sequences.

        Verdict lives on the FOLDER, not the file, so this asks which folders
        earned it and takes their contents -- the same unit the summary bar
        measured, so the two always agree.
        """
        return group_sequences(
            [entry for folder in self.folders
             if folder.verdict == verdict for entry in folder.entries])


def walk(root, progress=None):
    """
    Every file under root, as FileEntry, grouped by containing folder.

    Hand-rolled os.scandir recursion rather than os.walk, for two reasons that
    both matter on Windows:

    A DirEntry from scandir already carries the size and mtime -- the Win32
    find data includes them -- so entry.stat() costs no syscall for an ordinary
    file. os.walk yields bare names and throws those entries away, forcing a
    real os.stat() per file. On a project with hundreds of thousands of frames
    that is the difference between one pass and two.

    And follow_symlinks=False keeps us out of directory junctions. Windows is
    full of them (C:/Users/All Users, Documents and Settings), and following
    one either double-counts a folder or loops forever.

    Returns (folders, errors), mapping a directory path to its FileEntry list.
    """
    root = clean(root)
    folders = defaultdict(list)
    errors = []
    seen = 0

    # An explicit stack, not recursion. Project trees are usually shallow, but
    # a runaway junction or a deeply nested cache would blow Python's frame
    # limit, and a scan crashing on someone's real project is unacceptable.
    stack = [root]
    while stack:
        directory = stack.pop()
        # Every directory gets an entry, even an empty one. defaultdict would
        # silently omit them, and an empty folder is a thing worth reporting
        # -- a project full of them is a project someone half-cleaned.
        folders[clean(directory)]
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        # follow_symlinks=False: no syscall, and no junctions.
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() not in SKIP_DIRS:
                                stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                    except (OSError, IOError) as exc:
                        errors.append("%s: %s" % (entry.path, exc))
                        continue

                    folders[clean(directory)].append(
                        FileEntry(clean(entry.path), stat.st_size,
                                  stat.st_mtime))
                    seen += 1
        except (OSError, IOError) as exc:
            errors.append("%s: %s" % (directory, exc))
            continue

        if progress is not None and not progress(seen, clean(directory)):
            break

    return folders, errors


def find_scenes(folders):
    """Every scene file found in the walk, newest first."""
    scenes = []
    for entries in folders.values():
        for entry in entries:
            if scene_parser.is_scene(entry.path) \
                    and not rules.is_backup_name(entry.path):
                scenes.append(entry)
    scenes.sort(key=lambda e: -e.mtime)
    return scenes


def read_references(scenes, root, progress=None):
    """
    Read every scene and collect what the project as a whole references.

    Returns (paths, folders, opaque, used_by): the referenced file paths, the
    directories some scene builds paths inside, the scenes whose format we
    could not read at all, and a map of path -> the scenes naming it.

    That third value is the important one. A scene we cannot read contributes
    no references, so everything it uses looks unreferenced -- and acting on
    that would archive away live assets. The caller needs to distinguish "read
    it, found nothing" from "could not read it".

    used_by is what lets the UI answer "which scene needs this?", which is the
    question you actually ask before deleting a 3 GB cache. Knowing a file is
    referenced is much less useful than knowing what would break.
    """
    root = clean(root)
    paths = set()
    ref_folders = set()
    opaque = []
    used_by = {}
    folder_used_by = {}

    for index, scene in enumerate(scenes):
        if progress is not None and not progress(index, len(scenes),
                                                 scene.path):
            break

        if scene_parser.is_opaque(scene.path):
            opaque.append(scene.path)
            continue

        try:
            found = scene_parser.paths_in_scene(scene.path, root)
            folders = scene_parser.folders_in_scene(scene.path, root, root)
        except Exception as exc:      # a malformed scene must not stop a scan
            paths.add(key(scene.path))
            del exc
            continue

        paths |= found
        ref_folders |= folders
        for path in found:
            used_by.setdefault(path, []).append(scene.path)
        for folder in folders:
            folder_used_by.setdefault(folder, []).append(scene.path)

    return paths, ref_folders, opaque, (used_by, folder_used_by)


def mark_referenced(folders, referenced_paths, referenced_folders,
                    attribution=None):
    """
    Flag every file some scene refers to, directly or by folder, and record
    WHICH scenes those are.

    Sequence-aware: a scene naming "cache.$F4.bgeo" resolves to the frames
    that existed when it was read, so a frame outside that range still counts
    as referenced if its siblings are. Missing that would call half a cache
    unused.
    """
    used_by, folder_used_by = attribution or ({}, {})

    stems = {}
    for path in referenced_paths:
        stem, _frame = split_frame(path)
        if stem:
            stems.setdefault(stem, []).extend(used_by.get(path, []))

    for entries in folders.values():
        for entry in entries:
            path_key = key(entry.path)

            if path_key in referenced_paths:
                entry.referenced = True
                entry.used_by = list(used_by.get(path_key, ()))
                continue

            for folder in referenced_folders:
                if path_key.startswith(folder + "/"):
                    entry.referenced = True
                    entry.used_by = list(folder_used_by.get(folder, ()))
                    break
            if entry.referenced:
                continue

            stem, _frame = split_frame(path_key)
            if stem and stem in stems:
                entry.referenced = True
                # A frame outside the resolved range belongs to whichever
                # scenes named the sequence.
                entry.used_by = list(dict.fromkeys(stems[stem]))


def mark_superseded(folders):
    """
    Flag files that a higher version of themselves sits next to.

    Compared within a folder only. Across folders "v01/render.exr" versus
    "v02/render.exr" is the same filename twice, and the folder-level version
    check handles that case instead.
    """
    for entries in folders.values():
        highest = {}
        for entry in entries:
            version = rules.version_of(entry.path)
            if version is None:
                continue
            stem = rules.version_stem(entry.path)
            if version > highest.get(stem, -1):
                highest[stem] = version

        for entry in entries:
            version = rules.version_of(entry.path)
            if version is None:
                continue
            stem = rules.version_stem(entry.path)
            if highest.get(stem, -1) > version:
                entry.superseded = True


def mark_superseded_folders(folders, root):
    """
    Flag whole folders that a higher-numbered sibling supersedes.

    The version-per-file check cannot see this case: "render/v01/beauty.exr"
    and "render/v03/beauty.exr" are the same filename in different folders,
    and the version lives in the FOLDER name. This is the single most useful
    rule for archiving -- old render versions are usually the biggest
    reclaimable thing in a project.

    Only applies where the sibling folders are version names and nothing else
    differs, so "render/v01" versus "render/final" is left alone. Returns the
    set of folder paths judged superseded.

    Deliberately does NOT apply to source or scene folders: a tex/v01 may hold
    textures that tex/v03 does not, and losing those is unrecoverable.
    """
    by_parent = defaultdict(list)
    for path in folders:
        parent = clean(os.path.dirname(path))
        name = os.path.basename(clean(path))
        version = rules.version_of(name) if name else None
        # A bare "v03" has no stem for version_of's separator to find.
        if version is None:
            bare = re.match(r"^v(\d{1,4})$", name.lower())
            version = int(bare.group(1)) if bare else None
        if version is not None:
            by_parent[parent].append((version, path))

    superseded = set()
    for parent, versions in by_parent.items():
        if len(versions) < 2:
            continue
        highest = max(version for version, _path in versions)
        for version, path in versions:
            if version >= highest:
                continue
            # Only supersede regenerable output. Source material never.
            category = rules.category_from_path(path + "/x", root) \
                or rules.category_for_segment(os.path.basename(parent))
            if category in (rules.CAT_RENDER, rules.CAT_COMP,
                            rules.CAT_CACHE):
                superseded.add(path)

    return superseded


def group_sequences(entries):
    """Collapse numbered frames into Sequence rows, singles included."""
    groups = defaultdict(list)
    singles = []

    for entry in entries:
        stem, _frame = split_frame(entry.path)
        if stem:
            groups[stem].append(entry)
        else:
            singles.append(entry)

    sequences = [Sequence(pattern, sorted(items, key=lambda e: e.path))
                 for pattern, items in groups.items()]
    sequences.extend(Sequence(entry.path, [entry]) for entry in singles)
    sequences.sort(key=lambda s: -s.size)
    return sequences


def _folder_verdict(folder, scene_count, superseded_folders=(),
                    trust_references=True):
    """
    One folder's verdict, from the files in it.

    A folder is not a single thing, so the rule is deliberately conservative:
    the folder takes the SAFEST verdict any meaningful file in it earned. One
    irreplaceable texture in a cache folder makes the whole folder worth
    reviewing, which is the correct outcome -- the alternative recommends
    dropping it.
    """
    if not folder.entries:
        if folder.is_empty:
            return rules.DROP, "Empty folder -- nothing in it, at any depth."
        return rules.KEEP, "Holds only subfolders."

    counts = defaultdict(int)
    for entry in folder.entries:
        counts[entry.category] += 1
    folder.category = max(counts.items(), key=lambda kv: kv[1])[0]

    # A superseded version folder is settled regardless of what is in it: a
    # newer render of the same thing sits alongside.
    if key(folder.path) in superseded_folders:
        return rules.DROP, ("Superseded -- a higher version of this folder "
                            "exists alongside it.")

    best = rules.DROP
    best_reason = ""

    for entry in folder.entries:
        # Only claim a cache is orphaned when we could actually read the
        # scenes. With an unreadable one in the project, an unreferenced cache
        # is just as likely to be one we could not see the reference for.
        scene_missing = (trust_references
                         and entry.category == rules.CAT_CACHE
                         and not entry.referenced
                         and scene_count > 0)
        verdict, reason = rules.verdict_for(
            entry.category,
            referenced=entry.referenced,
            superseded=entry.superseded,
            scene_missing=scene_missing,
            trust_references=trust_references,
        )
        if rules.VERDICT_ORDER[verdict] < rules.VERDICT_ORDER[best]:
            best, best_reason = verdict, reason
        if best == rules.KEEP:
            break

    return best, best_reason


def scan(root, progress=None, scene_progress=None):
    """
    Scan a project folder and report on it. Reads only -- writes nothing.

    progress(files_seen, current_folder) is called during the walk and
    scene_progress(index, total, path) while reading scenes; returning False
    from either cancels the scan.
    """
    started = time.time()
    root = clean(root)
    result = ScanResult(root)

    if not root or not os.path.isdir(root):
        result.errors.append("Not a folder: %s" % root)
        return result

    raw_folders, errors = walk(root, progress)
    result.errors.extend(errors)

    scenes = find_scenes(raw_folders)
    result.scenes = scenes

    referenced_paths, referenced_folders, opaque, attribution =         read_references(scenes, root, scene_progress)
    result.opaque_scenes = opaque
    trust = result.references_trustworthy

    mark_referenced(raw_folders, referenced_paths, referenced_folders,
                    attribution)
    mark_superseded(raw_folders)
    superseded_folders = {key(p)
                          for p in mark_superseded_folders(raw_folders, root)}

    # A folder is empty only when nothing lives under it at any depth: no
    # files of its own, and no descendant with any. A parent that merely holds
    # subfolders is structure, not clutter.
    has_files = {path for path, entries in raw_folders.items() if entries}
    def _occupied(path):
        prefix = key(path) + "/"
        return any(key(other).startswith(prefix) for other in has_files)

    for path, entries in raw_folders.items():
        folder = FolderReport(path, root)
        folder.entries = entries
        for entry in entries:
            entry.category = rules.classify(entry.path, root)
        folder.sequences = group_sequences(entries)

        if not entries and not _occupied(path):
            folder.is_empty = True
            result.empty_folders.append(path)

        folder.verdict, folder.reason = _folder_verdict(
            folder, len(scenes), superseded_folders, trust)
        result.folders.append(folder)

    result.folders.sort(key=lambda f: rules.sort_key(f.verdict, f.size))
    result.duration = time.time() - started
    return result
