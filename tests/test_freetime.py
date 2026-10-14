"""Free time: only slots where class, teacher and a fitting room are all free; booking places and locks them."""
import copy

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from octt import ops
from octt.demo import demo
from octt.freetime import book, effect, find, rooms
from octt.model import Course
from octt.rules.soft import score, total
from tests.test_window import patch, window

APP = QApplication.instance() or QApplication([])


def extra(**kw):
    return Course(0, "Extra", kw.pop("ep_id", 1), kw.pop("teacher_id", 2), **kw)  # 5A with Alan


def test_only_slots_where_class_teacher_and_a_room_are_free():
    d = demo()  # Math 5A (Ada) sits at Mon period 1 in R101
    d.teachers[2].blocked = {(1, 0)}  # Alan is away Mon period 2
    slots = {(f.term, f.day) for f in find(d, extra())}
    assert (0, 0) not in slots and (1, 0) not in slots  # class busy; teacher away
    assert len(slots) == len(d.terms) * len(d.days) - 2
    assert all(f.rooms == [2, 1] for f in find(d, extra(students=5)))  # smallest fitting room first
    assert all(f.rooms == [1] for f in find(d, extra(students=20)))  # the 12-seat lab is too small
    assert find(d, extra(students=99)) == []


def test_best_first_and_penalty_matches_scoring_the_whole_timetable():
    d = demo()
    found = find(d, extra())
    assert [f.penalty for f in found] == sorted(f.penalty for f in found)
    assert found[0].penalty < found[-1].penalty  # next to Math on Monday beats a lone late lesson
    base = total(score(d))
    for f in found:
        d2 = copy.deepcopy(d)
        book(d2, extra(), [(f.term, f.day, f.rooms[0])])
        assert total(score(d2)) - base == f.penalty


def test_booking_adds_a_course_with_locked_lessons_that_pass_the_audit():
    d = demo()
    picks = [(f.term, f.day, f.rooms[0]) for f in find(d, extra())[:2]]
    cid = book(d, extra(), picks)
    assert d.courses[cid].lessons == 2 and d.unallocated(cid) == 0
    assert all(p.locked for p in d.placements if p.course_id == cid) and not ops.audit(d)


def test_lessons_together_are_priced_together_not_summed():
    d = demo()
    at = {(f.term, f.day): f for f in find(d, extra(ep_id=2))}
    base = total(score(d))
    for pair in (((0, 1), (1, 1)), ((0, 1), (0, 3))):  # a double lesson on Tuesday; Tuesday + Thursday
        picks = rooms([at[s] for s in pair])
        d2 = copy.deepcopy(d)
        book(d2, extra(ep_id=2), picks)
        assert effect(d, extra(ep_id=2), picks) == total(score(d2)) - base  # exact
    split = rooms([at[0, 1], at[0, 3]])  # 2 lessons/week want one double lesson: apart, the new course is flagged
    assert effect(d, extra(ep_id=2), split) > at[0, 1].penalty + at[0, 3].penalty


def test_same_day_picks_share_a_room_when_one_is_free_for_all():
    d = demo()
    d.rooms[2].blocked = {(1, 1)}  # the lab is taken on Tuesday period 2
    at = {(f.term, f.day): f for f in find(d, extra(ep_id=2, students=5))}
    assert at[0, 1].rooms == [2, 1] and at[1, 1].rooms == [1]
    assert rooms([at[0, 1], at[1, 1]]) == [(0, 1, 1), (1, 1, 1)]  # both in R101, not lab then R101
    assert rooms([at[0, 1], at[0, 2]]) == [(0, 1, 2), (0, 2, 2)]  # different days: each its smallest room


def test_dialog_finds_books_and_undoes():
    from octt.ui.freetime_dialog import FreeTimeDialog
    w = window(demo())
    dlg = FreeTimeDialog(w, ep_id=2, teacher_id=2)
    assert dlg.editor.ep.currentData() == 2 and dlg.table.rowCount() == len(dlg.found) > 0
    assert not dlg.add_btn.isEnabled()
    dlg.table.selectRow(0)
    assert dlg.add_btn.isEnabled() and dlg.together.text() == ""  # one lesson: its row already says it
    dlg.table.selectionModel().select(dlg.table.model().index(1, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert "2" in dlg.together.text()
    dlg.table.selectRow(0)
    before = len(w.doc.placements)
    dlg.accept()
    c = w.doc.courses[dlg.booked]
    assert (c.name, c.ep_id, c.teacher_id, c.lessons) == ("Extra session", 2, 2, 1)
    assert len(w.doc.placements) == before + 1 and w.doc.placements[-1].locked
    w.undo.undo()
    assert dlg.booked not in w.doc.courses and len(w.doc.placements) == before


def test_dialog_searches_again_before_booking_a_changed_form():
    from octt.ui.freetime_dialog import FreeTimeDialog
    w = window(demo())
    dlg = FreeTimeDialog(w)
    dlg.table.selectRow(0)
    dlg.editor.students.setValue(99)  # nothing fits now, but the search has not run yet
    dlg.accept()
    assert dlg.booked is None and dlg.table.rowCount() == 0 and len(w.doc.courses) == 3


def test_menu_action_starts_from_the_teacher_on_screen_and_shows_the_class_after():
    from octt.ui.freetime_dialog import FreeTimeDialog
    w = window(demo())
    w.show_view(("teacher", 2))
    seen = []

    def run(dlg):
        seen.append(dlg.editor.teacher.currentData())
        dlg.editor.ep.setCurrentIndex(dlg.editor.ep.findData(2))
        dlg.search()
        dlg.table.selectRow(0)
        dlg.accept()
        return 1

    undo = patch(FreeTimeDialog, "exec", run)
    try:
        w.find_free_time()
    finally:
        undo()
    assert seen == [2] and w.view == ("class", 2)


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
