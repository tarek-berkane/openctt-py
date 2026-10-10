# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
import copy
import threading
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QTabWidget, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHeaderView,
                               QLabel, QPlainTextEdit, QProgressBar, QWidget, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from octt import solver, views
from octt.i18n import N_, t as tr
from octt.model import Document
from octt.rules.soft import label, score, total
from octt.ui.grid import Block, Grid

STATUS = {"OPTIMAL": N_("Optimal"), "FEASIBLE": N_("Feasible")}


class Worker(QThread):
    progress = Signal(float)
    found = Signal(object)
    done = Signal(object)

    def __init__(self, doc: Document, keep: bool, count: int, seconds: float):
        super().__init__()
        self.doc, self.keep, self.count, self.seconds, self.stop = doc, keep, count, seconds, threading.Event()

    def run(self):
        self.done.emit(solver.solve_many(self.doc, self.keep, self.count, self.seconds, stop=self.stop,
                                         progress=self.progress.emit, found=self.found.emit))


def issues(res: solver.Result, n: int = 3) -> str:
    return ", ".join(f"{label(k)} {v:g}" for k, v in res.breakdown[:n]) or "–"


class SolveDialog(QDialog):
    """Options -> CP-SAT runs in a thread and offers several timetables -> `result` is the one the user applies."""

    def __init__(self, parent, doc: Document):
        super().__init__(parent)
        self.setWindowTitle(tr("Automatic timetable"))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint)
        self.setSizeGripEnabled(True)
        self.resize(1200, 760)
        self.doc, self.result, self.worker, self.results = copy.deepcopy(doc), None, None, []  # solve a copy
        self.t0, self.busy = 0.0, False
        locked = sum(p.locked for p in doc.placements)
        self.scratch = QCheckBox(tr("Start from scratch (discard unlocked lessons)"))
        self.count = QSpinBox(minimum=1, maximum=10, value=3)
        self.seconds = QDoubleSpinBox(minimum=1, maximum=3600, value=20, suffix=" " + tr("s"))
        self.status = QLabel(tr("Ready."))
        self.status.setWordWrap(True)
        self.bar = QProgressBar(maximum=100, value=0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", tr("Penalty"), tr("Differs from #1"), tr("Biggest issues")])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        for c in range(3):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        self.kind, self.entity = QComboBox(), QComboBox()
        for k, name in (("class", tr("Classes")), ("teacher", tr("Teachers")), ("room", tr("Rooms"))):
            self.kind.addItem(name, k)
        self.kind.currentIndexChanged.connect(self._fill_entities)
        self.entity.currentIndexChanged.connect(self._show)
        self.grid = Grid()
        self.grid.setDragEnabled(False)  # a preview: look, don't touch
        self.grid.viewport().setAcceptDrops(False)
        self.grid.setContextMenuPolicy(Qt.NoContextMenu)
        self.grid.setSelectionMode(QAbstractItemView.NoSelection)
        self.grid.set_dims(doc.days, doc.terms)
        self.legend = QLabel(tr("Grey lessons were already placed; coloured ones are new in this timetable."))
        self.legend.setWordWrap(True)
        self.pen_table = QTableWidget(0, 4)
        self.pen_table.setHorizontalHeaderLabels([tr("Constraint"), tr("Who"), tr("Penalty"), tr("Detail")])
        self.pen_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pen_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        pick = QHBoxLayout()
        pick.addWidget(self.kind)
        pick.addWidget(self.entity, 1)
        page = QVBoxLayout()
        page.addLayout(pick)
        page.addWidget(self.grid, 1)
        page.addWidget(self.legend)
        sched = QWidget()
        sched.setLayout(page)
        self.tabs = QTabWidget()
        self.tabs.addTab(sched, tr("Timetable"))
        self.tabs.addTab(self.pen_table, tr("Issues"))
        self.log = QPlainTextEdit(readOnly=True)
        self.log.hide()
        self.box = QDialogButtonBox()
        self.go = self.box.addButton(tr("Solve"), QDialogButtonBox.ActionRole)
        self.apply = self.box.addButton(tr("Apply"), QDialogButtonBox.AcceptRole)
        self.apply.setEnabled(False)
        self.stop = self.box.addButton(tr("Stop"), QDialogButtonBox.ActionRole)
        self.stop.setEnabled(False)
        self.box.addButton(QDialogButtonBox.Close)
        self.go.clicked.connect(self.start)
        self.stop.clicked.connect(lambda: self.worker.stop.set())
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        self.timer = QTimer(self, interval=250)
        self.timer.timeout.connect(self._tick)
        form = QFormLayout()
        form.addRow(self.scratch)
        form.addRow(tr("Timetables to find"), self.count)
        form.addRow(tr("Time per timetable"), self.seconds)
        side = QVBoxLayout()
        side.addLayout(form)
        if locked:
            note = QLabel(tr("{n} locked lesson(s) stay where they are.", n=locked))
            note.setWordWrap(True)
            side.addWidget(note)
        side.addWidget(self.status)
        side.addWidget(self.bar)
        side.addWidget(self.log)
        side.addStretch(1)
        side.addWidget(self.box)
        panel = QWidget()
        panel.setLayout(side)
        panel.setFixedWidth(300)
        main = QVBoxLayout()
        main.addWidget(self.table, 1)
        main.addWidget(self.tabs, 4)
        lay = QHBoxLayout(self)
        lay.addWidget(panel)
        lay.addLayout(main, 1)
        self.log.setMaximumHeight(200)
        self._fill_entities()

    def start(self):
        self.result, self.results = None, []
        self.table.setRowCount(0)
        self.log.hide()
        self.go.setEnabled(False)
        self.apply.setEnabled(False)
        self.stop.setEnabled(True)
        self.status.setText(tr("Building the model…"))
        self.t0, self.busy = time.time(), True
        self.bar.setValue(0)
        self.timer.start()
        self.worker = Worker(self.doc, not self.scratch.isChecked(), self.count.value(), self.seconds.value())
        self.worker.progress.connect(self._progress)  # a bound method, so Qt delivers it on the GUI thread (a lambda would not)
        self.worker.found.connect(self._found)
        self.worker.done.connect(self._done)
        self.worker.start()

    def _progress(self, v: float):
        self.status.setText(tr("Solving timetable {i} of {n}… best penalty so far: {v}",
                               i=len(self.results) + 1, n=self.count.value(), v=f"{v:g}"))

    def _tick(self):
        total = self.seconds.value() * self.count.value()
        self.bar.setValue(min(99, int(100 * (time.time() - self.t0) / total)))

    def _found(self, res: solver.Result):
        self.results.append(res)
        r = self.table.rowCount()
        self.table.insertRow(r)
        slots = lambda x: {(p.course_id, p.term, p.day) for p in x.placements}
        diff = len(slots(res) - slots(self.results[0]))  # lessons that sit in another slot than in timetable 1
        for c, v in enumerate((str(r + 1), f"{res.penalty:g}", "–" if not r else str(diff), issues(res))):
            self.table.setItem(r, c, QTableWidgetItem(v))
        best = min(range(len(self.results)), key=lambda i: self.results[i].penalty)
        self.table.selectRow(best)  # the lowest penalty so far is preselected; the user can pick another

    def _fill_entities(self, *_):
        rows = {"class": self.doc.eps, "teacher": self.doc.teachers, "room": self.doc.rooms}[self.kind.currentData()]
        self.entity.blockSignals(True)
        self.entity.clear()
        for id_ in sorted(rows, key=lambda i: views.title(self.doc, (self.kind.currentData(), i))):
            self.entity.addItem(views.title(self.doc, (self.kind.currentData(), id_)), id_)
        self.entity.blockSignals(False)
        self._show()

    def preview_doc(self, res: solver.Result) -> Document:
        d = copy.deepcopy(self.doc)
        d.placements = [p for p in d.placements if p not in res.removes] + res.placements
        return d

    def _show(self, *_):
        """Draw the selected timetable for the chosen class/teacher/room, and list its remaining issues."""
        self.grid.fill({}, set())
        self.pen_table.setRowCount(0)
        if self.result is None or self.entity.currentIndex() < 0:
            return
        d, new = self.preview_doc(self.result), self.result.placements
        v = (self.kind.currentData(), self.entity.currentData())
        cells = {}
        for p in views.lessons(d, v):
            title, detail = views.cell(d, v, p)
            fresh = p in new
            cells.setdefault((p.term, p.day), []).append(
                Block(p.course_id, title, detail, views.color(p.course_id) if fresh else "#e3e3e3", views.tooltip(d, p), p.locked))
        self.grid.fill(cells, views.blocked(d, v))
        pens = sorted(score(d), key=lambda q: -q.amount)
        self.pen_table.setRowCount(len(pens))
        self.tabs.setTabText(1, tr("Issues ({n})", n=len(pens)))
        for r, q in enumerate(pens):
            for c, val in enumerate((label(q.key), q.subject, f"{q.amount:g}", q.why)):
                self.pen_table.setItem(r, c, QTableWidgetItem(val))

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        self.result = self.results[rows[0].row()] if rows else None
        self._show()
        self.apply.setEnabled(not self.busy and self.result is not None and bool(self.result.placements or self.result.removes))

    def _done(self, results: list):
        self.timer.stop()
        self.busy = False
        self.stop.setEnabled(False)
        self.go.setEnabled(True)
        self.bar.setValue(100 if results and results[0].ok else 0)
        first = results[0]
        if not first.ok:
            self.status.setText(first.message.split("\n")[0] or first.status)
            self.log.setPlainText(first.message)
            self.log.setVisible("\n" in first.message)
            return
        if not self.results:  # nothing came through the live signal (e.g. 'nothing to place')
            for r in results:
                self._found(r)
        self._selected()
        self.status.setText(tr("{n} timetable(s) found. Pick one and apply it (one undo step); lower penalty is better.",
                               n=len(self.results)))

    def accept(self):
        if self.worker:
            self.worker.wait()
        super().accept()

    def reject(self):  # closing mid-solve: stop and wait so the thread isn't orphaned
        if self.worker and self.worker.isRunning():
            self.worker.stop.set()
            self.worker.wait()
        super().reject()
