# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Printable reports as HTML pages (no Qt). octt.pdf turns the HTML into a PDF.

Each report builds a list of Page(title, subtitle, body, landscape). Entity reports (one timetable per
class / teacher / room) can be limited to one entity via `entity`.
"""
from dataclasses import dataclass
from html import escape

from octt.i18n import N_, is_rtl, t as tr
from octt.model import Document
from octt.views import color as _color


@dataclass
class Page:
    title: str
    subtitle: str
    body: str
    landscape: bool = True


def _name(c) -> str:
    return escape(f"{c.name} {c.group}".strip())


def _table(head: list[str], rows: list[list[str]], widths: list[int] | None = None, row_h: int = 0) -> str:
    """rows hold ready-made HTML cells; a cell may be ('bgcolor', html) for a coloured one."""
    if is_rtl():  # Qt tables always run left to right, so mirror the columns by hand: first column on the right
        head, rows = head[::-1], [r[::-1] for r in rows]
        widths = widths[::-1] if widths else None
    th = "".join(f"<th bgcolor='#e8e8e8'>{h}</th>" for h in head)
    out = [f"<table width='100%' border='1' cellspacing='0' cellpadding='4'><tr>{th}</tr>"]
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            bg, html = c if isinstance(c, tuple) else (None, c)
            w = f" width='{widths[i]}%'" if widths else ""
            h = f" height='{row_h}'" if row_h else ""  # px of the 300 dpi layout: ~12.7 mm at 150
            tds.append(f"<td{w}{h}{f' bgcolor={bg!r}' if bg else ''}>{html}</td>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    return "".join(out) + "</table>"


def _timetable(doc: Document, lessons) -> str:
    """lessons: iterable of (placement, html_text). Terms down, days across."""
    cell: dict[tuple[int, int], list] = {}
    for p, text in lessons:
        cell.setdefault((p.term, p.day), []).append((p.course_id, text))
    rows = []
    for t, term in enumerate(doc.terms):
        row = [f"<b>{t + 1}</b><br>{escape(term)}"]
        for d in range(len(doc.days)):
            items = cell.get((t, d), [])
            if len(items) == 1:
                row.append((_color(items[0][0]), items[0][1]))
            else:
                row.append("<br>".join(f"<span style='background-color:{_color(c)}'>{h}</span>" for c, h in items))
        rows.append(row)
    return _table([""] + [escape(x) for x in doc.days], rows, [12] + [88 // max(len(doc.days), 1)] * len(doc.days), row_h=150)


def _subtitle(doc: Document) -> str:
    return escape(f"{doc.institution} {doc.year}".strip())


def class_pages(doc: Document, entity: int | None = None) -> list[Page]:
    pages = []
    for ep in doc.eps.values():
        if entity not in (None, ep.id):
            continue
        mine = [(p, doc.courses[p.course_id]) for p in doc.placements if doc.courses[p.course_id].ep_id == ep.id]
        body = _timetable(doc, ((p, f"<b>{_name(c)}</b><br>{escape(doc.teachers[c.teacher_id].name)}"
                                    f" · {escape(doc.rooms[p.room_id].name)}") for p, c in mine))
        left = [f"{_name(c)} ×{doc.unallocated(c.id)}" for c in doc.courses.values()
                if c.ep_id == ep.id and doc.unallocated(c.id) > 0]
        if left:
            body += f"<p><b>{escape(tr('Not yet placed:'))}</b> {escape(', '.join(left))}</p>"
        pages.append(Page(escape(f"{doc.epgs[ep.epg_id].name} · {ep.name}"), _subtitle(doc), body))
    return pages


def teacher_pages(doc: Document, entity: int | None = None) -> list[Page]:
    pages = []
    for t in doc.teachers.values():
        if entity not in (None, t.id):
            continue
        mine = [(p, doc.courses[p.course_id]) for p in doc.placements if doc.courses[p.course_id].teacher_id == t.id]
        body = _timetable(doc, ((p, f"<b>{_name(c)}</b><br>{escape(doc.eps[c.ep_id].name)}"
                                    f" · {escape(doc.rooms[p.room_id].name)}") for p, c in mine))
        pages.append(Page(escape(t.name), _subtitle(doc), body))
    return pages


def room_pages(doc: Document, entity: int | None = None) -> list[Page]:
    pages = []
    for r in doc.rooms.values():
        if entity not in (None, r.id):
            continue
        mine = [(p, doc.courses[p.course_id]) for p in doc.placements if p.room_id == r.id]
        body = _timetable(doc, ((p, f"<b>{_name(c)}</b><br>{escape(doc.eps[c.ep_id].name)}"
                                    f" · {escape(doc.teachers[c.teacher_id].name)}") for p, c in mine))
        pages.append(Page(escape(tr("Room {name} ({n} seats)", name=r.name, n=r.capacity)), _subtitle(doc), body))
    return pages


def master_pages(doc: Document, entity=None) -> list[Page]:
    """One page per day: classes down, periods across."""
    pages = []
    for d, day in enumerate(doc.days):
        rows = []
        for ep in doc.eps.values():
            row = [f"<b>{escape(ep.name)}</b>"]
            for t in range(len(doc.terms)):
                items = [(p, doc.courses[p.course_id]) for p in doc.placements
                         if (p.term, p.day) == (t, d) and doc.courses[p.course_id].ep_id == ep.id]
                row.append("<br>".join(f"<span style='background-color:{_color(c.id)}'>{_name(c)}"
                                       f" ({escape(doc.rooms[p.room_id].name)})</span>" for p, c in items))
            rows.append(row)
        head = [""] + [f"{t + 1}<br>{escape(term)}" for t, term in enumerate(doc.terms)]
        pages.append(Page(escape(tr("Master timetable — {day}", day=day)), _subtitle(doc), _table(head, rows)))
    return pages


def teacher_list(doc: Document, entity=None) -> list[Page]:
    rows = []
    for t in doc.teachers.values():
        cs = [c for c in doc.courses.values() if c.teacher_id == t.id]
        total = sum(c.lessons for c in cs)
        if not cs:
            rows.append([f"<b>{escape(t.name)}</b>", "—", "", "0", "0"])
        for i, c in enumerate(cs):
            rows.append([f"<b>{escape(t.name)}</b> {escape(tr('({n} lessons/week)', n=total))}" if i == 0 else "", _name(c),
                         escape(doc.eps[c.ep_id].name), str(c.lessons), str(c.lessons - max(doc.unallocated(c.id), 0))])
    body = _table([tr("Teacher"), tr("Course"), tr("Class"), tr("Lessons/week"), tr("Placed")], rows, [30, 25, 20, 13, 12])
    return [Page(tr("Teachers and their courses"), _subtitle(doc), body, landscape=False)]


def teacher_hours(doc: Document, entity=None) -> list[Page]:
    rows = []
    for t in doc.teachers.values():
        slots = {(p.term, p.day) for p in doc.placements if doc.courses[p.course_id].teacher_id == t.id}
        per_day = [sum(d == day for _, d in slots) for day in range(len(doc.days))]
        rows.append([f"<b>{escape(t.name)}</b>", *map(str, per_day), f"<b>{len(slots)}</b>", str(sum(n > 0 for n in per_day))])
    body = _table([tr("Teacher"), *map(escape, doc.days), tr("Total hours"), tr("Days")], rows)
    return [Page(tr("Teacher hours per week"), _subtitle(doc), body, landscape=False)]


def room_list(doc: Document, entity=None) -> list[Page]:
    rows = []
    for r in doc.rooms.values():
        free = len(doc.terms) * len(doc.days) - len(r.blocked)
        used = len({(p.term, p.day) for p in doc.placements if p.room_id == r.id})
        rows.append([f"<b>{escape(r.name)}</b>", str(r.capacity), str(used), str(free),
                     f"{100 * used / free:.0f}%" if free else "—"])
    body = _table([tr("Room"), tr("Seats"), tr("Hours used"), tr("Hours available"), tr("Utilisation")], rows)
    return [Page(tr("Rooms"), _subtitle(doc), body, landscape=False)]


# name -> (builder, what `entity` selects: 'eps' | 'teachers' | 'rooms' | None)
REPORTS = {
    N_("Class timetables"): (class_pages, "eps"),
    N_("Teacher timetables"): (teacher_pages, "teachers"),
    N_("Room timetables"): (room_pages, "rooms"),
    N_("Master timetable (one page per day)"): (master_pages, None),
    N_("Teacher list"): (teacher_list, None),
    N_("Teacher hours"): (teacher_hours, None),
    N_("Room list"): (room_list, None),
}


def build(doc: Document, kind: str, entity: int | None = None) -> list[Page]:
    return REPORTS[kind][0](doc, entity)


def to_html(page: Page, first: bool) -> str:
    brk = "" if first else " style='page-break-before: always'"
    return f"<h2{brk}>{page.title}</h2><p>{page.subtitle}</p>{page.body}"
