# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Reads a file saved by the original (C#) OpenCTT: XML, root <open_course_timetabler>. See Misc/FileOperations.cs there."""
import xml.etree.ElementTree as ET

from octt.i18n import WEEK, t as tr
from octt.model import Course, Document, Ep, Epg, Placement, Room, Teacher
from octt.rules.soft import defaults


def _text(e, tag, default=""):
    x = e.find(tag)
    return (x.text or "").strip() if x is not None else default


def _ids(e, tag):
    return [int(x.text) for x in e.findall(f"{tag}/classroom_id")] if e is not None else []


def load_octt(path) -> Document:
    try:
        return _load(ET.parse(path).getroot())
    except ET.ParseError as e:
        raise ValueError(f"not an OpenCTT file: {e}") from e
    except (AttributeError, TypeError) as e:  # a required element is missing
        raise ValueError(f"not a valid OpenCTT file ({e})") from e


def _load(root) -> Document:
    if root.tag != "open_course_timetabler":
        raise ValueError("not an OpenCTT file")
    real = sorted(int(x.text) for x in root.findall("incl_days/day_index")) or [1, 2, 3, 4, 5]  # 1 = Monday
    terms = [x.text.strip() for x in sorted(root.findall("incl_terms/term"), key=lambda x: int(x.get("index")))]
    doc = Document(institution=_text(root, "edu_institution_name"), year=_text(root, "school_year"),
                   days=[tr(WEEK[d - 1]) for d in real], terms=terms)

    def slots(e):  # blocked (term, day) set; the file lists whichever side is smaller
        s = e.find("spec_slots")
        if s is None:
            return set()
        listed = {(int(x.find("term_index").text) - 1, real.index(int(x.find("day_index").text))) for x in s.findall("spec_slot")}
        return listed if s.get("type") == "unallowed" else {(t, d) for t in range(len(terms)) for d in range(len(real))} - listed

    def rooms_of(e):
        ids = _ids(e, "allowed_classrooms")
        return set(ids) or None

    for e in root.findall("teachers/teacher"):
        i = int(e.get("id"))
        doc.teachers[i] = Teacher(i, f"{_text(e, 'name')} {_text(e, 'last_name')}".strip(), slots(e), rooms_of(e))
    for e in root.findall("classrooms/classroom"):
        i = int(e.get("id"))
        doc.rooms[i] = Room(i, _text(e, "name"), int(_text(e, "capacity", "0")), slots(e))
    eps, courses = {}, {}  # file ids (strings) -> our ids; ep ids are renumbered, they may be absent
    for g, ge in enumerate(root.findall("edu_program_groups/edu_program_group"), 1):
        doc.epgs[g] = Epg(g, _text(ge, "name"), slots(ge))
        for pe in ge.findall("edu_programs/edu_program"):
            i = len(doc.eps) + 1
            eps[pe.get("id")] = i
            doc.eps[i] = Ep(i, _text(pe, "name"), g, slots(pe))
            for ce in pe.findall("courses/course"):
                c = int(ce.get("id"))
                courses[c] = ce
                doc.courses[c] = Course(c, _text(ce, "name"), i, int(_text(ce, "teacher_id")), int(_text(ce, "num_of_lessons_per_week", "1")),
                                        int(_text(ce, "num_of_enrolled_students", "0")), _text(ce, "group_name"), rooms_of(ce))
    for c, ce in courses.items():  # hold-together is symmetric in our model
        for x in ce.findall("to_hold_together_with/course_id"):
            o = int(x.text)
            if o in doc.courses and o != c:
                for a, b in ((c, o), (o, c)):
                    if b not in doc.courses[a].hold_together:
                        doc.courses[a].hold_together.append(b)
    for e in root.findall("activities/lessons_in_tt/lesson_in_tt"):
        doc.placements.append(Placement(int(_text(e, "course_id")), int(_text(e, "term_index")) - 1,
                                        real.index(int(_text(e, "day_index"))), int(_text(e, "classroom_id"))))
    _soft(root, doc, eps, courses)
    return doc


def _soft(root, doc, eps, courses):
    """Soft-constraint limits: the file's global values, plus per-class / per-teacher / per-course overrides."""
    def ints(e, names):
        return {k: int(_text(e, tag)) for k, tag in names.items() if e is not None and e.find(tag) is not None}

    ep_tags = {"student_continuous": "max_hours_continuously", "student_daily": "max_hours_daily", "student_days": "max_days_per_week",
               "student_gaps": "gap_indicator", "student_start": "preferred_start_time_period"}
    t_tags = {"teacher_continuous": "max_hours_continuously", "teacher_daily": "max_hours_daily", "teacher_days": "max_days_per_week"}
    sc = root.find("soft_constraints")
    if sc is None:
        return
    base = {**ints(sc.find("sc_eps/sc_ep_base"), ep_tags), **ints(sc.find("sc_teachers/sc_teacher_base"), t_tags)}
    same = defaults(doc)
    doc.params = {k: v for k, v in base.items()
                  if v != same[k] and not (k.endswith("_days") and v >= len(doc.days))}  # can never apply: no limit
    for e in sc.findall("sc_eps/sc_ep"):
        if e.get("sc_ep_id") in eps:
            doc.eps[eps[e.get("sc_ep_id")]].limits = ints(e, ep_tags)
    for e in sc.findall("sc_teachers/sc_teacher"):
        i = int(e.get("sc_teacher_id", 0))
        if i in doc.teachers:
            doc.teachers[i].limits = ints(e, t_tags)
    for e in sc.findall("sc_courses/sc_course"):
        i = int(e.get("sc_course_id", 0))
        if i in doc.courses:
            doc.courses[i].blocks = [int(_text(e, t)) for t in ("min_block_size", "min_num_of_blocks", "max_num_of_blocks")]
