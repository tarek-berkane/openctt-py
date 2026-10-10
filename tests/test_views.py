from octt import ops
from octt.demo import demo
from octt.model import Document, Placement
from octt.rules.place import bad_slots, plan_place
from octt.views import blocked, cell, lessons, next_step, summary, title, todo, tooltip


def full():
    d = demo()
    d.placements += [Placement(1, 1, 0, 1), Placement(2, 0, 3, 2)]
    return d


def test_lessons_per_view():
    d = full()
    assert len(lessons(d, ("class", 1))) == 3 and len(lessons(d, ("class", 2))) == 0
    assert {p.course_id for p in lessons(d, ("teacher", 1))} == {1} and len(lessons(d, ("teacher", 2))) == 1
    assert [p.room_id for p in lessons(d, ("room", 2))] == [2]


def test_todo_per_view():
    d = full()  # open: Math 5A x1, CS A x1, Math 5B x3
    assert todo(d, ("class", 1)) == [2, 1]  # sorted by name: CS before Math
    assert todo(d, ("class", 2)) == [3, 3, 3]
    assert todo(d, ("teacher", 1)) == [1, 3, 3, 3] and todo(d, ("teacher", 2)) == [2]
    assert todo(d, ("room", 2)) == [2]  # the lab (12 seats) only fits the 10-student CS group
    assert todo(d, ("room", 1)) == [2, 1, 3, 3, 3]


def test_blocked_titles_summaries_cells():
    d = full()
    d.epgs[1].blocked, d.eps[1].blocked = {(0, 4)}, {(1, 4)}
    d.teachers[1].blocked, d.rooms[2].blocked = {(2, 2)}, {(3, 3)}
    assert blocked(d, ("class", 1)) == {(0, 4), (1, 4)}
    assert blocked(d, ("teacher", 1)) == {(2, 2)} and blocked(d, ("room", 2)) == {(3, 3)}
    assert title(d, ("class", 1)) == "Grade 5 · 5A" and title(d, ("room", 1)) == "Room R101 (30 seats)"
    assert summary(d, ("class", 1)) == "3 of 5 lessons placed"  # 5A has 3 Math + 2 CS lessons, 2 still open
    assert cell(d, ("class", 1), d.placements[0]) == ("Math", "Ada Lovelace · R101")
    assert cell(d, ("teacher", 1), d.placements[0]) == ("Math", "5A · R101")
    assert cell(d, ("room", 1), d.placements[0]) == ("Math", "5A · Ada Lovelace")
    assert "Teacher: Ada Lovelace" in tooltip(d, d.placements[0])


def test_room_forced_placement_and_hover_reasons():
    d = demo()
    d.rooms[3] = type(d.rooms[1])(3, "R102", 30)
    assert plan_place(d, 3, 1, 0, room=3)[1][0].room_id == 3
    assert plan_place(d, 1, 1, 0, room=2)[2]  # the lab is too small for 25 students
    bad = bad_slots(d, 3, None)
    assert (0, 0) in bad and any("already teaching" in e for e in bad[0, 0])  # reasons, not just a set
    assert (1, 0) not in bad and (1, 0) not in bad_slots(d, 3, None, room=3)


def test_next_step_walks_through_setup():
    d = Document()
    msgs = []
    for build in (lambda x: ops.add_group(x, "G"), lambda x: ops.add_ep(x, 1, "A"),
                  lambda x: ops.save_teacher(x, __import__("octt.model", fromlist=["Teacher"]).Teacher(1, "T")),
                  lambda x: ops.save_room(x, __import__("octt.model", fromlist=["Room"]).Room(1, "R", 20)),
                  lambda x: ops.save_course(x, __import__("octt.model", fromlist=["Course"]).Course(1, "M", 1, 1, 2, 5))):
        msgs.append(next_step(d))
        build(d)
    assert [m.split(":")[-1].strip()[:9] for m in msgs] == ["Data ▸ Ad"] * 5 and len(set(msgs)) == 5
    assert "2 lesson" in next_step(d)
    d.placements = [Placement(1, 0, 0, 1), Placement(1, 1, 0, 1)]
    assert next_step(d) is None


def test_make_terms():
    assert ops.make_terms("08:00", 3, 45, 10) == ["08:00-08:45", "08:55-09:40", "09:50-10:35"]
    assert ops.make_terms("23:00", 1, 60) == ["23:00-24:00"]
    try:
        ops.make_terms("23:00", 2, 45)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
