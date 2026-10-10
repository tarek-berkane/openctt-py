from PySide6.QtGui import QUndoStack

from octt.commands import PlacementEdit
from octt.demo import demo
from octt.rules.place import bad_slots, plan_place, plan_unplace


def test_place_picks_smallest_fitting_room():
    d = demo()
    remove, add, err = plan_place(d, 2, 1, 0)  # CS group, 10 students -> Lab
    assert (remove, err) == ([], []) and [(p.room_id, p.term, p.day) for p in add] == [(2, 1, 0)]


def test_place_rejects_clash_and_exhausted():
    d = demo()
    assert plan_place(d, 3, 0, 0)[2]  # Ada busy at (0,0)
    d.courses[1].lessons = 1  # its only lesson is already placed
    assert plan_place(d, 1, 1, 0)[2] == ["no lessons left"]


def test_move_ignores_own_old_slot():
    d = demo()
    remove, add, err = plan_place(d, 1, 1, 0, src=(0, 0))
    assert err == [] and len(remove) == 1 and (add[0].term, add[0].day) == (1, 0)
    assert plan_place(d, 1, 0, 0, src=(0, 0)) == ([], [], [])  # dropped on itself


def test_hold_together_moves_as_one():
    d = demo()
    d.courses[1].hold_together, d.courses[3].hold_together = [3], [1]
    d.rooms[3] = type(d.rooms[1])(3, "Hall", 60)
    d.placements.clear()
    _, add, err = plan_place(d, 1, 1, 0)
    assert err == [] and {p.course_id for p in add} == {1, 3} and len({p.room_id for p in add}) == 1
    d.placements.extend(add)
    assert len(plan_unplace(d, 3, 1, 0)) == 2


def test_bad_slots_marks_teacher_busy_row():
    d = demo()
    assert (0, 0) in bad_slots(d, 3, None) and (1, 0) not in bad_slots(d, 3, None)


def test_undo_redo_roundtrip():
    d, s = demo(), QUndoStack()
    before = list(d.placements)
    remove, add, _ = plan_place(d, 1, 1, 0, src=(0, 0))
    s.push(PlacementEdit(d, remove, add, "move", lambda: None))
    assert d.placements == add
    s.undo()
    assert d.placements == before
    s.redo()
    assert d.placements == add


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
