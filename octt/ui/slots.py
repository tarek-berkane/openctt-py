# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""When a group / class / teacher / room is available: a painted week grid in the timetable's own look
(green = available, grey hatch = not). Click or drag a rectangle to set many periods at once; click a day or a period
to flip all of it; arrows + Space from the keyboard."""
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from octt.i18n import t as tr
from octt.model import Document
from octt.ui.grid import GREEN, UNAVAILABLE

GAP = 3  # between tiles


class SlotGrid(QWidget):
    changed = Signal()

    def __init__(self, doc: Document, blocked: set):
        super().__init__()
        self.days, self.terms = list(doc.days), list(doc.terms)
        self.free = {(t, d) for t in range(len(self.terms)) for d in range(len(self.days))} - set(blocked)
        self.cur = (0, 0)  # keyboard cell
        self.hover = None  # (term|None, day|None): a cell, or a whole row / column under a header
        self.drag = None  # (start cell, state to paint, free set before the drag)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip(tr("Click or drag to change. Click a day or a period to change all of it."))
        self.small = self.font()  # day and period labels: captions, a little smaller than the text
        self.small.setPointSizeF(self.small.pointSizeF() * 0.9)
        fm = QFontMetrics(self.small)
        self.lw = max((fm.horizontalAdvance(t) for t in self.terms), default=0) + 12  # period labels
        self.cw = max(44, max((fm.horizontalAdvance(d) for d in self.days), default=0) + 10)
        self.hh = fm.height() + 8  # day labels
        self.rh = max(26, self.fontMetrics().height() + 10)

    # --- geometry (logical, then mirrored for right-to-left) ---------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(self.lw + len(self.days) * self.cw + 1, self.hh + len(self.terms) * self.rh + 1)

    minimumSizeHint = sizeHint

    def _x(self, x: int, w: int) -> int:
        return self.width() - x - w if self.layoutDirection() == Qt.RightToLeft else x

    def _rect(self, t: int | None, d: int | None) -> QRect:
        """A tile (t, d), a day header (None, d), or a period header (t, None)."""
        x, w = (self.lw + d * self.cw, self.cw) if d is not None else (0, self.lw)
        y, h = (self.hh + t * self.rh, self.rh) if t is not None else (0, self.hh)
        return QRect(self._x(x, w), y, w, h)

    def _at(self, pos: QPoint):
        x = self.width() - pos.x() if self.layoutDirection() == Qt.RightToLeft else pos.x()
        d = (x - self.lw) // self.cw if x >= self.lw else None
        t = (pos.y() - self.hh) // self.rh if pos.y() >= self.hh else None
        if (d is not None and not 0 <= d < len(self.days)) or (t is not None and not 0 <= t < len(self.terms)):
            return None
        return None if t is None and d is None else (t, d)

    # --- state -------------------------------------------------------------------------------------
    def _set(self, free: set):
        if free != self.free:
            self.free = free
            self.update()
            self.changed.emit()

    def _flip(self, cells: set):
        """Flip what most of `cells` are: a mostly free day becomes blocked (one cell simply toggles)."""
        self._set(self.free - cells if 2 * len(cells & self.free) >= len(cells) else self.free | cells)

    def _line(self, t, d) -> set:
        return {(t, dd) for dd in range(len(self.days))} if d is None else {(tt, d) for tt in range(len(self.terms))}

    def set_all(self, on: bool):
        self._set({(t, d) for t in range(len(self.terms)) for d in range(len(self.days))} if on else set())

    # --- painting ----------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        text, muted, accent = pal.color(QPalette.Text), pal.color(QPalette.PlaceholderText), pal.color(QPalette.Highlight)
        line = QColor(text)
        line.setAlpha(40)
        hover_t, hover_d = self.hover if self.hover else (-1, -1)
        for d, name in enumerate(self.days):
            r = self._rect(None, d)
            hot = self.hover is not None and hover_t is None and hover_d == d
            p.setPen(accent if hot else text)
            p.setFont(self.small)
            p.drawText(r, Qt.AlignCenter, name)
        for t, name in enumerate(self.terms):
            r = self._rect(t, None).adjusted(0, 0, -8, 0) if self.layoutDirection() == Qt.LeftToRight \
                else self._rect(t, None).adjusted(8, 0, 0, 0)
            hot = self.hover is not None and hover_d is None and hover_t == t
            p.setPen(accent if hot else muted)
            p.setFont(self.small)
            p.drawText(r, Qt.AlignVCenter | Qt.AlignTrailing, name)  # next to the grid, either direction
        fill, edge = QColor(GREEN), QColor(GREEN)
        fill.setAlpha(70)
        edge.setAlpha(150)
        for t in range(len(self.terms)):
            for d in range(len(self.days)):
                r = self._rect(t, d).adjusted(GAP, GAP, -GAP, -GAP)
                on = (t, d) in self.free
                p.setPen(QPen(edge if on else line, 1))
                p.setBrush(fill if on else pal.color(QPalette.Base))
                p.drawRoundedRect(r, 4, 4)
                if not on:
                    p.setPen(Qt.NoPen)
                    p.setBrush(UNAVAILABLE)
                    p.drawRoundedRect(r, 4, 4)
                in_line = self.hover is not None and None in self.hover and (hover_t == t or hover_d == d)
                if self.hover == (t, d) or in_line:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(accent, 2))
                    p.drawRoundedRect(r, 4, 4)
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(accent, 1.5, Qt.DashLine))
            p.drawRoundedRect(self._rect(*self.cur).adjusted(1, 1, -1, -1), 5, 5)

    # --- mouse -------------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        hit = self._at(e.position().toPoint())
        if e.button() != Qt.LeftButton or hit is None:
            return
        t, d = hit
        if t is None or d is None:  # a header: the whole day / period
            self._flip(self._line(t, d))
            return
        self.cur = hit
        self.drag = (hit, hit not in self.free, set(self.free))
        self._paint_to(hit)

    def _paint_to(self, end):
        (t0, d0), on, before = self.drag
        t1, d1 = end
        rect = {(t, d) for t in range(min(t0, t1), max(t0, t1) + 1) for d in range(min(d0, d1), max(d0, d1) + 1)}
        self._set(before | rect if on else before - rect)

    def mouseMoveEvent(self, e):
        hit = self._at(e.position().toPoint())
        if self.drag and hit and None not in hit:
            self._paint_to(hit)
        if hit != self.hover:
            self.hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()
            if hit and None not in hit:
                state = tr("available") if hit in self.free else tr("not available")
                QToolTip.showText(e.globalPosition().toPoint(), f"{self.days[hit[1]]} {self.terms[hit[0]]}: {state}", self)

    def mouseReleaseEvent(self, _):
        self.drag = None

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    # --- keyboard ----------------------------------------------------------------------------------
    def keyPressEvent(self, e):
        t, d = self.cur
        rtl = self.layoutDirection() == Qt.RightToLeft
        step = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0), Qt.Key_Left: (0, 1 if rtl else -1),
                Qt.Key_Right: (0, -1 if rtl else 1)}.get(e.key())
        if step:
            self.cur = (min(max(t + step[0], 0), len(self.terms) - 1), min(max(d + step[1], 0), len(self.days) - 1))
            self.update()
        elif e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._flip({self.cur})
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)


class Slots(QWidget):
    """The grid plus a count and the two shortcuts people reach for: everything available, or nothing."""
    changed = Signal()

    def __init__(self, doc: Document, blocked: set):
        super().__init__()
        self.grid = SlotGrid(doc, blocked)
        self.count = QLabel()
        self.all_btn = QPushButton(tr("All available"))
        self.none_btn = QPushButton(tr("None available"))
        for b in (self.all_btn, self.none_btn):  # quiet links: the grid is the main control
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton { color: palette(link); border: none; padding: 2px 4px; }"
                            "QPushButton:hover { text-decoration: underline; }"
                            "QPushButton:disabled { color: palette(mid); }")
        g = self.grid  # not `self` in the lambdas: a cycle back to this widget crashes PySide's shutdown
        self.all_btn.clicked.connect(lambda: g.set_all(True))
        self.none_btn.clicked.connect(lambda: g.set_all(False))
        hint = QLabel(tr("Click or drag to change. Click a day or a period to change all of it."), wordWrap=True)
        hint.setEnabled(False)  # muted, in every theme
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.count)
        row.addStretch(1)
        row.addWidget(self.all_btn)
        row.addWidget(self.none_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.grid, 0, Qt.AlignLeading)
        lay.addLayout(row)
        lay.addWidget(hint)
        self.grid.changed.connect(self._changed)
        self._count()

    def _count(self):
        n, m = len(self.grid.free), len(self.grid.days) * len(self.grid.terms)
        self.count.setText(tr("{n} of {m} periods available", n=n, m=m))
        self.all_btn.setEnabled(n < m)
        self.none_btn.setEnabled(n > 0)

    def _changed(self):
        self._count()
        self.changed.emit()

    def blocked(self) -> set:
        g = self.grid
        return {(t, d) for t in range(len(g.terms)) for d in range(len(g.days))} - g.free
