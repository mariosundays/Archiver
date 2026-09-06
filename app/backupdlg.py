# Archiver -- step 6: the archive dialog.
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
Choose where the archive goes, and whether it is a folder or a zip.

The plan is recomputed whenever anything changes, so the size, the file count
and any objection are all on screen before the copy starts rather than
discovered part way through a 200 GB job.

The copy runs on a worker thread. It is the longest operation in the app by a
wide margin and a frozen window through it would be unacceptable.
"""

import os

from PySide6 import QtCore, QtWidgets

from core import backup
from core.scanner import human


class ArchiveWorker(QtCore.QObject, QtCore.QRunnable):
    """Runs a plan off the main thread."""

    progress = QtCore.Signal(int, int, str)
    finished = QtCore.Signal(object, object)
    failed = QtCore.Signal(str)

    def __init__(self, plan):
        QtCore.QObject.__init__(self)
        QtCore.QRunnable.__init__(self)
        self.plan = plan
        self._cancel = False
        self.setAutoDelete(False)

    def cancel(self):
        self._cancel = True

    @QtCore.Slot()
    def run(self):
        try:
            def on_file(index, total, relative):
                self.progress.emit(index, total, relative)
                return not self._cancel

            copied, failed = backup.run(self.plan, on_file)
            self.finished.emit(copied, failed)
        except Exception as exc:            # a worker must never die silently
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))


class BackupDialog(QtWidgets.QDialog):
    """Step 6. Copies -- the project is never moved or altered."""

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = root
        self.plan = None
        self.worker = None
        self.pool = QtCore.QThreadPool()

        self.setWindowTitle("Archive project")
        self.resize(720, 400)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

        self._build()
        self._replan()

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        source = QtWidgets.QLabel("Archiving  %s" % self.root)
        source.setWordWrap(True)
        layout.addWidget(source)

        row = QtWidgets.QHBoxLayout()
        self.dest_edit = QtWidgets.QLineEdit()
        self.dest_edit.setPlaceholderText("Destination folder...")
        self.dest_edit.textChanged.connect(self._replan)
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse)
        row.addWidget(QtWidgets.QLabel("To"))
        row.addWidget(self.dest_edit, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        form = QtWidgets.QHBoxLayout()
        self.as_folder = QtWidgets.QRadioButton("Folder copy")
        self.as_folder.setChecked(True)
        self.as_folder.setToolTip(
            "A plain mirror. Fastest, and the archive stays browsable.")
        self.as_zip = QtWidgets.QRadioButton("Zip archive")
        self.as_zip.setToolTip(
            "One .zip file. Measured on a real 3.4 GB project: 99 seconds "
            "against 3 for a folder copy, to save 9%. Worth it when the "
            "archive has to travel as a single file, rarely otherwise.")
        for button in (self.as_folder, self.as_zip):
            button.toggled.connect(self._replan)
        form.addWidget(self.as_folder)
        form.addWidget(self.as_zip)
        form.addStretch(1)

        self.verify_box = QtWidgets.QCheckBox("Verify afterwards")
        self.verify_box.setChecked(True)
        self.verify_box.setToolTip(
            "Compare every file's size at the destination. Catches a copy "
            "that died part way, which is the failure that matters.")
        form.addWidget(self.verify_box)
        layout.addLayout(form)

        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.problems = QtWidgets.QLabel("")
        self.problems.setObjectName("warn")
        self.problems.setWordWrap(True)
        self.problems.hide()
        layout.addWidget(self.problems)

        layout.addStretch(1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)

        self.current = QtWidgets.QLabel("")
        self.current.setObjectName("hint")
        layout.addWidget(self.current)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self._close_requested)
        self.start_button = QtWidgets.QPushButton("Archive")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        self.start_button.setEnabled(False)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

    # -- planning -----------------------------------------------------------

    def _browse(self):
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Where should the archive go?",
            self.dest_edit.text().strip() or os.path.expanduser("~"))
        if chosen:
            self.dest_edit.setText(chosen)

    def _replan(self):
        destination = self.dest_edit.text().strip().strip('"')
        if not destination:
            self.summary.setText("Choose where the archive should go.")
            self.problems.hide()
            self.start_button.setEnabled(False)
            return

        self.plan = backup.plan(self.root, destination,
                                as_zip=self.as_zip.isChecked())

        parts = ["%s in %s files"
                 % (human(self.plan.total_bytes),
                    "{:,}".format(self.plan.count))]
        if self.plan.skipped_files:
            parts.append("leaving behind %s already staged for deletion"
                         % human(self.plan.skipped_bytes))

        free = backup.free_space(destination)
        if free is not None:
            parts.append("%s free at the destination" % human(free))

        target = (backup.zip_path(self.plan) if self.plan.as_zip
                  else destination.rstrip("/") + "/" + self.plan.name)

        # A gigabyte of EXR and MOV compresses by a few percent and costs
        # minutes: measured on a real 3.4 GB project, 99 seconds against 3,
        # to save 9%. Better said beforehand than discovered by waiting.
        note = ""
        if self.plan.as_zip and self.plan.total_bytes > 1024 ** 3:
            note = ("\n\nZipping this much image and video data is slow for "
                    "little gain — a folder copy is usually the better choice "
                    "unless the archive has to travel as a single file.")

        self.summary.setText("  —  ".join(parts) + "\n\n" + target + note)

        if self.plan.problems:
            self.problems.setText("  ".join(self.plan.problems))
            self.problems.show()
        else:
            self.problems.hide()

        self.start_button.setEnabled(not self.plan.problems
                                     and self.plan.count > 0)

    # -- running ------------------------------------------------------------

    def _start(self):
        if self.plan is None or self.plan.problems:
            return

        self.start_button.setEnabled(False)
        self.dest_edit.setEnabled(False)
        self.progress.setRange(0, max(1, self.plan.count))
        self.progress.setValue(0)
        self.progress.show()

        self.worker = ArchiveWorker(self.plan)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.pool.start(self.worker)

    @QtCore.Slot(int, int, str)
    def _on_progress(self, index, total, relative):
        self.progress.setValue(index)
        self.current.setText(relative)

    @QtCore.Slot(str)
    def _on_failed(self, message):
        self.progress.hide()
        self.start_button.setEnabled(True)
        self.dest_edit.setEnabled(True)
        QtWidgets.QMessageBox.critical(self, "Archive",
                                       "The archive failed:\n\n%s" % message)

    @QtCore.Slot(object, object)
    def _on_finished(self, copied, failed):
        self.progress.hide()
        self.current.setText("")
        self.dest_edit.setEnabled(True)
        self.start_button.setEnabled(True)

        cancelled = getattr(self.plan, "cancelled", False)
        incomplete = cancelled or bool(failed)

        # Report what actually arrived, not what was planned. Pairing the real
        # copied count with the planned total overstates a partial archive --
        # dangerous in a tool whose next step is deleting the source.
        moved = self.plan.bytes_for(copied)

        if cancelled:
            lines = ["Archive stopped. %s of %s files copied (%s) before you "
                     "cancelled."
                     % ("{:,}".format(len(copied)),
                        "{:,}".format(self.plan.count), human(moved))]
            lines.append("")
            lines.append("The project itself is untouched. What reached the "
                         "destination is a PARTIAL copy — delete it or run "
                         "the archive again.")
        else:
            lines = ["Archived %s files (%s)."
                     % ("{:,}".format(len(copied)), human(moved))]
            if len(copied) < self.plan.count:
                lines.append("%s of %s planned files did not arrive."
                             % ("{:,}".format(self.plan.count - len(copied)),
                                "{:,}".format(self.plan.count)))

        # Verify whenever anything was attempted. Skipping it when nothing
        # copied hides exactly the case the checkbox exists to catch.
        if self.verify_box.isChecked() and not cancelled:
            self.current.setText("Verifying...")
            QtWidgets.QApplication.processEvents()
            problems = backup.verify(self.plan)
            self.current.setText("")
            if problems:
                lines.append("")
                lines.append("%d file%s did not verify:"
                             % (len(problems),
                                "" if len(problems) == 1 else "s"))
                lines.extend("    %s — %s" % (name, why)
                             for name, why in problems[:8])
                incomplete = True
            elif copied:
                lines.append("Every file verified at the destination.")

        if failed:
            lines.append("")
            lines.append("%d could not be copied:" % len(failed))
            lines.extend("    %s — %s" % (name, why)
                         for name, why in failed[:8])

        if incomplete:
            QtWidgets.QMessageBox.warning(self, "Archive", "\n".join(lines))
        else:
            QtWidgets.QMessageBox.information(self, "Archive",
                                              "\n".join(lines))

    def _running(self):
        return self.worker is not None and self.pool.activeThreadCount() > 0

    def _close_requested(self):
        """
        Close, cancelling a copy in flight.

        reject() does NOT raise a close event, so hanging cancellation off
        closeEvent alone left the copy running against a dead window with
        nothing waiting on it. Both routes come through here.
        """
        if self._running():
            answer = QtWidgets.QMessageBox.question(
                self, "Archive",
                "Stop the archive?\n\nFiles already copied are left at the "
                "destination — the project itself is untouched.",
                QtWidgets.QMessageBox.Cancel | QtWidgets.QMessageBox.Yes,
                QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Yes:
                return
            self._stop()
        self.reject()

    def _stop(self):
        """Ask the worker to stop and wait for it, so nothing writes on after
        the dialog is gone."""
        if self.worker is not None:
            self.worker.cancel()
        self.current.setText("Stopping...")
        QtWidgets.QApplication.processEvents()
        self.pool.waitForDone(30000)

    def closeEvent(self, event):
        if self._running():
            self._stop()
        super().closeEvent(event)
