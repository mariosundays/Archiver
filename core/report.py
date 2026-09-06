# Archiver -- turn a scan into something readable.
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
Report rendering -- text, and a JSON form for anything downstream.

Qt-free, so the same report backs the CLI and the eventual UI, and so it can
be tested without a display.
"""

import json
import os

from . import rules
from .scanner import human


def _bar(fraction, width=28):
    """A proportion as a text bar. Size is the whole point of this report."""
    filled = int(round(fraction * width))
    return "#" * filled + "." * (width - filled)


def summary_lines(result):
    """The headline: what is here, and what could go."""
    lines = []
    total = result.total_size or 1

    lines.append("")
    lines.append("  %s" % result.root)
    lines.append("  %s in %s files, %d folders, %d scenes  (%.1fs)"
                 % (human(result.total_size), "{:,}".format(result.total_files),
                    len(result.folders), len(result.scenes), result.duration))
    lines.append("")

    totals = result.totals()
    for verdict in (rules.KEEP, rules.REVIEW, rules.DROP):
        size, folders, files = totals[verdict]
        lines.append("  %-7s %s  %10s  %4d folders  %s files"
                     % (rules.VERDICT_LABEL[verdict],
                        _bar(size / total),
                        human(size), folders, "{:,}".format(files)))
    lines.append("")
    lines.append("  Reclaimable now: %s" % human(result.reclaimable()))

    # The most important thing on the page when it applies. A scene we could
    # not read means every verdict leaning on references is weaker, and the
    # user has to know that before acting on any of it.
    if result.opaque_scenes:
        count = len(result.opaque_scenes)
        lines.append("")
        lines.append("  !  %d scene%s could not be read (Cinema 4D R20+ "
                     "files are compressed)."
                     % (count, "" if count == 1 else "s"))
        lines.append("     Nothing was checked against them, so caches and "
                     "geometry they use")
        lines.append("     look unreferenced. Verdicts here lean on file "
                     "type and location only.")

    if result.empty_folders:
        lines.append("")
        lines.append("  %d empty folder%s."
                     % (len(result.empty_folders),
                        "" if len(result.empty_folders) == 1 else "s"))
    return lines


def category_lines(result):
    """Where the bytes actually are, by what they are."""
    lines = ["", "  BY CATEGORY", ""]
    for category, size in result.by_category():
        if not size:
            continue
        lines.append("    %-22s %10s   %s"
                     % (rules.CATEGORY_LABEL.get(category, category),
                        human(size),
                        rules.CATEGORY_WHY.get(category, "")))
    return lines


def folder_lines(result, verdict=None, limit=40):
    """The folder table, worst verdict and biggest first."""
    folders = result.by_verdict(verdict) if verdict else result.folders
    # Empty folders have no files but are still worth listing -- that is the
    # whole point of flagging them.
    folders = [f for f in folders if f.count or f.is_empty]

    title = ("  %s FOLDERS" % rules.VERDICT_LABEL[verdict].upper()
             if verdict else "  FOLDERS")
    lines = ["", title, ""]

    if not folders:
        lines.append("    (none)")
        return lines

    for folder in folders[:limit]:
        lines.append("    %-7s %10s  %6s files  %-10s  %s"
                     % (rules.VERDICT_LABEL[folder.verdict],
                        folder.human_size,
                        "{:,}".format(folder.count),
                        folder.age,
                        folder.relative))
        if folder.reason:
            lines.append("            %s" % folder.reason)

    if len(folders) > limit:
        lines.append("    ... and %d more" % (len(folders) - limit))
    return lines


def text_report(result, detail=False):
    """The whole report as one string."""
    lines = []
    lines.append("=" * 72)
    lines.append("  ARCHIVER  --  scan report  (nothing was modified)")
    lines.append("=" * 72)
    lines.extend(summary_lines(result))
    lines.extend(category_lines(result))

    if detail:
        lines.extend(folder_lines(result))
    else:
        lines.extend(folder_lines(result, rules.DROP))
        lines.extend(folder_lines(result, rules.REVIEW))

    if result.errors:
        lines.extend(["", "  UNREADABLE (%d)" % len(result.errors), ""])
        for error in result.errors[:10]:
            lines.append("    %s" % error)
        if len(result.errors) > 10:
            lines.append("    ... and %d more" % (len(result.errors) - 10))

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def as_dict(result):
    """The scan as plain data, for JSON export or a UI to render."""
    totals = result.totals()
    return {
        "root": result.root,
        "scanned_files": result.total_files,
        "total_bytes": result.total_size,
        "reclaimable_bytes": result.reclaimable(),
        "duration_seconds": round(result.duration, 2),
        "scenes": [s.path for s in result.scenes],
        "unreadable_scenes": result.opaque_scenes,
        "references_trustworthy": result.references_trustworthy,
        "empty_folders": result.empty_folders,
        "errors": result.errors,
        "totals": {
            verdict: {
                "bytes": totals[verdict][0],
                "folders": totals[verdict][1],
                "files": totals[verdict][2],
            }
            for verdict in (rules.KEEP, rules.REVIEW, rules.DROP)
        },
        "categories": {
            category: size for category, size in result.by_category()
        },
        "folders": [
            {
                "path": folder.relative,
                "verdict": folder.verdict,
                "category": folder.category,
                "reason": folder.reason,
                "bytes": folder.size,
                "files": folder.count,
                "referenced_files": folder.referenced_count,
                "empty": folder.is_empty,
                "modified": folder.mtime,
            }
            for folder in result.folders if folder.count or folder.is_empty
        ],
    }


def write_json(result, path):
    """Save the report beside wherever the user asked -- never in the project."""
    path = os.path.abspath(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(as_dict(result), handle, indent=2)
    return path
