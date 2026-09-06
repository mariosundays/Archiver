# Archiver -- the birds-eye view: a folder tree with rolled-up sizes.
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
The folder tree, with sizes rolled up -- what step 1 shows you.

The scan's FolderReport list is deliberately FLAT and non-overlapping: each
folder counts only the files directly in it, so the totals add up. That is the
right model for a report and the wrong one for a birds-eye view, where the
question is "how big is render/, everything included?".

So this builds the other model on the same data: a tree where every node's
size includes its descendants. Both come from one walk.

Also here: the squarified treemap layout, so the view can draw itself. Pure
geometry, no Qt -- the layout is testable without a display, and the widget
just paints the rectangles it is handed.
"""

import os

from . import rules
from .scanner import human
from .scene_parser import clean, key


class Node(object):
    """
    One folder in the tree.

    own_size is what sits directly in it; total_size includes descendants.
    Keeping both is what lets the view say "render/ is 40 GB, of which 12 GB
    is loose in the folder itself".
    """

    __slots__ = ("path", "name", "parent", "children", "own_size",
                 "own_files", "report", "_total_size", "_total_files")

    def __init__(self, path, name, parent=None):
        self.path = path
        self.name = name
        self.parent = parent
        self.children = []
        self.own_size = 0
        self.own_files = 0
        self.report = None          # the FolderReport, when one exists
        self._total_size = None
        self._total_files = None

    @property
    def total_size(self):
        """Bytes in this folder and everything under it."""
        if self._total_size is None:
            self._total_size = self.own_size + sum(
                child.total_size for child in self.children)
        return self._total_size

    @property
    def total_files(self):
        if self._total_files is None:
            self._total_files = self.own_files + sum(
                child.total_files for child in self.children)
        return self._total_files

    @property
    def human_size(self):
        return human(self.total_size)

    @property
    def verdict(self):
        """This folder's own verdict, or None for a pure container."""
        return self.report.verdict if self.report else None

    @property
    def category(self):
        return self.report.category if self.report else None

    def reclaimable(self):
        """Bytes under here that are marked drop, including descendants."""
        total = 0
        if self.report is not None and self.report.verdict == rules.DROP:
            total += self.report.size
        for child in self.children:
            total += child.reclaimable()
        return total

    def descendants(self):
        """Every node below this one, depth first."""
        for child in self.children:
            yield child
            for node in child.descendants():
                yield node

    def sorted_children(self):
        """Children biggest first -- the only useful order for this view."""
        return sorted(self.children, key=lambda n: -n.total_size)

    def __repr__(self):
        return "<Node %s %s>" % (self.name, self.human_size)


def build(result):
    """
    Turn a ScanResult into a size-rolled-up tree. Returns the root Node.

    Intermediate folders that hold no files of their own still appear, because
    a path like render/v03/exr needs its middle folder to hang the leaf from.
    """
    root_path = clean(result.root)
    root = Node(root_path, os.path.basename(root_path) or root_path)
    nodes = {key(root_path): root}

    def node_for(path):
        """Find or create the node for a path, building parents as needed."""
        path = clean(path)
        path_key = key(path)
        if path_key in nodes:
            return nodes[path_key]

        parent_path = clean(os.path.dirname(path))
        # Guard against walking above the root, or a malformed path looping.
        if not parent_path or parent_path == path \
                or not path_key.startswith(key(root_path)):
            return root

        parent = node_for(parent_path)
        node = Node(path, os.path.basename(path), parent)
        parent.children.append(node)
        nodes[path_key] = node
        return node

    for report in result.folders:
        node = node_for(report.path)
        node.own_size = report.size
        node.own_files = report.count
        node.report = report

    return root


def flatten(node, depth=0, max_depth=None, min_fraction=0.0, total=None):
    """
    The tree as (node, depth) rows for a table, biggest first.

    min_fraction hides folders too small to matter -- a project has hundreds of
    folders and maybe twenty worth looking at. Passing 0.01 shows everything
    over 1% of the project.
    """
    total = total if total is not None else node.total_size
    rows = [(node, depth)]

    if max_depth is not None and depth >= max_depth:
        return rows

    for child in node.sorted_children():
        if total and (child.total_size / float(total)) < min_fraction:
            continue
        rows.extend(flatten(child, depth + 1, max_depth, min_fraction, total))
    return rows


# ---------------------------------------------------------------------------
# Squarified treemap layout
#
# Bruls, Huizing & van Wijk (2000). The plain "slice and dice" layout produces
# slivers that are impossible to see or click; squarifying keeps rectangles
# near-square by greedily filling a row until adding another would make the
# aspect ratio worse.
#
# Geometry only, deliberately: it returns plain tuples, so it is testable with
# no display and the widget's only job is to paint what it is given.
# ---------------------------------------------------------------------------

# Below this a rectangle is too small to see or click, so it is not worth
# laying out. The remainder is bucketed into a single "other" cell instead.
MIN_CELL_PX = 3.0

# A level with more cells than this is unreadable whatever their size.
MAX_CELLS = 80

# Target edge for a zero-byte folder's tile. Big enough to read a short label
# and hit with the mouse.
MIN_EMPTY_PX = 46.0


def _worst_ratio(row, length, scale):
    """The worst aspect ratio in a row -- the value squarify minimises."""
    if not row or length <= 0:
        return float("inf")
    total = sum(row) * scale
    if total <= 0:
        return float("inf")
    side = total / length
    worst = 0.0
    for value in row:
        area = value * scale
        if area <= 0:
            continue
        ratio = max(side * side / area, area / (side * side))
        worst = max(worst, ratio)
    return worst or float("inf")


def _layout_row(row, scale, x, y, width, height, horizontal, out):
    """Place one settled row of rectangles, and return the shrunken space."""
    total = sum(row) * scale
    if total <= 0:
        return x, y, width, height

    if horizontal:
        row_height = total / width if width else 0
        offset = x
        for value in row:
            cell_width = (value * scale) / row_height if row_height else 0
            out.append((offset, y, cell_width, row_height))
            offset += cell_width
        return x, y + row_height, width, height - row_height

    row_width = total / height if height else 0
    offset = y
    for value in row:
        cell_height = (value * scale) / row_width if row_width else 0
        out.append((x, offset, row_width, cell_height))
        offset += cell_height
    return x + row_width, y, width - row_width, height


def squarify(values, x, y, width, height):
    """
    Lay out values as a squarified treemap inside the given rectangle.

    values must be positive and sorted descending. Returns a list of
    (x, y, w, h) tuples, one per value, in the same order.
    """
    values = [float(v) for v in values]
    rects = []
    if width <= 0 or height <= 0:
        return [(x, y, 0.0, 0.0) for _ in values]

    remaining = [v for v in values if v > 0]
    if not remaining:
        return [(x, y, 0.0, 0.0) for _ in values]

    scale = (width * height) / sum(remaining)
    row = []
    index = 0

    while index < len(remaining):
        value = remaining[index]
        horizontal = width >= height
        length = width if horizontal else height

        # Greedy: keep adding to the row while the worst ratio improves.
        if row and _worst_ratio(row, length, scale) <= \
                _worst_ratio(row + [value], length, scale):
            x, y, width, height = _layout_row(row, scale, x, y, width, height,
                                              horizontal, rects)
            row = []
            continue

        row.append(value)
        index += 1

    if row:
        _layout_row(row, scale, x, y, width, height, width >= height, rects)

    # Values that were zero or negative got no rectangle; pad so the caller's
    # indices still line up with what it passed in.
    while len(rects) < len(values):
        rects.append((x, y, 0.0, 0.0))
    return rects


class Cell(object):
    """One laid-out rectangle, ready to paint."""

    __slots__ = ("node", "x", "y", "width", "height", "is_other", "count")

    def __init__(self, node, rect, is_other=False, count=1):
        self.node = node
        self.x, self.y, self.width, self.height = rect
        self.is_other = is_other
        self.count = count

    @property
    def label(self):
        if self.is_other:
            return "Other (%d)" % self.count
        return self.node.name

    def contains(self, px, py):
        return (self.x <= px < self.x + self.width
                and self.y <= py < self.y + self.height)


def layout_children(node, width, height, max_cells=MAX_CELLS):
    """
    Lay out one node's children as treemap cells.

    Children too small to see are collapsed into a single "Other" cell rather
    than drawn as invisible slivers -- a rectangle under a few pixels cannot be
    read or clicked, so drawing it only costs time and clutter.
    """
    children = node.sorted_children()
    if not children or width <= 0 or height <= 0:
        return []

    # Zero-byte folders are laid out SEPARATELY, in their own strip along the
    # bottom, rather than mixed into the weighted layout.
    #
    # Giving them a fake weight instead was the obvious approach and it does
    # not work: squarify optimises aspect ratio across the whole rectangle, so
    # a run of equal tiny weights packs into one row and each cell comes out
    # 275x8 -- the right AREA, unusable shape. Splitting the space first is
    # what actually guarantees a clickable tile, and it keeps the weighted
    # part strictly proportional, which is the property that matters for the
    # folders that hold real data.
    sized = [c for c in children if c.total_size > 0]
    empty = [c for c in children if c.total_size <= 0]

    if not sized:
        return _grid_cells(empty, 0.0, 0.0, float(width), float(height))

    strip = 0.0
    if empty:
        # One row of tiles, never more than a fifth of the panel.
        rows = 1 + (len(empty) - 1) // max(1, int(width // MIN_EMPTY_PX))
        strip = min(rows * MIN_EMPTY_PX, height * 0.2)

    main_height = float(height) - strip
    if main_height < MIN_EMPTY_PX:      # too short to split; drop the strip
        main_height, strip = float(height), 0.0
        empty = []

    children = sized
    weights = [float(c.total_size) for c in children]
    area = float(width) * main_height

    total = float(sum(weights))
    if total <= 0:
        return []

    # Everything below the visible threshold, plus anything past the cap.
    keep = []
    keep_weights = []
    spill = []
    spill_weight = 0.0
    for index, (child, weight) in enumerate(zip(children, weights)):
        cell_area = (weight / total) * area
        too_small = cell_area < (MIN_CELL_PX * MIN_CELL_PX)
        if index >= max_cells or too_small:
            spill.append(child)
            spill_weight += weight
        else:
            keep.append(child)
            keep_weights.append(weight)

    values = list(keep_weights)
    if spill_weight > 0:
        values.append(spill_weight)

    rects = squarify(values, 0.0, 0.0, float(width), main_height)

    cells = [Cell(child, rects[index]) for index, child in enumerate(keep)]
    if spill_weight > 0:
        cells.append(Cell(node, rects[len(keep)], is_other=True,
                          count=len(spill)))

    if empty and strip > 0:
        cells.extend(_grid_cells(empty, 0.0, main_height,
                                 float(width), strip))
    return cells


def _grid_cells(nodes, x, y, width, height):
    """
    Equal tiles in a simple grid. Used for zero-byte folders, which have no
    size to be proportional to -- every one is worth exactly as much attention
    as the next.
    """
    if not nodes or width <= 0 or height <= 0:
        return []

    columns = max(1, min(len(nodes), int(width // MIN_EMPTY_PX) or 1))
    rows = 1 + (len(nodes) - 1) // columns
    cell_w = width / columns
    cell_h = height / rows

    cells = []
    for index, node in enumerate(nodes):
        column = index % columns
        row = index // columns
        cells.append(Cell(node, (x + column * cell_w, y + row * cell_h,
                                 cell_w, cell_h)))
    return cells
