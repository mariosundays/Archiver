# Archiver -- the c4d-free half of the Cinema 4D asset export.
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
Everything the C4D export does that does not need Cinema 4D.

The plugin itself cannot be tested. Claude cannot drive C4D's UI or read its
console, so a bug in the .pyp costs a restart and a report back from Mario.
The answer is to keep the .pyp a shell: it calls GetAllAssetsNew, hands the
raw result here, and this module -- plain Python, importable and testable --
does the deciding.

So the split is:

    .pyp  ->  talks to c4d, finds scenes, opens documents
    here  ->  what counts as an asset, what its path is, what to skip

Which means the parts that actually get things wrong are the parts covered by
tests/test_c4d_assets.py.
"""

import os

# Extensions that are never a project asset even when C4D lists them.
SKIP_EXTS = (".c4d", ".lib4d")


def asset_paths(assets, scene_path=""):
    """
    The asset list C4D returned, reduced to a clean list of paths.

    C4D hands back a list of dicts -- "filename", "assetname", "owner",
    "exists" -- but the shape has moved between versions and a defensive
    reader costs nothing. Anything we cannot make sense of is skipped rather
    than guessed at.

    A MISSING asset is still recorded. "The scene wants a file that is not
    there" is information the scan should have; dropping it would quietly turn
    a broken reference into no reference at all.

    The scene's own path is excluded -- a document lists itself in some
    versions, and a scene is not its own asset.
    """
    scene_key = _key(scene_path)
    out = []
    seen = set()

    for asset in assets or []:
        path = _path_of(asset)
        if not path:
            continue

        lowered = _key(path)
        if lowered == scene_key:
            continue
        if lowered.endswith(SKIP_EXTS):
            # An .c4d asset is an xref, which the scan finds as a scene in its
            # own right and reads separately.
            continue
        if lowered in seen:
            continue

        seen.add(lowered)
        out.append(path)

    return out


def _path_of(asset):
    """One asset entry's filename, whatever shape the entry arrived in."""
    if isinstance(asset, str):
        return asset.strip()

    if isinstance(asset, dict):
        for field in ("filename", "assetname", "path"):
            value = asset.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    # Some versions hand back an object rather than a dict.
    for field in ("filename", "assetname", "path"):
        value = getattr(asset, field, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _key(path):
    return (path or "").replace("/", "\\").rstrip("\\").lower()


def find_scenes(root, recursive=True):
    """
    Every .c4d under a folder, sorted, skipping what is not worth opening.

    Backups and the staging folder are deliberately excluded. Opening a scene
    is slow -- this is the expensive part of a batch run -- and a _bak.c4d's
    asset list tells us nothing we act on: backups are dropped by category,
    not by reference.
    """
    found = []
    root = os.path.abspath(root)

    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not _skip_dir(d)]
        for name in files:
            if not name.lower().endswith(".c4d"):
                continue
            if _is_backup(name):
                continue
            found.append(os.path.join(folder, name))
        if not recursive:
            break

    return sorted(found)


def _skip_dir(name):
    lowered = name.lower()
    if lowered in ("_todelete", "__pycache__", ".git", ".svn"):
        return True
    # C4D's own autosave folder.
    return lowered in ("backup", "_backup", "autosave")


def _is_backup(name):
    lowered = name.lower()
    return (lowered.endswith("_bak.c4d")
            or lowered.endswith(".bak.c4d")
            or "_backup" in lowered)


def summarize(results):
    """
    A one-line-per-scene report of a batch run, plus a total.

    results is a list of (scene_path, count, error). Written here rather than
    in the .pyp so the message Mario reads after a 63-scene run is something
    that has actually been tested.
    """
    lines = []
    exported = 0
    failed = 0
    total_assets = 0

    for scene, count, error in results:
        name = os.path.basename(scene)
        if error:
            failed += 1
            lines.append("FAILED  %s -- %s" % (name, error))
        else:
            exported += 1
            total_assets += count
            lines.append("ok      %s (%d assets)" % (name, count))

    header = "Exported %d scene%s, %d asset%s" % (
        exported, "" if exported == 1 else "s",
        total_assets, "" if total_assets == 1 else "s")
    if failed:
        header += " -- %d FAILED" % failed

    return header + "\n\n" + "\n".join(lines)
