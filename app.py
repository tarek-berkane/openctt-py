"""Weekly school timetable. Click an empty slot to add, a block to edit/delete."""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QTime, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHeaderView, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QTimeEdit,
)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
START_H, END_H, STEP = 7, 22, 30  # grid range (hours) and slot size (minutes)
SLOTS = (END_H - START_H) * 60 // STEP
DATA = Path.home() / ".school_schedule.json"
COLORS = ["#8ecae6", "#ffb703", "#b5e48c", "#f4a6c0", "#cdb4db", "#ffd6a5"]


def to_slot(t: QTime) -> int:
    return (t.hour() * 60 + t.minute() - START_H * 60) // STEP


def overlaps(a: dict, b: dict) -> bool:
    return a["day"] == b["day"] and a["start"] < b["end"] and b["start"] < a["end"]


class SessionDialog(QDialog):
    def __init__(self, parent, s: dict, can_delete: bool):
        super().__init__(parent)
        self.setWindowTitle("Session")
        self.deleted = False
        self.title = QLineEdit(s["title"])
        self.day = QComboBox()
        self.day.addItems(DAYS)
        self.day.setCurrentIndex(s["day"])
        self.start, self.end = QTimeEdit(), QTimeEdit()
        for w, slot in ((self.start, s["start"]), (self.end, s["end"])):
            m = START_H * 60 + slot * STEP
            w.setDisplayFormat("HH:mm")
            w.setTime(QTime(m // 60 % 24, m % 60))
        form = QFormLayout(self)
        form.addRow("Title", self.title)
        form.addRow("Day", self.day)
        form.addRow("Start", self.start)
        form.addRow("End", self.end)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        if can_delete:
            d = box.addButton("Delete", QDialogButtonBox.DestructiveRole)
            d.clicked.connect(lambda: (setattr(self, "deleted", True), self.accept()))
        form.addRow(box)

    def result_session(self) -> dict:
        return {"title": self.title.text().strip(), "day": self.day.currentIndex(),
                "start": to_slot(self.start.time()), "end": to_slot(self.end.time())}


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("School Schedule")
        self.resize(900, 700)
        try:
            self.sessions = json.loads(DATA.read_text())
        except (OSError, ValueError):
            self.sessions = []
        t = self.table = QTableWidget(SLOTS, len(DAYS))
        t.setHorizontalHeaderLabels(DAYS)
        t.setVerticalHeaderLabels(
            [f"{START_H + i * STEP // 60}:{i * STEP % 60:02d}" for i in range(SLOTS)])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.verticalHeader().setDefaultSectionSize(22)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.cellClicked.connect(self.on_cell)
        self.setCentralWidget(t)
        add = QPushButton("+ Add")
        add.clicked.connect(lambda: self.edit(None, 0, 0))
        self.statusBar().addPermanentWidget(add)
        self.render()

    def render(self):
        t = self.table
        t.clearSpans()
        t.clearContents()
        for i, s in enumerate(self.sessions):
            item = QTableWidgetItem(s["title"])
            item.setBackground(QColor(COLORS[hash(s["title"].lower()) % len(COLORS)]))
            item.setForeground(Qt.black)
            item.setData(Qt.UserRole, i)
            t.setItem(s["start"], s["day"], item)
            if s["end"] - s["start"] > 1:
                t.setSpan(s["start"], s["day"], s["end"] - s["start"], 1)

    def on_cell(self, row: int, col: int):
        for i, s in enumerate(self.sessions):
            if s["day"] == col and s["start"] <= row < s["end"]:
                return self.edit(i, col, s["start"])
        self.edit(None, col, row)

    def edit(self, idx, day: int, slot: int):
        s = self.sessions[idx] if idx is not None else {
            "title": "", "day": day, "start": slot, "end": min(slot + 2, SLOTS)}
        dlg = SessionDialog(self, s, idx is not None)
        if not dlg.exec():
            return
        if dlg.deleted:
            del self.sessions[idx]
        else:
            new = dlg.result_session()
            if not new["title"] or not 0 <= new["start"] < new["end"] <= SLOTS:
                return QMessageBox.warning(
                    self, "Invalid", f"Need a title and a start before end, within {START_H}:00-{END_H}:00.")
            clash = [o for j, o in enumerate(self.sessions) if j != idx and overlaps(new, o)]
            if clash:
                return QMessageBox.warning(self, "Clash", f"Overlaps with '{clash[0]['title']}'.")
            if idx is None:
                self.sessions.append(new)
            else:
                self.sessions[idx] = new
        DATA.write_text(json.dumps(self.sessions))
        self.render()


if __name__ == "__main__":
    assert overlaps({"day": 0, "start": 0, "end": 2}, {"day": 0, "start": 1, "end": 3})
    assert not overlaps({"day": 0, "start": 0, "end": 2}, {"day": 0, "start": 2, "end": 3})
    app = QApplication(sys.argv)
    w = Main()
    w.show()
    sys.exit(app.exec())
