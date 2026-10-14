# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Free time: where could one more lesson go right now, without moving anything? (no Qt)

For an extra or make-up session: the class (or sub-group), its teacher and a fitting room must all be free.
Booking adds an ordinary course whose lessons are placed there and locked, so the solver leaves them alone."""
import copy
from dataclasses import dataclass

from octt.model import Course, Document, Placement
from octt.ops import next_id
from octt.rules.hard import candidate_rooms, violations
from octt.rules.soft import score, total


@dataclass
class Free:
    term: int
    day: int
    rooms: list[int]  # free rooms that fit, smallest first
    penalty: float  # change in the timetable's soft penalty if one lesson goes here (negative = better)


def _probe(doc: Document, course: Course, lessons: int = 1) -> tuple[Document, Document, int]:
    """A copy holding `course` (unplaced), and a view of it with only the lessons of its teacher and its class:
    new lessons only change those penalties, so scoring the view gives the same change, much faster."""
    t = copy.deepcopy(doc)
    c = copy.deepcopy(course)
    c.id, c.lessons, c.hold_together = next_id(t.courses), lessons, []
    t.courses[c.id] = c
    mine = copy.copy(t)
    mine.placements = [p for p in t.placements if (q := t.courses[p.course_id]).teacher_id == c.teacher_id
                       or q.ep_id == c.ep_id]
    return t, mine, c.id


def find(doc: Document, course: Course) -> list[Free]:
    """Every slot where one lesson of `course` (not in the document) fits now; least added penalty first."""
    t, mine, cid = _probe(doc, course)
    base = total(score(mine))
    out = []
    for term in range(len(t.terms)):
        for day in range(len(t.days)):
            if violations(t, cid, term, day):
                continue
            rooms = candidate_rooms(t, cid, term, day)
            mine.placements.append(Placement(cid, term, day, rooms[0]))
            out.append(Free(term, day, rooms, total(score(mine)) - base))
            mine.placements.pop()
    return sorted(out, key=lambda f: (f.penalty, f.day, f.term))


def rooms(picks: list[Free]) -> list[tuple[int, int, int]]:
    """(term, day, room) per pick. Picks on the same day share a room when one is free in all of them,
    so a double lesson stays in one room; otherwise each takes its smallest fitting room."""
    common = {}
    for f in picks:
        common[f.day] = common.get(f.day, set(f.rooms)) & set(f.rooms)
    return [(f.term, f.day, next((r for r in f.rooms if r in common[f.day]), f.rooms[0])) for f in picks]


def effect(doc: Document, course: Course, slots: list[tuple[int, int, int]]) -> float:
    """Penalty change if `course` gets all of `slots` (term, day, room) at once. Not the sum of each alone: lessons
    together can make a block, a gap or a long day, and the new course's own lesson-block rule applies."""
    t, mine, cid = _probe(doc, course, len(slots))
    base = total(score(mine))
    mine.placements += [Placement(cid, term, day, room) for term, day, room in slots]
    return total(score(mine)) - base


def book(doc: Document, course: Course, slots: list[tuple[int, int, int]]) -> int:
    """Add `course` with one locked lesson per (term, day, room). Returns its id."""
    c = copy.deepcopy(course)
    c.id, c.lessons, c.hold_together = next_id(doc.courses), len(slots), []
    doc.courses[c.id] = c
    doc.placements += [Placement(c.id, term, day, room, locked=True) for term, day, room in slots]
    return c.id
