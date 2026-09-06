"""
Rebuild the application icon from the Lucide SVG.

Run from the repo root: python tools/make_icon.py

Kept as a script rather than a build step because the icon changes about once
a year, and a checked-in .ico is one less thing to go wrong at package time.
"""

import os
import struct
import sys

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(HERE, "app", "resources")

SIZES = [16, 24, 32, 48, 64, 128, 256]
GLYPH = "#e8e8e8"
TILE = "#23282e"


def render(svg_text, size):
    """One square icon: the glyph on a dark rounded tile."""
    svg = svg_text.replace('stroke="currentColor"', 'stroke="%s"' % GLYPH)
    image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setBrush(QtGui.QColor(TILE))
    painter.setPen(QtCore.Qt.NoPen)
    radius = max(2, int(size * 0.18))
    painter.drawRoundedRect(QtCore.QRectF(0, 0, size, size), radius, radius)

    pad = size * 0.17
    QSvgRenderer(QtCore.QByteArray(svg.encode())).render(
        painter, QtCore.QRectF(pad, pad, size - 2 * pad, size - 2 * pad))
    painter.end()
    return image


def write_ico(png_paths, out_path):
    """A PNG-compressed .ico, which Windows Vista and later accept."""
    blobs = [(size, open(path, "rb").read()) for size, path in png_paths]
    header = struct.pack("<HHH", 0, 1, len(blobs))

    offset = 6 + 16 * len(blobs)
    entries = b""
    data = b""
    for size, blob in blobs:
        # 256 is stored as 0 in the directory entry.
        edge = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32,
                               len(blob), offset)
        data += blob
        offset += len(blob)

    with open(out_path, "wb") as handle:
        handle.write(header + entries + data)


def main():
    QtWidgets.QApplication(sys.argv)
    svg_text = open(os.path.join(RESOURCES, "archive.svg"),
                    encoding="utf-8").read()

    pngs = []
    for size in SIZES:
        path = os.path.join(RESOURCES, "icon_%d.png" % size)
        render(svg_text, size).save(path)
        pngs.append((size, path))

    render(svg_text, 256).save(os.path.join(RESOURCES, "icon.png"))
    write_ico(pngs, os.path.join(RESOURCES, "icon.ico"))
    print("wrote %d PNGs and icon.ico" % len(SIZES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
