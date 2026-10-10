# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
import os
import sys

from octt import cli

if sys.argv[1:2] and sys.argv[1] in cli.COMMANDS:  # terminal mode: no window
    sys.exit(cli.run(sys.argv[1:]))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from octt.demo import demo
from octt.ui import language
from octt.ui.main_window import MainWindow

app = QApplication(sys.argv)
app.setApplicationName("OpenCTT")
prefs = QSettings("OpenCTT", "OpenCTT")
language.apply(prefs.value("language") or language.system_language())  # saved choice, else the OS language
args = [a for a in sys.argv[1:] if not a.startswith("--")]
w = MainWindow(settings=prefs)
if "--demo" in sys.argv:
    w.load(demo())
elif args:
    w.open(args[0])
elif w.recent() and os.path.exists(w.recent()[0]):
    w.open(w.recent()[0])  # pick up where you left off
w.show()
sys.exit(app.exec())
