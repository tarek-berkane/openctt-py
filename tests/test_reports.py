import re
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from octt import reports
from octt.demo import demo
from octt.model import Placement
from octt.pdf import write_pdf
from octt.ui.report_dialog import ReportDialog

APP = QApplication.instance() or QApplication([])


def full_demo():
    d = demo()  # Math 5A at Mon/1; add the rest by hand
    d.placements += [Placement(1, 1, 0, 1), Placement(1, 2, 0, 1),
                     Placement(2, 0, 3, 2), Placement(2, 1, 3, 2),
                     Placement(3, 0, 1, 1), Placement(3, 1, 1, 1), Placement(3, 2, 1, 1)]
    return d


def tmp(name="r.pdf"):
    return str(Path(tempfile.mkdtemp()) / name)


def pages_in(path):
    return len(re.findall(rb"/Type\s*/Page\b", Path(path).read_bytes()))


def test_class_page_shows_lessons_teacher_room_and_unplaced():
    d = demo()  # only Math 5A at (0,0) placed; Math x2 and CS x2 still open
    (p5a, p5b) = reports.class_pages(d)
    assert "5A" in p5a.title and "Math" in p5a.body and "Ada Lovelace" in p5a.body and "R101" in p5a.body
    assert "Not yet placed" in p5a.body and "Math ×2" in p5a.body and "CS A ×2" in p5a.body
    assert "Math" not in p5b.body.split("Not yet placed")[0]  # 5B's grid is empty


def test_entity_filter_and_other_views():
    d = full_demo()
    assert len(reports.build(d, "Class timetables")) == 2 and len(reports.build(d, "Class timetables", 2)) == 1
    t = reports.build(d, "Teacher timetables", 2)[0]
    assert "Alan Turing" in t.title and "CS A" in t.body and "Math" not in t.body
    r = reports.build(d, "Room timetables", 2)[0]  # the lab holds only CS
    assert "Lab" in r.title and "CS A" in r.body and "Math" not in r.body


def test_master_has_one_page_per_day_and_html_is_escaped():
    d = full_demo()
    d.eps[1].name = "<5A> & co"
    pages = reports.build(d, "Master timetable (one page per day)")
    assert len(pages) == len(d.days) and "&lt;5A&gt; &amp; co" in pages[0].body and "<5A>" not in pages[0].body


def test_lists_count_hours():
    d = full_demo()
    hours = reports.teacher_hours(d)[0].body
    assert re.search(r"Ada Lovelace</b></td>.*?<b>6</b>", hours.replace("\n", ""))  # 3 + 3 distinct slots
    rooms = reports.room_list(d)[0].body
    assert "R101" in rooms and "Lab" in rooms
    tl = reports.teacher_list(d)[0].body
    assert "6 lessons/week" in tl and "2 lessons/week" in tl


def test_pdf_pages_orientation_and_footer():
    d = full_demo()
    path = tmp()
    write_pdf(reports.build(d, "Class timetables"), path)
    assert Path(path).read_bytes()[:5] == b"%PDF-" and pages_in(path) == 2
    w = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", Path(path).read_bytes())
    assert float(w.group(1)) > float(w.group(2))  # landscape
    path2 = tmp()
    write_pdf(reports.build(d, "Teacher hours"), path2)
    w = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", Path(path2).read_bytes())
    assert float(w.group(1)) < float(w.group(2))  # portrait


def test_many_rows_flow_onto_extra_pages():
    d = full_demo()
    d.terms = [f"{h}:00" for h in range(7, 31)]  # 24 periods: one timetable no longer fits a page
    path = tmp()
    write_pdf(reports.build(d, "Class timetables", 1), path)
    assert pages_in(path) >= 2


def test_dialog_exports_selected_entity_and_defaults_to_current_class():
    d = full_demo()
    dlg = ReportDialog(None, d, ep_id=2)
    dlg.kind.setCurrentText("Class timetables")
    assert dlg.entity.currentData() == 2  # defaults to the class on screen
    dlg.export(tmp("c.pdf"))
    assert dlg.saved and pages_in(dlg.saved) == 1
    dlg = ReportDialog(None, d)
    dlg.kind.setCurrentText("Room list")
    assert not dlg.entity.isEnabled()
    dlg.export(tmp("rooms.pdf"))
    assert dlg.saved


def test_nothing_to_print_is_reported_not_crashing():
    from octt.model import Document
    dlg = ReportDialog(None, Document())
    dlg.kind.setCurrentText("Class timetables")
    dlg.export(tmp())
    assert dlg.saved is None and "Nothing" in dlg.msg.text()


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
