import json
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from octt import io
from octt.commands import StateEdit, snapshot
from octt.demo import demo
from octt.model import Placement
from octt.rules.soft import PARAMS, score, total
from octt.solver import solve
from octt.ui.dialogs import SettingsDialog

APP = QApplication.instance() or QApplication([])


def late_start_doc():
    d = demo()
    d.placements = [Placement(1, 1, 0, 1)]  # 5A starts at period 2
    return d


def test_document_settings_drive_the_score():
    d = late_start_doc()
    assert total(score(d)) == 1
    d.weights["student_start"] = 4.0
    assert total(score(d)) == 4.0
    d.params["student_start"] = 2  # period 2 is now the preferred start
    assert score(d) == []


def test_weight_zero_switches_a_constraint_off():
    d = late_start_doc()
    d.weights["student_start"] = 0
    assert score(d) == []


def test_solver_uses_document_settings():
    d = demo()
    d.placements = []
    d.params = {"teacher_days": 5, "teacher_daily": 6, "teacher_continuous": 6}
    assert solve(d, keep=False, time_limit=10).penalty == 0  # with the odd default (1 day) this is 1+


def test_settings_roundtrip_through_json_and_old_files_load():
    d = demo()
    d.params, d.weights = {"student_gaps": 2}, {"course_blocks": 3.0}
    p = Path(tempfile.mkdtemp()) / "s.json"
    io.save(d, p)
    assert io.load(p) == d
    import json
    raw = json.loads(p.read_text())
    del raw["params"], raw["weights"]
    p.write_text(json.dumps(raw))
    assert io.load(p).params == {}


def test_failed_save_keeps_the_old_file():
    p = Path(tempfile.mkdtemp()) / "s.json"
    io.save(demo(), p)
    before = p.read_text()
    real, io.os.replace = io.os.replace, lambda *a: (_ for _ in ()).throw(OSError("disk full"))
    try:
        d = demo()
        d.institution = "changed"
        io.save(d, p)
        raise AssertionError("save should have failed")
    except OSError:
        pass
    finally:
        io.os.replace = real
    assert p.read_text() == before and list(p.parent.iterdir()) == [p]  # old content, no .tmp left behind


def test_old_files_keep_their_days_limits_where_they_can_apply():
    p = Path(tempfile.mkdtemp()) / "s.json"
    io.save(demo(), p)
    assert io.load(p).params == {}  # new file: lessons allowed every school day
    raw = json.loads(p.read_text())
    del raw["version"]  # as written before format 2: the old defaults (teachers 1, students 6) were not stored
    p.write_text(json.dumps(raw))
    d = io.load(p)
    assert d.params == {"teacher_days": 1}  # students' 6 can never apply in a 5-day week: not written in
    assert total(score(d)) == total(score(d, params={"teacher_days": 1, "student_days": 6}))  # scores as before
    io.save(d, p)
    assert io.load(p).params == {"teacher_days": 1}  # stays once re-saved in the new format
    raw["days"] = [*raw["days"], "Sat", "Sun"]
    p.write_text(json.dumps(raw))
    assert io.load(p).params == {"teacher_days": 1, "student_days": 6}  # in a 7-day week it can


def test_dialog_returns_only_differences_and_resets():
    d = demo()
    dlg = SettingsDialog(None, d)
    assert dlg.values() == ({}, {})
    dlg.limit["teacher_days"].setValue(3)
    dlg.weight["student_gaps"].setValue(2.5)
    assert dlg.values() == ({"teacher_days": 3}, {"student_gaps": 2.5})
    dlg.load({}, {})
    assert dlg.values() == ({}, {})
    dlg2 = SettingsDialog(None, type(d)(params={"student_gaps": 1}, weights={"student_days": 0.0}))
    assert dlg2.limit["student_gaps"].value() == 1 and dlg2.weight["student_days"].value() == 0
    assert dlg2.limit["student_start"].maximum() == len(d.terms)


def test_settings_change_is_undoable():
    from PySide6.QtGui import QUndoStack
    d, s = demo(), QUndoStack()
    before = snapshot(d)
    d.params = {"teacher_days": 4}
    s.push(StateEdit(d, before, snapshot(d), "settings", lambda: None))
    s.undo()
    assert d.params == {}
    s.redo()
    assert d.params == {"teacher_days": 4} and PARAMS["teacher_days"] == 7


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
