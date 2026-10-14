# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Turns a drop into a concrete change. Hold-together partners always move as one unit."""
from octt.i18n import t as tr
from octt.model import Document, Placement
from octt.rules.hard import candidate_rooms, fits_room, violations


def _group(doc: Document, cid: int) -> list[int]:
    return [cid, *doc.courses[cid].hold_together]


def plan_unplace(doc: Document, cid: int, term: int, day: int) -> list[Placement]:
    g = set(_group(doc, cid))
    return [p for p in doc.placements if (p.term, p.day) == (term, day) and p.course_id in g]


def plan_place(doc: Document, cid: int, term: int, day: int, src: tuple[int, int] | None = None,
               room: int | None = None):
    """-> (remove, add, errors). `src` = (term, day) when moving an already placed lesson;
    `room` forces that room (used by the room view)."""
    if src == (term, day):
        return [], [], []
    remove = plan_unplace(doc, cid, *src) if src else []
    if any(p.locked for p in remove):
        return [], [], [tr("locked: unlock it first")]
    keep = [p for p in doc.placements if p not in remove]

    def left(c):
        return doc.courses[c].lessons - sum(p.course_id == c for p in keep)

    if not src and left(cid) <= 0:
        return [], [], [tr("no lessons left")]
    saved, doc.placements = doc.placements, keep  # judge the slot as if the lesson were lifted
    try:
        errors = violations(doc, cid, term, day)
        rooms = candidate_rooms(doc, cid, term, day)
    finally:
        doc.placements = saved
    if not errors and room is not None:
        if room not in rooms:
            errors = [tr("{room} is not available or suitable then", room=doc.rooms[room].name)]
        rooms = [room]
    if errors:
        return [], [], errors
    moved = {p.course_id for p in remove}
    ids = [c for c in _group(doc, cid) if c == cid or c in moved or left(c) > 0]
    return remove, [Placement(c, term, day, rooms[0]) for c in ids], []


def set_locked(doc: Document, cid: int, term: int, day: int, locked: bool) -> None:
    for p in plan_unplace(doc, cid, term, day):  # hold-together partners are pinned together
        p.locked = locked


def bad_slots(doc: Document, cid: int, src: tuple[int, int] | None, room: int | None = None) -> dict:
    """slot -> reasons, for every slot the lesson cannot go to."""
    out = {}
    for t in range(len(doc.terms)):
        for d in range(len(doc.days)):
            if errs := plan_place(doc, cid, t, d, src, room)[2]:
                out[t, d] = errs
    return out


def placement_problems(doc: Document) -> list[str]:
    """Every placed lesson re-checked against the hard rules, as if it were lifted and dropped again."""
    saved, out, by_slot = doc.placements, [], {}
    for q in saved:
        by_slot.setdefault((q.term, q.day), []).append(q)
    try:
        for p in saved:
            # the hard rules only read the lesson's own slot, so lift it from that slot's lessons, not the whole list
            doc.placements = by_slot[p.term, p.day]
            lifted = plan_unplace(doc, p.course_id, p.term, p.day)
            doc.placements = [q for q in doc.placements if q not in lifted]
            errs = violations(doc, p.course_id, p.term, p.day, rooms=False)
            room = doc.rooms[p.room_id]
            if not (fits_room(doc, p.course_id, room) and (p.term, p.day) not in room.blocked
                    and all(q.room_id != room.id for q in doc.placements)):  # its own room still works: skip the full room search
                if not candidate_rooms(doc, p.course_id, p.term, p.day):
                    errs.append(tr("no free room fits"))
                elif not errs:
                    errs = [tr("room {room} no longer suitable", room=room.name)]
            out += [tr("{course} @ {day} {term}: {why}", course=doc.courses[p.course_id].name, day=doc.days[p.day],
                      term=doc.terms[p.term], why=e) for e in errs]
    finally:
        doc.placements = saved
    return out
