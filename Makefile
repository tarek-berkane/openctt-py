SHELL  := /bin/bash
VENV   := .venv
PY     := $(VENV)/bin/python
TESTS  := $(basename $(notdir $(wildcard tests/test_*.py)))

.PHONY: help setup run open dev test i18n clean install build

help:
	@echo "make setup   create .venv and install dependencies"
	@echo "make run     start the app (ARGS=file.json to open a file)"
	@echo "make open FILE=x.json   open that file (also .octt/.xml); ARGS=\"solve x.json\" with make run runs a terminal command"
	@echo "make dev     run with the example timetable in Python dev mode; restarts when octt/*.py changes (needs inotifywait)"
	@echo "make test    run all tests"
	@echo "make i18n    list missing / unused / broken translations (fr, ar)"
	@echo "make build   compile a single executable with Nuitka -> dist/octt (needs gcc + patchelf)"
	@echo "make clean   remove caches"

setup: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install -q -r requirements.txt
	touch $@

run: setup
	$(PY) -m octt $(ARGS)

open: setup
	$(PY) -m octt $(FILE)

# dev: Python dev mode (extra warnings/checks, faulthandler) + restart on source change.
# Closing the window ends it. Without inotifywait it just runs once in dev mode.
dev: setup
	@export PYTHONDEVMODE=1 PYTHONFAULTHANDLER=1; \
	if ! command -v inotifywait >/dev/null; then echo "(no inotifywait: no auto-restart)"; exec $(PY) -m octt --demo $(ARGS); fi; \
	while true; do \
	  $(PY) -m octt --demo $(ARGS) & app=$$!; \
	  inotifywait -qq -r -e modify,create,delete,move --exclude '__pycache__|\.pyc|\.swp|~$$' octt & watch=$$!; \
	  wait -n $$app $$watch; \
	  if kill -0 $$app 2>/dev/null; then echo "-- source changed, restarting"; kill $$app; wait $$app 2>/dev/null; \
	  else kill $$watch 2>/dev/null; echo "-- app closed"; break; fi; \
	done

# tests are plain functions (no pytest needed); QT_QPA_PLATFORM=offscreen lets them run headless
# (the grep hides the offscreen plugin's harmless 'propagateSizeHints' warning)
test: setup
	@for t in $(TESTS); do echo "== $$t"; QT_QPA_PLATFORM=offscreen $(PY) -m tests.$$t 2> >(grep -v propagateSizeHints >&2) || exit 1; done

i18n: setup
	$(PY) -m tests.i18n_scan

# Nuitka onefile build. Fonts are loaded via __file__, so ship them as data. First build is slow (minutes).
build: setup
	$(PY) -m pip install -q nuitka
	$(PY) -m nuitka --mode=onefile --enable-plugin=pyside6 --include-package=octt \
	  --include-data-dir=octt/fonts=octt/fonts --output-dir=dist --output-filename=octt octt/__main__.py

clean:
	rm -rf dist *.build *.dist *.onefile-build
	find . -name __pycache__ -not -path './$(VENV)/*' -prune -exec rm -rf {} +

install: setup  # `octt file.json` from any terminal
	mkdir -p ~/.local/bin && ln -sf $(CURDIR)/bin/octt ~/.local/bin/octt
