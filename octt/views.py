# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""What each timetable view (class / teacher / room) shows. Pure functions, no Qt."""
from octt.i18n import N_, menu_path, t as tr
from octt.model import Document, Placement, Slot
from octt.rules.hard import fits_room

PALETTE = ["#cfe8ff", "#ffe5b4", "#d5f5d0", "#f8d0e0", "#e2d4f5", "#fff3b0",
           "#c9f0ee", "#f6d6c4", "#dde6b8", "#d9d9f2", "#f2cfcf", "#cfe5d4"]
View = tuple[str, int]  # ("class" | "teacher" | "room", id)


def color(course_id: int) -> str:
    return PALETTE[course_id % len(PALETTE)]


def course_name(c) -> str:
    return f"{c.name} {c.group}".strip()


def lessons(doc: Document, view: View) -> list[Placement]:
    kind, id_ = view
    pick = {"class": lambda p: doc.courses[p.course_id].ep_id == id_,
            "teacher": lambda p: doc.courses[p.course_id].teacher_id == id_,
            "room": lambda p: p.room_id == id_}[kind]
    return [p for p in doc.placements if pick(p)]


def todo(doc: Document, view: View) -> list[int]:
    """One course id per lesson still to place that belongs in this view (room: ones that would fit)."""
    kind, id_ = view
    keep = {"class": lambda c: c.ep_id == id_,
            "teacher": lambda c: c.teacher_id == id_,
            "room": lambda c: fits_room(doc, c.id, doc.rooms[id_])}[kind]
    cs = sorted((c for c in doc.courses.values() if doc.unallocated(c.id) > 0 and keep(c)),
                key=lambda c: (doc.eps[c.ep_id].name, c.name, c.group))
    return [c.id for c in cs for _ in range(doc.unallocated(c.id))]


def blocked(doc: Document, view: View) -> set[Slot]:
    kind, id_ = view
    if kind == "class":
        ep = doc.eps[id_]
        return ep.blocked | doc.epgs[ep.epg_id].blocked
    return (doc.teachers if kind == "teacher" else doc.rooms)[id_].blocked


def title(doc: Document, view: View) -> str:
    kind, id_ = view
    if kind == "class":
        ep = doc.eps[id_]
        return f"{doc.epgs[ep.epg_id].name} · {ep.name}"
    if kind == "teacher":
        return doc.teachers[id_].name
    r = doc.rooms[id_]
    return tr("Room {name} ({n} seats)", name=r.name, n=r.capacity)


def summary(doc: Document, view: View) -> str:
    kind, id_ = view
    if kind == "room":
        used = len({(p.term, p.day) for p in lessons(doc, view)})
        free = len(doc.terms) * len(doc.days) - len(doc.rooms[id_].blocked)
        return tr("{used} of {free} periods in use", used=used, free=free)
    cs = [c for c in doc.courses.values() if (c.ep_id if kind == "class" else c.teacher_id) == id_]
    total = sum(c.lessons for c in cs)
    left = sum(max(doc.unallocated(c.id), 0) for c in cs)
    return tr("{n} of {m} lessons placed", n=total - left, m=total) if total else tr("no courses yet")


def cell(doc: Document, view: View, p: Placement) -> tuple[str, str]:
    """(bold title, detail line) of one lesson as shown in this view."""
    c = doc.courses[p.course_id]
    teacher, ep, room = doc.teachers[c.teacher_id].name, doc.eps[c.ep_id].name, doc.rooms[p.room_id].name
    detail = {"class": f"{teacher} · {room}", "teacher": f"{ep} · {room}", "room": f"{ep} · {teacher}"}[view[0]]
    return course_name(c), detail


def tooltip(doc: Document, p: Placement) -> str:
    c = doc.courses[p.course_id]
    return (f"{course_name(c)}\n{tr('Class:')} {doc.eps[c.ep_id].name}\n{tr('Teacher:')} {doc.teachers[c.teacher_id].name}\n"
            f"{tr('Room:')} {doc.rooms[p.room_id].name}\n"
            + tr("{day}, period {p} ({term})", day=doc.days[p.day], p=p.term + 1, term=doc.terms[p.term]))


def next_step(doc: Document) -> str | None:
    """The one thing a user most likely wants to do next, or None when nothing is pending."""
    if not doc.epgs:
        return tr("Start by adding a group (a grade or faculty): {where}", where=menu_path(N_("&Data"), N_("Add &group")))
    if not doc.eps:
        return tr("Add a class to the group: {where}", where=menu_path(N_("&Data"), N_("Add &class")))
    if not doc.teachers:
        return tr("Add your teachers: {where}", where=menu_path(N_("&Data"), N_("Add &teacher")))
    if not doc.rooms:
        return tr("Add your rooms: {where}", where=menu_path(N_("&Data"), N_("Add &room")))
    if not doc.courses:
        return tr("Add courses: {where}", where=menu_path(N_("&Data"), N_("Add c&ourse")))
    left = sum(max(doc.unallocated(c), 0) for c in doc.courses)
    if left:
        return tr("{n} lesson(s) still to place in total — drag them onto the grid, or use {where}", n=left,
              where=menu_path(N_("&Tools"), N_("&Solve automatically…")))
    return None


def preview(doc: Document, view: View, course_id: int) -> tuple[str, str]:
    """(title, detail) of a lesson that is being dragged, in the style of this view's grid blocks."""
    c = doc.courses[course_id]
    return course_name(c), (doc.teachers[c.teacher_id].name if view[0] == "class" else doc.eps[c.ep_id].name)


def todo_label(doc: Document, view: View, course_id: int) -> str:
    c = doc.courses[course_id]
    other = doc.teachers[c.teacher_id].name if view[0] == "class" else doc.eps[c.ep_id].name
    return f"{course_name(c)} · {other}"
