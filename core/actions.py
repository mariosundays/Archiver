# Archiver -- the parts that write. Everything else in core/ only reads.
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
The only module in core/ that modifies anything.

Kept separate on purpose. scanner.py, rules.py, tree.py and report.py are
read-only and have a test asserting a scan leaves the project byte-identical;
isolating the writes here means that guarantee stays easy to see and hard to
break by accident.

Every function takes dry_run and defaults it to True.
"""

import json
import os
import shutil
import time

from .scene_parser import clean, key

# Where approved folders go. Inside the project on purpose: a move within one
# filesystem is a rename -- instant, and atomic per folder -- while moving to
# another drive is a copy-then-delete that can half-finish on a 200 GB cache.
STAGING = "_toDelete"

# The record of what was moved and from where. Without it a restore depends on
# the app still being open with the same scan loaded, which is not a promise
# worth making about someone's project.
MANIFEST = "archiver_manifest.json"

# The scan report, dropped at the project root after every scan.
#
# Leading dot so it stays out of the way: hidden on macOS and Linux,
# de-emphasised on Windows, and unmistakably not a project asset.
REPORT = ".archiver_report.json"


def prune_empty_folders(result, dry_run=True, progress=None):
    """
    Remove the empty folders a scan found. Prep for archiving.

    Deleting an empty directory is the one destructive act that cannot lose
    data: nothing lives in it at any depth, or the scan would not have called
    it empty. That is why this can act for real while the rest of the tool
    stays report-only.

    Deepest first, so a chain like A_PROJ/ZB/OLD collapses in one pass --
    removing the leaf is what makes its parent removable.

    Uses os.rmdir, never shutil.rmtree. rmdir REFUSES a non-empty directory,
    so if the scan has gone stale and a file appeared since, the call fails
    loudly instead of destroying it. That refusal is the safety net, and it is
    the reason not to "improve" this with rmtree.

    Returns (removed, failed): a list of paths, and a list of (path, reason).
    """
    removed = []
    failed = []

    # Deepest first. Sorting by segment count rather than string length is
    # what makes it depth order rather than name order.
    ordered = sorted(result.empty_folders,
                     key=lambda p: clean(p).count("/"), reverse=True)

    root = key(result.root)
    for index, path in enumerate(ordered):
        if progress is not None and not progress(index, len(ordered), path):
            break

        # Never touch the project root itself, whatever the scan says.
        if key(path) == root:
            continue

        if dry_run:
            removed.append(path)
            continue

        try:
            os.rmdir(path)
            removed.append(path)
        except OSError as exc:
            failed.append((path, str(exc)))

    return removed, failed


# ---------------------------------------------------------------------------
# Staging -- step 5
#
# Approving does not delete. It MOVES the chosen folders into <root>/_toDelete,
# keeping their relative path, and writes a manifest saying where each came
# from. You then look at what is left, check the project still opens, and
# delete _toDelete yourself once satisfied.
#
# The point is that the destructive step stays one you take deliberately, in
# Explorer, having seen the consequences -- not one this tool takes for you on
# the strength of a heuristic.
# ---------------------------------------------------------------------------

def staging_dir(root):
    return clean(root) + "/" + STAGING


def manifest_path(root):
    return staging_dir(root) + "/" + MANIFEST


def _unique(path):
    """Never overwrite something already staged by an earlier run."""
    if not os.path.exists(path):
        return path
    for index in range(1, 1000):
        candidate = "%s__%d" % (path, index)
        if not os.path.exists(candidate):
            return candidate
    raise OSError("cannot find a free name for %s" % path)


def read_manifest(root):
    """What is currently staged: a list of {from, to, moved} entries."""
    try:
        with open(manifest_path(root), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, IOError, ValueError):
        return []
    entries = data.get("moved") if isinstance(data, dict) else data
    return entries if isinstance(entries, list) else []


def _write_manifest(root, entries):
    path = manifest_path(root)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"root": clean(root),
                   "staged": time.time(),
                   "moved": entries}, handle, indent=2)


def stage(root, paths, dry_run=True, progress=None):
    """
    Move each path into <root>/_toDelete, preserving its relative location.

    Nothing is deleted. Returns (moved, failed) -- manifest entries for what
    moved, and (path, reason) for what did not.

    Refuses rather than guesses in five cases, each a real way to lose work:

      - a path outside the project root. The selection should never produce
        one, but the consequence if it did is severe enough to check.
      - the project root itself.
      - anything already inside _toDelete, which would nest staging in
        staging and make a restore ambiguous.
      - a path that has vanished since the scan.
      - anything the user marked "never delete". The selection layer already
        refuses to tick those, so reaching here means something went wrong
        upstream -- which is exactly when a second, independent refusal
        earns its place. Marks are re-read from disk here rather than passed
        in, so this holds even for a caller that knows nothing about them.

    A failure part-way leaves the remaining entries untouched, and the
    manifest is written for whatever did move -- so a restore always has an
    accurate record even after a partial run.
    """
    root = clean(root)
    staging = staging_dir(root)
    root_key = key(root)
    staging_key = key(staging)

    # Read straight from disk: this refusal must not depend on the caller
    # having remembered to pass anything. A protection that only worked when
    # the UI cooperated would not be a protection.
    from . import protection as _protection
    marks, _marks_error = _protection.load(root)

    existing = read_manifest(root) if not dry_run else []
    fresh = []
    failed = []

    for index, path in enumerate(paths):
        path = clean(path)
        if progress is not None and not progress(index, len(paths), path):
            break

        path_key = key(path)
        if path_key == root_key:
            failed.append((path, "that is the project root"))
            continue
        if not path_key.startswith(root_key + "/"):
            failed.append((path, "outside the project"))
            continue
        if path_key == staging_key or path_key.startswith(staging_key + "/"):
            failed.append((path, "already staged"))
            continue
        if not os.path.exists(path):
            failed.append((path, "no longer on disk"))
            continue
        if marks.is_protected(path):
            # Name the mark that did it when it is an ancestor, or the
            # refusal sends someone hunting for a mark they cannot see.
            owner = marks.protected_by(path)
            owner_path = key(root + "/" + owner) if owner and owner != "." \
                else root_key
            if owner_path == path_key:
                failed.append((path, "marked never delete"))
            else:
                failed.append((path, "inside %s, which is marked never delete"
                                     % (owner if owner != "." else "the "
                                        "project")))
            continue

        # A folder is moved WHOLE, so a protected file anywhere inside it
        # would travel with it -- protection bypassed silently, which is the
        # one outcome this must never allow. Checking only the path handed in
        # is not enough; the subtree has to be clean too.
        inside = [m for m in marks.paths()
                  if key(m).startswith(path_key + "/")]
        if inside:
            relative = inside[0][len(root) + 1:]
            failed.append((path, "holds %s, which is marked never delete"
                                 % relative
                                 if len(inside) == 1 else
                                 "holds %d things marked never delete"
                                 % len(inside)))
            continue

        relative = path[len(root):].lstrip("/")
        destination = clean(staging + "/" + relative)

        if dry_run:
            fresh.append({"from": path, "to": destination})
            continue

        try:
            parent = os.path.dirname(destination)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            destination = _unique(destination)
            shutil.move(path, destination)
        except (OSError, IOError, shutil.Error) as exc:
            failed.append((path, str(exc)))
            continue

        fresh.append({"from": path, "to": destination, "moved": time.time()})

    if not dry_run and fresh:
        _write_manifest(root, existing + fresh)

    return fresh, failed


def restore(root, entries=None, dry_run=True, progress=None):
    """
    Put staged folders back where they came from.

    Reads the manifest rather than inferring from the folder layout, so a
    restore still works after the app has been closed and reopened.

    A destination that exists again is refused, never merged: something has
    been recreated there since staging, and quietly merging two versions of a
    cache is the kind of damage this tool exists to prevent.

    Returns (restored, failed).
    """
    root = clean(root)
    entries = read_manifest(root) if entries is None else entries

    restored = []
    failed = []
    remaining = []

    for index, entry in enumerate(entries):
        source = clean(entry.get("to", ""))
        target = clean(entry.get("from", ""))

        if progress is not None and not progress(index, len(entries), target):
            remaining.append(entry)
            continue

        if not source or not target:
            failed.append((source or "?", "malformed manifest entry"))
            continue
        if not os.path.exists(source):
            failed.append((source, "not in the staging folder any more"))
            continue
        if os.path.exists(target):
            failed.append((target, "something exists there again"))
            remaining.append(entry)
            continue

        if dry_run:
            restored.append(entry)
            continue

        try:
            parent = os.path.dirname(target)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent)
            shutil.move(source, target)
        except (OSError, IOError, shutil.Error) as exc:
            failed.append((target, str(exc)))
            remaining.append(entry)
            continue

        restored.append(entry)

    if not dry_run:
        _write_manifest(root, remaining)
        _prune_staging_tree(root)

    return restored, failed


def _prune_staging_tree(root):
    """
    Drop the empty scaffolding a restore leaves behind.

    The mirrored path structure has no value once its contents are gone, and
    leaving skeletons makes the staging area look like it still holds
    something. os.rmdir only, so anything still occupied survives.
    """
    staging = staging_dir(root)
    if not os.path.isdir(staging):
        return

    for folder, _dirnames, _filenames in os.walk(staging, topdown=False):
        if clean(folder) == staging:
            continue
        try:
            if not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass

    # And the staging folder itself, once only the manifest is left.
    try:
        if os.listdir(staging) == [MANIFEST]:
            os.remove(manifest_path(root))
            os.rmdir(staging)
    except OSError:
        pass


def staged_size(root):
    """Bytes currently sitting in the staging folder."""
    total = 0
    for folder, _dirnames, filenames in os.walk(staging_dir(root)):
        for name in filenames:
            if name == MANIFEST:
                continue
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# The scan report
#
# The scan itself stays read-only -- a test asserts the tree is byte-identical
# afterwards -- so writing the report is a SEPARATE, explicit step. That
# distinction is worth the extra call: it keeps "scanning costs you nothing"
# true, and puts the one write where every other write in this module lives.
# ---------------------------------------------------------------------------

def report_path(root):
    return clean(root) + "/" + REPORT


def write_report(root, data, dry_run=True):
    """
    Save a scan report at the project root.

    Written to a temporary file and moved into place, so an interrupted write
    cannot leave a half-written report where a good one used to be. A failure
    is returned rather than raised: a report that could not be saved is worth
    mentioning and never worth aborting a scan over.

    Returns (path, error). error is None on success.
    """
    target = report_path(root)
    if dry_run:
        return target, None

    if not os.path.isdir(clean(root)):
        return target, "the project folder is gone"

    temporary = target + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        # os.replace is atomic on the same filesystem, so a reader either
        # sees the old report or the new one, never a truncated file.
        os.replace(temporary, target)
    except (OSError, IOError, TypeError, ValueError) as exc:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
        return target, str(exc)

    return target, None
