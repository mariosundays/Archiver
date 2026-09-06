"""The rolled-up tree and the treemap layout. No Qt required."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import scanner, tree
from test_scanner import fake_hip, write


class TreeCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="archiver_tree_").replace("\\", "/")
        # 1 KB at the top, 2 KB one level down, 4 KB two levels down.
        write(self.root + "/loose.exr", b"x" * 1024)
        write(self.root + "/render/mid.exr", b"x" * 2048)
        write(self.root + "/render/v01/deep.exr", b"x" * 4096)
        self.result = scanner.scan(self.root)
        self.tree = tree.build(self.result)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def find(self, name):
        for node in self.tree.descendants():
            if node.name == name:
                return node
        self.fail("no node %r" % name)


class TestRollup(TreeCase):

    def test_root_total_is_everything(self):
        self.assertEqual(self.tree.total_size, 1024 + 2048 + 4096)

    def test_own_size_excludes_children(self):
        self.assertEqual(self.tree.own_size, 1024)

    def test_parent_includes_descendants(self):
        # The whole point of this model, and what the flat report cannot say.
        self.assertEqual(self.find("render").total_size, 2048 + 4096)
        self.assertEqual(self.find("render").own_size, 2048)

    def test_leaf_totals_itself(self):
        leaf = self.find("v01")
        self.assertEqual(leaf.total_size, 4096)
        self.assertEqual(leaf.total_size, leaf.own_size)

    def test_file_counts_roll_up(self):
        self.assertEqual(self.tree.total_files, 3)
        self.assertEqual(self.find("render").total_files, 2)

    def test_children_sorted_biggest_first(self):
        sizes = [c.total_size for c in self.tree.sorted_children()]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


class TestIntermediateFolders(unittest.TestCase):

    def test_folder_with_no_files_still_appears(self):
        # a/b/c holds the file; a and b must exist to hang it from.
        root = tempfile.mkdtemp(prefix="archiver_mid_").replace("\\", "/")
        try:
            write(root + "/a/b/c/file.exr", b"x" * 512)
            node = tree.build(scanner.scan(root))
            names = [n.name for n in node.descendants()]
            self.assertIn("a", names)
            self.assertIn("b", names)
            self.assertEqual(node.total_size, 512)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestFlatten(TreeCase):

    def test_root_first(self):
        rows = tree.flatten(self.tree)
        self.assertIs(rows[0][0], self.tree)
        self.assertEqual(rows[0][1], 0)

    def test_depth_increases(self):
        rows = dict((node.name, depth) for node, depth in
                    tree.flatten(self.tree))
        self.assertEqual(rows["render"], 1)
        self.assertEqual(rows["v01"], 2)

    def test_max_depth_stops(self):
        rows = tree.flatten(self.tree, max_depth=1)
        self.assertNotIn("v01", [n.name for n, _d in rows])

    def test_min_fraction_hides_small(self):
        # Nothing is under 90% of the project, so only the root survives.
        rows = tree.flatten(self.tree, min_fraction=0.9)
        self.assertEqual(len(rows), 1)


class TestSquarify(unittest.TestCase):
    """Geometry only -- these are the properties a treemap must have."""

    def test_areas_are_proportional(self):
        values = [50.0, 30.0, 20.0]
        rects = tree.squarify(values, 0, 0, 100, 100)
        total = sum(w * h for _x, _y, w, h in rects)
        self.assertAlmostEqual(total, 10000, delta=1.0)

        for value, (_x, _y, w, h) in zip(values, rects):
            expected = (value / 100.0) * 10000
            self.assertAlmostEqual(w * h, expected, delta=1.0)

    def test_rectangles_stay_inside(self):
        rects = tree.squarify([5, 4, 3, 2, 1], 0, 0, 200, 120)
        for x, y, w, h in rects:
            self.assertGreaterEqual(round(x, 6), 0)
            self.assertGreaterEqual(round(y, 6), 0)
            self.assertLessEqual(round(x + w, 6), 200)
            self.assertLessEqual(round(y + h, 6), 120)

    def test_rectangles_do_not_overlap(self):
        rects = tree.squarify([8, 6, 5, 3, 2, 1], 0, 0, 300, 200)
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                separate = (a[0] + a[2] <= b[0] + 1e-6
                            or b[0] + b[2] <= a[0] + 1e-6
                            or a[1] + a[3] <= b[1] + 1e-6
                            or b[1] + b[3] <= a[1] + 1e-6)
                self.assertTrue(separate, "%s overlaps %s" % (a, b))

    def test_one_value_fills_everything(self):
        rects = tree.squarify([1], 0, 0, 40, 25)
        self.assertAlmostEqual(rects[0][2] * rects[0][3], 1000, delta=0.01)

    def test_count_is_preserved(self):
        # Zero-sized values still need a slot, or caller indices misalign.
        self.assertEqual(len(tree.squarify([5, 0, 3], 0, 0, 10, 10)), 3)

    def test_degenerate_rect_is_safe(self):
        self.assertEqual(len(tree.squarify([1, 2], 0, 0, 0, 0)), 2)

    def test_empty_values(self):
        self.assertEqual(tree.squarify([], 0, 0, 10, 10), [])

    def test_aspect_ratios_are_reasonable(self):
        # The reason to squarify at all: slice-and-dice makes unusable slivers.
        rects = tree.squarify([10] * 16, 0, 0, 400, 400)
        for _x, _y, w, h in rects:
            if w > 0 and h > 0:
                self.assertLess(max(w / h, h / w), 4.0)


class TestLayoutChildren(TreeCase):

    def test_cells_for_children(self):
        cells = tree.layout_children(self.tree, 400, 300)
        self.assertTrue(cells)
        self.assertTrue(all(c.width >= 0 and c.height >= 0 for c in cells))

    def test_hit_testing(self):
        cells = tree.layout_children(self.tree, 400, 300)
        cell = cells[0]
        self.assertTrue(cell.contains(cell.x + 1, cell.y + 1))
        self.assertFalse(cell.contains(cell.x - 5, cell.y - 5))

    def test_tiny_children_collapse_into_other(self):
        root = tempfile.mkdtemp(prefix="archiver_many_").replace("\\", "/")
        try:
            write(root + "/big/f.exr", b"x" * (8 * 1024 * 1024))
            for i in range(150):
                write(root + "/small%03d/f.exr" % i, b"x" * 16)
            node = tree.build(scanner.scan(root))
            cells = tree.layout_children(node, 300, 200)

            self.assertLessEqual(len(cells), tree.MAX_CELLS + 1)
            self.assertTrue(any(c.is_other for c in cells),
                            "150 tiny folders should collapse")
            other = [c for c in cells if c.is_other][0]
            self.assertIn("Other", other.label)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_empty_folders_still_get_a_cell(self):
        # A zero-byte folder has no area, so strict proportionality drops it
        # from the treemap entirely -- and an empty folder is precisely what
        # the user is looking for. It must be visible and clickable.
        root = tempfile.mkdtemp(prefix="archiver_zero_").replace("\\", "/")
        try:
            write(root + "/big/f.exr", b"x" * (4 * 1024 * 1024))
            os.makedirs(root + "/empty_one")
            os.makedirs(root + "/empty_two")
            node = tree.build(scanner.scan(root))
            cells = tree.layout_children(node, 900, 340)

            names = [c.label for c in cells]
            self.assertIn("empty_one", names)
            self.assertIn("empty_two", names)

            # Presence is not enough -- weighting them into the main layout
            # produced cells of the right AREA but 275x8 in shape, which is
            # unreadable and unclickable. Assert the shape.
            for cell in cells:
                if cell.node.total_size == 0:
                    self.assertGreaterEqual(
                        cell.height, 20,
                        "%s is a sliver: %.0fx%.0f"
                        % (cell.label, cell.width, cell.height))
                    self.assertGreaterEqual(cell.width, 20)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_empty_strip_never_dominates(self):
        # A project with many empty folders must not lose its data folders to
        # the strip.
        root = tempfile.mkdtemp(prefix="archiver_many0_").replace("\\", "/")
        try:
            write(root + "/big/f.exr", b"x" * (4 * 1024 * 1024))
            for i in range(40):
                os.makedirs(root + "/empty%02d" % i)
            node = tree.build(scanner.scan(root))
            cells = tree.layout_children(node, 900, 400)

            big = [c for c in cells if c.label == "big"][0]
            self.assertGreater(big.width * big.height, 900 * 400 * 0.5,
                               "the folder holding the data got crowded out")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_all_empty_uses_the_whole_panel(self):
        root = tempfile.mkdtemp(prefix="archiver_all0_").replace("\\", "/")
        try:
            for name in ("a", "b", "c"):
                os.makedirs(root + "/" + name)
            node = tree.build(scanner.scan(root))
            cells = tree.layout_children(node, 600, 200)
            self.assertEqual(len(cells), 3)
            for cell in cells:
                self.assertGreater(cell.width, 20)
                self.assertGreater(cell.height, 20)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_no_children(self):
        leaf = self.find("v01")
        self.assertEqual(tree.layout_children(leaf, 100, 100), [])


class TestReclaimable(unittest.TestCase):

    def test_rolls_up_drop_folders(self):
        root = tempfile.mkdtemp(prefix="archiver_rec_").replace("\\", "/")
        try:
            write(root + "/tex/keep.exr", b"x" * 1024)
            write(root + "/tmp/junk.tmp", b"x" * 2048)
            node = tree.build(scanner.scan(root))
            # Only tmp/ is a drop, so that is all that is reclaimable.
            self.assertEqual(node.reclaimable(), 2048)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
