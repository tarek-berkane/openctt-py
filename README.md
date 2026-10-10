# OpenCTT

A desktop course timetabler for schools and universities, rewritten in Python/PySide6 from the C# original (Ivan Ćurak, GPL v2+; see [OPENCTT_SPEC.md](OPENCTT_SPEC.md)).

Define teachers, rooms, classes and courses; place lessons by drag-and-drop with live hard-constraint highlighting, or let the solver (OR-Tools CP-SAT) fill the grid while minimising weighted soft-constraint penalties. Export reports as PDF, HTML or XLSX. UI languages: English, French, Arabic.

## Quick start

```bash
make setup                     # creates .venv, installs PySide6 + ortools
make run                       # start the GUI
make open FILE=my.json         # open a file (.json, or an original .octt XML)
make dev                       # demo timetable, auto-restarts on source change (needs inotifywait)
make install                   # symlink `octt` into ~/.local/bin
```

Try it on `examples/example_school.json`.

## Command line

`octt <command> FILE` (or `python -m octt ...`) runs without a window:

| Command | Does |
|---|---|
| `info` | counts, problems, soft penalty |
| `check` | list hard-constraint problems; exit 1 if any |
| `solve [-o OUT] [--scratch] [--time 20]` | solve and save; `--scratch` discards unlocked lessons first |
| `convert FILE OUT` | any supported file → JSON |
| `export FILE OUT [--kind class\|teacher\|room\|master] [--entity ID] [--lang en\|fr\|ar]` | report; format from the OUT extension (`.pdf` `.html` `.xlsx`) |
| `set FILE [KEY=N \| w.KEY=N]` | change soft-constraint limits/weights; no pairs lists them |

Locked placements are never moved by the solver.

## Layout

```
octt/model/    document model        octt/rules/   hard + soft constraints
octt/solver.py CP-SAT solver         octt/ops.py   edit operations, audit
octt/ui/       Qt windows/dialogs    octt/reports.py, pdf.py, export.py
octt/locales/  fr, ar strings        tests/        plain-function tests
```

## Development

```bash
make test    # all tests, headless (QT_QPA_PLATFORM=offscreen), no pytest needed
make i18n    # missing / unused / broken translations
make build   # single executable via Nuitka -> dist/octt (needs gcc + patchelf)
```

## License

GPL v2 or later, inherited from the original OpenCTT. Bundled fonts: Inter (OFL), Cairo.
