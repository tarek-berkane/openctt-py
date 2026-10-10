# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""JSON persistence. Sets <-> sorted lists; tuples <-> [a, b]."""
import json
from dataclasses import asdict
from pathlib import Path

from octt.model import Course, Document, Ep, Epg, Placement, Room, Teacher


def _enc(o):
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(o)


def save(doc: Document, path: str | Path) -> None:
    # UTF-8 explicitly (Arabic / accented names must not depend on the OS locale); readable, not \uXXXX escapes
    Path(path).write_text(json.dumps(asdict(doc), default=_enc, indent=1, ensure_ascii=False), encoding="utf-8")


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


def load(path: str | Path) -> Document:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")  # -sig: tolerate a BOM from Windows editors
    if text.lstrip().startswith("<"):  # a file from the original OpenCTT
        from octt.octt_import import load_octt
        return load_octt(path)
    d = json.loads(text)
    return Document(
        institution=d["institution"], year=d["year"], days=d["days"], terms=d["terms"],
        epgs=_table(Epg, d["epgs"]), eps=_table(Ep, d["eps"]),
        teachers=_table(Teacher, d["teachers"]), rooms=_table(Room, d["rooms"]),
        courses=_table(Course, d["courses"]),
        placements=[Placement(**p) for p in d["placements"]],
        params=d.get("params", {}), weights=d.get("weights", {}),
    )
