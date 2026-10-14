"""Paste from a spreadsheet: each row is added, skipped as already there, or refused with a reason."""
from octt import ops
from octt.demo import demo
from octt.model import Epg
from octt.paste import paste, split


def notes(rows):
    return [(r.added, r.error) for r in rows]


def test_spreadsheet_rows_split_on_tabs_and_typed_rows_on_commas():
    assert split("R1\t30\nR2\t12\n\n", 2) == [["R1", "30"], ["R2", "12"]]
    assert split("R1, 30", 2) == [["R1", "30"]]
    assert split("Smith, John", 1) == [["Smith, John"]]  # one column: the comma is part of the name


def test_rooms_need_whole_seats_and_existing_ones_are_skipped():
    d = demo()
    rows = paste(d, "room", "Name\tSeats\nR201\t28\nlab\t12\nGym\t\nAula\tlots")
    assert notes(rows) == [(True, False), (False, False), (False, True), (False, True)]  # header row dropped
    assert any(r.name == "R201" and r.capacity == 28 for r in d.rooms.values()) and not ops.audit(d)


def test_classes_find_or_create_their_group():
    d = demo()
    rows = paste(d, "ep", "5C\n6A\tGrade 6\n6B\tgrade 6\n5A\tGrade 5")
    assert notes(rows) == [(True, False), (True, False), (True, False), (False, False)]
    assert "Grade 6" in rows[1].note and [g.name for g in d.epgs.values()] == ["Grade 5", "Grade 6"]
    d.epgs[9] = Epg(9, "Grade 7")
    assert paste(d, "ep", "7A")[0].error  # several groups: the group column is needed


def test_courses_create_missing_teachers_once_and_need_a_known_class():
    d = demo()
    n = len(d.teachers)
    rows = paste(d, "course", "Art\t5A\tFrida Kahlo\t2\nArt\t5B\tfrida kahlo\t2\t20\nMusic\t9Z\tAda Lovelace\nMath\t5A\tAda Lovelace\n"
                              "Gym\t5A\tAda Lovelace\tzero")
    assert notes(rows) == [(True, False), (True, False), (False, True), (False, False), (False, True)]
    assert "Frida Kahlo" in rows[0].note and len(d.teachers) == n + 1  # second row reuses the new teacher
    art = [c for c in d.courses.values() if c.name == "Art"]
    assert [(c.lessons, c.students) for c in art] == [(2, 0), (2, 20)] and not ops.audit(d)


def test_pasting_twice_adds_nothing_the_second_time():
    d = demo()
    text = "Grace Hopper\nAlan Turing\n\nKatherine Johnson"
    assert sum(r.added for r in paste(d, "teacher", text)) == 2
    assert sum(r.added for r in paste(d, "teacher", text)) == 0


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_"):
            fn()
            print("ok", n)
