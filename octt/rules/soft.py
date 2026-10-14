# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Soft-constraint score (spec §5): lower is better, 0 = perfect. Pure functions, no Qt.

Semantics follow the original solver's SC* classes. Deviations: occupancy counts distinct
(term, day) slots, and "course blocks" only applies once a course is fully placed.
"""
from dataclasses import dataclass

from octt.i18n import N_, t as tr
from octt.model import Document

PARAMS = {  # defaults from the original SCBaseSettings, except the *_days limits: see defaults()
    "teacher_days": 7, "teacher_daily": 4, "teacher_continuous": 4,
    "student_days": 7, "student_daily": 7, "student_continuous": 6,
    "student_gaps": 4,  # a gap of up to this many empty periods counts as a gap
    "student_start": 1,  # preferred first period (1-based)
}
WEIGHTS = {k: 1.0 for k in (*PARAMS, "course_blocks")}
TEACHER_KEYS = ("teacher_days", "teacher_daily", "teacher_continuous")  # overridable per teacher
STUDENT_KEYS = ("student_days", "student_daily", "student_continuous", "student_gaps", "student_start")  # per class
# lessons/week -> (min block size, min blocks, max blocks); >=10 uses the "default" row
BLOCKS = {2: (2, 1, 1), 3: (3, 1, 1), 4: (2, 1, 2), 5: (2, 2, 2), 6: (2, 2, 3), 7: (2, 2, 3),
          8: (2, 2, 4), 9: (2, 2, 4)}
BLOCKS_DEFAULT = (2, 3, 5)
LABELS = {
    "teacher_days": N_("Teacher: max days per week"), "teacher_daily": N_("Teacher: max hours per day"),
    "teacher_continuous": N_("Teacher: max hours in a row"), "student_days": N_("Students: max days per week"),
    "student_daily": N_("Students: max hours per day"), "student_continuous": N_("Students: max hours in a row"),
    "student_gaps": N_("Students: gaps"), "student_start": N_("Students: preferred first period"),
    "course_blocks": N_("Course: lesson blocks"),
}

OLD_DAYS = {"teacher_days": 1, "student_days": 6}  # the original's: files before io.VERSION 2 mean them when they store no value


def defaults(doc: Document) -> dict:
    """PARAMS for this document. Teachers and classes may have lessons every school day unless a limit is set
    (the original's teacher limit of 1 flagged nearly every teacher, so warnings on good timetables got ignored;
    its student limit of 6 meant nothing in a 5-day week). A limit at or above the number of days never applies."""
    return {**PARAMS, "teacher_days": len(doc.days), "student_days": len(doc.days)}


def label(key: str) -> str:
    return tr(LABELS[key])


@dataclass
class Penalty:
    key: str
    subject: str
    amount: float
    why: str


def _by_day(slots) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for t, d in sorted(slots):
        out.setdefault(d, []).append(t)
    return out


def _runs(terms: list[int]) -> list[list[int]]:
    runs = [[terms[0]]]
    for t in terms[1:]:
        runs[-1].append(t) if t == runs[-1][-1] + 1 else runs.append([t])
    return runs


def score(doc: Document, params: dict | None = None, weights: dict | None = None) -> list[Penalty]:
    P, W = {**defaults(doc), **doc.params, **(params or {})}, {**WEIGHTS, **doc.weights, **(weights or {})}
    out: list[Penalty] = []

    def add(key, subject, n, why):
        if n and W[key]:  # weight 0 switches the constraint off
            out.append(Penalty(key, subject, n * W[key], why))

    def load(who, subject, occ, P):  # days / hours daily / hours continuously
        days = _by_day(occ)
        add(f"{who}_days", subject, len(days) > P[f"{who}_days"], tr("{n} days", n=len(days)))
        for d, terms in days.items():
            add(f"{who}_daily", subject, len(terms) > P[f"{who}_daily"], tr("{day}: {n} h", day=doc.days[d], n=len(terms)))
        longest = max((len(r) for terms in days.values() for r in _runs(terms)), default=0)
        add(f"{who}_continuous", subject, longest > P[f"{who}_continuous"], tr("{n} h in a row", n=longest))

    placed = [(p, doc.courses[p.course_id]) for p in doc.placements]
    for t in doc.teachers.values():
        load("teacher", t.name, {(p.term, p.day) for p, c in placed if c.teacher_id == t.id}, {**P, **t.limits})

    for ep in doc.eps.values():
        Pe = {**P, **ep.limits}
        mine = [(p, c) for p, c in placed if c.ep_id == ep.id]
        for g in sorted({c.group for _, c in mine if c.group}) or [None]:
            occ = {(p.term, p.day) for p, c in mine if not c.group or c.group == g}
            subject = f"{ep.name} {g}" if g else ep.name
            load("student", subject, occ, Pe)
            days = _by_day(occ)
            for d, terms in days.items():
                gaps = sum(0 < b - a - 1 <= Pe["student_gaps"] for a, b in zip(terms, terms[1:]))
                add("student_gaps", subject, gaps, tr("{day}: {n} gap(s)", day=doc.days[d], n=gaps))
                add("student_start", subject, terms[0] + 1 != Pe["student_start"],
                    tr("{day}: starts at period {p}", day=doc.days[d], p=terms[0] + 1))

    for c in doc.courses.values():
        if c.lessons < 2 or doc.unallocated(c.id) != 0:
            continue
        size, lo, hi = c.blocks or BLOCKS.get(c.lessons, BLOCKS_DEFAULT)
        days: dict[int, list] = {}
        for p, cc in placed:
            if cc.id == c.id:
                days.setdefault(p.day, []).append(p)
        ok = lo <= len(days) <= hi
        for ps in days.values():
            terms = sorted(p.term for p in ps)
            ok &= len(_runs(terms)) == 1 and len(terms) >= size and len({p.room_id for p in ps}) == 1
        add("course_blocks", f"{c.name} {c.group}".strip(), not ok, tr("{n} lessons in {m} day(s)", n=c.lessons, m=len(days)))
    return out


def total(penalties: list[Penalty]) -> float:
    return sum(p.amount for p in penalties)
