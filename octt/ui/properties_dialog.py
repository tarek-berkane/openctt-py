# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QSpinBox, QTimeEdit, QVBoxLayout)

from octt import ops
from octt.i18n import t as tr
from octt.model import Document


def _min(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


class PropertiesDialog(QDialog):
    """Institution, year, day names/order and period layout of an existing timetable."""

    def __init__(self, doc: Document, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Timetable properties"))
        self.doc, self.touched = doc, False
        self.institution, self.year = QLineEdit(doc.institution), QLineEdit(doc.year)
        self.list = QListWidget()
        for i, d in enumerate(doc.days):
            self._add(d, i)
        self.list.currentRowChanged.connect(self._check)
        btns = QHBoxLayout()
        for text, fn in ((tr("Up"), lambda: self._move(-1)), (tr("Down"), lambda: self._move(1)),
                         (tr("Add day"), lambda: self._add(tr("New day"), None, edit=True)),
                         (tr("Remove day"), self._remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        a, b = doc.terms[0].split("-"), (doc.terms[1].split("-") if len(doc.terms) > 1 else None)
        self.count = QSpinBox(minimum=1, maximum=24, value=len(doc.terms))
        self.first = QTimeEdit(QTime(*divmod(_min(a[0]), 60)))
        self.first.setDisplayFormat("HH:mm")
        self.first.setLayoutDirection(Qt.LeftToRight)
        self.minutes = QSpinBox(minimum=5, maximum=240, value=_min(a[1]) - _min(a[0]), suffix=" " + tr("min"))
        self.gap = QSpinBox(minimum=0, maximum=120, value=max(0, _min(b[0]) - _min(a[1])) if b else 5, suffix=" " + tr("min"))
        for w in (self.count, self.minutes, self.gap):
            w.valueChanged.connect(self._periods_edited)
        self.first.timeChanged.connect(self._periods_edited)
        self.info = QLabel()
        self.info.setWordWrap(True)
        form = QFormLayout()
        form.addRow(tr("Institution"), self.institution)
        form.addRow(tr("School year"), self.year)
        form.addRow(tr("Days"), self.list)
        form.addRow("", btns)
        form.addRow(tr("Periods per day"), self.count)
        form.addRow(tr("First period starts"), self.first)
        form.addRow(tr("Lesson length"), self.minutes)
        form.addRow(tr("Break between"), self.gap)
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.info)
        lay.addWidget(QLabel(tr("Removing a day or period drops its blocked slots and unplaces its lessons. "
                                "Periods are matched by position.")))
        lay.addWidget(self.box)
        self._check()

    def _add(self, name, old, edit=False):
        it = QListWidgetItem(name)
        it.setData(Qt.UserRole, old)
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        self.list.addItem(it)
        if edit:
            self.list.setCurrentItem(it)
            self.list.editItem(it)
        self._check()

    def _move(self, d):
        r = self.list.currentRow()
        if 0 <= r + d < self.list.count():
            it = self.list.takeItem(r)
            self.list.insertItem(r + d, it)
            self.list.setCurrentRow(r + d)

    def _remove(self):
        if self.list.count() > 1:
            self.list.takeItem(self.list.currentRow())
            self._check()

    def _periods_edited(self, *_):
        self.touched = True
        self._check()

    def days(self) -> list[tuple[int | None, str]]:
        its = [self.list.item(i) for i in range(self.list.count())]
        return [(it.data(Qt.UserRole), it.text().strip()) for it in its]

    def terms(self) -> list[str] | None:
        if not self.touched:
            return None
        return ops.make_terms(self.first.time().toString("HH:mm"), self.count.value(), self.minutes.value(), self.gap.value())

    def _check(self, *_):
        if not hasattr(self, "box"):  # still building
            return
        try:
            self.terms()
            names = [n for _, n in self.days()]
            ok = all(names) and len(set(names)) == len(names)
            self.info.setText("" if ok else tr("Day names must be filled in and different."))
        except ValueError as e:
            ok = False
            self.info.setText(str(e))
        self.info.setStyleSheet("" if ok else "color: #b00020")
        self.box.button(QDialogButtonBox.Ok).setEnabled(ok)
