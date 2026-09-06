# Archiver -- asset sidecars written by a DCC, read by the scanner.
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
The asset list a scene cannot tell us itself.

Some scene formats hide their references from a byte scrape -- modern Cinema
4D above all, a proprietary compressed container with not one asset path in
plaintext. See scene_parser.is_opaque(). For those, the only thing that knows
what the scene loads is the application, so the application writes it down: a
small JSON file next to the scene, and the scanner reads that instead.

    shot_010.c4d
    shot_010.c4d.assets.json

One sidecar per scene, not one index per project. A per-scene file makes
staleness a per-scene fact we can actually check (its mtime against the
scene's), it travels with a scene that gets copied elsewhere, and re-exporting
one scene never rewrites the other sixty-two.

THE STALENESS RULE, which is the whole safety story here:

A sidecar older than its scene is evidence, not truth. Somebody may have added
a cache since the export. So a stale sidecar's paths still count -- they push
files toward KEEP, which is the direction that cannot lose data -- but the
scene STAYS opaque, so references_trustworthy stays False and nothing gets
promoted to DROP on the strength of old evidence. Fresh sidecar, and the scene
is as good as readable.

    fresh  -> scene reads normally, full trust
    stale  -> paths count as KEEP evidence, scene still opaque, trust False
    absent -> opaque, exactly as before

This module is imported by Archiver AND exec'd by the Cinema 4D plugin, whose
interpreter cannot see Archiver's package. So it imports nothing but the
standard library, and nothing from the rest of core.
"""

import json
import os

# The suffix appended to the scene's own filename, extension and all, so
# shot.c4d and shot.hip in one folder cannot collide on one sidecar.
SUFFIX = ".assets.json"

# Bumped when the on-disk shape changes in a way an older reader would get
# wrong. A sidecar from the future is ignored rather than guessed at.
FORMAT_VERSION = 1

# A scene edited within this many seconds of its sidecar counts as fresh.
# Writing the sidecar necessarily happens after the scene's mtime is read, and
# some pipelines touch a scene on save-and-close; a hard comparison would call
# a sidecar stale the instant it was written.
FRESH_TOLERANCE = 2.0


def sidecar_path(scene_path):
    """Where a scene's sidecar lives: beside it, named after it."""
    return scene_path + SUFFIX


def is_sidecar(path):
    """True for a sidecar file itself, which is never a project asset."""
    return path.lower().endswith(SUFFIX)


def build(scene_path, assets, app="", app_version="", scene_mtime=None):
    """
    The payload, as a plain dict. Split out from write() so the C4D side can
    build it without touching the disk, and so tests can assert on the shape.

    scene_mtime is recorded as the exporter saw it. The reader compares that
    against the scene's mtime NOW, which catches the case a file-time
    comparison alone misses: a scene restored from backup can be older than
    its sidecar and still not be the scene that was exported.
    """
    if scene_mtime is None:
        try:
            scene_mtime = os.path.getmtime(scene_path)
        except OSError:
            scene_mtime = 0.0

    seen = set()
    clean_assets = []
    for asset in assets:
        text = _normalize(asset)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        clean_assets.append(text)

    return {
        "format": FORMAT_VERSION,
        "scene": os.path.basename(scene_path),
        "scene_mtime": round(float(scene_mtime), 3),
        "app": app,
        "app_version": app_version,
        "assets": clean_assets,
    }


def write(scene_path, assets, app="", app_version="", scene_mtime=None):
    """
    Write a scene's sidecar. Returns the path written.

    Written to a temp file and replaced, so a crash mid-write cannot leave a
    truncated sidecar that reads as "this scene uses three textures" when it
    uses three hundred. os.replace is atomic on Windows for same-directory
    targets.
    """
    payload = build(scene_path, assets, app, app_version, scene_mtime)
    target = sidecar_path(scene_path)
    temp = target + ".tmp"

    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(temp, target)
    return target


def read(scene_path):
    """
    A scene's sidecar as (assets, fresh), or (None, False) when there is none.

    assets is the list of paths exactly as written -- resolution against the
    project is the caller's job, since only the caller knows the project root.

    Anything malformed reads as absent. A sidecar we cannot parse must leave
    the scene opaque, never look like a scene with no assets: the second is a
    statement that nothing is referenced, and that is how a live cache gets
    archived away.
    """
    target = sidecar_path(scene_path)
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None, False

    if not isinstance(payload, dict):
        return None, False
    if payload.get("format", 0) > FORMAT_VERSION:
        return None, False       # written by a newer Archiver; do not guess

    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None, False

    paths = [_normalize(item) for item in assets if isinstance(item, str)]
    return [p for p in paths if p], _is_fresh(scene_path, target, payload)


def _is_fresh(scene_path, sidecar, payload):
    """
    True when the sidecar describes the scene as it is on disk now.

    Two checks, because either alone has a hole. The recorded mtime catches a
    scene rolled back to an older version -- older than its sidecar, so a file
    comparison would call it fresh, but not the scene that was exported. The
    file comparison catches a sidecar copied in from another machine whose
    recorded mtime happens to match.
    """
    try:
        scene_mtime = os.path.getmtime(scene_path)
        sidecar_mtime = os.path.getmtime(sidecar)
    except OSError:
        return False

    recorded = payload.get("scene_mtime")
    if isinstance(recorded, (int, float)) and recorded > 0:
        if abs(scene_mtime - float(recorded)) > FRESH_TOLERANCE:
            return False

    return sidecar_mtime + FRESH_TOLERANCE >= scene_mtime


def _normalize(path):
    """
    A path as Windows means it: backslashes, no trailing separator, stripped.

    The C4D side hands us whatever the Asset Inspector holds, which mixes
    separators and occasionally arrives as a URL-ish string. Never percent-
    decode here -- a real filename may legitimately contain a percent sign,
    and Iris learned the hard way that round-tripping through as_uri() breaks
    paths with spaces.
    """
    if not isinstance(path, str):
        return ""
    text = path.strip().strip('"')
    if not text:
        return ""
    text = text.replace("/", "\\")
    while text.endswith("\\") and len(text) > 3:
        text = text[:-1]
    return text
