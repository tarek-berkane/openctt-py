# OpenCTT (Open Course Timetabler) — Architecture & Specification for a PySide6 Rewrite

Source analysed: `OpenCTTSolution/` (C#, .NET WinForms, ~40k LOC excluding .resx/designer; author Ivan Ćurak, 2007, **GPL v2+**).
Projects: `OpenCTT` (app), `OCTTAutomatedTT` (solver), `OCTTPluginInterface`, `OCTT_MySql_Plugin`, `OCTTSetup`, `SQL/`.

---

## 1. What the product is

A **course-timetabling** tool for schools (doc type 1) and universities (doc type 2). Given teachers, rooms, programs and courses (each with N lessons/week), it builds a weekly grid: **(term/period × day) × room**. Manual drag-and-drop placement with live hard-constraint highlighting, plus an automatic solver (Ant Colony Optimisation + local search) minimising weighted soft-constraint violations. Prints PDF reports. Imports data via plugin (MySQL).

School vs University differs only in **labels** ("class/grade" vs "study program/semester") — separate `.resx` string tables, no logic difference. Skip it or make it a string-table switch.

## 2. Layered architecture (as built)

```
AppForm (god-form, 5k LOC)  ── WinForms UI, trees, grid, toolbar, menus
   │  calls
Commands/ (45 classes)      ── Command pattern: doit/undo/redo, CommandProcessor (undo stack max 50), MacroCommand
   │  mutate
Model/                      ── OCTTDocument, EduProgramGroup > EduProgram > Course, Teacher, Room   (all extend TreeNode!)
Misc/HardConstraintChecks   ── feasibility of dropping a lesson in a slot
Misc/ModelOperations        ── add/delete day/term (resizes every bool[,] matrix), search, report tables
Misc/FileOperations         ── XML save/load + XSD validation (octtfileschema.xsd)
Misc/Settings, SCBaseSettings ── octtconfig.xml (user prefs), soft-constraint defaults & weights
Misc/PdfCreator*            ── PdfSharp reports
OCTTAutomatedTT             ── solver, isolated from UI via A* mirror classes (ACourse, ATeacher, AEduProgram, ALessonNode)
OCTTPluginInterface         ── IPlugin / IPluginHost (reflection-loaded DLLs)
```

**Flaws you should NOT copy:**
- Model classes **inherit `TreeNode`** (domain = UI widget). Global singleton `AppForm.CURR_OCTT_DOC` is read from inside models. Untestable.
- Time-slot matrices are `bool[term, day]` / `ArrayList[term, day]` and **must be reallocated on every add/delete day/term** (`ModelOperations`).
- Solver uses a flat 1-based slot id: `ts = room*(days*terms) + day*terms + term + 1`. Decode with `%`/`floor`. Error-prone; use a tuple/`dataclass` or `(room, day, term)` int triple.
- O(n) full-document scans for every hard-constraint check (teacher busy? room busy?). Use per-slot indexes.
- Duplicate logic in `markNotPossibleTimeSlots*` (colouring is mixed into validation). Separate "compute conflicts" from "paint".
- Copy-paste in `SC*` classes (each rebuilds the same occupancy grid). Build the grid once per entity.
- `.suo`, `.vdproj` installer, `Hashtable` string keys like `"epg,ep,course"` for mapping — drop all.

## 3. Domain model

| Entity | Fields | Notes |
|---|---|---|
| **Document** | type (1/2), version, institution name, school year, file path, `included_days[7]`, `terms[]` (start/end h:m, index 1..50), course types, teacher titles, teacher edu-ranks (lookup lists), unallocated-lesson counter | `getNumberOfDays`, map real weekday ↔ model index (only included days are columns) |
| **EduProgramGroup** (EPG) | name, extID, `allowed_slots[term][day]` | e.g. "Grade 5" / a faculty. Group-level blocked slots |
| **EduProgram** (EP) | name, code (nullable), semester, extID, `allowed_slots`, `timetable[term][day] -> list[(Course, Room)]`, `unallocated_lessons` list, student soft-constraint overrides (5) | A *class/cohort*. Uniqueness: name+semester (case-insens.) |
| **Course** | name, shortName, courseType, lessons/week, enrolled students, teacher, isGroup, groupName, extID, colour, `allowed_rooms` (None = any), `courses_to_hold_together[]`, lesson-block override `[minBlockSize,minBlocks,maxBlocks]` | Unique within EP by (name\|shortName, type[, group]). A **group** course = sub-cohort of an EP (e.g. lab group A) — students in other groups are not blocked |
| **Teacher** | name, lastName, title, eduRank, extID, `allowed_slots`, `allowed_rooms`, SC overrides: maxDays, maxHoursDaily, maxHoursContinuously (−1 = use default) | Unique on name+last+title+rank |
| **Room** | name, capacity, extID, `allowed_slots` | Unique name; capacity cannot drop below existing load |
| **Lesson placement** | `(course, term, day, room)`; same-slot may hold several (groups, hold-together) | Stored in the EP's timetable; unplaced ones in EP's `unallocated_lessons` |

Defaults: all `allowed_slots` start `True`; `-1` for any SC override means "inherit global default".

**Hold-together (HT) courses**: a course may be bound to others (cross-EP) that must occupy the *same* slot and room. Capacity = sum of all enrolled students. In the solver HT courses are folded into the primary (`IsHTCourse`) and not scheduled independently.

## 4. Hard constraints (must hold; UI blocks drops)

For dropping lesson of course **C** (teacher **T**, EP **E**, EPG **G**) into slot `(t,d)`:

1. `G.allowed[t][d]` and `E.allowed[t][d]` (and the same for every HT partner's EPG/EP).
2. **Student clash** in E: if C is not a group → slot must hold no lesson from E at all; if C is a group → no non-group lesson, and no lesson of the *same group name*. (Same applies to each HT partner against its own EP.)
3. **Teacher**: `T.allowed[t][d]` and T teaches nothing else in that slot in *any* EP.
4. **Room**: ≥1 room such that: in `T.allowed_rooms` (or None), in `C.allowed_rooms` (or None) and all HT partners' allowed rooms, `capacity ≥ C.students + Σ HT students`, `room.allowed[t][d]`, and room free in `(t,d)` across all EPs.
5. Also: a room view drop restricts the candidate room to the one selected.

Delete-guards: cannot delete a teacher in use; cannot delete a title/rank/course-type lookup value still referenced; cannot delete a day/term holding lessons; can't shrink room below placed load.

## 5. Soft constraints (solver objective — lower is better)

Total = Σ over all teachers + courses + EPs (per group) of `evaluate()`; each returns `0` or `weight` (or `count × weight`). Weights from user config (`0` → forced to `1.0`).

| Constraint | Scope | Parameter (default) | Penalty |
|---|---|---|---|
| Teacher max days/week | teacher | 1 (!) | weight if days used > N |
| Teacher max hours/day | teacher | 4 | weight if any day > N |
| Teacher max hours continuously | teacher | 4 | weight if any run > N |
| Student max days/week | EP(+group) | 6 | weight |
| Student max hours/day | EP(+group) | 7 | weight |
| Student max hours continuously | EP(+group) | 6 | weight |
| Student no gaps | EP(+group) | gap indicator 4 | `weight × #gaps` where gap length ≤ indicator |
| Student preferred start period | EP(+group) | 1 | `weight` per day not starting at period N |
| Course lesson blocks | course (if lessons/wk>1) | table keyed by lessons/week: 2→(2,1,1) 3→(3,1,1) 4→(2,1,2) 5→(2,2,2) 6,7→(2,2,3) 8→(2,2,…) ≥10→"default" | weight if lessons not in consecutive same-room blocks of ≥minSize, or block count outside [min,max] |

Note: "Student max days per week" reuses the *teacher* weight constant in the original (`SC_TEACHER_MAX_DAYS_PER_WEEK_WEIGHT`) — a bug; give it its own weight.
Group-aware occupancy: a student SC for group G counts courses whose group is G **or** empty.

## 6. Automatic solver (the algorithmically heavy part)

Pipeline:
1. **Prepare** (`prepareDataForAutomatedTT`): sort rooms by capacity; for each course compute `possible_slots` bitmap over `rooms × days × terms` = EPG∩EP∩teacher∩room allowed slots ∩ room capacity ∩ allowed rooms; create `ALessonNode` per lesson to place (`from scratch` = lessons/week, or `from current state` = currently unallocated, with already-placed lessons imported as **fixed nodes**). Attach soft constraints per teacher/course/EP-group. Build per-node **conflict table** (which slots become impossible given a placed node: same teacher; same EP/group; HT partners; room).
2. **ACO loop** (`findBestSolution`, up to 500 000 iterations, cancellable, reports progress `(solutionsFound, bestValue)`):
   - Each "ant": courses sorted by fewest possible slots first; for each lesson node pick a slot with probability ∝ (pheromone/Σpheromone)² over still-feasible slots, add to partial solution, prune conflicting slots from the rest of that course. Dead end → reset ant.
   - Evaluate total soft-constraint value; keep best-of-3-ants (`PHEROMONE_UPDATE_STEP = 3`).
   - **Local search** (`doLocalSearch/doPartialOptmisation`): pick 1 course, enumerate/backtrack all feasible positions for its nodes, keep improvements.
   - **Pheromone update**: with probability `γ·(local/global)` (γ=0.70) reinforce local-best else global-best; `Δ = |50·(1.2 − local/global)|`; evaporation ρ = 0.1; clamp [1, 100]; init 100.
   - Stop when global best == 0 or user presses Stop.
3. **Accept** (`acceptTheBestSolution`): write `PositionInGlobalBestSolution` of each node back to EP timetables (+HT partner EPs, same slot/room), decrement unallocated counters; clears undo stack.

Runs on a `BackgroundWorker` (→ `QThread`/`QRunnable` + signals). UI: start (from scratch | from current state), stop, live counters, "accept best".

**Replication advice:** do not port 1:1. A cleaner/faster route: model as CP-SAT (`ortools`) with hard constraints exact and soft constraints as weighted objective terms, or keep ACO but vectorise with NumPy. Hard constraints in §4 are the contract either way.

## 7. Command / undo system

`AbstractCommand{doit, undo, redo}`; `CommandProcessor` keeps `done`/`undone` stacks (max 50), `lastSavedCmd` for dirty tracking, `MacroCommand` composes commands (undo in reverse). ~45 commands: Add/Delete/Change × {Course, Teacher, Room, EP, EPG, Document, Days, Terms}, AllowedTimeSlots, AllowedRooms, HoldTogether, ConvertCourseToGroups, ClearTimetable, 6 drag-drop families (courses/teachers/rooms view × place/move/unplace), 4 soft-constraint settings. **Map to `QUndoStack`/`QUndoCommand` (`QUndoCommand` children = macro).** Dirty = `QUndoStack.isClean()`.

## 8. UI specification

Main window (`AppForm`):
- **Left dock**: `QTabWidget` with three trees (Courses: EPG>EP>Course · Teachers · Rooms) + below it an **"unallocated lessons"** list (drag source).
- **Centre**: scrollable timetable grid — day headers × term headers (with times), each cell (`TimeSlotPanel`) shows stacked (course, room) label pairs; colour per course. View depends on selected tree node:
  - course/EP node → that EP's timetable; EPG/root → merged; teacher → that teacher's; room → that room's.
- **Drag-drop**: dragging an unallocated lesson (or a placed one) → on drag start compute impossible slots (§4) and tint them; drop only on valid ones; room auto-picked (smallest fitting) or chosen via `RoomSelectionForm` if several. Placed lesson dragged back to the list = unplace.
- Status bar: selected-item description, "Unallocated lessons: N".
- Toolbar: new/open/save/print/undo/redo/search/auto-TT.
- Context menus per tree level (add/rename/delete/properties/allowed slots/room restriction/hold-together/convert to groups/clear timetable/copy-paste course via clipboard).
- Menus: File (recent files list), Document (properties, add/delete days & terms), Edit/EP/Course, Tools (auto-TT, settings, plugins), Print, Help.

Dialogs (25): Document properties, Add days, Add term, EPG/EP/Course/Teacher/Room properties, Allowed-time-slots grid (checkbox matrix for EPG/EP/teacher/room), Rooms restriction (course/teacher), Courses-to-hold-together, Course→groups conversion, Room selection, Search (across entities), Print selection, Settings (general/GUI/PDF layout/SC weights), 6 soft-constraint settings forms (base defaults + per teacher/EP/course overrides), Automated TT, splash.

Settings (`octtconfig.xml`, recent docs in `octtdh.xml`): institution, year, working dir, grid cell width/height/font, default label style, language (en / hr-HR), PDF reader, report layout (paper size/orientation, fonts, colours, column widths, course format), 9 SC weights. → `QSettings`.

## 9. Persistence

- **Format**: XML, root `<open_course_timetabler document_type="1|2" version="">`, validated against `octtfileschema.xsd` on load.
- Order: `edu_institution_name, school_year, incl_days{day_index*}, incl_terms{term index=..>"HH:mm-HH:mm"}, teachers, classrooms, edu_program_groups>edu_program_group>(name, extid, spec_slots, edu_programs>edu_program>(name, code, semester, extid, spec_slots, courses>course)), activities>lessons_in_tt>lesson_in_tt{course_id, day_index, term_index, classroom_id}`.
- `spec_slots type="allowed|unallowed"` lists whichever side is smaller (serialisation optimisation — `getIsThereMoreUnallowedThanAllowedTimeSlots`). Courses reference teachers/rooms by integer ids; hold-together by course id. SC overrides serialised per entity (lesson-blocks element).
- **Python plan:** use JSON (or SQLite) with the same logical schema; keep an XML importer only if you need to open original `.octt` files.

## 10. Reporting

PdfSharp: per-EP timetable, per-teacher, per-room, master timetable, teacher list, teacher-hours, room list. → `QPrinter`/`QPdfWriter` or `reportlab`; build as `QTextDocument` tables for least effort.

## 11. Plugin system

`IPlugin` (Name, Description, Author, Version, menu text, enable/disable type, optional form, Initialize/Dispose) + `IPluginHost` (get document as `DataSet`, close document, import `DataSet` to start a new timetable). Loaded by reflection from a plugins folder. MySQL plugin exports/imports tables: `tt_data, day, term, room, teacher, epg, ep, course, allocated_lesson` (SQL in `/SQL`). → Python: `importlib` entry points or plain modules with an `IPlugin` ABC; export to SQLite/CSV is the YAGNI substitute.

## 12. Suggested PySide6 architecture

```
octt/
  model/      dataclasses: Document, Epg, Ep, Course, Teacher, Room, Placement   (no Qt)
  rules/      hard.py (feasible_slots), soft.py (9 penalty fns)                   (no Qt, unit-tested)
  solver/     aco.py or cpsat.py, runs in QThread, emits progress
  io/         json_io.py, octt_xml_import.py, pdf_report.py
  commands/   QUndoCommand subclasses
  ui/         main_window.py, tree_models.py (QAbstractItemModel over the dataclasses),
              timetable_view.py (QGraphicsView or QTableView + delegate), dialogs/
```
- Trees → `QAbstractItemModel`/`QTreeView`; grid → `QTableView` with custom delegate (cheap) or `QGraphicsScene` (nicer drag/drop); drag-drop via `QMimeData`.
- Index every placement: `by_teacher[(t,d)]`, `by_room[(t,d)]`, `by_ep[(t,d)]` for O(1) checks.
- i18n via `QTranslator`; keep school/university as a string-table switch.

## 13. Build order (recommended)

1. Model + JSON I/O + **hard-constraint function with tests** (this is the product's core).
2. Main window: trees, grid, manual placement with highlighting, undo/redo.
3. Allowed-slots dialogs, hold-together, groups.
4. Soft-constraint evaluation (read-only score display) → **then** solver.
5. PDF reports, search, settings, i18n, plugins last (plugins likely never).

## 14. Licence

OpenCTT is **GPL v2-or-later**. A line-by-line port is a derivative work and must be GPL. Re-implementing from this *spec* (behaviour, not code) is a new work, but if you copy structure/algorithms closely, assume GPL and license accordingly.
