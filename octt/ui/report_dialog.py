# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFontComboBox, QPushButton, QSpinBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLabel,
                               QVBoxLayout)

from octt import reports
from octt.i18n import t as tr
from octt.model import Document
from octt.export import FORMATS, Style, write


class ReportDialog(QDialog):
    """Pick a report (and optionally one class / teacher / room), then save it as PDF, HTML or Excel."""

    def __init__(self, parent, doc: Document, ep_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Export report"))
        self.doc, self.ep_id, self.saved = doc, ep_id, None
        self.kind, self.entity = QComboBox(), QComboBox()
        for key in reports.REPORTS:  # shown translated, identified by the English key
            self.kind.addItem(tr(key), key)
        self.font_, self.size = QFontComboBox(), QSpinBox(minimum=0, maximum=40, specialValueText=tr("Default"), suffix=" " + tr("pt"))
        self.font_.setCurrentIndex(-1)  # nothing chosen = the bundled default font
        self.header, self.colors, self.borders = QPushButton(), QCheckBox(tr("Course colours")), QCheckBox(tr("Table lines"))
        self.colors.setChecked(True)
        self.borders.setChecked(True)
        self._header("#e8e8e8")
        self.header.clicked.connect(lambda: self._header(QColorDialog.getColor(QColor(self.header.text()), self).name()))
        self.msg = QLabel()
        self.msg.setStyleSheet("color: #b00020")
        form = QFormLayout()
        form.addRow(tr("Report"), self.kind)
        form.addRow(tr("Only"), self.entity)
        form.addRow(tr("Font"), self.font_)
        form.addRow(tr("Font size"), self.size)
        form.addRow(tr("Header colour"), self.header)
        form.addRow(self.colors)
        form.addRow(self.borders)
        box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        box.accepted.connect(self.export)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.msg)
        lay.addWidget(box)
        self.kind.currentIndexChanged.connect(lambda _: self._fill(self.kind.currentData()))
        self._fill(self.kind.currentData())

    def _fill(self, kind: str):
        what = reports.REPORTS[kind][1]
        rows = {"eps": [(e.id, e.name) for e in self.doc.eps.values()],
                "teachers": [(t.id, t.name) for t in self.doc.teachers.values()],
                "rooms": [(r.id, r.name) for r in self.doc.rooms.values()]}.get(what, [])
        self.entity.clear()
        self.entity.setEnabled(bool(what))
        self.entity.addItem(tr("All") if what else "—", None)
        for id_, name in rows:
            self.entity.addItem(name, id_)
        if what == "eps" and self.ep_id is not None:  # default to the class on screen
            self.entity.setCurrentIndex(max(self.entity.findData(self.ep_id), 0))

    def _header(self, c: str):
        if QColor(c).isValid() and c != "#000000":  # a cancelled colour dialog returns black
            self.header.setText(c)
            self.header.setStyleSheet(f"background: {c}")

    def style(self) -> Style:
        font = self.font_.currentFont().family() if self.font_.currentIndex() >= 0 else ""
        return Style(font, self.size.value(), self.header.text(), self.colors.isChecked(), self.borders.isChecked())

    def export(self, path: str | None = None):
        pages = reports.build(self.doc, self.kind.currentData(), self.entity.currentData())
        if not pages:
            self.msg.setText(tr("Nothing to print."))
            return
        path = path or QFileDialog.getSaveFileName(self, tr("Save report"), "timetable.pdf", FORMATS)[0]
        if path:
            write(pages, path, self.style())
            self.saved = path
            self.accept()
