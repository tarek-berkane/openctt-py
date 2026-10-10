# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
from octt.model import Course, Document, Ep, Epg, Placement, Room, Teacher


def demo() -> Document:
    d = Document(institution="Demo School", year="2026/27")
    d.epgs[1] = Epg(1, "Grade 5")
    d.eps[1] = Ep(1, "5A", 1)
    d.eps[2] = Ep(2, "5B", 1)
    d.teachers[1] = Teacher(1, "Ada Lovelace")
    d.teachers[2] = Teacher(2, "Alan Turing")
    d.rooms[1] = Room(1, "R101", 30)
    d.rooms[2] = Room(2, "Lab", 12)
    d.courses[1] = Course(1, "Math", 1, 1, lessons=3, students=25)
    d.courses[2] = Course(2, "CS", 1, 2, lessons=2, students=10, group="A")
    d.courses[3] = Course(3, "Math", 2, 1, lessons=3, students=22)
    d.placements.append(Placement(1, 0, 0, 1))
    return d
