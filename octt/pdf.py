# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""HTML pages -> PDF through Qt's text engine (no extra dependency).

QTextDocument.print_ ends up with ~20 mm of unexplained extra margin on QPdfWriter, so pages are
painted by hand: the document is laid out in device pixels and each page is a clipped drawContents().
"""
from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument

from octt.reports import Page, to_html
from octt.ui.language import text_font

DPI, MARGIN_MM = 300, 12


def write_pdf(pages: list[Page], path: str, st=None) -> None:
    """All pages share one orientation (taken from the first); every report kind is uniform."""
    if not pages:
        raise ValueError("nothing to print")
    from octt.export import Style, restyle  # late: export imports this module lazily
    st = st or Style()
    w = QPdfWriter(path)
    w.setResolution(DPI)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4),
                                QPageLayout.Landscape if pages[0].landscape else QPageLayout.Portrait,
                                QMarginsF(*[MARGIN_MM] * 4), QPageLayout.Millimeter))
    area = w.pageLayout().paintRectPixels(DPI)
    W, H = float(area.width()), float(area.height())
    doc = QTextDocument()
    doc.documentLayout().setPaintDevice(w)  # lay out in device pixels, fonts at 300 dpi
    font = text_font(st.size or 8)
    if st.font:
        font.setFamily(st.font)
    doc.setDefaultFont(font)
    doc.setPageSize(QSizeF(W, H))
    doc.setHtml(restyle("".join(to_html(p, i == 0) for i, p in enumerate(pages)), st))
    painter = QPainter(w)
    n = doc.pageCount()
    for i in range(n):
        if i:
            w.newPage()
        painter.save()
        painter.translate(0, -i * H)
        doc.drawContents(painter, QRectF(0, i * H, W, H))
        painter.restore()
        painter.setFont(text_font(7))
        painter.drawText(QRectF(0, H + 20, W, 80), Qt.AlignRight, f"{i + 1} / {n}")
    painter.end()
