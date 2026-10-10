# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Timetable grid + to-place list: custom-painted lesson blocks, drag chips, hover reasons."""
from dataclasses import dataclass

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QFont, QFontMetrics, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHeaderView, QListWidget, QListWidgetItem,
                               QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem)

from octt.i18n import t as tr

MIME = "application/x-octt-lesson"
BLOCKS = Qt.UserRole  # item data: list[Block]
UNAVAILABLE = QBrush(QColor(120, 120, 120, 130), Qt.BDiagPattern)
INK = QColor("#1b1b1b")  # pastel blocks always get dark text, whatever the theme
GREEN, RED = QColor(46, 160, 67), QColor(214, 69, 65)  # "you can drop here" / "you can't"


@dataclass
class Block:
    course_id: int
    title: str
    detail: str
    color: str
    tip: str = ""
    locked: bool = False  # pinned: drawn with a padlock, the solver and drag/drop leave it alone


def swatch(color: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QPen(QColor(0, 0, 0, 70)))
    p.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    p.end()
    return QIcon(pm)


def chip(text: str, color: str, font: QFont) -> QPixmap:
    """The little label that follows the cursor while dragging a lesson."""
    fm = QFontMetrics(font)
    w, h = fm.horizontalAdvance(text) + 22, fm.height() + 12
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QPen(QColor(0, 0, 0, 120), 1))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)
    p.setPen(INK)
    p.setFont(font)
    p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)
    p.end()
    return pm


def no_entry(size: int = 28) -> QPixmap:
    """The cursor shown while hovering a refused cell: a red disc with a white bar."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    _no_entry(p, QPointF(size / 2, size / 2), size / 2 - 1)
    p.end()
    return pm


def _no_entry(p: QPainter, c: QPointF, r: float):
    p.save()
    p.setPen(QPen(Qt.white, max(1.0, r / 7)))
    p.setBrush(RED)
    p.drawEllipse(c, r, r)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawRoundedRect(QRectF(c.x() - r * 0.58, c.y() - r * 0.17, r * 1.16, r * 0.34), r * 0.1, r * 0.1)
    p.restore()


def _start_drag(w, cid: int, src, label: str, color: str):
    m = QMimeData()
    m.setData(MIME, f"{cid}|{'' if src is None else src[0]}|{'' if src is None else src[1]}".encode())
    w.drag_begin.emit(cid, src)
    d = QDrag(w)
    d.setMimeData(m)
    pm = chip(label, color, w.font())
    d.setPixmap(pm)
    d.setHotSpot(QPoint(12, pm.height() // 2))
    d.setDragCursor(no_entry(), Qt.IgnoreAction)  # where the drop is refused the cursor says so
    d.exec(Qt.MoveAction)
    w.drag_end.emit()


def _read(e):
    """-> (course_id, src_slot_or_None), or None if the drag isn't ours."""
    if not e.mimeData().hasFormat(MIME):
        return None
    c, t, d = bytes(e.mimeData().data(MIME)).decode().split("|")
    return int(c), ((int(t), int(d)) if t else None)


class LessonList(QListWidget):
    """Lessons still to place (drag source). Dropping a placed lesson here takes it off the grid."""
    drag_begin, drag_end = Signal(int, object), Signal()
    unplaced = Signal(int, object)

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setIconSize(QPixmap(14, 14).size())
        self.empty_text = tr("Nothing left to place")
        self.target = False  # a placed lesson is being dragged: this list is where it can go to be removed
        self.hover = False

    def set_target(self, on: bool):
        self.target, self.hover = on, False
        self.viewport().update()

    def fill(self, rows: list[tuple[int, str, str]]):
        """rows: (course_id, text, color)"""
        self.target = self.hover = False
        self.clear()
        for cid, text, color in rows:
            it = QListWidgetItem(swatch(color), text, self)
            it.setData(Qt.UserRole, cid)
            it.setData(Qt.UserRole + 1, color)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        r = self.viewport().rect()
        if self.target:  # cue for "drop a placed lesson here to take it off the grid"
            p.setRenderHint(QPainter.Antialiasing)
            c = QColor(GREEN)
            c.setAlpha(110 if self.hover else 45)
            p.fillRect(r, c)
            p.setPen(QPen(GREEN, 3 if self.hover else 1.5, Qt.SolidLine if self.hover else Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(r).adjusted(1.5, 1.5, -1.5, -1.5))
            p.setPen(self.palette().text().color())
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.drawText(r.adjusted(12, 0, -12, 0), Qt.AlignCenter | Qt.TextWordWrap, tr("Drop here to take the lesson off the timetable"))
        elif not self.count():
            p.setPen(self.palette().placeholderText().color())
            p.drawText(r.adjusted(12, 0, -12, 0), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)

    def startDrag(self, actions):
        if it := self.currentItem():
            _start_drag(self, it.data(Qt.UserRole), None, it.text(), it.data(Qt.UserRole + 1))

    def dragEnterEvent(self, e):
        if (r := _read(e)) and r[1]:
            self.hover = True
            self.viewport().update()
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dragLeaveEvent(self, e):
        self.hover = False
        self.viewport().update()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        if (r := _read(e)) and r[1]:
            self.unplaced.emit(*r)
            e.acceptProposedAction()


@dataclass
class DragState:
    """What the grid knows about the lesson currently being dragged."""
    block: Block
    src: tuple | None  # slot it comes from (a move), None when dragged from the to-place list
    bad: dict  # slot -> reasons it cannot go there; every other slot accepts the drop
    hover: tuple | None = None


class CellDelegate(QStyledItemDelegate):
    """Paints each lesson of a cell as a rounded coloured block, plus live drag feedback on top:
    green = you can drop here, red hatch + no-entry sign = you can't (with the reason on hover)."""

    def __init__(self, parent, highlight: QColor):
        super().__init__(parent)
        self.highlight = highlight  # the view's own selection fill is made transparent; we draw an outline

    @staticmethod
    def block(p: QPainter, box: QRectF, b: Block, font: QFont, ghost: bool = False, rtl: bool = False):
        p.setPen(QPen(QColor(0, 0, 0, 120 if ghost else 60), 1, Qt.DashLine if ghost else Qt.SolidLine))
        p.setBrush(QColor(b.color))
        p.drawRoundedRect(box, 5, 5)
        inner = box.adjusted(6, 3, -6, -3)
        if b.locked and not ghost:  # padlock in the trailing corner; the text gives way to it
            w = 11.0
            x = inner.left() if rtl else inner.right() - w
            p.setPen(QPen(INK, 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(x + 2, inner.top() + 0.5, w - 4, 7), 0, 180 * 16)
            p.setBrush(INK)
            p.drawRoundedRect(QRectF(x, inner.top() + 4.5, w, 6.5), 1.5, 1.5)
            inner = inner.adjusted(w + 3 if rtl else 0, 0, 0 if rtl else -(w + 3), 0)
        bold = QFont(font)
        bold.setBold(True)
        p.setPen(INK)
        p.setFont(bold)
        p.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)  # AlignLeading = right edge when RTL
        fm = QFontMetrics(bold)
        flags = Qt.AlignLeading | Qt.AlignTop
        p.drawText(QRectF(inner.left(), inner.top(), inner.width(), fm.height()), flags,
                   fm.elidedText(b.title, Qt.ElideRight, int(inner.width())))
        if box.height() - 6 >= 2 * fm.height() + 6:
            p.setFont(font)
            fm2 = QFontMetrics(font)
            p.drawText(QRectF(inner.left(), inner.top() + fm.height(), inner.width(), fm2.height()), flags,
                       fm2.elidedText(b.detail, Qt.ElideRight, int(inner.width())))

    def paint(self, painter, option, index):
        st: DragState | None = self.parent().dnd
        slot = (index.row(), index.column())
        r = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.fillRect(r, bg)
        blocks = index.data(BLOCKS) or []
        rtl = option.direction == Qt.RightToLeft
        if st and st.src == slot:
            painter.setOpacity(0.35)  # the lesson being moved looks "lifted" from its cell
        for i, b in enumerate(blocks):
            h = r.height() / len(blocks)
            self.block(painter, QRectF(r.x() + 3, r.y() + i * h + 3, r.width() - 6, h - 6), b, option.font, rtl=rtl)
        painter.setOpacity(1)
        if st:
            self._feedback(painter, option, r, st, slot, blocks, rtl)
        if option.state & QStyle.State_Selected:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(self.highlight, 2.5))
            painter.drawRect(r.adjusted(1.5, 1.5, -1.5, -1.5))
        painter.restore()

    def _feedback(self, p: QPainter, option, r: QRectF, st: "DragState", slot, blocks, rtl: bool = False):
        hover = st.hover == slot
        frame = r.adjusted(1.5, 1.5, -1.5, -1.5)
        if st.src == slot:  # where it came from: dashed outline, nothing to decide
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(option.palette.text().color(), 1.5, Qt.DashLine))
            p.drawRect(frame)
            return
        reasons = st.bad.get(slot)
        if reasons is not None:  # refused
            fill = QColor(RED)
            fill.setAlpha(100 if hover else 42)
            p.fillRect(r, fill)
            hatch = QColor(RED)
            hatch.setAlpha(110 if hover else 70)
            p.fillRect(r, QBrush(hatch, Qt.BDiagPattern))
            p.setBrush(Qt.NoBrush)
            if hover:
                p.setPen(QPen(RED, 3))
                p.drawRect(frame)
                self._reason(p, option, r, reasons[0])
            else:
                _no_entry(p, QPointF(r.left() + 12 if rtl else r.right() - 12, r.top() + 12), 8)
            return
        fill = QColor(GREEN)  # accepted
        fill.setAlpha(105 if hover else 45)
        p.fillRect(r, fill)
        p.setBrush(Qt.NoBrush)
        if hover:
            p.setPen(QPen(GREEN, 3))
            p.drawRect(frame)
            if not blocks:  # preview of the lesson as it will look once dropped
                p.setOpacity(0.9)
                self.block(p, r.adjusted(3, 3, -3, -3), st.block, option.font, ghost=True, rtl=rtl)
                p.setOpacity(1)
        else:
            c = QColor(GREEN)
            c.setAlpha(170)
            p.setPen(QPen(c, 1.5, Qt.DashLine))
            p.drawRect(frame)

    @staticmethod
    def _reason(p: QPainter, option, r: QRectF, text: str):
        """No-entry sign in the middle of the hovered cell and the reason written under it."""
        side = min(14.0, r.height() * 0.2)
        _no_entry(p, QPointF(r.center().x(), r.top() + r.height() * 0.32), side)
        flags = Qt.AlignHCenter | Qt.AlignBottom | Qt.TextWordWrap
        area = r.adjusted(8, 0, -8, -6).toRect()
        want = p.fontMetrics().boundingRect(area, flags, text)
        box = QRectF(want).adjusted(-6, -3, 6, 3)
        p.setPen(QPen(RED, 1))
        c = option.palette.base().color()
        c.setAlpha(240)
        p.setBrush(c)
        p.drawRoundedRect(box, 4, 4)
        p.setPen(option.palette.text().color())
        p.drawText(area, flags, text)


class Grid(QTableWidget):
    """Terms down, days across. Cells hold Block lists; drag a block to move it, drop on a cell to place."""
    drag_begin, drag_end = Signal(int, object), Signal()
    dropped = Signal(int, object, int, int)  # course, src slot or None, row, col
    hint = Signal(str)  # why the cell under a drag is refused ("" = fine)
    remove = Signal(int, object)  # course, slot (Delete key)
    edit_course = Signal(int)  # double-click
    menu = Signal(int, int, object, object)  # row, col, course id or None, global pos

    def __init__(self):
        super().__init__()
        self.bad: dict[tuple[int, int], list[str]] = {}
        self.dnd: DragState | None = None  # live drag feedback, None when nothing is being dragged
        self._press = QPoint()
        hl = QApplication.palette().highlight().color()
        pal = self.palette()
        pal.setBrush(QPalette.Highlight, Qt.transparent)  # no solid selection fill over the lesson blocks
        self.setPalette(pal)
        self.setItemDelegate(CellDelegate(self, hl))
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setMinimumSectionSize(54)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)

    def set_dims(self, days: list[str], terms: list[str]):
        self.setRowCount(len(terms))
        self.setColumnCount(len(days))
        self.setHorizontalHeaderLabels(days)
        self.setVerticalHeaderLabels([f"{i + 1}\n{t}" for i, t in enumerate(terms)])

    def fill(self, cells: dict[tuple[int, int], list[Block]], unavailable: set):
        self.bad, self.dnd = {}, None
        for t in range(self.rowCount()):
            for d in range(self.columnCount()):
                it = QTableWidgetItem()
                blocks = cells.get((t, d), [])
                it.setData(BLOCKS, blocks)
                if blocks:
                    it.setToolTip("\n\n".join(b.tip for b in blocks if b.tip))
                elif (t, d) in unavailable:
                    it.setToolTip(tr("Not available"))
                if (t, d) in unavailable:
                    it.setBackground(UNAVAILABLE)
                self.setItem(t, d, it)

    def show_drag(self, block: Block, src, bad: dict):
        """A drag started: from now on every cell paints green (ok) or red (refused, with the reason)."""
        self.bad = bad
        self.dnd = DragState(block, src, bad)
        self.viewport().update()

    def end_drag(self):
        self.bad, self.dnd = {}, None
        self.viewport().update()

    def _set_hover(self, slot):
        if self.dnd and self.dnd.hover != slot:
            for s in (self.dnd.hover, slot):
                if s is not None and (i := self.model().index(*s)).isValid():
                    self.viewport().update(self.visualRect(i))
            self.dnd.hover = slot

    def block_at(self, pos: QPoint):
        """-> (row, col, Block|None) under a viewport position; the block is chosen by height in the cell."""
        i = self.indexAt(pos)
        if not i.isValid():
            return None
        blocks = self.item(i.row(), i.column()).data(BLOCKS)
        if not blocks:
            return i.row(), i.column(), None
        r = self.visualRect(i)
        k = min(int((pos.y() - r.top()) / (r.height() / len(blocks))), len(blocks) - 1)
        return i.row(), i.column(), blocks[max(k, 0)]

    # --- interaction ---------------------------------------------------------------------------
    def mousePressEvent(self, e):
        self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if (hit := self.block_at(e.position().toPoint())) and hit[2]:
            self.edit_course.emit(hit[2].course_id)
        else:
            super().mouseDoubleClickEvent(e)

    def startDrag(self, actions):
        if (hit := self.block_at(self._press)) and hit[2]:
            _start_drag(self, hit[2].course_id, (hit[0], hit[1]), hit[2].title, hit[2].color)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and (i := self.currentIndex()).isValid():
            if blocks := self.item(i.row(), i.column()).data(BLOCKS):
                self.remove.emit(blocks[0].course_id, (i.row(), i.column()))
                return
        super().keyPressEvent(e)

    def _menu(self, pos):
        hit = self.block_at(pos)
        if hit:
            self.setCurrentCell(hit[0], hit[1])
            self.menu.emit(hit[0], hit[1], hit[2].course_id if hit[2] else None, self.viewport().mapToGlobal(pos))

    def _cell(self, e):
        i = self.indexAt(e.position().toPoint())
        return (i.row(), i.column()) if i.isValid() else None

    def dragEnterEvent(self, e):
        slot = self._cell(e)
        self._set_hover(slot if _read(e) else None)
        if not _read(e) or slot is None:
            self.hint.emit("")
            return e.ignore()
        if slot in self.bad:
            self.hint.emit(" · ".join(self.bad[slot][:3]))
            return e.ignore()
        self.hint.emit("")
        e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dragLeaveEvent(self, e):
        self._set_hover(None)
        self.hint.emit("")
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        slot = self._cell(e)
        self._set_hover(None)
        if _read(e) and slot is not None and slot not in self.bad:
            self.dropped.emit(*_read(e), *slot)
            e.acceptProposedAction()
