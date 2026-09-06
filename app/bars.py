# Archiver -- the inline size bar and the summary strips.
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
Two ways of drawing a proportion.

SizeBarDelegate puts a bar INSIDE a tree row. That is the whole idea behind
this view: the bar sits in the same line as the folder it describes, so the
hierarchy and the sizes are read in one pass instead of looking between a
tree and a separate panel. Length is share of the parent; colour is the
verdict, so "big" and "disposable" are legible at once.

StackedBar is the slim summary strip -- one line, whole project, no
interaction beyond a tooltip.
"""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from core import rules
from core.scanner import human

# Verdict colours, shared with the rest of the UI.
VERDICT_FILL = {
    rules.KEEP: QtGui.QColor("#3f8f66"),
    rules.REVIEW: QtGui.QColor("#b08a3e"),
    rules.DROP: QtGui.QColor("#b05353"),
    None: QtGui.QColor("#5a5a5a"),
}

CATEGORY_FILL = {
    rules.CAT_CACHE: QtGui.QColor("#5b7fa6"),
    rules.CAT_RENDER: QtGui.QColor("#7a6ba8"),
    rules.CAT_COMP: QtGui.QColor("#4f8f8f"),
    rules.CAT_SOURCE: QtGui.QColor("#3f8f66"),
    rules.CAT_GEO_IN: QtGui.QColor("#6ba85f"),
    rules.CAT_SCENE: QtGui.QColor("#c2a34a"),
    rules.CAT_DELIVERY: QtGui.QColor("#c98a4b"),
    rules.CAT_BACKUP: QtGui.QColor("#a35b5b"),
    rules.CAT_TEMP: QtGui.QColor("#8a5b7a"),
    rules.CAT_DOC: QtGui.QColor("#7a8a99"),
    rules.CAT_OTHER: QtGui.QColor("#666666"),
}

# A segment thinner than this cannot be seen or hovered. Small categories are
# exactly the ones worth noticing, so they get floored to it.
MIN_SEGMENT_PX = 6.0

TRACK = QtGui.QColor("#2a2a2a")
TRACK_EDGE = QtGui.QColor("#333333")


# Verdict glyphs. Drawn rather than shipped as files: three coloured shapes
# need no assets, scale with the font, and cannot go missing from a build.
_VERDICT_ICONS = {}


def verdict_icon(verdict, size=13):
    """A small round badge for a verdict. Cached, since every row asks."""
    cache_key = (verdict, size)
    if cache_key in _VERDICT_ICONS:
        return _VERDICT_ICONS[cache_key]

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    colour = VERDICT_FILL.get(verdict, VERDICT_FILL[None])
    painter.setBrush(colour)
    painter.setPen(QtGui.QPen(colour.lighter(150), 1))
    painter.drawEllipse(1, 1, size - 2, size - 2)

    # A mark inside, so the three are told apart without relying on colour:
    # keep is a tick, review a question, drop a cross.
    painter.setPen(QtGui.QPen(QtGui.QColor("#12181d"), 1.6))
    inset = size * 0.30
    if verdict == rules.KEEP:
        painter.drawLine(QtCore.QPointF(inset, size * 0.52),
                         QtCore.QPointF(size * 0.44, size - inset))
        painter.drawLine(QtCore.QPointF(size * 0.44, size - inset),
                         QtCore.QPointF(size - inset, inset))
    elif verdict == rules.DROP:
        painter.drawLine(QtCore.QPointF(inset, inset),
                         QtCore.QPointF(size - inset, size - inset))
        painter.drawLine(QtCore.QPointF(size - inset, inset),
                         QtCore.QPointF(inset, size - inset))
    else:
        painter.drawLine(QtCore.QPointF(size * 0.5, size * 0.34),
                         QtCore.QPointF(size * 0.5, size * 0.60))
        painter.drawPoint(QtCore.QPointF(size * 0.5, size * 0.76))
    painter.end()

    icon = QtGui.QIcon(pixmap)
    _VERDICT_ICONS[cache_key] = icon
    return icon


CATEGORY_GLYPH = {
    rules.CAT_SCENE: "◆",       # filled diamond -- the project itself
    rules.CAT_SOURCE: "●",      # filled circle  -- solid, irreplaceable
    rules.CAT_GEO_IN: "▲",      # triangle       -- imported
    rules.CAT_CACHE: "▣",       # boxed square   -- generated
    rules.CAT_RENDER: "■",      # square         -- output
    rules.CAT_COMP: "▥",        # hatched square
    rules.CAT_BACKUP: "○",      # hollow circle  -- a copy
    rules.CAT_TEMP: "◌",        # dotted circle  -- disposable
    rules.CAT_DOC: "▬",         # bar            -- a page
    rules.CAT_DELIVERY: "★",    # star           -- the finished work
    rules.CAT_OTHER: "▷",
}


class SizeBarDelegate(QtWidgets.QStyledItemDelegate):
    """
    Draws a proportional bar in a tree column.

    The row supplies two things through item data: a fraction in [0, 1] and a
    verdict. Everything else -- the track, the label, the selection background
    -- is handled here so the tree stays a plain QTreeWidget.
    """

    FRACTION = Qt.UserRole + 10
    VERDICT = Qt.UserRole + 11

    def initStyleOption(self, option, index):
        """
        Strip the focus state before anything is drawn.

        Qt paints its focus rectangle over the current item, and across a
        coloured bar it comes out as a bright dotted outline that reads as an
        error. Clearing it inside paint() is too late and a stylesheet
        `outline: 0` does not reach it either -- the flag has to be gone from
        the style option itself. The selection fill already shows the row.
        """
        super().initStyleOption(option, index)
        option.state &= ~QtWidgets.QStyle.StateFlag.State_HasFocus

    def paint(self, painter, option, index):
        fraction = index.data(self.FRACTION)
        if fraction is None:
            super().paint(painter, option, index)
            return

        painter.save()

        if option.state & QtWidgets.QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        rect = option.rect.adjusted(4, 5, -4, -5)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        # The track, so a near-empty bar still reads as "measured, and small"
        # rather than as a missing value.
        painter.setPen(QtGui.QPen(TRACK_EDGE, 1))
        painter.setBrush(TRACK)
        painter.drawRoundedRect(rect, 2, 2)

        fraction = max(0.0, min(1.0, float(fraction)))
        if fraction > 0:
            filled = QtCore.QRectF(rect)
            # Always at least a sliver, so a real-but-tiny folder is not drawn
            # as nothing at all.
            filled.setWidth(max(2.0, rect.width() * fraction))
            colour = VERDICT_FILL.get(index.data(self.VERDICT),
                                      VERDICT_FILL[None])
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(filled, 2, 2)

        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        hint.setHeight(max(hint.height(), 22))
        return hint


class StackedBar(QtWidgets.QWidget):
    """
    One slim horizontal bar of proportional segments.

    Deliberately small and non-interactive: it answers a single question at a
    glance and gets out of the way. Hovering names the segment.
    """

    # Double-clicking a segment asks "what is actually in there?".
    segment_activated = QtCore.Signal(object)

    def __init__(self, height=18, parent=None):
        super().__init__(parent)
        self._segments = []          # (label, value, QColor, key)
        self._total = 0
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Fixed)

    def set_segments(self, segments):
        """
        segments: (label, value, QColor) or (label, value, QColor, key),
        largest first. The optional key is what segment_activated carries --
        the category or verdict the segment stands for.
        """
        normalised = []
        for segment in segments:
            if segment[1] <= 0:
                continue
            if len(segment) == 3:
                segment = tuple(segment) + (None,)
            normalised.append(tuple(segment))
        self._segments = normalised
        self._total = sum(s[1] for s in self._segments)
        self.update()

    def mouseDoubleClickEvent(self, event):
        segment = self._segment_at(event.position().x())
        if segment is not None and segment[3] is not None:
            self.segment_activated.emit(segment[3])
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        rect = QtCore.QRectF(self.rect()).adjusted(0, 0, -1, -1)
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 3, 3)
        painter.fillPath(path, TRACK)

        if not self._total:
            return

        painter.setClipPath(path)
        for offset, width, colour in self._laid_out(rect.width()):
            painter.fillRect(QtCore.QRectF(offset, rect.top(),
                                           width + 0.5, rect.height()),
                             colour)

        painter.setClipping(False)
        painter.setPen(QtGui.QPen(TRACK_EDGE, 1))
        painter.drawPath(path)

    def _laid_out(self, width):
        """
        Segment geometry as (offset, width, colour), floored so a small
        segment is still visible.

        Strict proportionality loses the segments that most need saying. On a
        real project 2 MB of disposable backups inside 3.4 GB is 0.06% -- a
        third of a pixel -- so the red simply was not there, and the bar
        implied there was nothing to clean.

        Any non-zero segment therefore gets at least MIN_SEGMENT_PX, taken
        pro-rata from the segments big enough to spare it. The large ones
        stay honest to within a couple of pixels, and every category present
        is at least visible. Painting and hit-testing share this, so a
        tooltip always names the segment actually under the cursor.
        """
        if not self._total or width <= 0:
            return []

        widths = [width * (segment[1] / float(self._total))
                  for segment in self._segments]

        short = [i for i, w in enumerate(widths) if w < MIN_SEGMENT_PX]
        if short:
            owed = sum(MIN_SEGMENT_PX - widths[i] for i in short)
            spare = [i for i, w in enumerate(widths) if w > MIN_SEGMENT_PX * 2]
            pool = sum(widths[i] for i in spare)

            # Only rescale when the big segments can actually cover it;
            # otherwise everything is small and proportions stay as they are.
            if pool > owed:
                for i in spare:
                    widths[i] -= owed * (widths[i] / pool)
                for i in short:
                    widths[i] = MIN_SEGMENT_PX

        out = []
        offset = 0.0
        for segment, segment_width in zip(self._segments, widths):
            out.append((offset, segment_width, segment[2]))
            offset += segment_width
        return out

    def _segment_at(self, x):
        for index, (offset, width, _colour) in enumerate(
                self._laid_out(self.width())):
            if offset <= x < offset + width:
                return self._segments[index]
        return self._segments[-1] if self._segments else None

    def event(self, event):
        if event.type() == QtCore.QEvent.Type.ToolTip:
            segment = self._segment_at(event.pos().x())
            if segment:
                label, value = segment[0], segment[1]
                QtWidgets.QToolTip.showText(
                    event.globalPos(),
                    "%s — %s (%.0f%%)" % (label, human(value),
                                          100.0 * value / self._total),
                    self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(event)


class _LegendEntry(QtWidgets.QLabel):
    """One legend label that reports its own double-click."""

    def __init__(self, text, key, on_activate, parent=None):
        super().__init__(text, parent)
        self._key = key
        self._on_activate = on_activate
        if key is not None:
            self.setCursor(Qt.PointingHandCursor)

    def mouseDoubleClickEvent(self, event):
        if self._key is not None:
            self._on_activate(self._key)
        super().mouseDoubleClickEvent(event)


class Legend(QtWidgets.QWidget):
    """
    A row of swatch + label pairs, sized to sit under a StackedBar.

    Entries are double-clickable for the same reason the bar is: a thin
    segment is hard to hit, and the legend names the same thing in a target
    you can actually click.
    """

    segment_activated = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

    def set_items(self, items):
        """items: (text, QColor) or (text, QColor, key)."""
        while self._layout.count():
            child = self._layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for item in items:
            text, colour = item[0], item[1]
            key = item[2] if len(item) > 2 else None
            swatch = _LegendEntry("", key, self.segment_activated.emit)
            swatch.setFixedSize(9, 9)
            swatch.setStyleSheet("background: %s; border-radius: 2px;"
                                 % colour.name())
            label = _LegendEntry(text, key, self.segment_activated.emit)
            label.setObjectName("hint")
            if key is not None:
                label.setToolTip("Double-click to list these files")
            self._layout.addWidget(swatch)
            self._layout.addWidget(label)
            self._layout.addSpacing(8)
        self._layout.addStretch(1)
