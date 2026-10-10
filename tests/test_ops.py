import copy

from PySide6.QtGui import QUndoStack

from octt import ops
from octt.commands import StateEdit, snapshot
from octt.demo import demo
from octt.model import Course, Placement, Room, Teacher


def test_demo_is_clean():
    assert ops.audit(demo()) == []


def test_duplicate_and_blank_names_rejected():
    d = demo()
    assert ops.trial(d, lambda x: ops.save_teacher(x, Teacher(9, " ada lovelace "))) == ["duplicate teacher ' ada lovelace '"]
    assert ops.trial(d, lambda x: ops.save_room(x, Room(9, "", 5)))
    assert ops.trial(d, lambda x: ops.save_room(x, Room(9, "R102", 40))) == []


def test_edit_cannot_break_placed_lessons():
    d = demo()  # Math 5A (25 students) sits in R101 at (0,0)
    assert ops.trial(d, lambda x: ops.save_room(x, Room(1, "R101", 10)))  # capacity below load
    r = copy.deepcopy(d.rooms[1])
    r.blocked.add((0, 0))
    assert ops.trial(d, lambda x: ops.save_room(x, r))  # blocks an occupied slot
    t = copy.deepcopy(d.teachers[1])
    t.blocked.add((0, 0))
    assert ops.trial(d, lambda x: ops.save_teacher(x, t))
    c = copy.deepcopy(d.courses[1])
    c.lessons = 0
    assert ops.trial(d, lambda x: ops.save_course(x, c))


def test_preexisting_problems_do_not_block_unrelated_edits():
    d = demo()
    d.rooms[1].capacity = 1  # file loaded in a bad state
    assert ops.audit(d)
    assert ops.trial(d, lambda x: ops.save_room(x, Room(9, "R102", 40))) == []


def test_hold_together_is_symmetric():
    d = demo()
    c = copy.deepcopy(d.courses[1])
    c.hold_together = [3]
    ops.save_course(d, c)
    assert d.courses[3].hold_together == [1]
    c2 = copy.deepcopy(c)
    c2.hold_together = []
    ops.save_course(d, c2)
    assert d.courses[3].hold_together == []


def test_audit_accepts_hold_together_lessons_sharing_a_slot():
    d = demo()
    ops.save_course(d, Course(1, "Math", 1, 1, 3, 25, hold_together=[3]))
    d.rooms[3] = Room(3, "Hall", 60)
    d.placements = [Placement(1, 1, 1, 3), Placement(3, 1, 1, 3), Placement(1, 2, 1, 3), Placement(3, 2, 1, 3)]
    assert ops.audit(d) == []


def test_add_group_and_class_get_fresh_ids_and_validate():
    d = demo()
    ops.add_group(d, "Grade 6")
    ops.add_ep(d, 2, "6A")
    assert d.epgs[2].name == "Grade 6" and d.eps[3].epg_id == 2 and ops.audit(d) == []
    assert ops.trial(d, lambda x: ops.add_group(x, "grade 6")) == ["duplicate group 'grade 6'"]
    assert ops.trial(d, lambda x: ops.add_ep(x, 2, " ")) == ["class name is empty"]


def test_deletes():
    d = demo()
    assert ops.trial(d, lambda x: ops.delete_teacher(x, 1))  # teaches courses
    assert ops.trial(d, lambda x: ops.delete_room(x, 1))  # holds a lesson
    assert ops.trial(d, lambda x: ops.delete_room(x, 2)) == []
    ops.delete_course(d, 1)
    assert d.placements == [] and 1 not in d.courses
    assert ops.audit(d) == []


def test_new_course_via_ids_and_state_undo():
    d, s = demo(), QUndoStack()
    before = snapshot(d)
    ops.save_course(d, Course(ops.next_id(d.courses), "Art", 1, 2, 1, 5))
    s.push(StateEdit(d, before, snapshot(d), "add", lambda: None))
    assert 4 in d.courses
    s.undo()
    assert 4 not in d.courses and len(d.placements) == 1
    s.redo()
    assert d.courses[4].name == "Art"


def test_set_schedule_reorders_days_and_drops_what_no_longer_fits():
    from octt import ops
    from octt.model import Document, Placement, Room
    d = Document(days=["A", "B", "C"], terms=["08:00-08:45", "09:00-09:45"])
    d.rooms[1] = Room(1, "R", 10, {(0, 0), (1, 2)})
    d.placements = [Placement(5, 0, 2, 1), Placement(6, 1, 1, 1), Placement(7, 0, 0, 1)]
    ops.set_schedule(d, "X", "Y", [(2, "C"), (0, "A"), (None, "N")], ["08:00-08:45"])
    assert d.days == ["C", "A", "N"] and d.terms == ["08:00-08:45"] and d.institution == "X"
    assert d.rooms[1].blocked == {(0, 1)}  # (1,2) fell with period 2; A moved to column 1
    assert [(p.course_id, p.day) for p in d.placements] == [(5, 0), (7, 1)]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
