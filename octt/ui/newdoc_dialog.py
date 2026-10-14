# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from octt import ops
from octt.i18n import WEEK, language, t as tr
from octt.model import Document



class NewDocumentDialog(QDialog):
    """Name the timetable and describe its week: which days, and how the periods are laid out."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("New timetable"))
        self.document: Document | None = None
        self.institution, self.year = QLineEdit(), QLineEdit()
        self.institution.setPlaceholderText(tr("e.g. Springfield High School"))
        self.year.setPlaceholderText(tr("e.g. 2026/27"))
        row = QWidget()
        self.row = QHBoxLayout(row)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.boxes = [QCheckBox(tr(d)) for d in WEEK]  # always in WEEK order; self.days is the displayed order
        arabic = language() == "ar"
        for i, cb in enumerate(self.boxes):
            cb.setChecked(i in ((6, 0, 1, 2, 3) if arabic else range(5)))
            cb.toggled.connect(self._preview)
        self.start = QComboBox()
        for d in (0, 5, 6):
            self.start.addItem(tr(WEEK[d]), d)
        self.start.setCurrentIndex(2 if arabic else 0)
        self.start.currentIndexChanged.connect(self._reorder)
        self.count = QSpinBox(minimum=1, maximum=24, value=6)
        self.first = QTimeEdit(QTime(8, 0))
        self.first.setDisplayFormat("HH:mm")
        self.first.setLayoutDirection(Qt.LeftToRight)  # Qt reverses the sections of a time in RTL ("00:08")
        self.minutes = QSpinBox(minimum=5, maximum=240, value=45, suffix=" " + tr("min"))
        self.gap = QSpinBox(minimum=0, maximum=120, value=5, suffix=" " + tr("min"))
        self.info = QLabel()
        self.info.setWordWrap(True)
        form = QFormLayout()
        form.addRow(tr("Institution"), self.institution)
        form.addRow(tr("School year"), self.year)
        form.addRow(tr("Week starts on"), self.start)
        form.addRow(tr("Days"), row)
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
        lay.addWidget(QLabel(tr("You can add teachers, rooms and courses afterwards. "
                                "Days and periods can't be changed later yet, so check them now.")))
        lay.addWidget(self.box)
        for w in (self.count, self.minutes, self.gap):
            w.valueChanged.connect(self._preview)
        self.first.timeChanged.connect(self._preview)
        self._reorder()

    def _reorder(self, *_):
        first = self.start.currentData()
        self.days = [self.boxes[(first + i) % 7] for i in range(7)]
        for cb in self.boxes:
            self.row.removeWidget(cb)
        for cb in self.days:
            self.row.addWidget(cb)
        self._preview()

    def _terms(self) -> list[str]:
        return ops.make_terms(self.first.time().toString("HH:mm"), self.count.value(), self.minutes.value(), self.gap.value())

    def _preview(self, *_):
        try:
            terms = self._terms()
            ok = any(cb.isChecked() for cb in self.days)
            self.info.setStyleSheet("")
            self.info.setText((tr("{first} … {last}  ({n} periods)", first=terms[0], last=terms[-1], n=len(terms)) if ok else tr("Pick at least one day.")))
            self.info.setStyleSheet("" if ok else "color: #b00020")
            self.box.button(QDialogButtonBox.Ok).setEnabled(ok)
        except ValueError as e:
            self.info.setStyleSheet("color: #b00020")
            self.info.setText(str(e))
            self.box.button(QDialogButtonBox.Ok).setEnabled(False)

    def accept(self):
        self.document = Document(institution=self.institution.text().strip(), year=self.year.text().strip(),
                                 days=[tr(d) for d, cb in zip((WEEK[(self.start.currentData() + i) % 7] for i in range(7)), self.days) if cb.isChecked()], terms=self._terms())
        super().accept()
