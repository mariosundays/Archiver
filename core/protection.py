# Archiver -- folders and files the user has said must never be deleted.
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
"Never delete this, whatever you decide about it."

Folders AND files. One irreplaceable file inside an otherwise disposable
folder is the case that matters most -- without file marks you would have to
protect the whole folder to save it, which protects a lot you did not mean to.
A mark on a file simply has nothing beneath it; the subtree rule below covers
both without a second code path.

A verdict is what the scan WORKED OUT. A protection is what the user KNOWS,
and it outranks the scan permanently -- so it cannot live in the verdict.
Overwriting the verdict would lose why the thing looked droppable, which is
exactly what you want to see next time you wonder about it.

Saved beside the project as a dotfile so it survives rescans, restarts and
reinstalls, and travels with the job to another machine. Relative paths, so
moving or renaming the project root keeps every mark -- Mario moves projects
around, and a protection that silently stopped applying would be worse than
never having offered one.

Nothing here decides anything. It answers "did the user protect this?" and the
selection and staging layers refuse accordingly. Two independent refusals, on
purpose: a protection that only greyed out a checkbox would be a suggestion.
"""

import json
import os

from .scene_parser import clean, key

MARKS = ".archiver_protected.json"

# Bumped only if the on-disk shape changes incompatibly. A file from the
# future is left alone rather than rewritten -- a newer Archiver may know
# something this one does not.
FORMAT = 1


def marks_path(root):
    return clean(root) + "/" + MARKS


class Protected(object):
    """
    The set of protected paths -- folders and files -- for one project.

    Holds RELATIVE paths. Absolute ones would break the moment the project
    moved, and this file is meant to be the durable half of the tool.
    """

    def __init__(self, root, relatives=()):
        self.root = clean(root)
        self._relatives = set()
        for relative in relatives:
            cleaned = _tidy(relative)
            if cleaned is not None:
                self._relatives.add(cleaned)

    # -- state --------------------------------------------------------------

    def __len__(self):
        return len(self._relatives)

    def __bool__(self):
        # An empty set is falsey, but "no marks" is a perfectly valid state
        # to hold and pass around, so callers must test len() or is None.
        return True

    __nonzero__ = __bool__          # py2 name, harmless here

    def relatives(self):
        """Every protected path, relative, shallowest first."""
        return sorted(self._relatives, key=lambda p: (p.count("/"), p))

    def paths(self):
        """Every protected path, absolute."""
        return [self.root + "/" + relative for relative in self.relatives()]

    def _relative_of(self, path):
        """The project-relative form of an absolute path, or None if outside."""
        cleaned = clean(path).rstrip("/")
        base = self.root.rstrip("/")
        if key(cleaned) == key(base):
            return "."
        if key(cleaned).startswith(key(base) + "/"):
            return cleaned[len(base) + 1:]
        return None

    def is_protected(self, path):
        """
        True when this path is protected, itself or through a parent.

        Protection covers the subtree: "never delete B_SOURCE" plainly means
        the things inside it too, and a protected parent holding a droppable
        child would be an incoherent thing to show someone. A marked FILE has
        nothing below it, so the same rule protects exactly that one file.
        """
        relative = self._relative_of(path)
        if relative is None:
            return False
        if "." in self._relatives:      # the whole project is protected
            return True
        marked = key(relative)
        for candidate in self._relatives:
            candidate = key(candidate)
            if marked == candidate or marked.startswith(candidate + "/"):
                return True
        return False

    def protected_by(self, path):
        """
        WHICH mark protects this path -- itself, or an ancestor's.

        Returned so the UI can say "protected by B_SOURCE" rather than
        leaving someone hunting for why a folder will not tick.
        """
        relative = self._relative_of(path)
        if relative is None:
            return None
        if "." in self._relatives:
            return "."
        marked = key(relative)
        best = None
        for candidate in self._relatives:
            ckey = key(candidate)
            if marked == ckey or marked.startswith(ckey + "/"):
                # The deepest ancestor is the most informative one.
                if best is None or len(ckey) > len(key(best)):
                    best = candidate
        return best

    # -- changing -----------------------------------------------------------

    def add(self, path):
        """Protect a folder or file. False if it is outside the project."""
        relative = self._relative_of(path)
        if relative is None:
            return False
        self._relatives.add(relative)
        # Marks now covered by this one are redundant. Dropping them keeps
        # the file honest: unprotecting the parent later should not leave
        # orphan children behind that nobody remembers marking.
        if relative == ".":
            self._relatives = {"."}
        else:
            prefix = key(relative) + "/"
            self._relatives = {r for r in self._relatives
                               if r == relative or not key(r).startswith(prefix)}
        return True

    def remove(self, path):
        """
        Unprotect a folder or file.

        Only removes a mark ON this path. Un-protecting something that is
        covered by a parent's mark is not a thing this can express, and
        silently removing the PARENT would unprotect its siblings too --
        so it returns False and the UI says which mark to remove instead.
        """
        relative = self._relative_of(path)
        if relative is None or relative not in self._relatives:
            return False
        self._relatives.discard(relative)
        return True

    def toggle(self, path):
        """Flip a mark on this exact path. Returns the new state."""
        relative = self._relative_of(path)
        if relative is None:
            return False
        if relative in self._relatives:
            self.remove(path)
            return False
        self.add(path)
        return True


def _tidy(relative):
    """Normalise a stored path, rejecting anything that escapes the root."""
    if not isinstance(relative, str):
        return None
    cleaned = clean(relative).strip("/")
    if not cleaned:
        return None
    if cleaned == ".":
        return "."
    # A stored "../.." would protect -- or worse, later unprotect -- things
    # outside the project. The file is editable by hand, so this is not
    # paranoia about our own writer.
    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts) if parts else None


def load(root):
    """
    Read the marks beside a project.

    A missing file is no marks. A CORRUPT file is also no marks, and that is
    a deliberate asymmetry: protection failing open would let something be
    deleted, so the caller is told about the error and can say so, rather
    than quietly proceeding as though nothing was ever protected.

    Returns (Protected, error). error is None when the file was absent or
    read cleanly.
    """
    path = marks_path(root)
    if not os.path.isfile(path):
        return Protected(root), None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, IOError, ValueError) as exc:
        return Protected(root), "could not read %s: %s" % (MARKS, exc)

    if not isinstance(data, dict):
        return Protected(root), "%s is not in the expected shape" % MARKS

    # "paths" is the current key; "folders" is read too so a file written by
    # an earlier build keeps working. Never silently discard someone's marks.
    entries = data.get("paths")
    if entries is None:
        entries = data.get("folders")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        return Protected(root), "%s is not in the expected shape" % MARKS

    return Protected(root, entries), None


def save(root, protected, dry_run=True):
    """
    Write the marks beside a project, atomically.

    Same shape as actions.write_report: temporary file then os.replace, so an
    interrupted write cannot destroy the marks that were already there. An
    error comes back rather than raising -- but callers MUST surface it,
    because a protection the user set and that did not persist is the worst
    outcome this module has.

    Returns (path, error).
    """
    target = marks_path(root)
    if dry_run:
        return target, None

    if not os.path.isdir(clean(root)):
        return target, "the project folder is gone"

    payload = {
        "format": FORMAT,
        "root": clean(root),
        "paths": protected.relatives(),
    }

    # No marks left: remove the file rather than leaving an empty one, so a
    # project with nothing protected looks exactly like one that never had
    # anything protected.
    if not protected.relatives():
        try:
            if os.path.isfile(target):
                os.remove(target)
        except OSError as exc:
            return target, "could not remove %s: %s" % (MARKS, exc)
        return target, None

    temporary = target + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(temporary, target)
    except (OSError, IOError, TypeError, ValueError) as exc:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
        return target, "could not write %s: %s" % (MARKS, exc)

    return target, None
