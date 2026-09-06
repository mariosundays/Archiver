# Archiver -- step 6: copy the project out to its archive home.
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
The last step: copy what survived to wherever the archive lives.

COPIES, never moves. The original project stays exactly where it is, so a
failed or interrupted archive costs nothing but time and the destination is
verified before anything is trusted. That is the opposite trade from staging,
where a same-filesystem move was the safe choice -- here the destination is
usually another drive or a NAS, and a copy is the only operation that leaves
you with a working project if it dies half way.

What gets copied is the project as it stands, minus `_toDelete`. Staging is
where the decision about what to keep was already made; repeating it here
would mean two different answers to the same question.
"""

import os
import shutil
import time
import zipfile

from . import actions
from .scene_parser import clean, key

# Junk that should never reach an archive, whatever the project holds.
SKIP_NAMES = {
    "thumbs.db", "desktop.ini", ".ds_store", "._.ds_store",
}

SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "$recycle.bin",
    "system volume information", ".dropbox.cache",
}


class Plan(object):
    """What an archive would consist of, worked out before touching anything."""

    def __init__(self, source, destination, as_zip=False):
        self.source = clean(source)
        self.destination = clean(destination)
        self.as_zip = as_zip
        self.files = []          # (absolute path, path relative to source)
        self.total_bytes = 0
        self.skipped_bytes = 0
        self.skipped_files = 0
        self.problems = []

    @property
    def count(self):
        return len(self.files)

    @property
    def name(self):
        return os.path.basename(self.source.rstrip("/")) or "archive"


def plan(source, destination, as_zip=False, skip_staging=True):
    """
    Work out what would be copied, and check the destination is sane.

    Everything that can be refused is refused HERE, before a single byte
    moves, so the UI can show the cost and the objections together rather than
    failing half way through a 200 GB copy.
    """
    result = Plan(source, destination, as_zip)
    source_key = key(result.source)
    dest_key = key(result.destination)

    if not os.path.isdir(result.source):
        result.problems.append("The project folder does not exist.")
        return result

    if not result.destination:
        result.problems.append("No destination chosen.")
        return result

    # Copying a folder into itself, or into its own subfolder, would recurse
    # until the disk filled.
    if dest_key == source_key:
        result.problems.append(
            "The destination is the project itself.")
    elif dest_key.startswith(source_key + "/"):
        result.problems.append(
            "The destination is inside the project, which would copy the "
            "archive into itself.")

    staging = key(actions.staging_dir(result.source))

    for folder, dirnames, filenames in os.walk(result.source):
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in SKIP_DIRS]
        folder_key = key(folder)

        # _toDelete holds what you already decided against. It is not
        # archived, but its size IS reported so the UI can say what is being
        # left behind.
        #
        # Note the walk still descends into it: pruning dirnames here would
        # stop at the top level and count only the manifest, which made the
        # "leaving behind" figure wrong by whatever was actually staged.
        if skip_staging and (folder_key == staging
                             or folder_key.startswith(staging + "/")):
            for name in filenames:
                if name == actions.MANIFEST:
                    continue
                try:
                    result.skipped_bytes += os.path.getsize(
                        os.path.join(folder, name))
                    result.skipped_files += 1
                except OSError:
                    pass
            continue

        for name in filenames:
            if name.lower() in SKIP_NAMES:
                continue
            full = clean(os.path.join(folder, name))
            relative = full[len(result.source):].lstrip("/")
            try:
                size = os.path.getsize(full)
            except OSError as exc:
                result.problems.append("%s: %s" % (relative, exc))
                continue
            result.files.append((full, relative))
            result.total_bytes += size

    if not result.files:
        result.problems.append("Nothing to copy.")

    free = free_space(result.destination)
    if free is not None and free < result.total_bytes:
        result.problems.append(
            "Not enough room at the destination: %d bytes free, %d needed."
            % (free, result.total_bytes))

    return result


def free_space(path):
    """Bytes free on the volume holding path, or None if it cannot be read."""
    probe = clean(path)
    # The destination usually does not exist yet; walk up to something that
    # does, since that is the volume the copy will land on.
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    try:
        return shutil.disk_usage(probe).free
    except (OSError, ValueError):
        return None


def run(plan_obj, progress=None):
    """
    Carry out a plan. Returns (copied, failed).

    A file that fails is reported and the rest continue: on a big archive one
    unreadable file should not throw away an hour of copying, and the caller
    is told exactly what did not make it.
    """
    if plan_obj.problems:
        return [], [("", "; ".join(plan_obj.problems))]

    if plan_obj.as_zip:
        return _run_zip(plan_obj, progress)
    return _run_copy(plan_obj, progress)


def _destination_root(plan_obj):
    """
    Where the copy actually lands: <destination>/<project name>.

    Copying the contents bare into the chosen folder would scatter a project
    across whatever else is already there, and archives get pointed at a
    shared drive far more often than at an empty folder.
    """
    return clean(plan_obj.destination + "/" + plan_obj.name)


def _run_copy(plan_obj, progress):
    copied = []
    failed = []
    target_root = _destination_root(plan_obj)

    for index, (full, relative) in enumerate(plan_obj.files):
        if progress is not None and not progress(index, plan_obj.count,
                                                 relative):
            break

        target = clean(target_root + "/" + relative)
        try:
            parent = os.path.dirname(target)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            # copy2 keeps mtimes, which is what makes an archive still look
            # like the project rather than like the day it was archived.
            shutil.copy2(full, target)
            copied.append(relative)
        except (OSError, IOError, shutil.Error) as exc:
            failed.append((relative, str(exc)))

    return copied, failed


def _run_zip(plan_obj, progress):
    copied = []
    failed = []
    target = zip_path(plan_obj)

    try:
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
    except OSError as exc:
        return [], [("", str(exc))]

    try:
        # ZIP64 for the size, and deflate: image and video data barely
        # compresses, but scenes and caches do, and the cost is one pass.
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                             allowZip64=True) as archive:
            for index, (full, relative) in enumerate(plan_obj.files):
                if progress is not None and not progress(index,
                                                         plan_obj.count,
                                                         relative):
                    break
                try:
                    archive.write(full, plan_obj.name + "/" + relative)
                    copied.append(relative)
                except (OSError, IOError, ValueError) as exc:
                    failed.append((relative, str(exc)))
    except (OSError, IOError, zipfile.BadZipFile) as exc:
        failed.append((target, str(exc)))

    return copied, failed


def zip_path(plan_obj):
    """Where the .zip lands, with the date so re-archiving does not clobber."""
    stamp = time.strftime("%Y%m%d")
    return clean("%s/%s_%s.zip" % (plan_obj.destination, plan_obj.name,
                                   stamp))


def verify(plan_obj, sample=None):
    """
    Check the copy arrived, by size.

    Not a checksum -- hashing 200 GB doubles the time and the failure this
    guards against is a truncated or missing file, which a size comparison
    catches. Returns a list of (relative, reason); empty means everything
    matched.

    Only meaningful for a plain copy; a zip is verified by reading it back.
    """
    problems = []
    if plan_obj.as_zip:
        target = zip_path(plan_obj)
        try:
            with zipfile.ZipFile(target) as archive:
                broken = archive.testzip()
                if broken is not None:
                    problems.append((broken, "corrupt entry in the zip"))
        except (OSError, IOError, zipfile.BadZipFile) as exc:
            problems.append((target, str(exc)))
        return problems

    target_root = _destination_root(plan_obj)
    files = plan_obj.files if sample is None else plan_obj.files[:sample]

    for full, relative in files:
        target = clean(target_root + "/" + relative)
        try:
            if os.path.getsize(target) != os.path.getsize(full):
                problems.append((relative, "size differs"))
        except OSError:
            problems.append((relative, "missing at the destination"))

    return problems
