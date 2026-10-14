"""Availability grid: click, drag a rectangle, flip a day / period, keyboard, all / none, right-to-left."""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from octt.demo import demo
from octt.ui.dialogs import TeacherEditor
from octt.ui.slots import Slots

APP = QApplication.instance() or QApplication([])


def make(blocked=(), rtl=False):
    s = Slots(demo(), set(blocked))  # 6 periods x 5 days
    if rtl:
        s.setLayoutDirection(Qt.RightToLeft)
    s.show()
    s.grid.resize(s.grid.sizeHint())
    return s


def at(s, t, d) -> QPoint:
    return s.grid._rect(t, d).center()


def drag(s, a, b):
    g = s.grid
    QTest.mousePress(g, Qt.LeftButton, Qt.NoModifier, at(s, *a))
    QTest.mouseMove(g, at(s, *b))
    QTest.mouseRelease(g, Qt.LeftButton, Qt.NoModifier, at(s, *b))


def test_click_toggles_one_period_and_says_so():
    s = make()
    seen = []
    s.changed.connect(lambda: seen.append(1))
    QTest.mouseClick(s.grid, Qt.LeftButton, Qt.NoModifier, at(s, 2, 1))
    assert s.blocked() == {(2, 1)} and seen and s.count.text().startswith("29 ")
    QTest.mouseClick(s.grid, Qt.LeftButton, Qt.NoModifier, at(s, 2, 1))
    assert s.blocked() == set()


def test_drag_paints_a_rectangle_with_the_first_cells_opposite():
    s = make(blocked={(0, 0)})
    drag(s, (0, 1), (1, 3))  # (0,1) was available: the drag blocks Tue-Thu, periods 1-2
    assert s.blocked() == {(0, 0)} | {(t, d) for t in (0, 1) for d in (1, 2, 3)}
    drag(s, (0, 0), (1, 1))  # starts on a blocked cell: makes the rectangle available again
    assert s.blocked() == {(t, d) for t in (0, 1) for d in (2, 3)}


def test_shrinking_a_drag_restores_what_it_left():
    s = make()
    g = s.grid
    QTest.mousePress(g, Qt.LeftButton, Qt.NoModifier, at(s, 0, 0))
    QTest.mouseMove(g, at(s, 3, 3))
    QTest.mouseMove(g, at(s, 1, 0))
    QTest.mouseRelease(g, Qt.LeftButton, Qt.NoModifier, at(s, 1, 0))
    assert s.blocked() == {(0, 0), (1, 0)}


def test_headers_flip_a_whole_day_or_period():
    s = make(blocked={(0, 4)})
    QTest.mouseClick(s.grid, Qt.LeftButton, Qt.NoModifier, at(s, None, 4))  # Friday, mostly free: blocked
    assert s.blocked() == {(t, 4) for t in range(6)}
    QTest.mouseClick(s.grid, Qt.LeftButton, Qt.NoModifier, at(s, 5, None))  # last period, mostly free: blocked
    assert s.blocked() == {(t, 4) for t in range(6)} | {(5, d) for d in range(5)}
    QTest.mouseClick(s.grid, Qt.LeftButton, Qt.NoModifier, at(s, None, 4))  # Friday, all blocked: free again
    assert s.blocked() == {(5, d) for d in range(4)}


def test_all_and_none():
    s = make(blocked={(1, 1)})
    s.none_btn.click()
    assert len(s.blocked()) == 30 and not s.none_btn.isEnabled() and s.all_btn.isEnabled()
    s.all_btn.click()
    assert s.blocked() == set() and not s.all_btn.isEnabled()


def test_keyboard_moves_and_toggles():
    s = make()
    g = s.grid
    g.setFocus()
    for key in (Qt.Key_Down, Qt.Key_Down, Qt.Key_Right, Qt.Key_Space):
        QTest.keyClick(g, key)
    assert s.blocked() == {(2, 1)}
    QTest.keyClick(g, Qt.Key_Up)
    QTest.keyClick(g, Qt.Key_Up)
    QTest.keyClick(g, Qt.Key_Up)  # stops at the edge
    assert g.cur == (0, 1)


def test_right_to_left_mirrors_days_and_arrow_keys():
    s = make(rtl=True)
    g = s.grid
    assert g._rect(0, 0).left() > g._rect(0, 4).left()  # Monday on the right
    assert g._rect(0, None).left() > g._rect(0, 0).left()  # period labels to the right of the week
    QTest.mouseClick(g, Qt.LeftButton, Qt.NoModifier, at(s, 3, 0))
    assert s.blocked() == {(3, 0)}  # the click hit the cell drawn there
    g.setFocus()
    g.cur = (0, 0)
    QTest.keyClick(g, Qt.Key_Left)  # left = towards Tuesday when the week runs right to left
    assert g.cur == (0, 1)


def test_editing_the_grid_marks_the_form_changed():
    d = demo()
    e = TeacherEditor(d, d.teachers[1])
    seen = []
    e.changed(lambda *_: seen.append(1))
    base = e.result()
    e.slots.grid.set_all(False)
    assert seen and e.result() != base and len(e.result().blocked) == 30


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
