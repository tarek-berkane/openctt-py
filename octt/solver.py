# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Automatic timetabling with OR-Tools CP-SAT (no Qt).

Hard constraints = spec §4 (pruned up front with rules.hard, pairwise conflicts as linear constraints).
Objective = the soft-constraint score of rules.soft, encoded one-sided (a penalty variable is only
forced to 1 when its condition holds; minimisation does the rest). Weights are scaled by SCALE to ints.

Model: one unit per lesson-set that must share slot+room (a course plus its hold-together partners).
x[u,t,d] = unit u has a lesson at (term t, day d). Rooms that no unit can tell apart (same fitting units,
same blocked slots) form a room class; y[u,t,d,c] = ... in a room of class c, and a class only needs a
per-slot head count. Concrete rooms are handed out afterwards (_assign_rooms), which is what keeps a school
with 60 identical classrooms from needing 60 variables per lesson and slot.
Locked placements are never touched; keep=False only discards the unlocked ones.
"""
import copy
import os
import threading
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from octt.diagnose import explain
from octt.i18n import t as tr
from octt.model import Document, Placement
from octt.rules.hard import broken_hold_together, fits_room, violations
from octt.rules.soft import BLOCKS, BLOCKS_DEFAULT, WEIGHTS, defaults, score, total

SCALE = 1000


@dataclass
class Result:
    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN | INVALID
    message: str = ""
    placements: list[Placement] = field(default_factory=list)  # lessons to add
    removes: list[Placement] = field(default_factory=list)  # unlocked lessons discarded (keep=False)
    penalty: float | None = None  # soft score of the full resulting timetable
    breakdown: list[tuple[str, float]] = field(default_factory=list)  # (soft constraint key, penalty), biggest first

    @property
    def ok(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")


@dataclass
class Unit:
    members: list  # courses placed together
    leader: object
    n: int  # lessons still to place
    slots: dict = field(default_factory=dict)  # (t, d) -> room classes with a free room there


def _units(doc: Document):
    bad = [c for c in doc.courses.values() if broken_hold_together(doc, c)]
    if bad:
        return None, "\n".join(tr("{name}: bad hold-together list", name=c.name) for c in bad)
    units, seen = [], set()
    for c in sorted(doc.courses.values(), key=lambda c: c.id):
        if c.id in seen or doc.unallocated(c.id) <= 0:
            continue
        members = [c] + [doc.courses[i] for i in c.hold_together
                         if i not in seen and doc.unallocated(i) > 0]
        seen.update(m.id for m in members)
        lefts = {doc.unallocated(m.id) for m in members}
        if len(lefts) > 1:
            names = ", ".join(f"{m.name} ({doc.unallocated(m.id)})" for m in members)
            return None, tr("Hold-together courses need the same number of lessons left: {names}", names=names)
        units.append(Unit(members, c, lefts.pop()))
    return units, ""


def _assign_rooms(work: Document, units, chosen, classes, busy) -> list[Placement]:
    """chosen = [(unit index, t, d, class)]. Any free room of the class works; prefer one the course already
    uses that day (the soft 'one room per block' rule), else the smallest."""
    taken = {k: set(v) for k, v in busy.items()}
    day_rooms = {}
    for p in work.placements:
        day_rooms.setdefault((p.course_id, p.day), set()).add(p.room_id)
    out = []
    for i, t, d, c in sorted(chosen, key=lambda z: (z[2], z[1])):
        u = units[i]
        free = [r for r in classes[c] if r not in taken.setdefault((t, d), set())]
        liked = set().union(*(day_rooms.get((m.id, d), set()) for m in u.members))
        r = next((r for r in free if r in liked), free[0])
        taken[t, d].add(r)
        for m in u.members:
            day_rooms.setdefault((m.id, d), set()).add(r)
            out.append(Placement(m.id, t, d, r))
    return out


def solve(doc: Document, keep: bool = True, time_limit: float = 30.0, params: dict | None = None,
          weights: dict | None = None, stop: threading.Event | None = None, progress=None) -> Result:
    return solve_many(doc, keep, 1, time_limit, params, weights, stop, progress)[0]


def solve_many(doc: Document, keep: bool = True, count: int = 1, time_limit: float = 30.0, params: dict | None = None,
               weights: dict | None = None, stop: threading.Event | None = None, progress=None, found=None,
               spread: float = 0.1) -> list[Result]:
    """Up to `count` different timetables, best-first as found: each later one must move at least `spread`
    (a fraction) of the new lessons to another slot compared with every earlier one.
    keep=True: placed lessons stay and only the unallocated ones are solved; False: unlocked lessons are discarded.
    `time_limit` is per solution. `progress(penalty)` fires on every improvement, `found(result)` per finished solution
    (both from the solver thread). Failure is always a single non-ok Result."""
    P, W = {**defaults(doc), **doc.params, **(params or {})}, {**WEIGHTS, **doc.weights, **(weights or {})}
    work = copy.deepcopy(doc)
    removes = [] if keep else [p for p in work.placements if not p.locked]
    if not keep:
        work.placements = [p for p in work.placements if p.locked]
    units, err = _units(work)
    if units is None:
        return [Result("INVALID", err)]
    if not units:
        res = Result("OPTIMAL", tr("Nothing to place."), [], removes, total(score(work, P, W)))
        return [res]
    T, D = len(work.terms), len(work.days)
    cells = [(t, d) for t in range(T) for d in range(D)]

    # --- room classes: rooms no unit can tell apart --------------------------------------------
    sigs = {}
    for r in sorted(work.rooms.values(), key=lambda r: (r.capacity, r.id)):
        fit = tuple(i for i, u in enumerate(units) if fits_room(work, u.leader.id, r))
        sigs.setdefault((fit, frozenset(r.blocked)), []).append(r.id)
    classes = list(sigs.values())
    class_fits = [set(k[0]) for k in sigs]
    class_blocked = [k[1] for k in sigs]
    class_of = {r: c for c, rs in enumerate(classes) for r in rs}
    busy = {}  # (t, d) -> rooms taken by placed lessons
    here = {}  # (t, d) -> courses placed there
    for p in work.placements:
        busy.setdefault((p.term, p.day), set()).add(p.room_id)
        here.setdefault((p.term, p.day), []).append(work.courses[p.course_id])
    free = {(t, d, c): sum(r not in busy.get((t, d), ()) for r in rs)
            for c, rs in enumerate(classes) for t, d in cells if (t, d) not in class_blocked[c]}

    # --- hard constraints that only depend on already placed lessons: prune the variables ------
    stuck = []
    for i, u in enumerate(units):
        why = {}
        for t, d in cells:
            bad = violations(work, u.leader.id, t, d, here.get((t, d), []), rooms=False)
            cs = [c for c in range(len(classes)) if i in class_fits[c] and free.get((t, d, c), 0) > 0]
            if not bad and not cs:
                bad = [tr("no free room fits")]
            if not bad:
                u.slots[t, d] = cs
            for b in bad:
                why[b] = why.get(b, 0) + 1
        if len(u.slots) < u.n:
            top = ", ".join(w for w, _ in sorted(why.items(), key=lambda kv: -kv[1])[:2])
            stuck.append(tr("{course}: {n} lesson(s) but only {slots} possible slot(s)",
                           course=f"{u.leader.name} {u.leader.group}".strip(), n=u.n, slots=len(u.slots))
                         + (f" — {top}" if top else ""))
    if stuck:
        return [Result("INFEASIBLE", tr("Not enough possible slots:") + "\n" + "\n".join(stuck))]
    short = explain(work, units)
    if short:
        return [Result("INFEASIBLE", tr("Not enough capacity:") + "\n" + "\n".join(short))]

    m = cp_model.CpModel()
    x, y, wanted = {}, {}, {}
    on = []  # one assumption literal per unit, so an infeasible model can name a culprit set
    for i, u in enumerate(units):
        for (t, d), cs in u.slots.items():
            x[i, t, d] = m.NewBoolVar(f"x{i}_{t}_{d}")
            if len(cs) == 1:
                y[i, t, d, cs[0]] = x[i, t, d]
            else:
                for c in cs:
                    y[i, t, d, c] = m.NewBoolVar(f"y{i}_{t}_{d}_{c}")
                m.Add(sum(y[i, t, d, c] for c in cs) == x[i, t, d])
            for c in cs:
                wanted.setdefault((t, d, c), []).append(y[i, t, d, c])
        a = m.NewBoolVar(f"on{i}")
        on.append(a)
        m.Add(sum(x[i, t, d] for t, d in u.slots) == u.n).OnlyEnforceIf(a)
    m.AddAssumptions(on)

    # --- pairwise hard constraints between new lessons ------------------------------------------
    for (t, d, c), vs in wanted.items():
        if len(vs) > free[t, d, c]:
            m.Add(sum(vs) <= free[t, d, c])
    for tid in work.teachers:
        mine = {i for i, u in enumerate(units) if any(c.teacher_id == tid for c in u.members)}
        for t, d in cells:
            m.AddAtMostOne(x[i, t, d] for i in mine if (i, t, d) in x)
    ep_groups = {}  # ep -> sorted group names of all its courses (None-view if it has none)
    for ep in work.eps.values():
        ep_groups[ep.id] = sorted({c.group for c in work.courses.values() if c.ep_id == ep.id and c.group})
        whole = {i for i, u in enumerate(units) if any(c.ep_id == ep.id and not c.group for c in u.members)}
        for t, d in cells:
            w = [x[i, t, d] for i in whole if (i, t, d) in x]
            m.AddAtMostOne(w)
            for g in ep_groups[ep.id]:
                gu = {i for i, u in enumerate(units) if any(c.ep_id == ep.id and c.group == g for c in u.members)}
                m.AddAtMostOne(w + [x[i, t, d] for i in gu if (i, t, d) in x])

    # --- soft constraints -> objective ------------------------------------------------------------
    def add_soft():
        cost = []

        def pen(key):  # a penalty variable that minimisation keeps at 0 unless forced
            v = m.NewBoolVar(key)
            if W[key]:
                cost.append(round(W[key] * SCALE) * v)
            return v

        def occ_var(expr_terms, fixed):  # BoolVar == sum of the new-lesson vars (+1 if a placed lesson is there)
            o = m.NewBoolVar("occ")
            m.Add(o == sum(expr_terms) + (1 if fixed else 0))
            return o

        def load(who, occ, P):
            """days / hours daily / hours in a row for one teacher or student view. Returns day-used vars."""
            used = []
            for d in range(D):
                u = m.NewBoolVar("used")
                m.AddMaxEquality(u, [occ[t, d] for t in range(T)])
                used.append(u)
                v = pen(f"{who}_daily")
                m.Add(sum(occ[t, d] for t in range(T)) <= P[f"{who}_daily"]).OnlyEnforceIf(v.Not())
            v = pen(f"{who}_days")
            m.Add(sum(used) <= P[f"{who}_days"]).OnlyEnforceIf(v.Not())
            n = P[f"{who}_continuous"]
            v = pen(f"{who}_continuous")
            for d in range(D):
                for s in range(T - n):
                    m.Add(sum(occ[t, d] for t in range(s, s + n + 1)) <= n).OnlyEnforceIf(v.Not())
            return used

        placed = [(p, work.courses[p.course_id]) for p in work.placements]
        for tid in work.teachers:
            mine = {i for i, u in enumerate(units) if any(c.teacher_id == tid for c in u.members)}
            if mine:
                fixed = {(p.term, p.day) for p, c in placed if c.teacher_id == tid}
                load("teacher", {(t, d): occ_var([x[i, t, d] for i in mine if (i, t, d) in x], (t, d) in fixed)
                                 for t, d in cells}, {**P, **work.teachers[tid].limits})

        for ep in work.eps.values():
            Pe = {**P, **ep.limits}
            for g in ep_groups[ep.id] or [None]:
                mine = {i for i, u in enumerate(units)
                        if any(c.ep_id == ep.id and (not c.group or c.group == g) for c in u.members)}
                if not mine:
                    continue
                fixed = {(p.term, p.day) for p, c in placed if c.ep_id == ep.id and (not c.group or c.group == g)}
                occ = {(t, d): occ_var([x[i, t, d] for i in mine if (i, t, d) in x], (t, d) in fixed) for t, d in cells}
                used = load("student", occ, Pe)
                for d in range(D):
                    for a in range(T):
                        for b in range(a + 2, min(a + 2 + Pe["student_gaps"], T)):  # gap of b-a-1 in 1..student_gaps
                            v = pen("student_gaps")
                            between = sum(1 - occ[k, d] for k in range(a + 1, b))
                            m.Add(v >= occ[a, d] + occ[b, d] + between - (b - a))
                    pref = Pe["student_start"] - 1
                    v = pen("student_start")
                    for t in range(min(pref, T)):
                        m.Add(v >= occ[t, d])
                    m.Add(v >= used[d] - (occ[pref, d] if pref < T else 0))

        for i, u in enumerate(units):
            for c in u.members:
                if c.lessons < 2:
                    continue
                size, lo, hi = c.blocks or BLOCKS.get(c.lessons, BLOCKS_DEFAULT)
                mine_fixed = [p for p, cc in placed if cc.id == c.id]
                fixed = {(p.term, p.day) for p in mine_fixed}
                occ = {(t, d): occ_var([x[i, t, d]] if (i, t, d) in x else [], (t, d) in fixed) for t, d in cells}
                ok = pen("course_blocks").Not()
                used = []
                for d in range(D):
                    ud = m.NewBoolVar("cused")
                    m.AddMaxEquality(ud, [occ[t, d] for t in range(T)])
                    used.append(ud)
                    m.Add(sum(occ[t, d] for t in range(T)) >= size * ud).OnlyEnforceIf(ok)
                    for a in range(T):
                        for b in range(a + 2, T):
                            for k in range(a + 1, b):  # no hole inside a day's lessons
                                m.Add(occ[a, d] + occ[b, d] - occ[k, d] <= 1).OnlyEnforceIf(ok)
                    z = {}  # room classes used that day (rooms inside a class are chosen to match later)
                    for (ii, t, dd, cl), v in y.items():
                        if ii == i and dd == d:
                            z.setdefault(cl, m.NewBoolVar("z"))
                            m.Add(z[cl] >= v)
                    for p in mine_fixed:
                        if p.day == d:
                            z.setdefault(class_of[p.room_id], m.NewBoolVar("z"))
                            m.Add(z[class_of[p.room_id]] == 1)
                    m.Add(sum(z.values()) <= 1).OnlyEnforceIf(ok)
                m.Add(sum(used) >= lo).OnlyEnforceIf(ok)
                m.Add(sum(used) <= hi).OnlyEnforceIf(ok)
        m.Minimize(sum(cost))

    # --- solve --------------------------------------------------------------------------------------
    def run(first_only=False, cb=None):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_workers = min(8, os.cpu_count() or 1)
        solver.parameters.stop_after_first_solution = first_only
        solver.parameters.log_search_progress = bool(os.environ.get("OCTT_LOG"))
        done, watcher = threading.Event(), None
        if stop is not None:
            def watch():
                while not done.is_set():
                    if stop.wait(0.05):
                        solver.StopSearch()
                        return
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
        status = solver.Solve(m, cb)
        done.set()
        if watcher:
            watcher.join()  # never leave it running into interpreter shutdown
        return solver, solver.StatusName(status)

    def read(solver):
        return [(i, t, d, next(c for c in cs if solver.Value(y[i, t, d, c])))
                for i, u in enumerate(units) for (t, d), cs in u.slots.items() if solver.Value(x[i, t, d])]

    # phase 1: any timetable that satisfies the hard rules. On big schools the optimiser cannot find one
    # on its own within a sensible time, but it improves quickly once it is handed this as a hint.
    solver, name = run(first_only=True)
    if name not in ("OPTIMAL", "FEASIBLE"):
        if name != "INFEASIBLE":
            return [Result(name, tr("No solution found in the time limit."))]
        core = set(solver.SufficientAssumptionsForInfeasibility())
        lines = [f"{c.name} {c.group}".strip() + f" ({work.teachers[c.teacher_id].name}, {work.eps[c.ep_id].name})"
                 for u, a in zip(units, on) if a.Index() in core for c in u.members]
        msg = tr("No complete timetable satisfies the hard constraints.")
        if lines:
            msg += "\n" + tr("These lessons cannot all be placed together; one of them has to change:") + "\n" \
                   + "\n".join(lines[:12]) + ("\n" + tr("… and {n} more", n=len(lines) - 12) if len(lines) > 12 else "")
        return [Result(name, msg)]
    first = read(solver)
    m.ClearAssumptions()  # assumptions pin CP-SAT to one thread; the optimisation wants all of them
    m.AddBoolAnd(on)
    add_soft()
    for i, t, d, c in first:
        m.AddHint(x[i, t, d], 1)

    # phase 2: optimise; later rounds must differ from every earlier timetable
    results = []

    class Cb(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            if progress:
                progress(self.ObjectiveValue() / SCALE)

    for k in range(count):
        if k:
            m.ClearHints()
            if stop is not None and stop.is_set():
                break
            solver, name = run(cb=Cb())
            if name not in ("OPTIMAL", "FEASIBLE"):
                break  # no further different timetable (or out of time): keep what we have
        else:
            solver, name = run(cb=Cb())
        chosen = read(solver) if name in ("OPTIMAL", "FEASIBLE") else first  # stopped before beating the phase-1 timetable
        name = name if name in ("OPTIMAL", "FEASIBLE") else "FEASIBLE"
        add = _assign_rooms(work, units, chosen, classes, busy)
        final = copy.deepcopy(work)
        final.placements += add
        pens = score(final, P, W)
        by_key = {}
        for q in pens:
            by_key[q.key] = by_key.get(q.key, 0) + q.amount
        res = Result(name, "", add, removes, total(pens), sorted(by_key.items(), key=lambda kv: -kv[1]))
        results.append(res)
        if found:
            found(res)
        mine = [x[i, t, d] for i, t, d, _ in chosen]
        m.Add(sum(mine) <= len(mine) - min(len(mine), max(1, round(len(mine) * spread))))
    return results
