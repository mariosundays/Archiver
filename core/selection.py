# Archiver -- what the user has chosen to remove.
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
The selection: step 3, and the thing steps 4 and 5 act on.

Kept out of the UI on purpose. What is selected, what that frees, and which
folders are only partly chosen are all questions with exact answers, and they
are far easier to get right -- and to test -- as plain data than as the state
of a pile of checkboxes.

Nothing is selected until the user says so. The tool's verdicts inform that
choice; they never make it.

The model is folder-level: selecting a folder means everything at or under it.
That is the whole contract, and it is what keeps "what does this free?"
answerable without walking every file.
"""

from . import rules
from .scene_parser import key

# Tri-state, for a tree that shows parents of partly-selected folders.
UNCHECKED = 0
PARTIAL = 1
CHECKED = 2


class Selection(object):
    """
    The set of folders chosen for removal, over one scan's tree.

    Holds node PATHS rather than nodes, so a selection survives a rescan --
    which matters because acting on the selection triggers exactly that.
    """

    def __init__(self, root_node):
        self.root = root_node
        self._chosen = set()          # keys of explicitly selected nodes

    # -- state --------------------------------------------------------------

    def is_selected(self, node):
        """True when this node is selected, itself or through an ancestor."""
        return self._covered(key(node.path))

    def _covered(self, node_key):
        if node_key in self._chosen:
            return True
        # An ancestor being selected selects everything beneath it.
        for chosen in self._chosen:
            if node_key.startswith(chosen + "/"):
                return True
        return False

    def state(self, node):
        """
        CHECKED, PARTIAL or UNCHECKED, for a tri-state checkbox.

        PARTIAL means something under this node is selected but not all of it
        -- the signal that there is more to look at further down.
        """
        if self.is_selected(node):
            return CHECKED
        for child in node.children:
            if self.state(child) != UNCHECKED:
                return PARTIAL
        return UNCHECKED

    # -- editing ------------------------------------------------------------

    def set(self, node, selected):
        """
        Select or deselect a whole subtree.

        Selecting drops any redundant descendant entries, so the set stays the
        minimal description of the choice -- otherwise deselecting a parent
        would leave orphaned children behind and the tree would disagree with
        itself.
        """
        node_key = key(node.path)

        # Either way, everything below is now governed by this node.
        self._chosen = {c for c in self._chosen
                        if not c.startswith(node_key + "/")}

        if selected:
            # If an ancestor is already selected this changes nothing.
            if not self._covered(node_key):
                self._chosen.add(node_key)
            return

        self._chosen.discard(node_key)

        # Deselecting inside a selected ancestor: the ancestor has to be
        # broken up into its other children, or the removal would still be
        # covered by it. This is what makes a tri-state tree behave.
        ancestor = self._selected_ancestor(node_key)
        if ancestor is not None:
            self._explode(ancestor, node_key)

    def _selected_ancestor(self, node_key):
        for chosen in self._chosen:
            if node_key.startswith(chosen + "/"):
                return chosen
        return None

    def _explode(self, ancestor_key, exclude_key):
        """
        Replace a selected ancestor with its children, minus the branch
        leading to the exclusion -- and recurse down that branch, so every
        level between the two is broken up in the same way.

        Recursion is the whole point. Handling only the top level dropped
        every folder on the path: deselecting "render/v01" inside a selected
        root removed "render" and never selected its sibling "render/v02",
        silently shrinking the selection to less than the user asked for.
        """
        node = self._find(ancestor_key)
        self._chosen.discard(ancestor_key)
        if node is None:
            return

        for child in node.children:
            child_key = key(child.path)
            if child_key == exclude_key:
                continue            # the branch being deselected
            if exclude_key.startswith(child_key + "/"):
                # On the path to the exclusion: keep descending, so this
                # child's other children stay selected.
                self._chosen.add(child_key)
                self._explode(child_key, exclude_key)
                continue
            self._chosen.add(child_key)

    def _find(self, node_key):
        if key(self.root.path) == node_key:
            return self.root
        for node in self.root.descendants():
            if key(node.path) == node_key:
                return node
        return None

    def clear(self):
        self._chosen.clear()

    def select_verdict(self, verdict):
        """
        Select every folder carrying a given verdict.

        The convenience behind a "select all Drop" button. Deliberately not a
        default: the user opts in, and this is them doing so explicitly.
        """
        for node in self.root.descendants():
            if node.verdict == verdict and node.report \
                    and (node.report.count or node.report.is_empty):
                self.set(node, True)

    # -- totals -------------------------------------------------------------

    def nodes(self):
        """
        The selected nodes themselves, top-most first, no duplicates.

        Includes the root: descendants() excludes it, and without this a
        selection of the whole project totalled zero bytes.
        """
        found = []
        if key(self.root.path) in self._chosen:
            found.append(self.root)
        for node in self.root.descendants():
            if key(node.path) in self._chosen:
                found.append(node)
        return sorted(found, key=lambda n: n.path)

    def total_bytes(self):
        """
        What removing the selection would free.

        Sums the top-most selected nodes only. Adding every selected
        descendant would double-count, since a selected folder already
        includes everything under it.
        """
        return sum(node.total_size for node in self.nodes())

    def total_files(self):
        return sum(node.total_files for node in self.nodes())

    def is_empty(self):
        return not self._chosen

    def by_verdict(self):
        """
        (verdict -> bytes) across the selection, for the review screen.

        A selection that is mostly Keep-verdict folders is worth showing back
        plainly, because it means the user is overriding the tool.
        """
        totals = {}
        for node in self.nodes():
            verdict = node.verdict or rules.REVIEW
            totals[verdict] = totals.get(verdict, 0) + node.total_size
        return totals

    def overrides(self):
        """
        Selected folders the tool judged worth keeping.

        Surfaced at review because it is the one case where the user and the
        tool disagree, and the user should see that stated rather than
        discover it afterwards.
        """
        return [node for node in self.nodes() if node.verdict == rules.KEEP]
