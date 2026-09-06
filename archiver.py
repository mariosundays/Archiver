# Archiver -- command line entry point.
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
Scan a project folder and report what could be archived.

    python archiver.py "D:/Projects/shot01"
    python archiver.py "D:/Projects/shot01" --detail
    python archiver.py "D:/Projects/shot01" --json report.json

Reads only. Nothing is moved, written, or deleted in the scanned folder.
"""

import argparse
import sys

from core import report, scanner


def _progress(seen, folder):
    """Live counter on one rewritten line -- a big project takes a while."""
    sys.stderr.write("\r  scanning... %s files" % "{:,}".format(seen))
    sys.stderr.flush()
    return True


def _scene_progress(index, total, path):
    sys.stderr.write("\r  reading scenes... %d/%d          " % (index + 1, total))
    sys.stderr.flush()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scan a VFX project and report what can be archived. "
                    "Read-only: nothing is modified.")
    parser.add_argument("root", help="project folder to scan")
    parser.add_argument("--detail", action="store_true",
                        help="list every folder, not just drop and review")
    parser.add_argument("--json", metavar="PATH",
                        help="also write the report as JSON")
    parser.add_argument("--quiet", action="store_true",
                        help="no progress output")
    args = parser.parse_args(argv)

    walk_cb = None if args.quiet else _progress
    scene_cb = None if args.quiet else _scene_progress

    result = scanner.scan(args.root, walk_cb, scene_cb)

    if not args.quiet:
        sys.stderr.write("\r" + " " * 50 + "\r")
        sys.stderr.flush()

    print(report.text_report(result, detail=args.detail))

    if args.json:
        written = report.write_json(result, args.json)
        print("  JSON written to %s\n" % written)

    return 1 if result.errors and not result.folders else 0


if __name__ == "__main__":
    sys.exit(main())
