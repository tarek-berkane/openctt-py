"""Pixel-level checks of the live drag feedback: green = drop allowed, red = refused."""
import warnings

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent

from octt.demo import demo
from octt.model import Placement
from octt.ui.grid import MIME, no_entry
from tests.test_window import _KEEP, cell_pos, mime, pick_class, window

warnings.filterwarnings("ignore", category=DeprecationWarning)


def avg(w, row, col):
    """Mean RGB of a strip along the cell's lower-left corner (clear of blocks, icons and reason text)."""
    w.grid.viewport().repaint()
    img = w.grid.viewport().grab().toImage()
    r = w.grid.visualRect(w.grid.model().index(row, col))
    px = [img.pixelColor(r.left() + 6 + i, r.bottom() - 10) for i in range(0, max(r.width() - 40, 10), 2)]
    return tuple(sum(c.getRgb()[k] for c in px) / len(px) for k in range(3))


def edge(w, row, col):
    """Mean RGB just inside the cell's left border, where the hover frame is painted."""
    w.grid.viewport().repaint()
    img = w.grid.viewport().grab().toImage()
    r = w.grid.visualRect(w.grid.model().index(row, col))
    px = [img.pixelColor(r.left() + dx, y) for dx in (1, 2) for y in range(r.top() + 20, r.bottom() - 20, 2)]
    return tuple(sum(c.getRgb()[k] for c in px) / len(px) for k in range(3))


def greenness(c):
    return c[1] - c[0]


def redness(c):
    return c[0] - c[1]


def hover(w, row, col):
    ev = QDragMoveEvent(cell_pos(w.grid, row, col).toPoint(), Qt.MoveAction, mime(3), Qt.LeftButton, Qt.NoModifier)
    w.grid.dragMoveEvent(ev)
    return ev


def start(w, cid=3, src=None):
    w.grid.drag_begin.emit(cid, src)  # what _start_drag does first
    return w


def test_before_a_drag_cells_are_neutral():
    w = window(demo())
    pick_class(w, 2)
    base = avg(w, 1, 2)
    assert abs(greenness(base)) < 4 and abs(redness(base)) < 4  # white / grey, no colour cast


def test_valid_cells_turn_green_and_refused_cells_red_as_soon_as_the_drag_starts():
    w = window(demo())
    pick_class(w, 2)
    base_ok, base_bad = avg(w, 1, 2), avg(w, 0, 0)
    start(w)  # dragging Math 5B: Ada already teaches Mon/1 (the demo's only placed lesson)
    assert greenness(avg(w, 1, 2)) > greenness(base_ok) + 12  # Tue.. free cell: green wash
    assert redness(avg(w, 0, 0)) > redness(base_bad) + 12  # Mon/1: red wash
    assert redness(avg(w, 0, 0)) > 4 and greenness(avg(w, 1, 2)) > 8


def test_hovering_strengthens_the_colour_and_shows_the_reason_in_the_cell_and_status_bar():
    w = window(demo())
    pick_class(w, 2)
    start(w)
    calm_ok, calm_bad = edge(w, 4, 2), edge(w, 0, 0)
    ev = hover(w, 4, 2)
    assert ev.isAccepted() and w.grid.dnd.hover == (4, 2)
    assert greenness(edge(w, 4, 2)) > greenness(calm_ok) + 25  # solid green frame vs the resting dashes
    ev = hover(w, 0, 0)
    assert not ev.isAccepted() and w.grid.dnd.hover == (0, 0)
    assert redness(edge(w, 0, 0)) > redness(calm_bad) + 50  # solid red frame
    assert "already teaching" in w.statusBar().currentMessage()
    assert w.grid.dnd.bad[0, 0][0].endswith("already teaching")  # the text the cell paints
    assert greenness(edge(w, 4, 2)) <= greenness(calm_ok) + 1  # the cell we left went back to resting


def test_leaving_the_grid_or_ending_the_drag_clears_everything():
    w = window(demo())
    pick_class(w, 2)
    base = avg(w, 1, 2)
    start(w)
    hover(w, 0, 0)
    w.grid.dragLeaveEvent(QDragLeaveEvent())
    assert w.grid.dnd.hover is None
    w.grid.drag_end.emit()  # window.refresh runs
    assert w.grid.dnd is None and w.grid.bad == {}
    now = avg(w, 1, 2)
    assert abs(greenness(now) - greenness(base)) < 4 and abs(redness(avg(w, 0, 0))) < 4


def test_a_cell_is_never_green_and_refused_at_once():
    w = window(demo())
    pick_class(w, 2)
    start(w)
    for slot in [(t, d) for t in range(6) for d in range(5)]:
        refused = slot in w.grid.dnd.bad
        ev = hover(w, *slot)
        assert ev.isAccepted() != refused, slot  # what is painted == what the drop will do


def test_moving_a_lesson_marks_its_origin_and_offers_the_list_as_a_target():
    w = window(demo())
    pick_class(w, 1)
    assert not w.todo.target
    start(w, cid=1, src=(0, 0))  # lifting Math 5A from Mon/1
    assert w.grid.dnd.src == (0, 0) and (0, 0) not in w.grid.dnd.bad  # its own cell is never "refused"
    assert w.todo.target and not w.todo.hover
    w.todo.dragEnterEvent(QDragEnterEvent(w.todo.rect().center(), Qt.MoveAction, mime(1, (0, 0)), Qt.LeftButton, Qt.NoModifier))
    assert w.todo.hover
    w.grid.drag_end.emit()
    assert not w.todo.target and not w.todo.hover


def test_dragging_from_the_list_does_not_make_the_list_a_target():
    w = window(demo())
    pick_class(w, 2)
    start(w, cid=3, src=None)
    assert not w.todo.target and w.grid.dnd.src is None


def test_refused_drop_does_nothing_and_valid_drop_places():
    w = window(demo())
    pick_class(w, 2)
    start(w)
    from tests.test_window import drop
    n = len(w.doc.placements)
    drop(w, w.grid, 3, None, 0, 0)  # refused cell
    assert len(w.doc.placements) == n
    drop(w, w.grid, 3, None, 4, 2)
    assert len(w.doc.placements) == n + 1


def test_no_entry_cursor_is_a_red_disc():
    pm = no_entry(28)
    c = pm.toImage().pixelColor(14, 6)  # inside the disc, above the white bar
    assert not pm.isNull() and c.red() > 180 and c.green() < 110 and c.alpha() == 255


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
