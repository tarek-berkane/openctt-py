import tempfile
import time
import warnings
from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt
from PySide6.QtGui import QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QMessageBox

from octt import io
from octt.demo import demo
from octt.model import Document, Placement
from octt import views
from octt.rules.place import bad_slots
from octt.rules.soft import score
from octt.ui import main_window as mw
from octt.ui.grid import BLOCKS, MIME
from octt.ui.newdoc_dialog import NewDocumentDialog

APP = QApplication.instance() or QApplication([])
warnings.filterwarnings("ignore", category=DeprecationWarning)  # QDragMoveEvent(QPoint) is the only ctor


def window(doc=None, path=None):
    prefs = QSettings(str(Path(tempfile.mkdtemp()) / "prefs.ini"), QSettings.IniFormat)
    w = mw.MainWindow(doc, path, settings=prefs)
    w.show()
    return w


_KEEP = []  # QDropEvent keeps a raw pointer to its QMimeData: Python must not free it first


def mime(cid, src=None):
    m = QMimeData()
    _KEEP.append(m)
    m.setData(MIME, f"{cid}|{'' if not src else src[0]}|{'' if not src else src[1]}".encode())
    return m


def cell_pos(grid, row, col):
    return QPointF(grid.visualRect(grid.model().index(row, col)).center())


def drop(w, widget, cid, src, row=None, col=None):
    pos = cell_pos(widget, row, col) if row is not None else QPointF(5, 5)
    widget.dropEvent(QDropEvent(pos, Qt.MoveAction, mime(cid, src), Qt.LeftButton, Qt.NoModifier))


def pick_class(w, ep_id):
    w.tree.setCurrentItem(w.ep_items[ep_id])


def patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    return lambda: setattr(obj, name, old)


def test_empty_start_guides_the_user():
    w = window()
    assert w.view is None and not w.grid.isEnabled()
    assert "adding a group" in w.banner.text() and w.windowTitle() == "Untitled[*] — OpenCTT"
    assert w.todo.empty_text == "Select a class, teacher or room" and "Nothing selected" == w.title_lbl.text()


def test_views_switch_with_tabs_and_show_the_right_lessons():
    w = window(demo())
    assert w.view == ("class", 1) and w.title_lbl.text() == "Grade 5 · 5A"
    w.tabs.setCurrentIndex(1)  # teachers: first one auto-selected
    assert w.view == ("teacher", 1) and w.title_lbl.text() == "Ada Lovelace" and w.todo.count() == 5
    w.tabs.setCurrentIndex(2)
    assert w.view == ("room", 1) and "R101" in w.title_lbl.text()
    w.tabs.setCurrentIndex(0)
    assert w.view == ("class", 1)
    assert w.items[3].text(0) == "Math  · 3 to place" and w.teachers.item(0).text() == "Ada Lovelace  · 5 to place"


def test_drag_drop_place_move_unplace_and_undo_in_class_view():
    w = window(demo())
    pick_class(w, 2)
    assert w.todo.count() == 3
    drop(w, w.grid, 3, None, 1, 2)
    assert w.todo.count() == 2 and w.grid.item(1, 2).data(Qt.UserRole) is not None and not w.undo.isClean()
    assert w.isWindowModified()
    drop(w, w.grid, 3, (1, 2), 4, 3)
    assert not w.grid.item(1, 2).data(Qt.UserRole) and w.grid.item(4, 3).data(Qt.UserRole)
    drop(w, w.todo, 3, (4, 3))
    assert w.todo.count() == 3 and not w.grid.item(4, 3).data(Qt.UserRole)
    for _ in range(3):
        w.undo.undo()
    assert w.undo.isClean() and w.todo.count() == 3 and not w.isWindowModified()


def test_room_view_forces_the_room():
    w = window(demo())
    d = w.doc
    d.rooms[3] = type(d.rooms[1])(3, "R102", 30)
    w.structure_changed()
    w.tabs.setCurrentIndex(2)
    w.rooms.setCurrentRow(2)  # R102
    assert w.view == ("room", 3)
    drop(w, w.grid, 3, None, 1, 0)  # Math 5B dropped on R102's grid
    assert d.placements[-1].room_id == 3
    w.rooms.setCurrentRow(1)  # the lab: 22 students do not fit
    drop(w, w.grid, 1, None, 2, 2)
    assert "suitable" in w.statusBar().currentMessage() and len(d.placements) == 2


def test_drag_over_a_bad_cell_is_refused_with_the_reason():
    w = window(demo())
    pick_class(w, 2)
    w._tint(3, None)  # what starting a drag of Math 5B does: Ada is already teaching Mon/1
    seen = []
    w.grid.hint.connect(seen.append)
    ev = QDragMoveEvent(cell_pos(w.grid, 0, 0).toPoint(), Qt.MoveAction, mime(3), Qt.LeftButton, Qt.NoModifier)
    w.grid.dragMoveEvent(ev)
    assert not ev.isAccepted() and "already teaching" in seen[-1]
    ev = QDragMoveEvent(cell_pos(w.grid, 3, 3).toPoint(), Qt.MoveAction, mime(3), Qt.LeftButton, Qt.NoModifier)
    w.grid.dragMoveEvent(ev)
    assert ev.isAccepted() and seen[-1] == ""


def test_cell_menu_offers_remove_edit_and_place():
    w = window(demo())
    pick_class(w, 1)
    texts = [(t, e) for t, e, _ in w.cell_actions(0, 0, 1)]
    assert texts == [("Lock lesson", True), ("Remove from timetable", True), ("Edit course…", True)]
    acts = w.cell_actions(2, 2, None)  # empty cell; todo = CS A x2, Math x2
    assert [a[0] for a in acts][0].startswith("Place CS A") and all(a[1] for a in acts)
    acts = w.cell_actions(0, 1, None)  # Tue/1 is free for Math; CS A (Alan) is free too
    pick_class(w, 2)
    busy = w.cell_actions(0, 0, None)  # Ada is teaching 5A Math at Mon/1
    assert busy[0][1] is False and "already teaching" in busy[0][0]
    acts[0][2]()  # run a callback: places the lesson
    assert len(w.doc.placements) == 2
    w.cell_actions(0, 0, 1)[1][2]()  # remove it again
    assert all(p.course_id != 1 or (p.term, p.day) != (0, 0) for p in w.doc.placements)


def test_unsaved_changes_guard_new_open_and_close():
    w = window(demo())
    undo = []
    try:
        w.doc.placements.clear()
        w.structure_changed()
        w.place(1, None, 0, 0)  # dirty
        undo.append(patch(QMessageBox, "exec", lambda self: QMessageBox.Cancel))
        assert w.maybe_save() is False
        w.new()
        assert w.doc.institution == "Demo School"  # cancelled: nothing replaced
        undo.append(patch(QMessageBox, "exec", lambda self: QMessageBox.Discard))
        assert w.maybe_save() is True
        target = str(Path(tempfile.mkdtemp()) / "t.json")
        undo.append(patch(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (target, ""))))
        undo.append(patch(QMessageBox, "exec", lambda self: QMessageBox.Save))
        assert w.maybe_save() is True and Path(target).exists() and w.undo.isClean()
        assert w.windowTitle() == "t.json[*] — OpenCTT" and w.recent() == [target]
        assert io.load(target) == w.doc
    finally:
        for u in reversed(undo):
            u()


def test_close_event_respects_cancel():
    w = window(demo())
    w.place(1, None, 1, 1)
    undo = patch(QMessageBox, "exec", lambda self: QMessageBox.Cancel)
    try:
        assert w.close() is False and w.isVisible()
    finally:
        undo()
    undo = patch(QMessageBox, "exec", lambda self: QMessageBox.Discard)
    try:
        assert w.close() is True
    finally:
        undo()
    assert w.prefs.value("geometry") is not None


def test_open_invalid_file_reports_instead_of_crashing():
    w = window(demo())
    bad = Path(tempfile.mkdtemp()) / "bad.json"
    bad.write_text("{not json")
    shown = []
    undo = patch(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    try:
        w.open(str(bad))
    finally:
        undo()
    assert shown and "not a valid timetable" in shown[0] and w.doc.institution == "Demo School"


def test_recent_files_are_deduplicated_and_capped():
    r = []
    for i in range(10):
        r = mw.push_recent(r, f"/f{i}.json")
    r = mw.push_recent(r, "/f5.json")
    assert r[0] == "/f5.json" and len(r) == mw.MAX_RECENT and r.count("/f5.json") == 1


def test_new_document_dialog():
    dlg = NewDocumentDialog()
    ok = dlg.box.button(QDialogButtonBox.Ok)
    assert ok.isEnabled() and "08:00-08:45" in dlg.info.text() and "(6 periods)" in dlg.info.text()
    dlg.institution.setText(" Springfield ")
    dlg.count.setValue(3)
    for cb in dlg.days[3:]:
        cb.setChecked(False)
    dlg.accept()
    d = dlg.document
    assert d.institution == "Springfield" and d.days == ["Mon", "Tue", "Wed"] and len(d.terms) == 3
    dlg = NewDocumentDialog()
    dlg.count.setValue(24)
    dlg.first.setTime(dlg.first.time().addSecs(12 * 3600))  # 20:00 start: runs past midnight
    assert not dlg.box.button(QDialogButtonBox.Ok).isEnabled() and "midnight" in dlg.info.text()
    for cb in dlg.days:
        cb.setChecked(False)
    dlg.count.setValue(1)
    assert not dlg.box.button(QDialogButtonBox.Ok).isEnabled() and "at least one day" in dlg.info.text()


def test_new_creates_an_empty_timetable_that_survives_a_roundtrip():
    w = window(demo())
    w.undo.setClean()
    d = Document(institution="X", days=["Mon"], terms=["08:00-09:00"])
    undo = patch(NewDocumentDialog, "exec", lambda self: (setattr(self, "document", d), 1)[1])
    try:
        w.new()
    finally:
        undo()
    assert w.doc is d and w.grid.rowCount() == 1 and w.grid.columnCount() == 1 and w.path is None
    assert "adding a group" in w.banner.text()


def test_properties_edit_is_undoable_and_resizes_the_grid():
    from octt.ui.properties_dialog import PropertiesDialog
    w = window(demo())
    days, terms = list(w.doc.days), list(w.doc.terms)
    dlg = PropertiesDialog(w.doc)
    dlg.list.takeItem(len(days) - 1)
    dlg.count.setValue(3)
    w.properties_dialog = lambda: type("D", (), {"exec": lambda s: 1, "institution": dlg.institution, "year": dlg.year,
                                                  "days": dlg.days, "terms": dlg.terms})()
    w.properties()
    assert (len(w.doc.days), len(w.doc.terms), w.grid.columnCount(), w.grid.rowCount()) == (len(days) - 1, 3, len(days) - 1, 3)
    w.undo.undo()
    assert (w.doc.days, w.doc.terms, w.grid.columnCount(), w.grid.rowCount()) == (days, terms, len(days), len(terms))


def test_locking_pins_a_lesson_against_moves_removal_and_the_solver():
    w = window(demo())
    pick_class(w, 1)
    dict((t, fn) for t, _, fn in w.cell_actions(0, 0, 1))["Lock lesson"]()
    assert w.doc.placements[0].locked and w.cell_actions(0, 0, 1)[0][0] == "Unlock lesson"
    assert bad_slots(w.doc, 1, (0, 0)).keys() >= {(3, 3), (1, 1)}  # nowhere to drag it
    w.unplace(1, (0, 0))
    assert len(w.doc.placements) == 1 and "unlock" in w.statusBar().currentMessage()
    w.undo.undo()
    assert not w.doc.placements[0].locked  # lock is an undoable step
    w.undo.redo()
    dict((t, fn) for t, _, fn in w.cell_actions(0, 0, 1))["Unlock lesson"]()
    w.unplace(1, (0, 0))
    assert w.doc.placements == []


def test_solve_dialog_offers_several_timetables_and_applies_the_chosen_one():
    from octt.ui.solve_dialog import SolveDialog
    w = window(demo())
    dlg = SolveDialog(w, w.doc)
    dlg.count.setValue(3)
    dlg.seconds.setValue(3)
    dlg.start()
    while dlg.busy:  # _done runs on the GUI thread and clears it
        APP.processEvents()
        time.sleep(0.01)
    dlg.worker.wait()
    assert dlg.table.rowCount() >= 2 and dlg.apply.isEnabled() and dlg.result is not None
    best = min(r.penalty for r in dlg.results)
    assert dlg.result.penalty == best  # lowest penalty preselected
    dlg.table.selectRow(1)
    assert dlg.result is dlg.results[1]
    shown = lambda: sum(len(dlg.grid.item(r, c).data(BLOCKS) or []) for r in range(dlg.grid.rowCount()) for c in range(dlg.grid.columnCount()))
    dlg.kind.setCurrentIndex(0)
    dlg.entity.setCurrentIndex(0)  # a class: the preview must show exactly that class's lessons in the chosen timetable
    want = len(views.lessons(dlg.preview_doc(dlg.result), ("class", dlg.entity.currentData())))
    assert want > 0 and shown() == want
    dlg.table.selectRow(0)
    assert dlg.pen_table.rowCount() == len(score(dlg.preview_doc(dlg.results[0])))  # issues tab follows the selection
    dlg.table.selectRow(1)
    w.undo.push(mw.PlacementEdit(w.doc, list(dlg.result.removes), dlg.result.placements, "x", w.refresh))
    assert all(w.doc.unallocated(c) == 0 for c in w.doc.courses)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    # leaving through interpreter teardown segfaults ~4% of the time (PySide destroying hundreds of windows); all tests passed
    import os
    import sys
    sys.stdout.flush()
    os._exit(0)
