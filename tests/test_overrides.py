import copy
import tempfile
from itertools import combinations, product
from pathlib import Path

from PySide6.QtWidgets import QApplication

from octt import io, ops
from octt.demo import demo
from octt.model import Course, Document, Ep, Epg, Placement, Room, Teacher
from octt.rules.soft import score, total
from octt.solver import solve
from octt.ui.dialogs import BlocksEditor, CourseDialog, EpDialog, Limits, TeacherDialog

APP = QApplication.instance() or QApplication([])


def keys(d):
    return sorted((p.key, p.subject) for p in score(d))


def test_teacher_override_replaces_global_limit_for_that_teacher_only():
    d = demo()
    d.placements = [Placement(1, 0, 0, 1), Placement(3, 0, 1, 1), Placement(2, 0, 0, 2)]  # Ada Mon+Tue, Alan Mon
    assert ("teacher_days", "Ada Lovelace") in keys(d)
    d.teachers[1].limits = {"teacher_days": 2}
    assert ("teacher_days", "Ada Lovelace") not in keys(d)
    d.params = {"teacher_days": 0}  # global now strict: Alan (no override) is flagged, Ada still is not
    assert ("teacher_days", "Alan Turing") in keys(d) and ("teacher_days", "Ada Lovelace") not in keys(d)


def test_class_override_only_affects_that_class():
    d = demo()
    d.placements = [Placement(1, 1, 0, 1), Placement(3, 1, 1, 2)]  # both classes start at period 2
    assert [k for k in keys(d) if k[0] == "student_start"] == [("student_start", "5A"), ("student_start", "5B")]
    d.eps[1].limits = {"student_start": 2}
    assert [k for k in keys(d) if k[0] == "student_start"] == [("student_start", "5B")]


def test_course_blocks_override():
    d = demo()
    split = [Placement(1, 0, 0, 1), Placement(1, 1, 0, 1), Placement(1, 0, 2, 1)]
    d.placements = split
    assert ("course_blocks", "Math") in keys(d)
    d.courses[1].blocks = [1, 1, 3]  # blocks of any size, 1..3 days
    assert ("course_blocks", "Math") not in keys(d)


def test_audit_rejects_bad_overrides():
    d = demo()
    for mutate in (lambda x: x.teachers[1].limits.update(student_gaps=1),  # wrong kind of key
                   lambda x: x.eps[1].limits.update(student_start=99),
                   lambda x: x.eps[1].limits.update(student_days=-1),
                   lambda x: setattr(x.courses[1], "blocks", [2, 3, 1]),
                   lambda x: setattr(x.courses[1], "blocks", [0, 1, 1])):
        assert ops.trial(d, mutate), mutate


def test_brute_force_optimum_with_overrides():
    d = Document(days=["Mon", "Tue"], terms=["1", "2", "3", "4"])
    d.epgs[1], d.eps[1] = Epg(1, "G"), Ep(1, "A", 1, limits={"student_gaps": 0, "student_start": 3})
    d.teachers[1] = Teacher(1, "T1", limits={"teacher_continuous": 1, "teacher_days": 2})
    d.teachers[2] = Teacher(2, "T2")
    d.rooms[1], d.rooms[2] = Room(1, "R1", 30), Room(2, "R2", 30)
    d.courses[1] = Course(1, "X", 1, 1, lessons=2, students=10, blocks=[1, 1, 2])
    d.courses[2] = Course(2, "Y", 1, 2, lessons=3, students=10)
    d.params = {"teacher_days": 1, "teacher_continuous": 3, "student_continuous": 2, "student_daily": 3,
                "student_start": 1, "student_gaps": 2}
    cells = [(t, dd) for t in range(4) for dd in range(2)]
    best = None
    for sx, sy in product(combinations(cells, 2), combinations(cells, 3)):
        if set(sx) & set(sy):
            continue
        for rx, ry in product(product((1, 2), repeat=2), product((1, 2), repeat=3)):
            d.placements = [Placement(1, t, dd, r) for (t, dd), r in zip(sx, rx)] + \
                           [Placement(2, t, dd, r) for (t, dd), r in zip(sy, ry)]
            v = total(score(d))
            best = v if best is None else min(best, v)
    d.placements = []
    res = solve(d, keep=False, time_limit=30)
    assert res.status == "OPTIMAL" and abs(res.penalty - best) < 1e-9, (res.penalty, best)


def test_overrides_survive_json_and_old_files_load():
    d = demo()
    d.teachers[1].limits = {"teacher_days": 3}
    d.eps[1].limits = {"student_gaps": 1}
    d.courses[1].blocks = [1, 1, 3]
    p = Path(tempfile.mkdtemp()) / "o.json"
    io.save(d, p)
    assert io.load(p) == d
    import json
    raw = json.loads(p.read_text())
    for t in raw["teachers"].values(): del t["limits"]
    for e in raw["eps"].values(): del e["limits"]
    for c in raw["courses"].values(): del c["blocks"]
    p.write_text(json.dumps(raw))
    old = io.load(p)
    assert old.teachers[1].limits == {} and old.courses[1].blocks is None


def test_dialogs_edit_overrides():
    d = demo()
    lim = Limits(d, ("teacher_days", "teacher_daily"), {"teacher_days": 3})
    assert lim.value() == {"teacher_days": 3}
    lim.rows["teacher_daily"][0].setChecked(True)
    assert lim.value() == {"teacher_days": 3, "teacher_daily": PARAMS_DAILY()}

    dlg = TeacherDialog(None, d, d.teachers[1])
    dlg.limits.rows["teacher_continuous"][0].setChecked(True)
    dlg.limits.rows["teacher_continuous"][1].setValue(2)
    dlg.accept()
    assert dlg.entity.limits == {"teacher_continuous": 2}

    ed = EpDialog(None, d, d.eps[1])
    ed.name.setText("5A+")
    ed.limits.rows["student_start"][0].setChecked(True)
    ed.limits.rows["student_start"][1].setValue(2)
    ed.accept()
    assert ed.entity.name == "5A+" and ed.entity.limits == {"student_start": 2} and ed.entity.epg_id == 1

    cd = CourseDialog(None, d, d.courses[1])
    assert cd.blocks.value() is None
    cd.blocks.on.setChecked(True)
    cd.blocks.spins[1].setValue(3)  # min blocks 3 > max blocks 1 -> rejected inside the dialog
    cd.accept()
    assert cd.entity is None and "lesson blocks" in cd.err.text()
    cd.blocks.spins[2].setValue(3)
    cd.accept()
    assert cd.entity.blocks == [3, 3, 3]
    assert BlocksEditor(3, None).value() is None


def PARAMS_DAILY():
    from octt.rules.soft import PARAMS
    return PARAMS["teacher_daily"]


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
