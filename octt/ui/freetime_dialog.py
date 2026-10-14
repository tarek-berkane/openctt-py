# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Find free time for an extra session: describe it with the course form, see every slot where it fits now
(best first), pick one or more and add it as a course with those lessons placed and locked."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from octt import freetime
from octt.i18n import N_, t as tr
from octt.ui.dialogs import KINDS, CourseEditor


class FreeTimeDialog(QDialog):
    def __init__(self, win, ep_id: int | None = None, teacher_id: int | None = None):
        super().__init__(win)
        self.win, self.found, self.booked = win, [], None
        self.setWindowTitle(tr("Find free time"))
        e = self.editor = CourseEditor(win.doc, None, ep_id=ep_id)
        e.name.setText(tr("Extra session"))
        e.teacher.setCurrentIndex(max(e.teacher.findData(teacher_id), 0))
        for w in (e.lessons, e.ht, e.blocks):  # one lesson per picked slot; a one-off is held with nothing
            e.form.setRowVisible(w, False)
        self.timer = QTimer(self, singleShot=True, interval=250, timeout=self.search)  # search once typing stops
        e.changed(lambda *_: self.timer.start())

        t = self.table = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels([tr(h) for h in (N_("Day"), N_("Period"), N_("Free rooms"), N_("Penalty change"))])
        t.horizontalHeaderItem(2).setToolTip(tr("The first one, the smallest that fits, is booked."))
        t.horizontalHeaderItem(3).setToolTip(tr("How much the timetable's soft penalty changes with one lesson here. Lower is better."))
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        t.itemSelectionChanged.connect(self._update)
        self.summary = QLabel(wordWrap=True)
        self.together = QLabel(wordWrap=True)  # the selection's real effect: lessons together are not the sum of each
        self.err = QLabel(wordWrap=True)
        self.err.setStyleSheet("color: #b00020")
        self.box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.add_btn = self.box.addButton("", QDialogButtonBox.AcceptRole)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)

        right = QVBoxLayout()
        right.addWidget(self.summary)
        right.addWidget(t, 1)
        right.addWidget(self.together)
        left = QVBoxLayout()
        left.addWidget(e)
        left.addStretch(1)  # the form keeps its natural height
        cols = QHBoxLayout()
        cols.addLayout(left)
        cols.addLayout(right, 1)
        lay = QVBoxLayout(self)
        lay.addLayout(cols, 1)
        lay.addWidget(self.err)
        lay.addWidget(self.box)
        self.resize(1000, 520)
        self.search()

    def search(self):
        self.timer.stop()  # this search is the fresh one
        c, doc = self.editor.result(), self.win.doc
        self.found = freetime.find(doc, c) if c.ep_id is not None and c.teacher_id is not None else []
        t = self.table
        t.setRowCount(len(self.found))
        for r, f in enumerate(self.found):
            names = [doc.rooms[i].name for i in f.rooms]
            rooms = ", ".join(names[:4]) + (" …" if len(names) > 4 else "")
            for col, text in enumerate((doc.days[f.day], doc.terms[f.term], rooms, f"\u200e{f.penalty:+g}")):  # LRM: '+2' must not turn into '2+' in Arabic
                t.setItem(r, col, QTableWidgetItem(text))
        self.summary.setText(
            tr("{n} free slot(s), best first. Select one or more (Ctrl+click), then add.", n=len(self.found))
            if self.found else
            tr("No slot has the class, the teacher and a fitting room free at once. Try another teacher, "
               "fewer students, a sub-group or other rooms."))
        self.err.clear()
        self._update()

    def picked(self) -> list:
        return [self.found[r] for r in sorted({i.row() for i in self.table.selectedIndexes()})]

    def _update(self):
        picks = self.picked()
        n = len(picks)
        if n > 1:
            change = freetime.effect(self.win.doc, self.editor.result(), freetime.rooms(picks))
            self.together.setText(tr("Together: {n} lesson(s), penalty change {p}", n=n, p=f"\u200e{change:+g}"))
        else:
            self.together.clear()
        self.add_btn.setText(tr("Add with {n} lesson(s)", n=n))
        self.add_btn.setEnabled(n > 0)

    def accept(self):
        if self.timer.isActive():  # the form changed after the last search: the picks may no longer fit
            return self.search()
        c, slots = self.editor.result(), freetime.rooms(self.picked())
        made = []
        problems = self.win.try_apply(tr(KINDS["course"].add), lambda d: made.append(freetime.book(d, c, slots)))
        if problems:
            return self.err.setText("\n".join(problems[:4]))
        self.booked = made[-1]
        super().accept()
