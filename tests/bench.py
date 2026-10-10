"""Not a test: `python -m tests.bench [classes] [teachers] [seconds]` times the solver on a generated school."""
import random
import sys
import time

from octt.model import Course, Document, Ep, Epg, Room, Teacher
from octt.solver import solve


def school(classes=50, teachers=100, rooms=None, days=5, periods=8, seed=1) -> Document:
    rnd = random.Random(seed)
    d = Document(institution="Bench", days=[f"D{i}" for i in range(days)], terms=[f"P{i}" for i in range(periods)])
    d.epgs[1] = Epg(1, "All")
    for t in range(1, teachers + 1):
        d.teachers[t] = Teacher(t, f"T{t}")
    for r in range(1, (rooms or classes + 10) + 1):
        d.rooms[r] = Room(r, f"R{r}", 30)
    cid, load = 0, {t: 0 for t in d.teachers}
    for e in range(1, classes + 1):
        d.eps[e] = Ep(e, f"C{e}", 1)
        for _ in range(9):
            cid += 1
            n = rnd.choice((2, 3, 4))
            t = min(load, key=lambda k: (load[k], rnd.random()))  # least-loaded teacher keeps the instance feasible
            load[t] += n
            d.courses[cid] = Course(cid, f"S{cid}", e, t, lessons=n, students=25)
    return d


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:]] + [50, 100, 60][len(sys.argv) - 1:]
    d = school(a[0], a[1])
    n = sum(c.lessons for c in d.courses.values())
    print(f"{a[0]} classes, {a[1]} teachers, {len(d.courses)} courses, {n} lessons", flush=True)
    t0 = time.time()
    res = solve(d, keep=False, time_limit=a[2], progress=lambda v: print(f"  {time.time() - t0:6.1f}s penalty {v:g}", flush=True))
    print(res.status, res.message[:300], f"penalty={res.penalty}", f"{time.time() - t0:.1f}s")
