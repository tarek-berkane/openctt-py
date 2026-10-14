# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""JSON persistence. Sets <-> sorted lists; tuples <-> [a, b]."""
import json
import os
from dataclasses import asdict
from pathlib import Path

from octt.model import Course, Document, Ep, Epg, Placement, Room, Teacher
from octt.rules.soft import OLD_DAYS

VERSION = 2  # 2: default teacher_days / student_days became the number of days (files store only values that differ)


def _enc(o):
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(o)


def save(doc: Document, path: str | Path) -> None:
    # UTF-8 explicitly (Arabic / accented names must not depend on the OS locale); readable, not \uXXXX escapes
    # write a sibling file, then swap it in: a full disk or crash mid-write must not destroy the old file
    tmp = Path(f"{path}.tmp")
    try:
        tmp.write_text(json.dumps({"version": VERSION, **asdict(doc)}, default=_enc, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _table(cls, rows: dict, slots=("blocked",), sets=("allowed_rooms",)):
    out = {}
    for k, r in rows.items():
        r = dict(r)
        for f in slots:
            if f in r:
                r[f] = {tuple(s) for s in r[f]}
        for f in sets:
            if r.get(f) is not None:
                r[f] = set(r[f])
        out[int(k)] = cls(**r)
    return out


def is_octt(path: str | Path) -> bool:
    """A file from the original OpenCTT (XML), whatever its extension. It is imported, never overwritten."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:  # -sig: tolerate a BOM from Windows editors
        return f.read(4096).lstrip().startswith("<")


def load(path: str | Path) -> Document:
    if is_octt(path):
        from octt.octt_import import load_octt
        return load_octt(path)
    d = json.loads(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
    try:
        doc = Document(
            institution=d["institution"], year=d["year"], days=d["days"], terms=d["terms"],
            epgs=_table(Epg, d["epgs"]), eps=_table(Ep, d["eps"]),
            teachers=_table(Teacher, d["teachers"]), rooms=_table(Room, d["rooms"]),
            courses=_table(Course, d["courses"]),
            placements=[Placement(**p) for p in d["placements"]],
            params=d.get("params", {}), weights=d.get("weights", {}),
        )
    except (KeyError, TypeError, AttributeError) as e:  # valid JSON, wrong shape: callers only handle ValueError
        raise ValueError(f"missing or bad field: {e}") from e
    if d.get("version", 1) < 2:  # an old file without the value meant the old default; kept where it can apply
        for k, v in OLD_DAYS.items():
            if v < len(doc.days):
                doc.params.setdefault(k, v)
    return doc
