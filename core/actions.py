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

import os

from .scene_parser import clean, key


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
