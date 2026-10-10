import tempfile
from pathlib import Path

from octt import io
from octt.demo import demo
from octt.model import Placement
from octt.rules.hard import candidate_rooms, violations


def test_free_slot_ok():
    assert violations(demo(), 1, 1, 0) == []


def test_student_clash_and_teacher_busy():
    d = demo()  # Math 5A at (0,0). Same ep, non-group -> clash
    assert any("students busy" in v for v in violations(d, 2, 0, 0))
    assert any("already teaching" in v for v in violations(d, 3, 0, 0))  # Ada also teaches 5B Math


def test_group_course_ignores_other_group_but_not_whole_class():
    d = demo()
    d.placements.append(Placement(2, 2, 0, 2))  # CS group A at (2,0)
    assert any("students busy" in v for v in violations(d, 1, 2, 0))  # whole-class Math vs group
    d.courses[1].group = "B"
    assert not any("students busy" in v for v in violations(d, 1, 2, 0))  # different groups coexist


def test_blocked_slots():
    d = demo()
    d.epgs[1].blocked.add((1, 1))
    d.teachers[1].blocked.add((1, 2))
    assert any("group blocked" in v for v in violations(d, 1, 1, 1))
    assert any("unavailable" in v for v in violations(d, 1, 1, 2))


def test_room_capacity_busy_and_restriction():
    d = demo()
    assert candidate_rooms(d, 1, 1, 0) == [1]  # 25 students: lab (12) too small
    assert candidate_rooms(d, 2, 1, 0) == [2, 1]  # smallest fitting first
    d.courses[2].allowed_rooms = {1}
    assert candidate_rooms(d, 2, 1, 0) == [1]
    assert candidate_rooms(d, 1, 0, 0) == []  # R101 busy at (0,0)
    assert "no free room fits" in violations(d, 3, 0, 0)


def test_hold_together_needs_summed_capacity():
    d = demo()
    d.courses[1].hold_together = [3]  # 25 + 22 = 47 > 30
    assert candidate_rooms(d, 1, 1, 0) == []


def test_json_roundtrip():
    d = demo()
    d.teachers[1].blocked.add((1, 1))
    d.courses[2].allowed_rooms = {2}
    p = Path(tempfile.mkdtemp()) / "t.json"
    io.save(d, p)
    assert io.load(p) == d


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
