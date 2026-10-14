# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Add many groups / classes / teachers / rooms / courses from rows copied out of a spreadsheet (no Qt).

paste() adds to the document it is given and reports each row, so the same call previews (on a copy) and applies.
Rows that already exist are skipped, so pasting the same list twice adds nothing the second time."""
from dataclasses import dataclass

from octt.i18n import N_, t as tr
from octt.model import Course, Document, Ep, Epg, Room, Teacher
from octt.ops import next_id

# kind -> columns, in the order they are pasted. Only the name is required, except where noted below.
COLUMNS = {
    "epg": (N_("Name"),),
    "ep": (N_("Name"), N_("Group")),
    "teacher": (N_("Name"),),
    "room": (N_("Name"), N_("Seats")),
    "course": (N_("Name"), N_("Class"), N_("Teacher"), N_("Lessons/week"), N_("Students"), N_("Sub-group")),
}


@dataclass
class Row:
    cells: list[str]
    note: str  # what was done, or why not
    added: bool
    error: bool  # False with added=False: skipped on purpose (already there)


class Exists(ValueError):
    pass


def split(text: str, columns: int) -> list[list[str]]:
    """Spreadsheets copy as tab-separated lines. Typed by hand, ';' or ',' work too (',' only with several columns,
    so 'Smith, John' stays one teacher)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    sep = "\t" if "\t" in text else ";" if ";" in text else "," if columns > 1 else None
    return [[c.strip() for c in (ln.split(sep) if sep else [ln])] for ln in lines]


def _key(s: str) -> str:
    return s.strip().casefold()  # how audit() compares names


def _find(rows: dict, name: str) -> list:
    return [x for x in rows.values() if _key(x.name) == _key(name)]


def _int(value: str, column: str, default: int | None = None, low: int = 0) -> int:
    if not value and default is not None:
        return default
    if not value.isdigit() or int(value) < low:
        raise ValueError(tr("{column}: '{value}' is not a whole number of at least {n}", column=tr(column), value=value, n=low))
    return int(value)


def _name(name: str) -> str:
    if not name:
        raise ValueError(tr("the name is empty"))
    return name


def _group(doc, name):
    name = _name(name)
    if _find(doc.epgs, name):
        raise Exists(tr("already exists"))
    g = next_id(doc.epgs)
    doc.epgs[g] = Epg(g, name)
    return tr("added")


def _class(doc, name, group):
    name, note = _name(name), tr("added")
    if group:
        found = _find(doc.epgs, group)
        if not found:
            g = next_id(doc.epgs)
            doc.epgs[g] = Epg(g, group)
            found, note = [doc.epgs[g]], tr("added, with new group {name}", name=group)
    elif len(doc.epgs) == 1:
        found = list(doc.epgs.values())
    else:
        raise ValueError(tr("which group? There are several"))
    g = found[0].id
    if any(e.epg_id == g and _key(e.name) == _key(name) for e in doc.eps.values()):
        raise Exists(tr("already exists"))
    e = next_id(doc.eps)
    doc.eps[e] = Ep(e, name, g)
    return note


def _teacher(doc, name):
    name = _name(name)
    if _find(doc.teachers, name):
        raise Exists(tr("already exists"))
    t = next_id(doc.teachers)
    doc.teachers[t] = Teacher(t, name)
    return tr("added")


def _room(doc, name, seats):
    name = _name(name)
    if not seats:
        raise ValueError(tr("{column} is missing", column=tr("Seats")))
    seats = _int(seats, N_("Seats"), low=1)
    if _find(doc.rooms, name):
        raise Exists(tr("already exists"))
    r = next_id(doc.rooms)
    doc.rooms[r] = Room(r, name, seats)
    return tr("added")


def _course(doc, name, cls, teacher, lessons, students, group):
    name, note = _name(name), tr("added")
    eps = _find(doc.eps, cls)
    if not eps:
        raise ValueError(tr("no class called '{name}'", name=cls))
    if len(eps) > 1:
        raise ValueError(tr("several classes are called '{name}'", name=cls))
    lessons, students = _int(lessons, N_("Lessons/week"), 1, low=1), _int(students, N_("Students"), 0)
    if not teacher:
        raise ValueError(tr("{column} is missing", column=tr("Teacher")))
    e = eps[0].id
    if any(c.ep_id == e and _key(c.name) == _key(name) and _key(c.group) == _key(group) for c in doc.courses.values()):
        raise Exists(tr("already exists"))
    ts = _find(doc.teachers, teacher)
    if not ts:  # typing the teacher once in the course list is the point; the note shows it, so typos are visible
        t = next_id(doc.teachers)
        doc.teachers[t] = Teacher(t, teacher)
        ts, note = [doc.teachers[t]], tr("added, with new teacher {name}", name=teacher)
    c = next_id(doc.courses)
    doc.courses[c] = Course(c, name, e, ts[0].id, lessons=lessons, students=students, group=group)
    return note


ADD = {"epg": _group, "ep": _class, "teacher": _teacher, "room": _room, "course": _course}


def paste(doc: Document, kind: str, text: str) -> list[Row]:
    """Add every good row of `text` to `doc`; one Row per line, in order. A first line of column titles is skipped."""
    cols = COLUMNS[kind]
    rows = split(text, len(cols))
    if rows and _key(rows[0][0]) in {_key(cols[0]), _key(tr(cols[0]))}:
        rows = rows[1:]
    out = []
    for cells in rows:
        cells = (cells + [""] * len(cols))[:len(cols)]
        try:
            out.append(Row(cells, ADD[kind](doc, *cells), True, False))
        except Exists as e:
            out.append(Row(cells, str(e), False, False))
        except ValueError as e:
            out.append(Row(cells, str(e), False, True))
    return out
