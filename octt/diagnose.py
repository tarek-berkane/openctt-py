# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Why can't the rest be placed? Counting arguments that name the culprit (no Qt, no solver).

Each check is a necessary condition: lessons to place must not exceed the free slots of whoever
has to attend them. A failed check is a proof; passing all of them proves nothing (the solver
then reports an unsatisfiable core instead)."""
from octt.i18n import t as tr
from octt.model import Document


def _free(doc: Document, blocked: set, taken: set) -> int:
    return len(doc.terms) * len(doc.days) - len(blocked | taken)


def explain(doc: Document, units) -> list[str]:
    """`units`: objects with .members (courses placed together) and .n (lessons still to place)."""
    out = []
    placed = [(p, doc.courses[p.course_id]) for p in doc.placements]

    for tid, tch in doc.teachers.items():
        need = sum(u.n for u in units if any(c.teacher_id == tid for c in u.members))
        taken = {(p.term, p.day) for p, c in placed if c.teacher_id == tid}
        free = _free(doc, tch.blocked, taken)
        if need > free:
            out.append(tr("{teacher}: {n} lesson(s) to place but only {k} free slot(s)", teacher=tch.name, n=need, k=free))

    for ep in doc.eps.values():
        mine = [u for u in units if any(c.ep_id == ep.id for c in u.members)]
        if not mine:
            continue
        groups = sorted({c.group for u in units for c in u.members if c.ep_id == ep.id and c.group}
                        | {c.group for c in doc.courses.values() if c.ep_id == ep.id and c.group}) or [""]
        block = ep.blocked | doc.epgs[ep.epg_id].blocked
        for g in groups:
            def mine_g(c):
                return c.ep_id == ep.id and (not c.group or c.group == g)

            need = sum(u.n for u in units if any(mine_g(c) for c in u.members))
            taken = {(p.term, p.day) for p, c in placed if mine_g(c)}
            free = _free(doc, block, taken)
            if need > free:
                who = f"{ep.name} {g}".strip()
                out.append(tr("{who}: {n} lesson(s) to place but only {k} free slot(s)", who=who, n=need, k=free))

    # rooms: lessons whose possible rooms are all inside a set F need room-slots of F (Hall's condition, one F per distinct fit set)
    from octt.rules.hard import fits_room
    fit = [frozenset(r.id for r in doc.rooms.values() if fits_room(doc, u.members[0].id, r)) for u in units]
    for F in set(fit):
        need = sum(u.n for u, f in zip(units, fit) if f <= F)
        supply = sum(_free(doc, doc.rooms[r].blocked, {(p.term, p.day) for p in doc.placements if p.room_id == r}) for r in F)
        if need > supply:
            names = ", ".join(sorted(doc.rooms[r].name for r in F)[:4]) + (", …" if len(F) > 4 else "")
            out.append(tr("{n} lesson(s) can only use the rooms {rooms}, which have {k} free room-slot(s)",
                          n=need, rooms=names or "–", k=supply))
    return out
