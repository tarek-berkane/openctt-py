# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Applies a UI language to the whole application: our catalogs, Qt's own strings, text direction."""
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from octt import i18n

_qt_translators: list[QTranslator] = []
_default_font: list[QFont] = []
LATIN_FONT = "Inter"  # bundled (SIL OFL), same reason
ARABIC_FONT = "Cairo"  # bundled (SIL OFL) so Arabic looks the same on every machine, not whatever fallback the OS picks


def load_fonts() -> None:
    if not (QFontDatabase.hasFamily(ARABIC_FONT) and QFontDatabase.hasFamily(LATIN_FONT)):
        for f in (Path(__file__).parent.parent / "fonts").glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(f))


def text_font(size: float) -> QFont:
    """Font for painted/PDF text in the current language."""
    if i18n.is_rtl():
        load_fonts()
        return QFont(ARABIC_FONT, int(size))
    load_fonts()
    return QFont(LATIN_FONT, int(size))


def system_language() -> str:
    code = QLocale.system().name()[:2]
    return code if code in i18n.LANGUAGES else "en"


def apply(code: str) -> str:
    """Switch language everywhere that is not a widget we built ourselves. Returns the code actually used."""
    code = i18n.set_language(code)
    app = QApplication.instance()
    if app is None:
        return code
    for tr_ in _qt_translators:
        app.removeTranslator(tr_)
    _qt_translators.clear()
    if code != "en":  # OK / Cancel / Save / Discard / file dialog texts come from Qt's own catalogs
        path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
        for name in ("qtbase", "qt"):
            tr_ = QTranslator(app)
            if tr_.load(QLocale(code), name, "_", path):
                app.installTranslator(tr_)
                _qt_translators.append(tr_)
    if not _default_font:
        _default_font.append(app.font())
    load_fonts()
    f = QFont(_default_font[0])
    f.setFamily(ARABIC_FONT if i18n.is_rtl() else LATIN_FONT)
    app.setFont(f)
    for cls in ("QMenu", "QMenuBar", "QToolButton", "QTabBar", "QHeaderView", "QComboBox"):
        app.setFont(f, cls)  # the platform theme gives these their own font, which a plain setFont leaves alone
    app.setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)  # mirrors every layout
    return code
