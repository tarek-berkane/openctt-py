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
    assert d.params == {"teacher_days": 4} and PARAMS["teacher_days"] == 1


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
