# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Hard constraints (spec §4). Pure functions; the UI only paints what these return."""
from octt.i18n import t as tr
from octt.model import Document


def fits_room(doc: Document, course_id: int, room) -> bool:
    """Capacity and allowed-room lists of the course (+ hold-together partners); ignores the time."""
    group = [doc.courses[course_id], *(doc.courses[i] for i in doc.courses[course_id].hold_together)]
    return (room.capacity >= sum(c.students for c in group)
            and all(c.allowed_rooms is None or room.id in c.allowed_rooms for c in group)
            and all((t := doc.teachers[c.teacher_id]).allowed_rooms is None or room.id in t.allowed_rooms
                    for c in group))


def candidate_rooms(doc: Document, course_id: int, term: int, day: int) -> list[int]:
    """Rooms that fit the course (+ hold-together partners) and are free in the slot."""
    busy = {p.room_id for p in doc.placements if (p.term, p.day) == (term, day)}
    out = [r.id for r in doc.rooms.values()
           if fits_room(doc, course_id, r) and (term, day) not in r.blocked and r.id not in busy]
    return sorted(out, key=lambda i: doc.rooms[i].capacity)  # smallest fitting room first


def violations(doc: Document, course_id: int, term: int, day: int, here=None, rooms: bool = True) -> list[str]:
    """Empty list = the lesson may be placed at (term, day). The solver passes `here` (courses already placed
    in that slot) and rooms=False because it prices room supply itself; both only save time."""
    slot = (term, day)
    main = doc.courses[course_id]
    group = [main, *(doc.courses[i] for i in main.hold_together)]
    if here is None:
        here = [doc.courses[p.course_id] for p in doc.placements if (p.term, p.day) == slot]
    out = []
    for c in group:
        ep = doc.eps[c.ep_id]
        if slot in doc.epgs[ep.epg_id].blocked:
            out.append(tr("{ep}: group blocked", ep=ep.name))
        if slot in ep.blocked:
            out.append(tr("{ep}: program blocked", ep=ep.name))
        for o in here:  # student clash
            if o.ep_id == c.ep_id and (not o.group or not c.group or o.group == c.group):
                out.append(tr("{ep}: students busy with {course}", ep=ep.name, course=o.name))
        tch = doc.teachers[c.teacher_id]
        if slot in tch.blocked:
            out.append(tr("{teacher}: unavailable", teacher=tch.name))
        if any(o.teacher_id == tch.id for o in here):
            out.append(tr("{teacher}: already teaching", teacher=tch.name))
    if rooms and not candidate_rooms(doc, course_id, term, day):
        out.append(tr("no free room fits"))
    return out
