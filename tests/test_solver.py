import copy

from octt import ops
from octt.demo import demo
from octt.model import Course, Document, Ep, Epg, Placement, Room, Teacher
from octt.rules.place import placement_problems
from octt.rules.soft import score, total
from octt.solver import solve


def applied(d, res):
    out = copy.deepcopy(d)
    out.placements = [p for p in out.placements if p not in res.removes] + res.placements
    return out


def test_demo_solves_validly_from_scratch():
    d = demo()
    res = solve(d, keep=False, time_limit=10)
    assert res.ok, res.message
    out = applied(d, res)
    assert placement_problems(out) == [] and ops.audit(out) == []
    assert all(out.unallocated(c) == 0 for c in out.courses)
    assert abs(res.penalty - total(score(out))) < 1e-9


def test_keep_mode_leaves_existing_lessons():
    d = demo()  # Math 5A already at (0,0) in R101
    res = solve(d, keep=True, time_limit=10)
    assert res.ok and not res.removes
    out = applied(d, res)
    assert Placement(1, 0, 0, 1) in out.placements and ops.audit(out) == []
    assert sum(p.course_id == 1 for p in out.placements) == 3


def test_optimum_matches_the_score_function():
    """Tiny instance whose optimum is known: 2 lessons of one course -> one 2-period block, period 1 start, 0 gaps."""
    d = Document(days=["Mon", "Tue"], terms=["1", "2", "3"])
    d.epgs[1], d.eps[1] = Epg(1, "G"), Ep(1, "A", 1)
    d.teachers[1], d.rooms[1] = Teacher(1, "T"), Room(1, "R", 30)
    d.courses[1] = Course(1, "Math", 1, 1, lessons=2, students=10)
    res = solve(d, keep=False, time_limit=10, params={"teacher_days": 1})
    assert res.status == "OPTIMAL" and res.penalty == 0
    ps = sorted((p.day, p.term) for p in res.placements)
    assert ps[0][0] == ps[1][0] and ps[0][1] == 0 and ps[1][1] == 1


def test_objective_beats_a_bad_hand_made_timetable():
    d = demo()
    res = solve(d, keep=False, time_limit=10)
    bad = copy.deepcopy(d)
    bad.placements = [Placement(1, 0, 0, 1), Placement(1, 5, 1, 1), Placement(1, 3, 3, 1)]
    assert res.penalty <= total(score(bad))


def test_hold_together_gets_same_slot_and_room():
    d = demo()
    ops.save_course(d, Course(1, "Math", 1, 1, 3, 25, hold_together=[3]))
    d.rooms[3] = Room(3, "Hall", 60)
    d.placements = []
    res = solve(d, keep=False, time_limit=10)
    assert res.ok, res.message
    by = {}
    for p in (p for p in res.placements if p.course_id in (1, 3)):
        by.setdefault((p.term, p.day), []).append(p)
    assert all(len(v) == 2 and len({p.room_id for p in v}) == 1 for v in by.values()) and len(by) == 3
    assert placement_problems(applied(d, res)) == []


def test_infeasible_is_explained():
    d = demo()
    d.courses[1].lessons = 99
    res = solve(d, keep=False)
    assert res.status == "INFEASIBLE" and "Math" in res.message


def test_pairwise_infeasibility():
    d = Document(days=["Mon"], terms=["1"])  # one slot, two classes, one teacher, one room
    d.epgs[1] = Epg(1, "G")
    d.eps[1], d.eps[2] = Ep(1, "A", 1), Ep(2, "B", 1)
    d.teachers[1], d.rooms[1] = Teacher(1, "T"), Room(1, "R", 30)
    d.courses[1] = Course(1, "X", 1, 1, 1, 5)
    d.courses[2] = Course(2, "Y", 2, 1, 1, 5)
    assert solve(d, keep=False, time_limit=5).status == "INFEASIBLE"


def test_matches_brute_force_optimum():
    """Exhaustively score every valid timetable of a tiny instance; CP-SAT must reach the same minimum."""
    from itertools import combinations, product

    d = Document(days=["Mon", "Tue"], terms=["1", "2", "3", "4"])
    d.epgs[1], d.eps[1] = Epg(1, "G"), Ep(1, "A", 1)
    d.teachers[1], d.teachers[2] = Teacher(1, "T1"), Teacher(2, "T2")
    d.rooms[1], d.rooms[2] = Room(1, "R1", 30), Room(2, "R2", 30)
    d.courses[1] = Course(1, "X", 1, 1, lessons=2, students=10)
    d.courses[2] = Course(2, "Y", 1, 2, lessons=3, students=10)
    params = {"teacher_days": 1, "teacher_continuous": 2, "student_continuous": 2, "student_daily": 3,
              "student_start": 2, "student_gaps": 2}
    cells = [(t, dd) for t in range(4) for dd in range(2)]
    best = None
    for sx, sy in product(combinations(cells, 2), combinations(cells, 3)):
        if set(sx) & set(sy):
            continue  # same class, one student group: no overlap
        for rx, ry in product(product((1, 2), repeat=2), product((1, 2), repeat=3)):
            d.placements = [Placement(1, t, dd, r) for (t, dd), r in zip(sx, rx)] + \
                           [Placement(2, t, dd, r) for (t, dd), r in zip(sy, ry)]
            v = total(score(d, params))
            best = v if best is None else min(best, v)
    d.placements = []
    res = solve(d, keep=False, time_limit=30, params=params)
    assert res.status == "OPTIMAL" and abs(res.penalty - best) < 1e-9, (res.penalty, best)


def test_unequal_hold_together_is_rejected():
    d = demo()
    d.courses[1].hold_together, d.courses[3].hold_together = [3], [1]
    d.courses[3].lessons = 2
    d.placements = []
    assert solve(d, keep=False).status == "INVALID"


def test_hold_together_chain_is_rejected():
    d = demo()  # chain 1-3, 3-2 without 1-2 would let course 2 be placed apart from 3
    d.courses[1].hold_together, d.courses[3].hold_together, d.courses[2].hold_together = [3], [1, 2], [3]
    d.placements = []
    assert solve(d, keep=False).status == "INVALID"
    assert any("bad hold-together" in m for m in ops.audit(d))
    d = demo()
    ops.save_course(d, Course(1, "Math", 1, 1, 3, 25, hold_together=[3]))
    assert ops.trial(d, lambda x: ops.save_course(x, Course(2, x.courses[2].name, x.courses[2].ep_id,
                                                             x.courses[2].teacher_id, hold_together=[3])))


def test_solve_many_gives_valid_distinct_timetables():
    from octt.solver import solve_many
    d = demo()
    d.placements = []
    found = []
    rs = solve_many(d, keep=False, count=3, time_limit=5, found=found.append)
    assert len(rs) == len(found) >= 2 and all(r.ok for r in rs)
    for r in rs:
        out = applied(d, r)
        assert placement_problems(out) == [] and abs(r.penalty - total(score(out))) < 1e-9
        assert abs(sum(v for _, v in r.breakdown) - r.penalty) < 1e-9
    slots = [{(p.course_id, p.term, p.day) for p in r.placements} for r in rs]
    n = len(slots[0])
    assert all(len(a - b) >= max(1, round(n * 0.1)) for i, a in enumerate(slots) for b in slots[:i])


def test_locked_lessons_survive_a_solve_from_scratch():
    d = demo()
    d.placements = [Placement(1, 3, 2, 1, locked=True), Placement(3, 0, 0, 1)]
    res = solve(d, keep=False, time_limit=10)
    assert res.ok and res.removes == [Placement(3, 0, 0, 1)]
    out = applied(d, res)
    assert Placement(1, 3, 2, 1, locked=True) in out.placements and ops.audit(out) == []
    assert sum(p.course_id == 1 for p in out.placements) == 3


def test_unsat_core_names_the_lessons_that_clash():
    d = Document(days=["Mon"], terms=["1", "2"])
    d.epgs[1], d.eps[1] = Epg(1, "G"), Ep(1, "A", 1)
    d.teachers[1], d.teachers[2], d.teachers[3] = Teacher(1, "T1", {(0, 0)}), Teacher(2, "T2", {(0, 0)}), Teacher(3, "T3")
    d.rooms[1] = Room(1, "R", 30)
    d.courses[1] = Course(1, "Xray", 1, 1, 1, 5)  # both can only meet in period 2, same class
    d.courses[2] = Course(2, "Yacht", 1, 2, 1, 5)
    res = solve(d, keep=False, time_limit=5)
    assert res.status == "INFEASIBLE" and "Xray" in res.message and "Yacht" in res.message, res.message


def test_overloaded_teacher_and_room_are_named():
    d = demo()
    d.placements = []
    d.courses[1].lessons, d.courses[3].lessons = 20, 14  # Ada teaches both: 34 lessons, 30 slots
    res = solve(d, keep=False)
    assert res.status == "INFEASIBLE" and "Ada Lovelace" in res.message and "free slot" in res.message
    d = demo()
    d.placements = []
    d.rooms[1].blocked = {(t, dd) for t in range(6) for dd in range(5)}  # R101 never free: only the Lab (12 seats) is left
    res = solve(d, keep=False)
    assert res.status == "INFEASIBLE" and "no free room fits" in res.message


def test_identical_rooms_are_interchangeable_but_a_block_keeps_one_room():
    d = Document(days=["Mon", "Tue"], terms=["1", "2", "3"])
    d.epgs[1] = Epg(1, "G")
    for e in (1, 2, 3):
        d.eps[e] = Ep(e, f"C{e}", 1)
        d.teachers[e] = Teacher(e, f"T{e}")
        d.courses[e] = Course(e, f"X{e}", e, e, lessons=2, students=10)
    for r in (1, 2, 3):
        d.rooms[r] = Room(r, f"R{r}", 30)
    res = solve(d, keep=False, time_limit=10, params={"teacher_days": 1})
    out = applied(d, res)
    assert res.ok and res.penalty == 0 and placement_problems(out) == []
    for c in (1, 2, 3):
        assert len({p.room_id for p in out.placements if p.course_id == c}) == 1, "a 2-lesson block must stay in one room"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
