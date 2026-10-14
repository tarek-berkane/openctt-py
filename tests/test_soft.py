from octt.demo import demo
from octt.model import Course, Placement
from octt.rules.soft import defaults, score, total


def keys(d, **kw):
    return sorted(p.key for p in score(d, **kw))


def doc_with(*slots):  # slots: (course_id, term, day, room_id)
    d = demo()
    d.placements = [Placement(*s) for s in slots]
    return d


def test_empty_and_perfect_timetable_score_zero():
    assert score(doc_with()) == []
    # Math 5A: 3 consecutive periods from period 1, one room -> one block, no gaps, right start
    d = doc_with((1, 0, 0, 1), (1, 1, 0, 1), (1, 2, 0, 1))
    assert score(d) == []


def test_teachers_may_work_every_day_by_default():
    d = doc_with(*[(1 + 2 * (day % 2), 0, day, 1) for day in range(5)])  # Ada teaches all 5 days
    assert "teacher_days" not in keys(d)
    assert "teacher_days" in keys(d, params={"teacher_days": 4})
    assert "student_days" not in keys(d) and "student_days" in keys(d, params={"student_days": 2})  # 5A: Mon, Wed, Fri
    d.days.append("Sat")  # the defaults follow the week
    assert defaults(d)["teacher_days"] == defaults(d)["student_days"] == 6


def test_continuous_and_daily_hours():
    d = doc_with(*[(1, t, 0, 1) for t in range(3)], *[(3, t, 0, 1) for t in range(3, 6)])
    ks = keys(d, params={"teacher_days": 5})
    assert "teacher_continuous" in ks and "teacher_daily" in ks  # 6 h in a row > 4


def test_student_gap_and_late_start():
    d = doc_with((1, 1, 0, 1), (1, 3, 0, 1))  # 5A: periods 2 and 4 -> starts late, one gap
    ks = keys(d)
    assert ks.count("student_gaps") == 1 and ks.count("student_start") == 1


def test_gap_longer_than_indicator_is_not_a_gap():
    d = doc_with((1, 0, 0, 1), (1, 5, 0, 1))  # gap of 4 empty periods -> counts (<= 4)
    assert "student_gaps" in keys(d)
    assert "student_gaps" not in keys(d, params={"student_gaps": 3})


def test_group_students_include_whole_class_lessons():
    d = doc_with((1, 0, 0, 1), (2, 2, 0, 2))  # Math (whole class) + CS group A, gap at period 2
    assert any(p.key == "student_gaps" and p.subject == "5A A" for p in score(d))


def test_course_blocks_only_when_fully_placed_and_contiguous():
    assert "course_blocks" not in keys(doc_with((1, 0, 0, 1), (1, 1, 0, 1)))  # 2 of 3 placed
    split = doc_with((1, 0, 0, 1), (1, 1, 0, 1), (1, 0, 2, 1))  # block of 2 + 1 on another day
    assert "course_blocks" in keys(split)
    two_rooms = doc_with((1, 0, 0, 1), (1, 1, 0, 2), (1, 2, 0, 1))
    assert "course_blocks" in keys(two_rooms)


def test_weights_scale_the_total():
    d = doc_with((1, 1, 0, 1))
    base = total(score(d))
    assert base == 1 and total(score(d, weights={"student_start": 2.5})) == 2.5


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
