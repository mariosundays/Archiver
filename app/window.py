# Archiver -- the main window.
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
The main window: check the project, see what can go, select, review.

Steps 1-4 of the wizard. All of it reads except one action -- deleting empty
folders -- which is delegated to core.actions and cannot lose data, since an
empty folder has nothing in it at any depth. Steps 5 and 6 (move to
_toDelete, then archive out) are not built.

The scan runs on a QThreadPool worker. A cold network project can take a while
and a frozen window during it would be unacceptable.
"""

import os

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from core import actions, report, rules, scanner, selection, tree
from core.scanner import human

from .bars import (CATEGORY_FILL, Legend, SizeBarDelegate,
                   StackedBar, VERDICT_FILL)
from .explorer import add_reveal_menu
from .filelist import FileListPanel
from .review import ReviewDialog

DARK = "#1a1a1a"
PANEL = "#212121"
TEXT = "#e0e0e0"
DIM = "#9aa0a6"

STYLE = """
QWidget { background: %(dark)s; color: %(text)s;
          font-family: 'Segoe UI'; font-size: 12px; }
QPushButton { background: #2e2e2e; border: 1px solid #3d3d3d;
              padding: 6px 14px; border-radius: 3px; }
QPushButton:hover { background: #383838; }
QPushButton:disabled { color: #666; background: #242424; }
QPushButton#primary { background: #35566e; border-color: #44708f; }
QPushButton#primary:hover { background: #3f6382; }
QLineEdit { background: #171717; border: 1px solid #3d3d3d;
            padding: 6px; border-radius: 3px; }
QTreeWidget { background: %(panel)s; border: 1px solid #303030;
              alternate-background-color: #262626; }
QTreeWidget::item { padding: 3px; }
QTreeWidget::item:selected { background: #35566e; }
/* An unticked box on a dark row was nearly invisible -- a light border and a
   lifted fill make it read as an empty control rather than as absent. */
QTreeWidget::indicator { width: 14px; height: 14px; border-radius: 3px; }
QTreeWidget::indicator:unchecked { background: #3a3f45; border: 1px solid #6c757d; }
QTreeWidget::indicator:unchecked:hover { background: #49505a; border: 1px solid #93a1ad; }
QTreeWidget::indicator:checked { background: #4c8fd6; border: 1px solid #7fb4e8;
                                 image: none; }
QTreeWidget::indicator:indeterminate { background: #2f5f8f; border: 1px solid #7fb4e8; }
/* Qt draws a dotted focus rectangle over the current item; across a coloured
   size bar it reads as an error outline. The selection fill is enough. */
QTreeWidget { outline: 0; }
QTreeWidget::item:focus { border: 0; }
QHeaderView::section { background: #2a2a2a; padding: 5px;
                       border: 0; border-right: 1px solid #333; }
QLabel#hint { color: %(dim)s; }
QLabel#warn { color: #ffb86b; background: #3a2f1c;
              padding: 8px; border-radius: 3px; }
QProgressBar { background: #171717; border: 1px solid #333;
               border-radius: 3px; text-align: center; }
QProgressBar::chunk { background: #35566e; }
QTabWidget::pane { border: 1px solid #303030; }
QTabBar::tab { background: #262626; padding: 7px 16px; border: 0; }
QTabBar::tab:selected { background: #35566e; }
""" % {"dark": DARK, "panel": PANEL, "text": TEXT, "dim": DIM}


def _short_path(relative, keep=2):
    """
    The tail of a path, which is the part that identifies it.

    Every row in the findings table shares a long prefix, so Qt's elide eats
    the folder name and leaves the identical project stem visible on every
    line. Showing the last couple of segments instead makes the rows
    distinguishable; the full path stays in the tooltip.
    """
    parts = [p for p in (relative or "").split("/") if p]
    if len(parts) <= keep:
        return relative or "."
    return ".../" + "/".join(parts[-keep:])


def _node_path(item):
    """The on-disk path behind a tree row, for the right-click menu."""
    node = item.data(0, Qt.UserRole)
    if node is None:
        return None
    # The overview tree stores tree.Node objects; the findings table stores
    # FolderReport. Both carry .path.
    return getattr(node, "path", None)


def _age_of(node):
    """
    A node's age, rolled up.

    A FolderReport only knows the mtime of files directly inside it, so every
    folder that holds only subfolders reported a blank age -- which was most
    of the tree. Take the newest thing anywhere underneath instead: for
    "how stale is this?", the most recent touch is the honest answer.
    """
    newest = node.report.mtime if node.report else 0
    for child in node.descendants():
        if child.report and child.report.mtime > newest:
            newest = child.report.mtime
    return scanner.age_label(newest) if newest else ""


class ScanWorker(QtCore.QObject, QtCore.QRunnable):
    """
    Runs a scan off the main thread.

    QRunnable has no signals of its own, so this pairs it with a QObject. The
    scan itself is pure Python and touches no Qt, which is what makes handing
    it to a worker safe.
    """

    progress = QtCore.Signal(int, str)
    scenes = QtCore.Signal(int, int)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, root):
        QtCore.QObject.__init__(self)
        QtCore.QRunnable.__init__(self)
        self.root = root
        self._cancel = False
        self.setAutoDelete(False)

    def cancel(self):
        self._cancel = True

    @QtCore.Slot()
    def run(self):
        try:
            def on_walk(seen, folder):
                self.progress.emit(seen, folder)
                return not self._cancel

            def on_scene(index, total, path):
                self.scenes.emit(index + 1, total)
                return not self._cancel

            result = scanner.scan(self.root, on_walk, on_scene)
            if self._cancel:
                return
            self.finished.emit(result)
        except Exception as exc:            # never let a worker die silently
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))


class MainWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Archiver")
        self.resize(1180, 780)
        self.setStyleSheet(STYLE)

        self.result = None
        self.tree_root = None
        self.current = None
        self.selection = None
        self._syncing = False
        self.pool = QtCore.QThreadPool()
        self.worker = None

        self._build()

    # -- layout -------------------------------------------------------------

    def _build(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        outer.addLayout(self._build_pathbar())

        self.warning = QtWidgets.QLabel()
        self.warning.setObjectName("warn")
        self.warning.setWordWrap(True)
        self.warning.hide()
        outer.addWidget(self.warning)

        self.summary = QtWidgets.QLabel("No project scanned yet.")
        self.summary.setObjectName("hint")
        outer.addWidget(self.summary)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_overview(), "1 - Check project")
        self.tabs.addTab(self._build_findings(), "2 - What can go")
        outer.addWidget(self.tabs, 1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)

        self.status = self.statusBar()
        self.status.showMessage("Pick a project folder to begin.")

    def _build_pathbar(self):
        row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("Project folder...")
        self.path_edit.returnPressed.connect(self.start_scan)

        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse)

        self.scan_button = QtWidgets.QPushButton("Scan")
        self.scan_button.setObjectName("primary")
        self.scan_button.clicked.connect(self.start_scan)

        self.export_button = QtWidgets.QPushButton("Export JSON")
        self.export_button.clicked.connect(self._export)
        self.export_button.setEnabled(False)

        row.addWidget(QtWidgets.QLabel("Project"))
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        row.addWidget(self.scan_button)
        row.addWidget(self.export_button)
        return row

    def _build_overview(self):
        """
        The tree IS the view.

        An earlier version gave the treemap a 340px panel above the tree, and
        the two competed for the same job -- the treemap needed drilling to
        say anything, while the tree said it immediately. Putting the
        proportion INSIDE the row, as a bar next to the folder it describes,
        makes the hierarchy and the sizes readable in a single pass. The
        stacked strips above answer the two whole-project questions the tree
        cannot: how much can go, and what is this made of.
        """
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        layout.addLayout(self._build_strips())

        self.folder_tree = QtWidgets.QTreeWidget()
        self.folder_tree.setHeaderLabels(
            ["Folder", "Size", "Share", "Files", "Verdict", "Age"])
        self.folder_tree.setAlternatingRowColors(True)
        self.folder_tree.setRootIsDecorated(True)
        self.folder_tree.setUniformRowHeights(True)
        self.folder_tree.setSortingEnabled(False)
        # No inline rename. A double-click means "open this folder", and an
        # accidental edit box in a tool that will later move files is a hazard.
        self.folder_tree.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self.folder_tree.itemDoubleClicked.connect(self._tree_activated)
        self.folder_tree.currentItemChanged.connect(self._on_tree_current)
        self.folder_tree.itemChanged.connect(self._on_item_checked)

        # The delegate goes on the WHOLE tree, not just the bar column: it
        # also suppresses Qt's focus rectangle, and that has to apply to every
        # column or the dotted outline just moves to the ones it does not own.
        self._bar_delegate = SizeBarDelegate(self)
        self.folder_tree.setItemDelegate(self._bar_delegate)

        header = self.folder_tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Fixed)
        self.folder_tree.setColumnWidth(2, 190)
        for column in (1, 3, 4, 5):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeToContents)

        add_reveal_menu(self.folder_tree, _node_path)

        # The file panel lives in a splitter so it can be dragged to any
        # height, and starts hidden -- it only makes sense once you have
        # asked about a specific segment.
        self.overview_split = QtWidgets.QSplitter(Qt.Vertical)
        self.overview_split.addWidget(self.folder_tree)

        self.file_panel = FileListPanel()
        self.file_panel.closed.connect(self._close_file_panel)
        self.file_panel.hide()
        self.overview_split.addWidget(self.file_panel)
        self.overview_split.setStretchFactor(0, 3)
        self.overview_split.setStretchFactor(1, 2)

        layout.addWidget(self.overview_split, 1)
        layout.addLayout(self._build_selection_bar())
        return page

    def _build_selection_bar(self):
        """
        Step 3: what you have chosen, and what it would free.

        Nothing starts ticked. The verdicts are the tool's opinion; the ticks
        are the user's decision, and an accidental Approve on an untouched
        scan must do nothing at all.
        """
        row = QtWidgets.QHBoxLayout()

        self.select_drops = QtWidgets.QPushButton("Tick all Drop")
        self.select_drops.clicked.connect(self._select_drops)
        self.select_drops.setEnabled(False)

        self.clear_selection = QtWidgets.QPushButton("Clear")
        self.clear_selection.clicked.connect(self._clear_selection)
        self.clear_selection.setEnabled(False)

        self.selection_label = QtWidgets.QLabel("Nothing selected")
        self.selection_label.setObjectName("hint")

        self.review_button = QtWidgets.QPushButton("Review selection")
        self.review_button.setObjectName("primary")
        self.review_button.clicked.connect(self._review)
        self.review_button.setEnabled(False)

        row.addWidget(self.select_drops)
        row.addWidget(self.clear_selection)
        row.addSpacing(12)
        row.addWidget(self.selection_label, 1)
        row.addWidget(self.review_button)
        return row

    def _build_strips(self):
        """The two slim summary bars: verdict, then category."""
        grid = QtWidgets.QVBoxLayout()
        grid.setSpacing(2)

        self.verdict_bar = StackedBar(16)
        self.verdict_legend = Legend()
        self.category_bar = StackedBar(16)
        self.category_legend = Legend()

        self.verdict_bar.segment_activated.connect(self._show_verdict_files)
        self.verdict_legend.segment_activated.connect(self._show_verdict_files)
        self.category_bar.segment_activated.connect(self._show_category_files)
        self.category_legend.segment_activated.connect(
            self._show_category_files)

        grid.addWidget(self.verdict_bar)
        grid.addWidget(self.verdict_legend)
        grid.addSpacing(4)
        grid.addWidget(self.category_bar)
        grid.addWidget(self.category_legend)
        return grid

    def _fill_strips(self):
        result = self.result
        totals = result.totals()

        self.verdict_bar.set_segments([
            (rules.VERDICT_LABEL[v], totals[v][0], VERDICT_FILL[v], v)
            for v in (rules.KEEP, rules.REVIEW, rules.DROP)])
        self.verdict_legend.set_items([
            ("%s %s" % (rules.VERDICT_LABEL[v], human(totals[v][0])),
             VERDICT_FILL[v], v)
            for v in (rules.KEEP, rules.REVIEW, rules.DROP)
            if totals[v][0]])

        categories = result.by_category()
        self.category_bar.set_segments([
            (rules.CATEGORY_LABEL.get(name, name), size,
             CATEGORY_FILL.get(name, CATEGORY_FILL[rules.CAT_OTHER]), name)
            for name, size in categories])
        # Only the handful worth naming; the rest stay in the tooltip.
        self.category_legend.set_items([
            ("%s %s" % (rules.CATEGORY_LABEL.get(name, name), human(size)),
             CATEGORY_FILL.get(name, CATEGORY_FILL[rules.CAT_OTHER]), name)
            for name, size in categories[:5] if size])

    def _build_findings(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)

        row = QtWidgets.QHBoxLayout()
        self.filters = {}
        for verdict in (rules.DROP, rules.REVIEW, rules.KEEP):
            box = QtWidgets.QCheckBox(rules.VERDICT_LABEL[verdict])
            box.setChecked(verdict != rules.KEEP)
            box.stateChanged.connect(self._fill_findings)
            self.filters[verdict] = box
            row.addWidget(box)
        row.addStretch(1)
        self.findings_total = QtWidgets.QLabel("")
        self.findings_total.setObjectName("hint")
        row.addWidget(self.findings_total)
        layout.addLayout(row)

        self.findings = QtWidgets.QTreeWidget()
        self.findings.setHeaderLabels(
            ["Folder", "Size", "Files", "Verdict", "Why", "Age"])
        self.findings.setAlternatingRowColors(True)
        self.findings.setRootIsDecorated(False)
        self.findings.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self.findings.itemChanged.connect(self._on_finding_checked)
        add_reveal_menu(self.findings, _node_path)
        header = self.findings.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        self.findings.setColumnWidth(0, 340)
        layout.addWidget(self.findings, 1)

        bottom = QtWidgets.QHBoxLayout()
        note = QtWidgets.QLabel(
            "Report only — nothing here has been moved or deleted. "
            "Selecting and approving comes next.")
        note.setObjectName("hint")
        bottom.addWidget(note, 1)

        # The one action v1 will actually perform. Removing an empty directory
        # cannot lose data, which is what makes it safe to ship ahead of the
        # select/approve flow.
        self.prune_button = QtWidgets.QPushButton("Delete empty folders")
        self.prune_button.clicked.connect(self._prune_empty)
        self.prune_button.setEnabled(False)
        bottom.addWidget(self.prune_button)

        layout.addLayout(bottom)
        return page

    def _prune_empty(self):
        if not self.result or not self.result.empty_folders:
            return

        count = len(self.result.empty_folders)
        preview = "\n".join(
            "    " + p[len(self.result.root):].lstrip("/")
            for p in sorted(self.result.empty_folders)[:15])
        if count > 15:
            preview += "\n    ... and %d more" % (count - 15)

        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Delete empty folders")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("Permanently delete %d empty folder%s?"
                    % (count, "" if count == 1 else "s"))
        box.setInformativeText(
            "They contain no files at any depth, so nothing can be lost.\n"
            "Any folder that has gained a file since the scan will be "
            "skipped and reported.\n\n" + preview)
        box.setStandardButtons(QtWidgets.QMessageBox.Cancel |
                               QtWidgets.QMessageBox.Yes)
        box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        if box.exec() != QtWidgets.QMessageBox.Yes:
            return

        removed, failed = actions.prune_empty_folders(self.result,
                                                      dry_run=False)
        message = "Removed %d folder%s." % (len(removed),
                                            "" if len(removed) == 1 else "s")
        if failed:
            message += ("\n\n%d could not be removed:\n\n" % len(failed)
                        + "\n".join("%s\n    %s"
                                    % (path[len(self.result.root):], why)
                                    for path, why in failed[:8]))
            QtWidgets.QMessageBox.warning(self, "Delete empty folders",
                                          message)
        else:
            QtWidgets.QMessageBox.information(self, "Delete empty folders",
                                              message)
        self.status.showMessage(message.splitlines()[0])
        self.start_scan()       # the tree on screen is now stale

    # -- scanning -----------------------------------------------------------

    def _browse(self):
        start = self.path_edit.text().strip() or os.path.expanduser("~")
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose a project folder", start)
        if chosen:
            self.path_edit.setText(chosen)
            self.start_scan()

    def start_scan(self):
        root = self.path_edit.text().strip().strip('"')
        if not root or not os.path.isdir(root):
            QtWidgets.QMessageBox.warning(
                self, "Archiver", "That is not a folder:\n\n%s" % root)
            return

        self.scan_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.progress.show()
        self.warning.hide()
        self.status.showMessage("Scanning...")

        self.worker = ScanWorker(root)
        self.worker.progress.connect(self._on_progress)
        self.worker.scenes.connect(self._on_scenes)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.pool.start(self.worker)

    @QtCore.Slot(int, str)
    def _on_progress(self, seen, folder):
        self.status.showMessage("Scanning... %s files" % "{:,}".format(seen))

    @QtCore.Slot(int, int)
    def _on_scenes(self, index, total):
        self.status.showMessage("Reading scenes... %d/%d" % (index, total))

    @QtCore.Slot(str)
    def _on_failed(self, message):
        self.progress.hide()
        self.scan_button.setEnabled(True)
        self.status.showMessage("Scan failed.")
        QtWidgets.QMessageBox.critical(self, "Archiver",
                                       "The scan failed:\n\n%s" % message)

    @QtCore.Slot(object)
    def _on_finished(self, result):
        self.progress.hide()
        self.scan_button.setEnabled(True)
        self.export_button.setEnabled(True)

        self.result = result
        self.tree_root = tree.build(result)
        self.selection = selection.Selection(self.tree_root)
        self._show_node(self.tree_root)
        self.select_drops.setEnabled(True)
        self._update_selection_label()
        self._fill_findings()
        self._update_summary()
        self.prune_button.setEnabled(bool(result.empty_folders))
        self.prune_button.setText(
            "Delete %d empty folders" % len(result.empty_folders)
            if result.empty_folders else "No empty folders")
        self.status.showMessage(
            "Scanned %s files in %.1fs — nothing was modified."
            % ("{:,}".format(result.total_files), result.duration))

    def _update_summary(self):
        result = self.result
        totals = result.totals()
        parts = []
        for verdict in (rules.KEEP, rules.REVIEW, rules.DROP):
            size, folders, _files = totals[verdict]
            parts.append("%s %s in %d folders"
                         % (rules.VERDICT_LABEL[verdict], human(size),
                            folders))
        self.summary.setText(
            "%s in %s files, %d scenes   —   %s   —   "
            "reclaimable now %s"
            % (human(result.total_size),
               "{:,}".format(result.total_files), len(result.scenes),
               "   ".join(parts), human(result.reclaimable())))

        notes = []
        if result.opaque_scenes:
            notes.append(
                "%d scene%s could not be read (Cinema 4D R20+ files are "
                "compressed). Nothing was checked against them, so caches "
                "and geometry they use look unreferenced — verdicts "
                "here lean on file type and location only."
                % (len(result.opaque_scenes),
                   "" if len(result.opaque_scenes) == 1 else "s"))
        if result.empty_folders:
            notes.append("%d empty folder%s found."
                         % (len(result.empty_folders),
                            "" if len(result.empty_folders) == 1 else "s"))
        if notes:
            self.warning.setText("  ".join(notes))
            self.warning.show()
        else:
            self.warning.hide()

    # -- overview -----------------------------------------------------------

    def _show_node(self, node):
        self.current = node
        self._fill_folder_tree(node)
        self._fill_strips()

    def _fill_folder_tree(self, node):
        """
        The whole hierarchy under node, with a share bar on every row.

        Share is measured against the PARENT, not the project. Against the
        project every row below the top two would be a flat nothing on a
        3 GB job; against the parent, each level answers "what dominates
        here?", which is the question you ask at every step down.
        """
        self.folder_tree.clear()

        def add(parent_item, child, parent_size):
            item = QtWidgets.QTreeWidgetItem(parent_item)
            item.setText(0, child.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setText(1, child.human_size)

            fraction = (child.total_size / float(parent_size)
                        if parent_size else 0.0)
            # The project root is always 100% of itself; a full bar there is
            # noise. Every row below it earns one.
            if parent_item is not None or len(node.children) > 1:
                item.setData(2, SizeBarDelegate.FRACTION, fraction)
                item.setData(2, SizeBarDelegate.VERDICT, child.verdict)
                item.setToolTip(2, "%.1f%% of %s"
                                % (100.0 * fraction,
                                   parent_item.text(0) if parent_item
                                   else "the project"))

            item.setText(3, "{:,}".format(child.total_files))
            verdict = child.verdict
            item.setText(4, rules.VERDICT_LABEL.get(verdict, ""))
            item.setText(5, _age_of(child))
            item.setData(0, Qt.UserRole, child)

            if verdict:
                item.setForeground(4, QtGui.QBrush(
                    VERDICT_FILL[verdict].lighter(150)))
            if child.report and child.report.reason:
                item.setToolTip(4, child.report.reason)
                item.setToolTip(0, child.report.reason)

            for grandchild in child.sorted_children():
                add(item, grandchild, child.total_size)
            return item

        for child in node.sorted_children():
            self.folder_tree.addTopLevelItem(
                add(None, child, node.total_size))

        self._expand_biggest()

    def _expand_biggest(self):
        """
        Open the path down to where the data actually is.

        Expanding one level shows top-level folders; expanding everything
        buries them. Following the biggest child down puts the folder worth
        looking at on screen without any clicking, which on the test project
        is the 2.8 GB alembic cache four levels deep.
        """
        item = self.folder_tree.topLevelItem(0)
        depth = 0
        while item is not None and depth < 6:
            item.setExpanded(True)
            if not item.childCount():
                break
            # Children are added biggest-first, so index 0 is the heaviest.
            item = item.child(0)
            depth += 1
        if item is not None:
            self.folder_tree.setCurrentItem(item)
            self.folder_tree.scrollToItem(item)

    # -- drill-down ---------------------------------------------------------

    def _show_category_files(self, category):
        """List every file of one category in the panel below the tree."""
        if not self.result:
            return
        self._open_file_panel(
            rules.CATEGORY_LABEL.get(category, category),
            self.result.files_in_category(category))

    def _show_verdict_files(self, verdict):
        if not self.result:
            return
        self._open_file_panel(
            "%s folders" % rules.VERDICT_LABEL.get(verdict, verdict),
            self.result.files_with_verdict(verdict))

    def _open_file_panel(self, title, sequences):
        self.file_panel.show_sequences(title, sequences, self.result.root)
        if not self.file_panel.isVisible():
            self.file_panel.show()
            height = self.overview_split.height()
            self.overview_split.setSizes([int(height * 0.6),
                                          int(height * 0.4)])

    def _close_file_panel(self):
        self.file_panel.hide()

    # -- selection ----------------------------------------------------------

    def _on_item_checked(self, item, column):
        """
        A checkbox changed. Push it into the model, then redraw every box.

        The guard matters: setCheckState below re-enters this slot, and
        without it a single click would recurse through the whole tree
        rewriting the model as it went.
        """
        if column != 0 or self._syncing or self.selection is None:
            return
        node = item.data(0, Qt.UserRole)
        if node is None:
            return

        self.selection.set(node, item.checkState(0) == Qt.Checked)
        self._sync_check_states()
        self._sync_finding_states()
        self._update_selection_label()

    def _on_finding_checked(self, item, column):
        """
        A checkbox on the findings tab. Same model as the tree.

        Both tabs edit ONE selection, so ticking a folder here shows up on the
        overview tree and in the total. Two independent selections would be a
        trap -- you would approve one having looked at the other.
        """
        if column != 0 or self._syncing or self.selection is None:
            return
        folder = item.data(0, Qt.UserRole)
        if folder is None:
            return
        node = self._node_for_path(getattr(folder, "path", None))
        if node is None:
            return

        self.selection.set(node, item.checkState(0) == Qt.Checked)
        self._sync_check_states()
        self._sync_finding_states()
        self._update_selection_label()

    def _node_for_path(self, path):
        if not path or self.tree_root is None:
            return None
        wanted = str(path).lower()
        if self.tree_root.path.lower() == wanted:
            return self.tree_root
        for node in self.tree_root.descendants():
            if node.path.lower() == wanted:
                return node
        return None

    def _sync_finding_states(self):
        """Repaint the findings checkboxes from the model."""
        if self.selection is None:
            return
        self._syncing = True
        try:
            for index in range(self.findings.topLevelItemCount()):
                item = self.findings.topLevelItem(index)
                folder = item.data(0, Qt.UserRole)
                node = self._node_for_path(getattr(folder, "path", None))
                if node is None:
                    continue
                state = self.selection.state(node)
                item.setCheckState(0, {
                    selection.CHECKED: Qt.Checked,
                    selection.PARTIAL: Qt.PartiallyChecked,
                    selection.UNCHECKED: Qt.Unchecked,
                }[state])
        finally:
            self._syncing = False

    def _sync_check_states(self):
        """
        Repaint every checkbox from the model.

        The model is the truth, not the widgets: ticking a parent implies its
        children, unticking a child breaks the parent into its siblings, and
        both are easier to compute once and apply than to maintain click by
        click.
        """
        state_map = {
            selection.CHECKED: Qt.Checked,
            selection.PARTIAL: Qt.PartiallyChecked,
            selection.UNCHECKED: Qt.Unchecked,
        }

        self._syncing = True
        try:
            stack = [self.folder_tree.topLevelItem(i)
                     for i in range(self.folder_tree.topLevelItemCount())]
            while stack:
                item = stack.pop()
                node = item.data(0, Qt.UserRole)
                if node is not None:
                    item.setCheckState(
                        0, state_map[self.selection.state(node)])
                stack.extend(item.child(i) for i in range(item.childCount()))
        finally:
            self._syncing = False

    def _update_selection_label(self):
        if self.selection is None or self.selection.is_empty():
            self.selection_label.setText("Nothing selected")
            self.review_button.setEnabled(False)
            self.clear_selection.setEnabled(False)
            return

        folders = len(self.selection.nodes())
        text = ("Selected %s in %d folder%s (%s files)"
                % (human(self.selection.total_bytes()), folders,
                   "" if folders == 1 else "s",
                   "{:,}".format(self.selection.total_files())))

        overrides = self.selection.overrides()
        if overrides:
            text += "  —  including %d the scan says keep" % len(overrides)

        self.selection_label.setText(text)
        self.review_button.setEnabled(True)
        self.clear_selection.setEnabled(True)

    def _select_drops(self):
        if self.selection is None:
            return
        self.selection.select_verdict(rules.DROP)
        self._sync_check_states()
        self._sync_finding_states()
        self._sync_finding_states()
        self._update_selection_label()

    def _clear_selection(self):
        if self.selection is None:
            return
        self.selection.clear()
        self._sync_check_states()
        self._sync_finding_states()
        self._update_selection_label()

    def _review(self):
        dialog = ReviewDialog(self.selection, self.result, self)
        dialog.exec()

    def _tree_activated(self, item, _column):
        # Double-click toggles the branch. There is no drill-down mode any
        # more -- the whole tree is present, so opening a folder means
        # expanding it.
        item.setExpanded(not item.isExpanded())

    def _on_tree_current(self, item, _previous):
        if item is None:
            return
        node = item.data(0, Qt.UserRole)
        if node is None:
            return
        self.status.showMessage(
            "%s — %s in %s files%s"
            % (node.name, node.human_size,
               "{:,}".format(node.total_files),
               "  |  " + node.report.reason
               if node.report and node.report.reason else ""))

    # -- findings -----------------------------------------------------------

    def _fill_findings(self):
        self.findings.clear()
        if not self.result:
            return

        wanted = {v for v, box in self.filters.items() if box.isChecked()}
        total = 0
        shown = 0

        for folder in self.result.folders:
            if folder.verdict not in wanted:
                continue
            if not folder.count and not folder.is_empty:
                continue

            item = QtWidgets.QTreeWidgetItem(self.findings)
            # The relative path is long and every row shares a prefix, so a
            # plain elide hides the only part that identifies the folder.
            # Lead with the name, keep the path behind it and in the tooltip.
            item.setText(0, _short_path(folder.relative))
            item.setToolTip(0, folder.path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setText(1, folder.human_size)
            item.setText(2, "{:,}".format(folder.count))
            item.setText(3, rules.VERDICT_LABEL[folder.verdict])
            item.setText(4, folder.reason)
            item.setText(5, folder.age)
            item.setForeground(3, QtGui.QBrush(
                VERDICT_FILL[folder.verdict].lighter(160)))
            item.setData(0, Qt.UserRole, folder)
            total += folder.size
            shown += 1

        self.findings_total.setText(
            "%d folders, %s" % (shown, human(total)))
        self._sync_finding_states()

    # -- export -------------------------------------------------------------

    def _export(self):
        if not self.result:
            return
        default = os.path.join(
            os.path.expanduser("~"),
            "%s_archiver.json" % os.path.basename(self.result.root.rstrip("/")))
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save report", default, "JSON (*.json)")
        if not path:
            return
        try:
            report.write_json(self.result, path)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Archiver",
                                          "Could not write:\n\n%s" % exc)
            return
        self.status.showMessage("Report written to %s" % path)
