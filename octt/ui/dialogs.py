# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from octt import ops
from octt.i18n import N_, t as tr
from octt.model import Course, Document, Ep, Room, Teacher
from octt.rules.soft import BLOCKS, BLOCKS_DEFAULT, PARAMS, STUDENT_KEYS, TEACHER_KEYS

CHECKABLE = Qt.ItemIsUserCheckable | Qt.ItemIsEnabled


class Slots(QTableWidget):
    """Allowed-time-slots grid: checked = allowed. Click a header to flip a whole day / period."""

    def __init__(self, doc: Document, blocked: set):
        super().__init__(len(doc.terms), len(doc.days))
        self.setHorizontalHeaderLabels(doc.days)
        self.setVerticalHeaderLabels(doc.terms)
        self.setMinimumHeight(40 + 30 * len(doc.terms))
        for t in range(self.rowCount()):
            for d in range(self.columnCount()):
                it = QTableWidgetItem()
                it.setFlags(CHECKABLE)
                it.setCheckState(Qt.Unchecked if (t, d) in blocked else Qt.Checked)
                self.setItem(t, d, it)
        self.horizontalHeader().sectionClicked.connect(lambda d: self._flip([(t, d) for t in range(self.rowCount())]))
        self.verticalHeader().sectionClicked.connect(lambda t: self._flip([(t, d) for d in range(self.columnCount())]))

    def _flip(self, cells):
        on = all(self.item(t, d).checkState() == Qt.Checked for t, d in cells)
        for t, d in cells:
            self.item(t, d).setCheckState(Qt.Unchecked if on else Qt.Checked)

    def blocked(self) -> set:
        return {(t, d) for t in range(self.rowCount()) for d in range(self.columnCount())
                if self.item(t, d).checkState() != Qt.Checked}


class Checklist(QListWidget):
    def __init__(self, rows: list[tuple[int, str]], checked: set):
        super().__init__()
        for id_, text in rows:
            it = QListWidgetItem(text, self)
            it.setFlags(CHECKABLE)
            it.setData(Qt.UserRole, id_)
            it.setCheckState(Qt.Checked if id_ in checked else Qt.Unchecked)

    def value(self) -> set:
        return {self.item(i).data(Qt.UserRole) for i in range(self.count())
                if self.item(i).checkState() == Qt.Checked}


class RoomPicker(QWidget):
    """'Any room' (None) or an explicit set of rooms."""

    def __init__(self, doc: Document, allowed: set | None):
        super().__init__()
        self.only = QCheckBox(tr("Only these rooms"))
        self.only.setChecked(allowed is not None)
        self.list = Checklist([(r.id, r.name) for r in doc.rooms.values()], allowed or set())
        self.list.setMaximumHeight(90)
        self.list.setEnabled(allowed is not None)
        self.only.toggled.connect(self.list.setEnabled)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.only)
        lay.addWidget(self.list)

    def value(self) -> set | None:
        return self.list.value() if self.only.isChecked() else None


class Limits(QWidget):
    """Optional per-entity overrides of the document's soft-constraint limits (unchecked = inherit)."""

    def __init__(self, doc: Document, keys: tuple, current: dict):
        super().__init__()
        base = {**PARAMS, **doc.params}
        self.rows = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        for k in keys:
            label, unit = SETTINGS_ROWS[k]
            start = k == "student_start"
            cb = QCheckBox(tr(label))
            sp = QSpinBox(minimum=1 if start else 0, maximum=len(doc.terms) if start else 99, suffix=f" {tr(unit)}")
            sp.setValue(min(current.get(k, base[k]), sp.maximum()))
            sp.setEnabled(k in current)
            cb.setChecked(k in current)
            cb.toggled.connect(sp.setEnabled)
            form.addRow(cb, sp)
            self.rows[k] = cb, sp

    def value(self) -> dict:
        return {k: sp.value() for k, (cb, sp) in self.rows.items() if cb.isChecked()}


class BlocksEditor(QWidget):
    """Optional custom lesson-block rule for one course (unchecked = the table by lessons/week)."""

    def __init__(self, lessons: int, current: list | None):
        super().__init__()
        self.on = QCheckBox(tr("Custom lesson blocks"))
        self.on.setChecked(current is not None)
        size, lo, hi = current or BLOCKS.get(lessons, BLOCKS_DEFAULT)
        self.spins = [QSpinBox(minimum=1, maximum=60, value=v, prefix=p) for v, p in
                      ((size, tr("min block") + " "), (lo, tr("min blocks") + " "), (hi, tr("max blocks") + " "))]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.on)
        for s in self.spins:
            s.setEnabled(current is not None)
            self.on.toggled.connect(s.setEnabled)
            lay.addWidget(s)

    def value(self) -> list | None:
        return [s.value() for s in self.spins] if self.on.isChecked() else None


class _Dialog(QDialog):
    """Validates through ops.trial() so the dialog stays open until the edit is acceptable."""

    def __init__(self, parent, doc: Document, title: str):
        super().__init__(parent)
        self.doc, self.entity = doc, None
        self.setWindowTitle(title)
        self.form = QFormLayout()
        self.err = QLabel()
        self.err.setStyleSheet("color: #b00020")
        self.err.setWordWrap(True)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(self.form)
        lay.addWidget(self.err)
        lay.addWidget(box)

    def accept(self):
        entity = self.result()
        problems = ops.trial(self.doc, lambda d: self.save(d, entity))
        if problems:
            self.err.setText("\n".join(problems[:4]))
        else:
            self.entity = entity
            super().accept()


class TeacherDialog(_Dialog):
    save = staticmethod(ops.save_teacher)

    def __init__(self, parent, doc: Document, t: Teacher | None = None):
        super().__init__(parent, doc, tr("Teacher"))
        self.id = t.id if t else ops.next_id(doc.teachers)
        self.name = QLineEdit(t.name if t else "")
        self.rooms = RoomPicker(doc, t.allowed_rooms if t else None)
        self.slots = Slots(doc, t.blocked if t else set())
        self.limits = Limits(doc, TEACHER_KEYS, t.limits if t else {})
        self.form.addRow(tr("Name"), self.name)
        self.form.addRow(tr("Rooms"), self.rooms)
        self.form.addRow(tr("Available"), self.slots)
        self.form.addRow(tr("Override limits"), self.limits)

    def result(self) -> Teacher:
        return Teacher(self.id, self.name.text().strip(), self.slots.blocked(), self.rooms.value(),
                       self.limits.value())


class RoomDialog(_Dialog):
    save = staticmethod(ops.save_room)

    def __init__(self, parent, doc: Document, r: Room | None = None):
        super().__init__(parent, doc, tr("Room"))
        self.id = r.id if r else ops.next_id(doc.rooms)
        self.name = QLineEdit(r.name if r else "")
        self.cap = QSpinBox(minimum=0, maximum=100000, value=r.capacity if r else 30)
        self.slots = Slots(doc, r.blocked if r else set())
        self.form.addRow(tr("Name"), self.name)
        self.form.addRow(tr("Capacity"), self.cap)
        self.form.addRow(tr("Available"), self.slots)

    def result(self) -> Room:
        return Room(self.id, self.name.text().strip(), self.cap.value(), self.slots.blocked())


class CourseDialog(_Dialog):
    save = staticmethod(ops.save_course)

    def __init__(self, parent, doc: Document, c: Course | None = None, ep_id: int | None = None):
        super().__init__(parent, doc, tr("Course"))
        self.id = c.id if c else ops.next_id(doc.courses)
        self.name = QLineEdit(c.name if c else "")
        self.ep = QComboBox()
        for e in doc.eps.values():
            self.ep.addItem(f"{doc.epgs[e.epg_id].name} / {e.name}", e.id)
        self.ep.setCurrentIndex(max(self.ep.findData(c.ep_id if c else ep_id), 0))
        self.teacher = QComboBox()
        for t in doc.teachers.values():
            self.teacher.addItem(t.name, t.id)
        if c:
            self.teacher.setCurrentIndex(self.teacher.findData(c.teacher_id))
        self.lessons = QSpinBox(minimum=0, maximum=60, value=c.lessons if c else 2)
        self.students = QSpinBox(minimum=0, maximum=100000, value=c.students if c else 0)
        self.group = QLineEdit(c.group if c else "")
        self.group.setPlaceholderText(tr("empty = whole class"))
        self.rooms = RoomPicker(doc, c.allowed_rooms if c else None)
        others = [(o.id, f"{doc.eps[o.ep_id].name}: {o.name} {o.group}".strip())
                  for o in doc.courses.values() if o.id != self.id]
        self.ht = Checklist(others, set(c.hold_together) if c else set())
        self.ht.setMaximumHeight(90)
        self.blocks = BlocksEditor(self.lessons.value(), c.blocks if c else None)
        for label, w in ((tr("Name"), self.name), (tr("Class"), self.ep), (tr("Teacher"), self.teacher),
                         (tr("Lessons / week"), self.lessons), (tr("Students"), self.students),
                         (tr("Group"), self.group), (tr("Rooms"), self.rooms), (tr("Hold together with"), self.ht),
                         (tr("Lesson blocks"), self.blocks)):
            self.form.addRow(label, w)

    def result(self) -> Course:
        return Course(self.id, self.name.text().strip(), self.ep.currentData(), self.teacher.currentData(),
                      self.lessons.value(), self.students.value(), self.group.text().strip(),
                      self.rooms.value(), sorted(self.ht.value()), self.blocks.value())


# key -> (label, limit label or None). Order = display order, grouped by the key prefix.
SETTINGS_ROWS = {
    "teacher_days": (N_("Max days per week"), N_("days")),
    "teacher_daily": (N_("Max hours per day"), N_("hours")),
    "teacher_continuous": (N_("Max hours in a row"), N_("hours")),
    "student_days": (N_("Max days per week"), N_("days")),
    "student_daily": (N_("Max hours per day"), N_("hours")),
    "student_continuous": (N_("Max hours in a row"), N_("hours")),
    "student_gaps": (N_("Gaps (up to this many empty periods count)"), N_("periods")),
    "student_start": (N_("Preferred first period"), N_("period")),
    "course_blocks": (N_("Lesson blocks (fixed table by lessons/week)"), None),
}
GROUPS = {"teacher": N_("Teachers"), "student": N_("Students (per class / group)"), "course": N_("Courses")}


class SettingsDialog(QDialog):
    """Soft-constraint limits and weights for this document. Weight 0 switches a constraint off."""

    def __init__(self, parent, doc: Document):
        super().__init__(parent)
        from octt.rules.soft import PARAMS, WEIGHTS

        self.setWindowTitle(tr("Soft-constraint settings"))
        self.defaults = (PARAMS, WEIGHTS)
        self.limit, self.weight = {}, {}
        lay = QVBoxLayout(self)
        for prefix, title in GROUPS.items():
            box, form = QGroupBox(tr(title)), QFormLayout()
            box.setLayout(form)
            for key, (label, unit) in SETTINGS_ROWS.items():
                if not key.startswith(prefix):
                    continue
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                if unit:
                    hi = len(doc.terms) if key == "student_start" else 99
                    self.limit[key] = QSpinBox(minimum=1 if key == "student_start" else 0, maximum=hi,
                                               suffix=f" {tr(unit)}")
                    h.addWidget(self.limit[key])
                h.addWidget(QLabel(tr("weight")))
                self.weight[key] = QDoubleSpinBox(minimum=0, maximum=1000, decimals=2, singleStep=0.5)
                h.addWidget(self.weight[key])
                form.addRow(tr(label), row)
            lay.addWidget(box)
        lay.addWidget(QLabel(tr("Weight 0 = off. Lower total penalty is better; the solver minimises it.")))
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        self.box.button(QDialogButtonBox.RestoreDefaults).clicked.connect(lambda: self.load({}, {}))
        lay.addWidget(self.box)
        self.load(doc.params, doc.weights)

    def load(self, params: dict, weights: dict):
        P, W = {**self.defaults[0], **params}, {**self.defaults[1], **weights}
        for k, w in self.limit.items():
            w.setValue(P[k])
        for k, w in self.weight.items():
            w.setValue(W[k])

    def values(self) -> tuple[dict, dict]:
        """Only what differs from the defaults, so later changes to the defaults still apply."""
        P, W = self.defaults
        return ({k: w.value() for k, w in self.limit.items() if w.value() != P[k]},
                {k: w.value() for k, w in self.weight.items() if w.value() != W[k]})


class EpDialog(_Dialog):
    """Edit a class: name, availability, and its own student soft-constraint limits."""
    save = staticmethod(ops.save_ep)

    def __init__(self, parent, doc: Document, e: Ep):
        super().__init__(parent, doc, tr("Class"))
        self.e = e
        self.name = QLineEdit(e.name)
        self.slots = Slots(doc, e.blocked)
        self.limits = Limits(doc, STUDENT_KEYS, e.limits)
        self.form.addRow(tr("Name"), self.name)
        self.form.addRow(tr("Available"), self.slots)
        self.form.addRow(tr("Override limits"), self.limits)

    def result(self) -> Ep:
        return Ep(self.e.id, self.name.text().strip(), self.e.epg_id, self.slots.blocked(), self.limits.value())
