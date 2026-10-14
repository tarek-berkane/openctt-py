"""Data manager: every kind can be listed, searched, added, edited, duplicated and deleted, all undoable."""
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from octt import io, ops
from octt.demo import demo
from octt.model import Room
from tests.test_window import patch, window

APP = QApplication.instance() or QApplication([])


def manager(doc=None):
    w = window(doc or io.load("examples/example_school.json"))
    w.manage()
    return w, w.manager


def row_of(page, id_):
    return next(r for r in range(page.table.rowCount()) if page.table.item(r, 0).data(0x0100) == id_)


def test_every_kind_is_listed_with_counts():
    w, m = manager()
    d = w.doc
    for kind, n in (("epg", len(d.epgs)), ("ep", len(d.eps)), ("teacher", len(d.teachers)), ("room", len(d.rooms)),
                    ("course", len(d.courses))):
        assert m.pages[kind].table.rowCount() == n
    assert m.tabs.tabText(2).endswith(f"({len(d.teachers)})")


def test_add_teacher_then_undo_from_the_main_window():
    w, m = manager()
    p = m.pages["teacher"]
    n = len(w.doc.teachers)
    p.add()
    assert not p.save_btn.isEnabled()  # nothing typed yet
    p.editor.name.setText("Grace Hopper")
    assert p.save_btn.isEnabled()
    assert p.save()
    assert len(w.doc.teachers) == n + 1 and p.table.rowCount() == n + 1
    assert w.doc.teachers[p.current].name == "Grace Hopper" and p.heading.text() == "Grace Hopper"
    w.undo.undo()
    assert len(w.doc.teachers) == n and p.table.rowCount() == n and p.editor is None  # the form went with it


def test_rename_group_and_move_class_to_another_group():
    w, m = manager()
    g = m.pages["epg"]
    g._picked(row_of(g, 1))
    g.editor.name.setText("Year 7")
    assert g.save() and w.doc.epgs[1].name == "Year 7"
    assert any(w.tree.topLevelItem(i).text(0) == "Year 7" for i in range(w.tree.topLevelItemCount()))
    c = m.pages["ep"]
    ep = next(e for e in w.doc.eps.values() if e.epg_id == 1)
    c._picked(row_of(c, ep.id))
    c.editor.epg.setCurrentIndex(c.editor.epg.findData(2))
    assert c.save() and w.doc.eps[ep.id].epg_id == 2


def test_duplicate_class_brings_its_courses_and_invites_a_rename():
    w, m = manager()
    p = m.pages["ep"]
    ep = next(iter(w.doc.eps.values()))
    p._picked(row_of(p, ep.id))
    before = len(w.doc.courses)
    p.duplicate()
    new = w.doc.eps[p.current]
    assert new.name == f"{ep.name} (2)" and new.epg_id == ep.epg_id
    assert len(w.doc.courses) - before == sum(c.ep_id == ep.id for c in w.doc.courses.values())
    assert p.editor.name.hasSelectedText()
    w.undo.undo()
    assert len(w.doc.courses) == before


def test_refused_delete_explains_and_allowed_delete_selects_the_neighbour():
    w, m = manager()
    p = m.pages["teacher"]
    p._picked(0)
    tid = p.current
    p.delete()
    assert tid in w.doc.teachers and "teaches" in p.err.text()
    r = m.pages["room"]
    idle = next(x.id for x in w.doc.rooms.values() if not any(q.room_id == x.id for q in w.doc.placements))
    r._picked(row_of(r, idle))
    r.delete()
    assert idle not in w.doc.rooms and r.current is not None and r.current in w.doc.rooms


def test_search_filters_rows():
    w, m = manager()
    p = m.pages["teacher"]
    p.search.setText("ada")
    shown = [p.table.item(r, 0).text() for r in range(p.table.rowCount()) if not p.table.isRowHidden(r)]
    assert shown == ["Ada Lovelace"]


def test_unsaved_changes_ask_before_switching():
    w, m = manager()
    p = m.pages["teacher"]
    p._picked(0)
    first = p.current
    p.editor.name.setText("Changed")
    undo = patch(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Cancel))
    try:
        p._picked(1)
    finally:
        undo()
    assert p.current == first and p.editor.name.text() == "Changed"  # stayed, edits kept
    undo = patch(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    try:
        p._picked(1)
    finally:
        undo()
    assert p.current != first and w.doc.teachers[first].name != "Changed"


def test_show_timetable_and_open_from_the_main_window():
    w, m = manager()
    p = m.pages["teacher"]
    p._picked(2)
    p.show_timetable()
    assert w.view == ("teacher", p.current)
    w.manage("room", 3)
    assert m.tabs.currentWidget() is m.pages["room"] and m.pages["room"].current == 3


def test_opening_another_file_resets_the_manager():
    w, m = manager()
    m.pages["teacher"].add()
    w.load(demo())
    assert m.pages["teacher"].table.rowCount() == len(w.doc.teachers) and m.pages["teacher"].editor is None


def test_paste_list_previews_then_adds_in_one_undo_step():
    from octt.ui.manage import PasteDialog
    w, m = manager()
    p = m.pages["room"]
    n = len(w.doc.rooms)
    dlg = PasteDialog(p, "Name\tSeats\nR901\t30\nR902\t20\nR903\tmany")
    ok = dlg.box.button(QDialogButtonBox.Ok)
    assert dlg.preview.rowCount() == 3 and ok.isEnabled() and ok.text().endswith("2")
    assert len(w.doc.rooms) == n  # the preview ran on a copy
    dlg.accept()
    assert len(w.doc.rooms) == n + 2 and p.table.rowCount() == n + 2
    w.undo.undo()
    assert len(w.doc.rooms) == n


def test_select_several_rows_and_delete_them_together_or_not_at_all():
    w, m = manager()
    p = m.pages["room"]
    for i in range(3):
        w.doc.rooms[900 + i] = Room(900 + i, f"Spare {i}", 10)
    m.reload(force=True)
    t = p.table

    def pick(*ids):  # what Ctrl+click does
        t.clearSelection()
        for i in ids:
            t.selectionModel().select(t.model().index(row_of(p, i), 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)

    pick(900, 901, 902)
    assert sorted(p.selected()) == [900, 901, 902] and p.del_btn.text().endswith("(3)")
    undo = patch(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    try:
        p.delete()
        assert not {900, 901, 902} & set(w.doc.rooms)
        w.undo.undo()  # one step brings all three back
        assert {900, 901, 902} <= set(w.doc.rooms)
        busy = next(iter(w.doc.placements)).room_id  # a room holding lessons cannot go, so none go
        pick(900, busy)
        p.delete()
    finally:
        undo()
    assert {900, busy} <= set(w.doc.rooms) and "holds placed lessons" in p.err.text()


def test_duplicate_group_brings_its_classes_and_courses():
    w, m = manager()
    g = m.pages["epg"]
    gid = next(iter(w.doc.epgs))
    eps = [e for e in w.doc.eps.values() if e.epg_id == gid]
    courses = len(w.doc.courses)
    g._picked(row_of(g, gid))
    g.duplicate()
    new = g.current
    assert w.doc.epgs[new].name.endswith("(2)")
    assert sorted(e.name for e in w.doc.eps.values() if e.epg_id == new) == sorted(e.name for e in eps)
    added = len(w.doc.courses) - courses
    assert added == sum(c.ep_id in {e.id for e in eps} for c in list(w.doc.courses.values())[:courses])
    assert not ops.audit(w.doc)


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
