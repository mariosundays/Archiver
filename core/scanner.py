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

from . import actions, rules, scene_parser
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
                 "superseded", "used_by", "folder")

    def __init__(self, path, size, mtime):
        self.path = path
        self.size = size
        self.mtime = mtime
        self.category = rules.CAT_OTHER
        self.referenced = False
        self.superseded = False
        self.used_by = []       # scenes naming this file, when readable
        self.folder = None      # the FolderReport holding it

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

    @property
    def folder(self):
        """The FolderReport these frames live in, for verdict and reason."""
        return getattr(self.entries[0], "folder", None) if self.entries             else None


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
        self.reason = ""        # the full argument, for the detail strip
        self.reason_short = ""  # a few words, for the Why column
        self.category = rules.CAT_OTHER
        self.is_empty = False
        self.superseded = False
        self.confidence = None
        self.signals = []

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
        self.opaque_scenes = []     # scenes whose references we lack
        self.stale_sidecars = []    # read from a sidecar older than the scene
        self.empty_folders = []
        self.staged_bytes = 0       # sitting in _toDelete, already decided
        self.staged_files = 0
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
        """
        Every file of one category, as sequences, biggest first.

        Each entry carries a back-reference to its FolderReport, so the panel
        can show the same verdict, confidence and reason the findings tab
        does. Without it, drilling into a bar segment gave a bare file list
        and the same question had two different answers depending on where
        you asked it.
        """
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


def walk(root, progress=None, staging=None):
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
    staging_key = key(staging) if staging else None
    folders = defaultdict(list)
    errors = []
    seen = 0
    staged = [0, 0]         # bytes, files

    # An explicit stack, not recursion. Project trees are usually shallow, but
    # a runaway junction or a deeply nested cache would blow Python's frame
    # limit, and a scan crashing on someone's real project is unacceptable.
    stack = [root]
    while stack:
        directory = stack.pop()

        # _toDelete holds what the user already decided against. Re-scanning
        # it means re-judging settled decisions, inflating every total, and
        # showing the staging folder itself as a candidate -- on a real
        # project it appeared as a 2.8 GB row marked Keep. Measure it so the
        # UI can say what is waiting, and walk no further.
        if staging_key and key(directory) == staging_key:
            for folder, _dirs, names in os.walk(directory):
                for name in names:
                    # The manifest is Archiver's own bookkeeping, not the
                    # user's data. Counting it makes "2.8 GB in 12 files"
                    # out of 11 staged files plus our own record.
                    if name == actions.MANIFEST:
                        continue
                    try:
                        staged[0] += os.path.getsize(
                            os.path.join(folder, name))
                        staged[1] += 1
                    except OSError:
                        pass
            continue
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
                        # Our own report lives at the project root. Counting
                        # it would make the scan report on itself, and grow
                        # the file count by one every run.
                        if entry.name == actions.REPORT:
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

    return folders, errors, staged


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

    Returns (paths, folders, opaque, used_by, stale): the referenced file
    paths, the directories some scene builds paths inside, the scenes whose
    references we could not establish, a map of path -> the scenes naming it,
    and the scenes read from a sidecar that has fallen behind them.

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
    stale = []
    used_by = {}
    folder_used_by = {}

    for index, scene in enumerate(scenes):
        if progress is not None and not progress(index, len(scenes),
                                                 scene.path):
            break

        if scene_parser.is_opaque(scene.path):
            # Unreadable by scrape, but the application may have written its
            # asset list down beside it. See core/sidecar.py.
            found, fresh = scene_parser.paths_from_sidecar(scene.path, root)
            if found is None:
                opaque.append(scene.path)
                continue

            paths |= found
            for path in found:
                used_by.setdefault(path, []).append(scene.path)

            # A stale sidecar's paths still protect what they name, but the
            # scene stays opaque: somebody may have added a cache since the
            # export, and only a fresh sidecar may license a DROP.
            if not fresh:
                opaque.append(scene.path)
                stale.append(scene.path)
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

    return paths, ref_folders, opaque, (used_by, folder_used_by), stale


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
    # Grouped by (parent, versionless name), NOT by parent alone.
    #
    # A folder of dailies holds one directory per shot per version --
    # SH010_v002, SH010_v003, SH050_v005, SH050_v006 -- all siblings. Pooling
    # them by parent compares SH070_v001 against SH050_v006 and calls the only
    # version of shot 70 superseded, which would offer live work for deletion.
    # The stem is what says two folders are versions of the SAME thing.
    by_group = defaultdict(list)
    for path in folders:
        parent = clean(os.path.dirname(path))
        name = os.path.basename(clean(path))
        version = rules.version_of(name) if name else None
        stem = rules.version_stem(name) if name else ""
        # A bare "v03" has no stem for version_of's separator to find, and
        # its siblings are distinguished by the parent alone.
        if version is None:
            bare = re.match(r"^v(\d{1,4})$", name.lower())
            if bare:
                version = int(bare.group(1))
                stem = ""
        if version is not None:
            by_group[(parent, stem)].append((version, path))

    superseded = set()
    for (parent, _stem), versions in by_group.items():
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


def _split_reason(reason):
    """
    verdict_for returns (long, short) now; older call sites pass a bare
    string. Accept both so nothing has to change in lockstep.
    """
    if isinstance(reason, tuple):
        return reason[0], reason[1] if len(reason) > 1 else reason[0]
    return reason, reason


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
        folder.reason_short = "empty" if folder.is_empty else "structure"
        if folder.is_empty:
            return rules.DROP, "Empty folder -- nothing in it, at any depth."
        return rules.KEEP, "Holds only subfolders."

    counts = defaultdict(int)
    for entry in folder.entries:
        counts[entry.category] += 1
    folder.category = max(counts.items(), key=lambda kv: kv[1])[0]

    # A superseded version folder is settled regardless of what is in it: a
    # newer render of the same thing sits alongside.
    # Record it, then let the loop below run so the confidence layer can see
    # every signal. The verdict is forced back to DROP after -- a superseded
    # folder is settled whatever else is in it.
    if key(folder.path) in superseded_folders:
        folder.superseded = True

    # Starts as DROP with no reason, and only a SAFER verdict used to record
    # one -- so a folder where everything genuinely drops came out with an
    # empty explanation, which is the row most in need of one. Every verdict
    # now carries the reason that produced it.
    best = None
    best_reason = ""
    best_short = ""

    for entry in folder.entries:
        # Only claim a cache is orphaned when we could actually read the
        # scenes. With an unreadable one in the project, an unreferenced cache
        # is just as likely to be one we could not see the reference for.
        scene_missing = (trust_references
                         and entry.category == rules.CAT_CACHE
                         and not entry.referenced
                         and scene_count > 0)
        verdict, raw_reason = rules.verdict_for(
            entry.category,
            referenced=entry.referenced,
            superseded=entry.superseded,
            scene_missing=scene_missing,
            trust_references=trust_references,
        )
        if best is None \
                or rules.VERDICT_ORDER[verdict] < rules.VERDICT_ORDER[best]:
            best = verdict
            best_reason, best_short = _split_reason(raw_reason)
        if best == rules.KEEP:
            break

    if best is None:
        folder.reason_short = "nothing recognisable"
        return rules.REVIEW, "Nothing recognisable in it."

    # A newer version of the same thing sits alongside. What that is worth
    # depends on what the folder HOLDS -- an old render version is dead
    # weight, an old cut of the dailies is a record of what was shown. See
    # rules.SUPERSEDE_DROPS.
    # mark_superseded_folders only ever flags render/comp/cache folders, and
    # the policy decides what that is worth. A cache folder whose scenes
    # could not be read is already held at REVIEW by verdict_for above, so
    # this does not need to re-litigate the C4D case.
    _policy = rules.supersede_policy(folder.category)
    if folder.superseded and _policy is not None:
        if _policy == rules.DROP:
            best = rules.DROP
        elif best == rules.KEEP:
            best = rules.REVIEW

    # How much independent evidence agrees, named rather than scored. Two
    # signals that fail in different ways agreeing is worth saying; a
    # percentage would be invented, and false precision on a tool that
    # deletes things invites acting without checking.
    if best == rules.DROP:
        signals = rules.drop_signals(
            folder.category,
            superseded=folder.superseded,
            referenced=any(e.referenced for e in folder.entries),
            trust_references=trust_references,
            expensive=rules.is_expensive_sim(folder.path))
        if folder.superseded and _policy is not None:
            best_reason = ("Superseded -- a higher version of this folder "
                           "exists alongside it.")
            best_short = "a newer version exists"
        if signals:
            # Recorded, not appended to the reason. Writing it into the text
            # put it past where the Why column truncates, so every STRONG was
            # invisible; it has its own column and the detail strip now.
            folder.confidence = rules.confidence(signals)
            folder.signals = signals

    # Superseded but only worth a REVIEW -- dailies and cuts. The block above
    # only speaks for DROP, and a row moved by a rule with no reason shown is
    # the row people stop trusting.
    if (folder.superseded and _policy == rules.REVIEW
            and best == rules.REVIEW):
        best_reason = ("A newer version of this folder exists alongside it. "
                       "Older cuts and dailies are often worth keeping, so "
                       "this is your call.")
        best_short = "a newer version exists"

    # A slow sim is regenerable and that is beside the point: re-running a
    # FLIP or pyro cache is an afternoon. Say so, so "Drop" never reads as
    # "free to lose".
    if folder.category == rules.CAT_CACHE             and rules.is_expensive_sim(folder.path):
        best_reason += "  SLOW to re-cook -- this looks like a simulation."

    # The category prefix is gone from the SHORT form. It used half the
    # column restating what the row already shows, and pushed the actual
    # reason past the truncation point. The long form keeps it, since the
    # detail strip has room and the context helps there.
    label = rules.CATEGORY_LABEL.get(folder.category, "")
    if label and best_reason and not best_reason.startswith(label):
        best_reason = "%s — %s" % (label, best_reason)

    folder.reason_short = best_short
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

    staging = actions.staging_dir(root)

    raw_folders, errors, staged = walk(root, progress, staging)
    result.errors.extend(errors)
    result.staged_bytes, result.staged_files = staged

    scenes = find_scenes(raw_folders)
    result.scenes = scenes

    referenced_paths, referenced_folders, opaque, attribution, stale = \
        read_references(scenes, root, scene_progress)
    result.opaque_scenes = opaque
    result.stale_sidecars = stale
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
        for entry in entries:
            entry.folder = folder
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
