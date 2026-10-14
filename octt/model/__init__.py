# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Plain-dataclass domain model (no Qt). Slots are (term, day) indices; blocked slots are sets,
so adding/deleting days or terms never reallocates matrices. Entities reference each other by id."""
from dataclasses import dataclass, field

Slot = tuple[int, int]  # (term_index, day_index)


@dataclass
class Epg:  # program group, e.g. "Grade 5" / a faculty
    id: int
    name: str
    blocked: set[Slot] = field(default_factory=set)


@dataclass
class Ep:  # a class / cohort
    id: int
    name: str
    epg_id: int
    blocked: set[Slot] = field(default_factory=set)
    limits: dict[str, int] = field(default_factory=dict)  # per-class overrides of student_* soft limits


@dataclass
class Teacher:
    id: int
    name: str
    blocked: set[Slot] = field(default_factory=set)
    allowed_rooms: set[int] | None = None  # None = any room
    limits: dict[str, int] = field(default_factory=dict)  # per-teacher overrides of teacher_* soft limits


@dataclass
class Room:
    id: int
    name: str
    capacity: int
    blocked: set[Slot] = field(default_factory=set)


@dataclass
class Course:
    id: int
    name: str
    ep_id: int
    teacher_id: int
    lessons: int = 1
    students: int = 0
    group: str = ""  # non-empty = sub-cohort of the ep (e.g. lab group A)
    allowed_rooms: set[int] | None = None
    hold_together: list[int] = field(default_factory=list)  # course ids sharing slot+room
    blocks: list[int] | None = None  # [min block size, min blocks, max blocks]; None = table by lessons/week


@dataclass
class Placement:
    course_id: int
    term: int
    day: int
    room_id: int
    locked: bool = False  # pinned by the user: the solver keeps it and drag/drop leaves it alone


@dataclass
class Document:
    institution: str = ""
    year: str = ""
    days: list[str] = field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])
    terms: list[str] = field(default_factory=lambda: [f"{h:02d}:00-{h:02d}:45" for h in range(8, 14)])
    epgs: dict[int, Epg] = field(default_factory=dict)
    eps: dict[int, Ep] = field(default_factory=dict)
    teachers: dict[int, Teacher] = field(default_factory=dict)
    rooms: dict[int, Room] = field(default_factory=dict)
    courses: dict[int, Course] = field(default_factory=dict)
    placements: list[Placement] = field(default_factory=list)
    params: dict = field(default_factory=dict)  # soft-constraint limits that differ from rules.soft.defaults(doc)
    weights: dict = field(default_factory=dict)  # ... and weights that differ from rules.soft.WEIGHTS

    def unallocated(self, course_id: int) -> int:
        placed = sum(p.course_id == course_id for p in self.placements)
        return self.courses[course_id].lessons - placed
