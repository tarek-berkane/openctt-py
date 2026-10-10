# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Terminal interface: `python -m octt <command> ...` (no window, no Qt except for `pdf`)."""
import argparse
import os
import sys

from octt import ops, solver
from octt.io import load, save
from octt.rules.soft import PARAMS, WEIGHTS, score, total

COMMANDS = ("info", "check", "solve", "convert", "pdf", "export", "set")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="octt", description="OpenCTT from the terminal")
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("info", help="counts, problems and soft penalty").add_argument("file")
    s.add_parser("check", help="list hard problems; exit 1 if any").add_argument("file")
    a = s.add_parser("solve", help="solve and save the timetable")
    a.add_argument("file")
    a.add_argument("-o", "--out", help="write here instead of overwriting FILE")
    a.add_argument("--scratch", action="store_true", help="discard unlocked lessons first")
    a.add_argument("--time", type=float, default=20, help="seconds for the solver (default 20)")
    a = s.add_parser("convert", help="open any supported file (.json / original .octt XML) and save it as JSON")
    a.add_argument("file")
    a.add_argument("out")
    a = s.add_parser("export", aliases=["pdf"], help="export a report; OUT ends in .pdf, .html or .xlsx")
    a.add_argument("file")
    a.add_argument("out")
    a.add_argument("--kind", default="class", help="report name, e.g. 'class', 'teacher', 'room', 'master' (prefix match)")
    a.add_argument("--entity", type=int, help="id of one class/teacher/room (default: all)")
    a.add_argument("--lang", default="en", help="en, fr or ar")
    a.add_argument("--font", default="", help="font family")
    a.add_argument("--size", type=float, default=0, help="font size in pt")
    a.add_argument("--header", default="#e8e8e8", help="table header colour, e.g. '#cce5ff'")
    a.add_argument("--no-colors", action="store_true", help="plain lessons, no course colours")
    a.add_argument("--no-borders", action="store_true", help="no table lines")
    a = s.add_parser("set", help="change soft-constraint limits (KEY=N) or weights (w.KEY=N); no pairs = list them")
    a.add_argument("file")
    a.add_argument("pairs", nargs="*")
    return p


def _set(doc, pairs: list[str]) -> None:
    for pair in pairs:
        k, _, v = pair.partition("=")
        table, name = (doc.weights, k[2:]) if k.startswith("w.") else (doc.params, k)
        if name not in (WEIGHTS if table is doc.weights else PARAMS) or not v.replace(".", "", 1).isdigit():
            sys.exit(f"bad setting '{pair}'. Keys: {', '.join(PARAMS)}; weights: w.<key> and w.course_blocks")
        table[name] = float(v) if table is doc.weights else int(float(v))


def run(argv: list[str]) -> int:
    a = _parser().parse_args(argv)
    try:
        doc = load(a.file)
    except (OSError, ValueError) as e:
        sys.exit(f"cannot open {a.file}: {e}")
    if a.cmd == "info":
        print(f"{doc.institution} {doc.year}: {len(doc.days)} days x {len(doc.terms)} terms, {len(doc.eps)} classes, "
              f"{len(doc.teachers)} teachers, {len(doc.rooms)} rooms, {len(doc.courses)} courses")
        need = sum(c.lessons for c in doc.courses.values())
        print(f"lessons placed: {len(doc.placements)} of {need}, soft penalty {total(score(doc)):g}")
        for m in ops.audit(doc):
            print("problem:", m)
    elif a.cmd == "check":
        bad = ops.audit(doc)
        print("\n".join(bad) or "ok")
        return 1 if bad else 0
    elif a.cmd == "solve":
        r = solver.solve(doc, not a.scratch, a.time)
        if not r.ok:
            print(r.status, r.message, file=sys.stderr)
            return 1
        doc.placements = [p for p in doc.placements if p not in r.removes] + r.placements
        out = a.out or a.file
        save(doc, out)
        print(f"{r.status}: placed {len(r.placements)} lesson(s), penalty {r.penalty:g} -> {out}")
    elif a.cmd == "convert":
        save(doc, a.out)
    elif a.cmd == "set":
        if a.pairs:
            _set(doc, a.pairs)
            save(doc, a.file)
        print({**PARAMS, **doc.params}, {f"w.{k}": v for k, v in {**WEIGHTS, **doc.weights}.items()}, sep="\n")
    elif a.cmd in ("pdf", "export"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from octt import reports
        from octt.export import Style, write
        from octt.ui import language
        app = QApplication.instance() or QApplication([])
        language.apply(a.lang)
        from octt.i18n import t as tr
        names = [k for k in reports.REPORTS if k.lower().startswith(a.kind.lower())]
        names = names or [k for k in reports.REPORTS if tr(k).lower().startswith(a.kind.lower())]
        if not names:
            sys.exit("unknown report. Choose from: " + ", ".join(reports.REPORTS))
        write(reports.build(doc, names[0], a.entity), a.out,
              Style(a.font, a.size, a.header, not a.no_colors, not a.no_borders))
        print(f"{names[0]} -> {a.out}")
    return 0
