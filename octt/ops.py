# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Document edits + validation (no Qt). Dialogs and the window both go through trial()/audit()."""
import copy
from collections import Counter

from octt.i18n import N_, t as tr
from octt.model import Course, Document, Ep, Epg, Room, Teacher
from octt.rules.hard import broken_hold_together
from octt.rules.place import placement_problems
from octt.rules.soft import STUDENT_KEYS, TEACHER_KEYS, label


def make_terms(first: str, count: int, minutes: int, gap: int = 0) -> list[str]:
    """'08:00', 6, 45, 10 -> ['08:00-08:45', '08:55-09:40', ...]. Raises ValueError past midnight."""
    h, m = map(int, first.split(":"))
    t, out = h * 60 + m, []
    for _ in range(count):
        if t + minutes > 24 * 60:
            raise ValueError(tr("periods run past midnight"))
        out.append(f"{t // 60:02d}:{t % 60:02d}-{(t + minutes) // 60:02d}:{(t + minutes) % 60:02d}")
        t += minutes + gap
    return out


def set_schedule(doc: Document, institution: str, year: str, days: list[tuple[int | None, str]],
                 terms: list[str] | None) -> None:
    """Rename/reorder/add/drop days (`days` = (old index or None, new name)) and replace period labels.
    Slots follow their day; periods map by position. Blocked slots and lessons that no longer fit are dropped."""
    dmap = {old: new for new, (old, _) in enumerate(days) if old is not None}
    n_terms = len(terms) if terms is not None else len(doc.terms)

    def move(slots):
        return {(t, dmap[d]) for t, d in slots if d in dmap and t < n_terms}

    for rows in (doc.epgs, doc.eps, doc.teachers, doc.rooms):
        for x in rows.values():
            x.blocked = move(x.blocked)
    for p in doc.placements:
        p.day = dmap.get(p.day, -1)
    doc.placements = [p for p in doc.placements if p.day >= 0 and p.term < n_terms]
    for e in doc.eps.values():
        if "student_start" in e.limits:
            e.limits["student_start"] = min(e.limits["student_start"], n_terms)
    doc.institution, doc.year, doc.days = institution, year, [name for _, name in days]
    if terms is not None:
        doc.terms = terms


def next_id(table: dict) -> int:
    return max(table, default=0) + 1


def add_group(doc: Document, name: str) -> None:
    g = next_id(doc.epgs)
    doc.epgs[g] = Epg(g, name)


def add_ep(doc: Document, epg_id: int, name: str) -> None:
    e = next_id(doc.eps)
    doc.eps[e] = Ep(e, name, epg_id)


def save_group(doc: Document, g: Epg) -> None:
    doc.epgs[g.id] = g


def save_teacher(doc: Document, t: Teacher) -> None:
    doc.teachers[t.id] = t


def save_ep(doc: Document, e: Ep) -> None:
    doc.eps[e.id] = e


def save_room(doc: Document, r: Room) -> None:
    doc.rooms[r.id] = r


def save_course(doc: Document, c: Course) -> None:
    """Hold-together is symmetric: keep partners' back-links in step."""
    old = doc.courses.get(c.id)
    for pid in old.hold_together if old else []:
        if pid not in c.hold_together and pid in doc.courses:
            doc.courses[pid].hold_together = [x for x in doc.courses[pid].hold_together if x != c.id]
    for pid in c.hold_together:
        if pid in doc.courses and c.id not in doc.courses[pid].hold_together:
            doc.courses[pid].hold_together.append(c.id)
    doc.courses[c.id] = c


def delete_teacher(doc: Document, tid: int) -> None:
    n = sum(c.teacher_id == tid for c in doc.courses.values())
    if n:
        raise ValueError(tr("{teacher} teaches {n} course(s)", teacher=doc.teachers[tid].name, n=n))
    del doc.teachers[tid]


def delete_ep(doc: Document, eid: int) -> None:
    n = sum(c.ep_id == eid for c in doc.courses.values())
    if n:
        raise ValueError(tr("{ep} has {n} course(s)", ep=doc.eps[eid].name, n=n))
    del doc.eps[eid]


def delete_group(doc: Document, gid: int) -> None:
    n = sum(e.epg_id == gid for e in doc.eps.values())
    if n:
        raise ValueError(tr("{group} has {n} class(es)", group=doc.epgs[gid].name, n=n))
    del doc.epgs[gid]


def delete_room(doc: Document, rid: int) -> None:
    if any(p.room_id == rid for p in doc.placements):
        raise ValueError(tr("{room} holds placed lessons", room=doc.rooms[rid].name))
    users = [x for x in (*doc.teachers.values(), *doc.courses.values()) if x.allowed_rooms == {rid}]
    if users:
        raise ValueError(tr("{room} is the only allowed room of {who}", room=doc.rooms[rid].name, who=users[0].name))
    for x in (*doc.teachers.values(), *doc.courses.values()):
        if x.allowed_rooms:
            x.allowed_rooms.discard(rid)
    del doc.rooms[rid]


def delete_course(doc: Document, cid: int) -> None:
    doc.placements = [p for p in doc.placements if p.course_id != cid]
    for c in doc.courses.values():
        c.hold_together = [x for x in c.hold_together if x != cid]
    del doc.courses[cid]


def _free_name(taken: set[str], name: str) -> str:
    """'Maths' -> 'Maths (2)', or the next number not in `taken` (compared like audit does: trimmed, casefolded)."""
    taken = {t.strip().casefold() for t in taken}
    n = 2
    while f"{name} ({n})".casefold() in taken:
        n += 1
    return f"{name} ({n})"


def duplicate(doc: Document, kind: str, id_: int) -> int:
    """Copy a group / class / teacher / room / course under a free name. Returns the new id.
    A class brings copies of its courses; a group brings copies of its classes (same names) and their courses."""
    table = {"epg": doc.epgs, "teacher": doc.teachers, "room": doc.rooms, "course": doc.courses, "ep": doc.eps}[kind]
    new = copy.deepcopy(table[id_])
    new.id = next_id(table)
    if kind == "course":
        new.hold_together = []  # its partners would not list it back
        taken = {c.name for c in doc.courses.values() if c.ep_id == new.ep_id and c.group == new.group}
    elif kind == "ep":
        taken = {e.name for e in doc.eps.values() if e.epg_id == new.epg_id}
    else:
        taken = {x.name for x in table.values()}
    new.name = _free_name(taken, new.name)
    table[new.id] = new
    if kind == "ep":
        _copy_courses(doc, {id_: new.id})
    elif kind == "epg":
        eps = {}
        for e in [e for e in doc.eps.values() if e.epg_id == id_]:
            eps[e.id] = eid = next_id(doc.eps)
            doc.eps[eid] = copy.deepcopy(e)
            doc.eps[eid].id, doc.eps[eid].epg_id = eid, new.id
        _copy_courses(doc, eps)
    return new.id


def _copy_courses(doc: Document, eps: dict[int, int]) -> None:
    """Copy every course of the classes in `eps` (old class id -> its copy). Hold-together partners that were
    copied too follow the copies; partners outside the copy stay with the original."""
    ids = {}
    for c in [c for c in doc.courses.values() if c.ep_id in eps]:
        ids[c.id] = cid = next_id(doc.courses)
        doc.courses[cid] = copy.deepcopy(c)
        doc.courses[cid].id, doc.courses[cid].ep_id = cid, eps[c.ep_id]
    for old, cid in ids.items():
        doc.courses[cid].hold_together = [ids[h] for h in doc.courses[old].hold_together if h in ids]


def _dups(pairs) -> list[str]:
    seen, out = set(), []
    for key, message in pairs:
        if key in seen:
            out.append(message)
        seen.add(key)
    return out


def audit(doc: Document) -> list[str]:
    out = []
    for kind, rows in ((N_("group"), doc.epgs), (N_("class"), doc.eps), (N_("teacher"), doc.teachers),
                       (N_("room"), doc.rooms), (N_("course"), doc.courses)):
        out += [tr("{kind} name is empty", kind=tr(kind)) for x in rows.values() if not x.name.strip()]

    def dup(kind, name):
        return tr("duplicate {kind} '{name}'", kind=tr(kind), name=name)

    out += _dups((t.name.strip().casefold(), dup(N_("teacher"), t.name)) for t in doc.teachers.values())
    out += _dups((r.name.strip().casefold(), dup(N_("room"), r.name)) for r in doc.rooms.values())
    out += _dups((g.name.strip().casefold(), dup(N_("group"), g.name)) for g in doc.epgs.values())
    out += _dups(((e.epg_id, e.name.strip().casefold()), dup(N_("class"), e.name)) for e in doc.eps.values())
    out += _dups(((c.ep_id, c.name.strip().casefold(), c.group.strip().casefold()),
                  tr("duplicate course '{name}' in that class", name=f"{c.name} {c.group}".strip()))
                 for c in doc.courses.values())
    for r in doc.rooms.values():
        if r.capacity < 1:
            out.append(tr("{name}: capacity must be at least 1", name=r.name))
    for c in doc.courses.values():
        if c.teacher_id not in doc.teachers or c.ep_id not in doc.eps:
            out.append(tr("{name}: needs a class and a teacher", name=c.name))
        if c.lessons < 1:
            out.append(tr("{name}: needs at least 1 lesson per week", name=c.name))
        if broken_hold_together(doc, c):
            out.append(tr("{name}: bad hold-together list", name=c.name))
        if c.allowed_rooms is not None and not c.allowed_rooms:
            out.append(tr("{name}: restricted to no rooms", name=c.name))
    for t in doc.teachers.values():
        if t.allowed_rooms is not None and not t.allowed_rooms:
            out.append(tr("{name}: restricted to no rooms", name=t.name))
    for rows, keys in ((doc.teachers, TEACHER_KEYS), (doc.eps, STUDENT_KEYS)):
        for x in rows.values():
            for k, v in x.limits.items():
                if k not in keys or not isinstance(v, int) or v < 0 or (k == "student_start" and not 1 <= v <= len(doc.terms)):
                    out.append(tr("{name}: bad {limit} override", name=x.name, limit=label(k)))
    for c in doc.courses.values():
        b = c.blocks
        if b is not None and not (len(b) == 3 and all(isinstance(v, int) for v in b) and b[0] >= 1 and 1 <= b[1] <= b[2]):
            out.append(tr("{name}: lesson blocks must be [size >= 1, 1 <= min blocks <= max blocks]", name=c.name))
    if out:  # placement checks assume the references above are sound
        return out
    placed = Counter(p.course_id for p in doc.placements)
    out += [tr("{name}: {n} more lesson(s) placed than allowed", name=c.name, n=placed[c.id] - c.lessons)
            for c in doc.courses.values() if placed[c.id] > c.lessons]
    return out or placement_problems(doc)


def trial(doc: Document, mutate) -> list[str]:
    """Run `mutate` on a copy; return only the problems it introduces (empty = safe to apply)."""
    def key(msg):  # a lesson already in trouble stays "known" even if the reason text changes
        return msg.split(":")[0] if " @ " in msg else msg

    baseline = {key(p) for p in audit(doc)}
    t = copy.deepcopy(doc)  # ponytail: whole-document copy, fine for school-sized data
    try:
        mutate(t)
    except ValueError as e:
        return [str(e)]
    return [p for p in audit(t) if key(p) not in baseline]
