# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Data manager: one tab per kind (groups, classes, teachers, rooms, courses). Each tab is a searchable, sortable
table with the numbers that matter (lessons, load, use) and, beside it, the same form the edit dialogs use.
Every change goes through MainWindow.try_apply, so it is validated and undoable like any other edit."""
import copy
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from octt import ops, paste
from octt.i18n import N_, t as tr
from octt.model import Document
from octt.ui.dialogs import KINDS

ID, SORT = Qt.UserRole, Qt.UserRole + 1
WARN, MUTED = QColor("#b00020"), QColor("#808080")


class Item(QTableWidgetItem):
    """A cell that sorts by its value (numbers as numbers, text ignoring case), not by its display text."""

    def __init__(self, value, text: str | None = None, warn: str = ""):
        super().__init__(str(value) if text is None else text)
        self.setData(SORT, value.casefold() if isinstance(value, str) else value)
        if not isinstance(value, str):
            self.setTextAlignment(Qt.AlignTrailing | Qt.AlignVCenter)  # numbers line up on their last digit
        if warn:
            self.setForeground(QBrush(WARN))
            self.setToolTip(warn)

    def __lt__(self, other):
        return self.data(SORT) < other.data(SORT)


def _free(doc: Document, blocked: set) -> int:
    return len(doc.terms) * len(doc.days) - len(blocked)


def _pct(n: int, of: int) -> Item:
    p = round(100 * n / of) if of else 0
    return Item(p, f"{p}%")


def _rooms(doc: Document, allowed: set | None) -> Item:
    if allowed is None:
        return Item(tr("any"))
    names = sorted(doc.rooms[r].name for r in allowed if r in doc.rooms)
    return Item(", ".join(names[:3]) + (" …" if len(names) > 3 else ""))


def group_rows(doc: Document):
    for g in doc.epgs.values():
        eps = {e.id for e in doc.eps.values() if e.epg_id == g.id}
        yield g.id, [Item(g.name), Item(len(eps)), Item(sum(c.ep_id in eps for c in doc.courses.values())),
                     Item(_free(doc, g.blocked))]


def class_rows(doc: Document):
    placed = Counter(doc.courses[p.course_id].ep_id for p in doc.placements)
    for e in doc.eps.values():
        cs = [c for c in doc.courses.values() if c.ep_id == e.id]
        yield e.id, [Item(e.name), Item(doc.epgs[e.epg_id].name), Item(len(cs)), Item(sum(c.lessons for c in cs)),
                     Item(placed[e.id]), Item(_free(doc, e.blocked | doc.epgs[e.epg_id].blocked))]


def teacher_rows(doc: Document):
    placed = Counter(doc.courses[p.course_id].teacher_id for p in doc.placements)
    for t in doc.teachers.values():
        cs = [c for c in doc.courses.values() if c.teacher_id == t.id]
        need, free = sum(c.lessons for c in cs), _free(doc, t.blocked)
        load = _pct(need, free)
        if need > free:
            load = Item(load.data(SORT), load.text(), tr("More lessons than free periods"))
        yield t.id, [Item(t.name), Item(len(cs)), Item(need), Item(placed[t.id]), Item(free), load,
                     _rooms(doc, t.allowed_rooms)]


def room_rows(doc: Document):
    used = Counter((p.room_id, p.term, p.day) for p in doc.placements)
    in_use = Counter(r for r, _, _ in used)
    for r in doc.rooms.values():
        free = _free(doc, r.blocked)
        yield r.id, [Item(r.name), Item(r.capacity), Item(in_use[r.id]), Item(free), _pct(in_use[r.id], free)]


def course_rows(doc: Document):
    placed = Counter(p.course_id for p in doc.placements)
    for c in doc.courses.values():
        held = ", ".join(doc.courses[h].name for h in c.hold_together if h in doc.courses)
        yield c.id, [Item(c.name), Item(c.group or "—"), Item(doc.eps[c.ep_id].name),
                     Item(doc.teachers[c.teacher_id].name), Item(c.lessons), Item(placed[c.id]), Item(c.students),
                     _rooms(doc, c.allowed_rooms), Item(held or "—")]


# kind -> (tab title, column titles, rows(doc), timetable view kind or None)
PAGES = {
    "epg": (N_("Groups"), [N_("Name"), N_("Classes"), N_("Courses"), N_("Free periods")], group_rows, None),
    "ep": (N_("Classes"), [N_("Name"), N_("Group"), N_("Courses"), N_("Lessons/week"), N_("Placed"), N_("Free periods")],
           class_rows, "class"),
    "teacher": (N_("Teachers"), [N_("Name"), N_("Courses"), N_("Lessons/week"), N_("Placed"), N_("Free periods"),
                                 N_("Load"), N_("Rooms")], teacher_rows, "teacher"),
    "room": (N_("Rooms"), [N_("Name"), N_("Seats"), N_("Periods in use"), N_("Free periods"), N_("Use")], room_rows, "room"),
    "course": (N_("Courses"), [N_("Name"), N_("Sub-group"), N_("Class"), N_("Teacher"), N_("Lessons/week"), N_("Placed"),
                               N_("Students"), N_("Rooms"), N_("Held with")], course_rows, None),
}


class Page(QWidget):
    """Table of one kind on the left, the form of the selected (or new) entity on the right."""

    def __init__(self, win, kind: str):
        super().__init__()
        self.win, self.kind = win, kind
        self.current: int | None = None  # id in the form; None with a form = a new one not saved yet
        self.editor, self.baseline = None, None
        title, headers, self.rows, self.view = PAGES[kind]

        self.search = QLineEdit(placeholderText=tr("Search…"), clearButtonEnabled=True)
        self.search.textChanged.connect(self._filter)
        self.add_btn = QPushButton(tr("Add"))
        self.dup_btn = QPushButton(tr("Duplicate"))
        self.paste_btn = QPushButton(tr("Paste list…"))
        self.paste_btn.setToolTip(tr("Add many at once from rows copied out of a spreadsheet (Ctrl+V on the table)"))
        self.del_btn = QPushButton(tr("Delete"))
        self.show_btn = QPushButton(tr("Show timetable"))
        self.add_btn.clicked.connect(self.add)
        self.dup_btn.clicked.connect(self.duplicate)
        self.del_btn.clicked.connect(self.delete)
        self.show_btn.clicked.connect(self.show_timetable)
        self.paste_btn.clicked.connect(lambda: self.paste_list())
        self.show_btn.setVisible(self.view is not None)
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        for b in (self.add_btn, self.dup_btn, self.paste_btn, self.del_btn, self.show_btn):
            bar.addWidget(b)

        t = self.table = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels([tr(h) for h in headers])
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Ctrl/Shift+click: delete several at once
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)  # names are never cut; wide tables scroll
        t.horizontalHeader().setStretchLastSection(True)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.AscendingOrder)
        t.currentCellChanged.connect(lambda row, *_: self._picked(row))
        t.itemSelectionChanged.connect(self._update)

        self.heading = QLabel()
        f = self.heading.font()
        f.setPointSizeF(f.pointSizeF() * 1.3)
        f.setBold(True)
        self.heading.setFont(f)
        self.scroll = QScrollArea(widgetResizable=True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.err = QLabel(wordWrap=True)
        self.err.setStyleSheet("color: #b00020")
        self.save_btn = QPushButton(tr("Save"))
        self.revert_btn = QPushButton(tr("Revert"))
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.save)
        self.revert_btn.clicked.connect(lambda: self._open(self.current))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.revert_btn)
        buttons.addWidget(self.save_btn)
        form = QWidget()
        fl = QVBoxLayout(form)
        fl.addWidget(self.heading)
        fl.addWidget(self.scroll, 1)
        fl.addWidget(self.err)
        fl.addLayout(buttons)

        split = QSplitter()
        split.addWidget(t)
        split.addWidget(form)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(split, 1)

        for keys, fn, owner in ((QKeySequence.Find, self.search.setFocus, self), (QKeySequence.New, self.add, self),
                                (QKeySequence.Save, self.save, self), (QKeySequence.Delete, self.delete, t),
                                (QKeySequence.Paste, lambda: self.paste_list(QApplication.clipboard().text()), t)):
            sc = QShortcut(keys, owner, activated=fn)
            sc.setContext(Qt.WidgetWithChildrenShortcut)  # Delete sits on the table: in a text field it must edit text
        self.reload(force=True)

    # --- state ----------------------------------------------------------------------------------
    @property
    def doc(self) -> Document:
        return self.win.doc

    def dirty(self) -> bool:
        return self.editor is not None and self.editor.result() != self.baseline

    def _entities(self) -> dict:
        return getattr(self.doc, KINDS[self.kind].table)

    def reload(self, force: bool = False):
        """Refill the table from the document. The form is rebuilt too, unless it holds unsaved changes."""
        t = self.table
        t.setSortingEnabled(False)  # or rows reorder while they are being filled
        t.setRowCount(0)
        for id_, cells in self.rows(self.doc):
            r = t.rowCount()
            t.insertRow(r)
            for c, item in enumerate(cells):
                item.setData(ID, id_)
                t.setItem(r, c, item)
        t.setSortingEnabled(True)
        self._filter()
        if self.current is not None and self.current not in self._entities():
            self.current, self.editor = None, None  # deleted, by us or by an undo
        if force or not self.dirty():
            if self.current is not None:
                self._open(self.current)
            elif force or self.editor is None:
                self._open_none()  # (a new, still untouched form is left alone)
        self._select_row()

    def _select_row(self):
        t = self.table
        t.blockSignals(True)
        t.clearSelection()
        t.setCurrentItem(None)
        for r in range(t.rowCount()):
            if t.item(r, 0).data(ID) == self.current:
                t.selectRow(r)
                t.scrollToItem(t.item(r, 0))
        t.blockSignals(False)

    def _picked(self, row: int):
        id_ = self.table.item(row, 0).data(ID) if row >= 0 and self.table.item(row, 0) else None
        if id_ is None or (id_ == self.current and self.editor is not None):
            return
        if self.leave():
            self.current = id_
            self._open(id_)  # (the table keeps its selection: Ctrl+click adds rows to it)
        else:
            self._select_row()  # puts the selection back: the user stayed

    def leave(self) -> bool:
        """True when the form may be replaced: nothing unsaved, saved now, or discarded."""
        if not self.dirty():
            return True
        r = QMessageBox.question(self, tr("Unsaved changes"), tr("Save the changes to this form first?"),
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        return self.save() if r == QMessageBox.Save else r == QMessageBox.Discard

    # --- the form ---------------------------------------------------------------------------------
    def _open(self, id_: int | None, **defaults):
        """Show the form of `id_`, or an empty one for a new entity (id_=None)."""
        k = KINDS[self.kind]
        entity = self._entities().get(id_) if id_ is not None else None
        self.editor = k.editor(self.doc, entity, **defaults)
        self.baseline = self.editor.result()
        self.editor.changed(self._update)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.addWidget(self.editor)
        bl.addStretch(1)
        self.scroll.setWidget(box)
        self.scroll.setMinimumWidth(box.sizeHint().width() + self.scroll.verticalScrollBar().sizeHint().width())  # whole form, whole week
        self.heading.setText(entity.name if entity else tr(k.add))
        self.err.clear()
        self._update()

    def _open_none(self):
        self.editor, self.baseline = None, None
        empty = QLabel(tr("Select a row to edit it, or click Add.") if self.table.rowCount() else
                       tr("Nothing here yet. Click Add to create the first one."), alignment=Qt.AlignCenter, wordWrap=True)
        empty.setEnabled(False)
        self.scroll.setWidget(empty)
        self.heading.clear()
        self.err.clear()
        self._update()

    def _update(self, *_):
        dirty = self.dirty()
        self.save_btn.setEnabled(dirty)
        self.revert_btn.setEnabled(dirty)
        has, n = self.current is not None, len(self.selected())
        self.dup_btn.setEnabled(has)
        self.del_btn.setEnabled(n > 0 or self.editor is not None)
        self.del_btn.setText(tr("Delete") if n < 2 else f"{tr('Delete')} ({n})")
        self.show_btn.setEnabled(has)

    def selected(self) -> list[int]:
        """Ids of the selected rows still shown by the search; else the one in the form."""
        t = self.table
        rows = sorted({i.row() for i in t.selectedIndexes()})
        ids = [t.item(r, 0).data(ID) for r in rows if not t.isRowHidden(r)]
        return ids or ([self.current] if self.current is not None else [])

    def _filter(self, *_):
        q = self.search.text().strip().casefold()
        t = self.table
        for r in range(t.rowCount()):
            t.setRowHidden(r, bool(q) and not any(q in t.item(r, c).text().casefold() for c in range(t.columnCount())))

    # --- actions ----------------------------------------------------------------------------------
    def save(self) -> bool:
        if not self.dirty():
            return True
        k, entity = KINDS[self.kind], self.editor.result()
        problems = self.win.try_apply(tr(k.add if self.current is None else k.edit), lambda d: k.editor.save(d, entity))
        if problems:
            self.err.setText("\n".join(problems[:4]))
            return False
        self.current = entity.id
        self.reload(force=True)
        return True

    def add(self):
        if not self.leave():
            return
        if self.kind == "ep" and not self.doc.epgs:
            return self.err.setText(tr("Add a group first"))
        if self.kind == "course" and (not self.doc.eps or not self.doc.teachers):
            return self.err.setText(tr("A course needs a class and a teacher first"))
        self.current = None
        self._open(None)
        self._select_row()
        self.editor.name.setFocus()

    def duplicate(self):
        if self.current is None or not self.leave():
            return
        made = []
        name = self._entities()[self.current].name
        problems = self.win.try_apply(tr("Duplicate {name}", name=name),
                                      lambda d: made.append(ops.duplicate(d, self.kind, self.current)))
        if problems:
            return self.err.setText("\n".join(problems[:4]))
        self.current = made[-1]
        self.reload(force=True)
        self.editor.name.setFocus()  # a copy almost always wants a new name next
        self.editor.name.selectAll()

    def delete(self):
        ids = self.selected()
        if not ids:  # a new one that was never saved: just drop the form
            return self._open_none() if self.editor is not None else None
        rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        at = next((i for i, r in enumerate(rows) if self.table.item(r, 0).data(ID) in ids), 0)
        problems = self.win.delete(self.kind, *ids)
        if problems:
            return self.err.setText("\n".join(problems[:4]))
        if ids[0] in self._entities():
            return  # the user said no
        rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
        self.current = self.table.item(rows[min(at, len(rows) - 1)], 0).data(ID) if rows else None
        self.reload(force=True)  # the neighbour takes the deleted row's place

    def paste_list(self, text: str = ""):
        PasteDialog(self, text).exec()

    def show_timetable(self):
        if self.current is not None:
            self.win.show_view((self.view, self.current))


class PasteDialog(QDialog):
    """Rows copied from a spreadsheet; a live preview says what each row will do before anything is added."""

    def __init__(self, page: Page, text: str = ""):
        super().__init__(page)
        self.page = page
        cols = [tr(c) for c in paste.COLUMNS[page.kind]]
        self.setWindowTitle(f"{tr('Paste list')} — {tr(PAGES[page.kind][0])}")
        hint = QLabel(tr("Copy rows from a spreadsheet and paste them below, one per line, with these columns:")
                      + f"<br><b>{' | '.join(cols)}</b><br>" + tr("Rows that already exist are skipped."), wordWrap=True)
        self.text = QPlainTextEdit(placeholderText="\t".join(cols))
        self.text.textChanged.connect(self._preview)
        self.preview = QTableWidget(0, len(cols) + 1)
        self.preview.setHorizontalHeaderLabels([*cols, tr("Result")])
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.err = QLabel(wordWrap=True)
        self.err.setStyleSheet("color: #b00020")
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.preview, 2)
        lay.addWidget(self.err)
        lay.addWidget(self.box)
        self.resize(800, 600)
        self.text.setPlainText(text)
        self._preview()

    def _preview(self):
        rows = paste.paste(copy.deepcopy(self.page.doc), self.page.kind, self.text.toPlainText())
        t = self.preview
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate([*row.cells, row.note]):
                item = QTableWidgetItem(value)
                if not row.added:
                    item.setForeground(QBrush(WARN if row.error else MUTED))
                t.setItem(r, c, item)
        n = sum(row.added for row in rows)
        ok = self.box.button(QDialogButtonBox.Ok)
        ok.setText(tr("Add {n}", n=n))
        ok.setEnabled(n > 0)
        self.err.clear()

    def accept(self):
        kind, text = self.page.kind, self.text.toPlainText()
        problems = self.page.win.try_apply(tr("Paste list"), lambda d: paste.paste(d, kind, text))
        if problems:  # audit caught something the row checks did not: nothing was added
            return self.err.setText("\n".join(problems[:4]))
        super().accept()


class ManageDialog(QDialog):
    """Non-modal: the timetable stays usable. MainWindow.placements_changed reloads it after every edit, undo or redo."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(tr("Manage data"))
        self.resize(1150, 700)
        self.tabs = QTabWidget()
        self.pages = {k: Page(win, k) for k in PAGES}
        for k, p in self.pages.items():
            self.tabs.addTab(p, "")
        QVBoxLayout(self).addWidget(self.tabs)
        self._titles()

    def reload(self, force: bool = False):
        for p in self.pages.values():
            p.reload(force)
        self._titles()

    def _titles(self):
        for i, (k, p) in enumerate(self.pages.items()):
            self.tabs.setTabText(i, f"{tr(PAGES[k][0])} ({p.table.rowCount()})")

    def show_kind(self, kind: str, id_: int | None = None):
        self.tabs.setCurrentWidget(p := self.pages[kind])
        if id_ is not None and id_ != p.current and p.leave():
            p.current = id_
            p.reload(force=True)

    def reject(self):  # Escape or the close button
        if all(p.leave() for p in self.pages.values()):
            super().reject()
