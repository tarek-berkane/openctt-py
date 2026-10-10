"""English / French / Arabic: catalogs, live language switch, right-to-left layout, Unicode data, PDFs."""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QDragMoveEvent
from PySide6.QtWidgets import QApplication

from octt import i18n, io, ops, reports
from octt.demo import demo
from octt.model import Course, Document, Ep, Epg, Placement, Room, Teacher
from octt.pdf import write_pdf
from octt.rules.hard import violations
from octt.ui import language
from octt.ui.newdoc_dialog import NewDocumentDialog
from tests.i18n_scan import collect_keys, problems
from tests.test_window import _KEEP, cell_pos, mime, pick_class, window

APP = QApplication.instance() or QApplication([])
ARABIC = re.compile("[؀-ۿﭐ-﷿ﹰ-﻿]")


class lang:
    """with lang('ar'): ...  -- switches everything (our catalogs, Qt's, direction) and always restores English."""

    def __init__(self, code):
        self.code = code

    def __enter__(self):
        language.apply(self.code)

    def __exit__(self, *exc):
        language.apply("en")


def arabic_doc() -> Document:
    d = Document(institution="ثانوية ابن خلدون", year="2026/27", days=["الأحد", "الاثنين", "الثلاثاء"],
                 terms=["08:00-08:45", "08:55-09:40", "09:50-10:35"])
    d.epgs[1], d.eps[1] = Epg(1, "السنة الأولى"), Ep(1, "1 علوم", 1)
    d.teachers[1], d.teachers[2] = Teacher(1, "أحمد بن علي"), Teacher(2, "Élodie Martin")
    d.rooms[1] = Room(1, "قاعة 1", 35)
    d.courses[1] = Course(1, "الرياضيات", 1, 1, 2, 30)
    d.courses[2] = Course(2, "Français", 1, 2, 2, 30)
    d.placements = [Placement(1, 0, 0, 1), Placement(1, 1, 0, 1), Placement(2, 0, 1, 1)]
    return d


# --- catalogs ---------------------------------------------------------------------------------
def test_every_string_is_translated_with_matching_placeholders():
    assert problems() == {"fr": [], "ar": []}
    assert len(collect_keys()) > 250  # the scanner really sees the code


def test_unknown_keys_fall_back_to_english_and_bad_catalogs_never_crash():
    with lang("fr"):
        assert i18n.t("never translated {x}", x=1) == "never translated 1"
        i18n.catalog("fr")["__probe__ {a}"] = "{b} cassé"  # wrong placeholder in a translation
        try:
            assert i18n.t("__probe__ {a}", a=7) == "__probe__ 7"
        finally:
            del i18n.catalog("fr")["__probe__ {a}"]


def test_language_flags_and_menu_paths():
    assert i18n.language() == "en" and not i18n.is_rtl()
    assert i18n.menu_path("&Data", "Add &group") == "Data ▸ Add group"
    with lang("fr"):
        assert i18n.menu_path("&Data", "Add &group") == "Données ▸ Ajouter un groupe"
    with lang("ar"):
        assert i18n.is_rtl() and i18n.menu_path("&Data", "Add &group") == "البيانات ◂ إضافة مجموعة"
    assert i18n.language() == "en"


def test_rule_and_validation_messages_follow_the_language():
    d = demo()
    msg = {c: [] for c in ("en", "fr", "ar")}
    for c in msg:
        with lang(c):
            msg[c] = violations(d, 3, 0, 0)  # Ada already teaches Math 5A at Mon/1
    assert any("already teaching" in m for m in msg["en"])
    assert any("enseigne déjà" in m for m in msg["fr"]) and any("يُدرّس" in m for m in msg["ar"])
    with lang("fr"):
        assert ops.trial(d, lambda x: ops.add_group(x, "grade 5")) == ["doublon (groupe) : « grade 5 »"]
    with lang("ar"):
        assert ARABIC.search(ops.trial(d, lambda x: ops.add_ep(x, 1, " "))[0])


# --- Unicode data -------------------------------------------------------------------------------
def test_arabic_and_french_names_survive_save_and_load_as_readable_utf8():
    d = arabic_doc()
    path = Path(tempfile.mkdtemp()) / "t.json"
    io.save(d, path)
    raw = path.read_bytes()
    assert "ثانوية ابن خلدون".encode() in raw and b"\\u" not in raw  # readable, not \uXXXX escapes
    assert io.load(path) == d
    path.write_bytes(b"\xef\xbb\xbf" + raw)  # a BOM from a Windows editor must not break loading
    assert io.load(path) == d


def test_accented_and_arabic_names_count_as_duplicates_correctly():
    d = arabic_doc()
    assert ops.audit(d) == []
    assert ops.trial(d, lambda x: ops.save_teacher(x, Teacher(9, "ÉLODIE MARTIN")))  # casefold handles É/é
    assert ops.trial(d, lambda x: ops.save_teacher(x, Teacher(9, "أحمد بن علي")))
    assert ops.trial(d, lambda x: ops.save_teacher(x, Teacher(9, "أحمد بن عمر"))) == []


def test_new_document_dialog_names_the_days_in_the_current_language():
    for code, first in (("en", "Mon"), ("fr", "Lun"), ("ar", "الأحد")):
        with lang(code):
            dlg = NewDocumentDialog()
            assert dlg.days[0].text() == first
            dlg.accept()
            assert dlg.document.days[0] == first and len(dlg.document.days) == 5


# --- the window ---------------------------------------------------------------------------------
def menu_titles(w):
    return [a.text().replace("&", "") for a in w.menuBar().actions()]


def test_window_switches_language_live_and_remembers_it():
    w = window(demo())
    assert menu_titles(w) == ["File", "Edit", "Data", "Tools", "Help"] and w.tabs.tabText(1) == "Teachers"
    try:
        w.set_language("fr")
        assert menu_titles(w) == ["Fichier", "Édition", "Données", "Outils", "Aide"]
        assert w.tabs.tabText(1) == "Enseignants" and w.windowTitle() == "Sans titre[*] — OpenCTT"
        assert w.score_btn.text() == "Pénalité 0 ✓" and "séances placées" in w.summary_lbl.text()
        assert w.items[3].text(0).endswith("à placer") and not APP.layoutDirection() == Qt.RightToLeft
        w.set_language("ar")
        assert menu_titles(w) == ["ملف", "تحرير", "البيانات", "أدوات", "مساعدة"] and w.tabs.tabText(0) == "الصفوف"
        assert APP.layoutDirection() == Qt.RightToLeft and w.layoutDirection() == Qt.RightToLeft
        assert w.prefs.value("language") == "ar"
        langs = {a.text(): a.isChecked() for a in w.findChildren(type(w._actions[0])) if a.isCheckable()}
        assert langs.get("العربية") and not langs.get("English")
        w.set_language("en")
        assert menu_titles(w) == ["File", "Edit", "Data", "Tools", "Help"] and APP.layoutDirection() == Qt.LeftToRight
        assert w.windowTitle() == "Untitled[*] — OpenCTT" and w.tabs.tabText(2) == "Rooms"
    finally:
        language.apply("en")


def test_banner_and_hints_name_the_real_menu_entries_in_each_language():
    w = window()
    try:
        w.set_language("fr")
        assert "Données ▸ Ajouter un groupe" in w.banner.text()
        entries = [a.text().replace("&", "") for m in w.menuBar().actions() if m.text().replace("&", "") == "Données"
                   for a in m.menu().actions()]
        assert "Ajouter un groupe" in entries  # the hint matches what the menu really says
        w.set_language("ar")
        assert "البيانات ◂ إضافة مجموعة" in w.banner.text()
    finally:
        language.apply("en")


def test_arabic_mirrors_the_layout_and_the_grid():
    with lang("ar"):
        w = window(arabic_doc())
        pick_class(w, 1)
        g = w.grid
        assert g.columnViewportPosition(0) > g.columnViewportPosition(g.columnCount() - 1)  # first day on the right
        sp = w.split
        assert sp.widget(0).geometry().left() > sp.widget(1).geometry().left()  # side panel on the right
        assert w.title_lbl.alignment() & Qt.AlignLeading and w.title_lbl.text().startswith("السنة")
        m = w.left_lay.contentsMargins()
        assert m.left() == 0 and m.right() > 0  # no gap at the window edge, gap at the splitter
    w2 = window(arabic_doc())
    assert w2.grid.columnViewportPosition(0) < w2.grid.columnViewportPosition(2)  # back to left-to-right


def dark_x_range(w, row, col, ink_max=90):
    """x extent (relative to the cell, 0..1) of the dark text pixels inside the first lesson block of a cell."""
    img = w.grid.viewport().grab().toImage()
    r = w.grid.visualRect(w.grid.model().index(row, col))
    xs = [x for y in range(r.top() + 6, r.top() + 24) for x in range(r.left() + 8, r.right() - 8)
          if img.pixelColor(x, y).red() < ink_max]
    return ((min(xs) - r.left()) / r.width(), (max(xs) - r.left()) / r.width()) if xs else None


def test_lesson_text_aligns_to_the_reading_side():
    d = arabic_doc()
    w = window(d)
    pick_class(w, 1)
    ltr = dark_x_range(w, 0, 0)
    with lang("ar"):
        w = window(d)
        pick_class(w, 1)
        rtl = dark_x_range(w, 0, 0)
    assert ltr and rtl
    assert ltr[0] < 0.2 and rtl[1] > 0.8  # text hugs the left edge in English, the right edge in Arabic


def test_refusal_badge_moves_to_the_trailing_corner_in_rtl():
    def badge_side(w):
        w.grid.drag_begin.emit(2, None)  # Français: Alan.. teacher 2 is free, but class 1 is busy at Sun/1
        bad = sorted(w.grid.dnd.bad)
        row, col = bad[0]
        w.grid.viewport().repaint()
        img = w.grid.viewport().grab().toImage()
        r = w.grid.visualRect(w.grid.model().index(row, col))
        red = [x for y in range(r.top(), r.top() + 26) for x in range(r.left(), r.right())
               if abs(img.pixelColor(x, y).red() - 214) < 12 and abs(img.pixelColor(x, y).green() - 69) < 14
               and abs(img.pixelColor(x, y).blue() - 65) < 14]
        assert red
        return (sum(red) / len(red) - r.left()) / r.width()
    d = arabic_doc()
    w = window(d)
    pick_class(w, 1)
    right_in_ltr = badge_side(w)
    with lang("ar"):
        w = window(d)
        pick_class(w, 1)
        left_in_rtl = badge_side(w)
    assert right_in_ltr > 0.7 and left_in_rtl < 0.3


# --- PDF ----------------------------------------------------------------------------------------
def text_of(path):
    return subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True).stdout


def test_reports_in_every_language():
    d = arabic_doc()
    for code in ("en", "fr", "ar"):
        with lang(code):
            for kind in reports.REPORTS:
                pages = reports.build(d, kind)
                assert pages, (code, kind)
                path = Path(tempfile.mkdtemp()) / "r.pdf"
                write_pdf(pages, str(path))
                assert path.read_bytes()[:5] == b"%PDF-"


def test_report_texts_and_column_order_follow_the_language():
    d = arabic_doc()
    en = reports.teacher_list(d)[0].body
    with lang("fr"):
        fr = reports.teacher_list(d)[0]
    with lang("ar"):
        ar = reports.teacher_list(d)[0]
    heads = lambda html: re.findall(r"<th[^>]*>(.*?)</th>", html)
    assert heads(en)[0] == "Teacher" and heads(fr.body)[0] == "Enseignant"
    assert heads(ar.body)[-1] == "المعلم" and heads(ar.body)[0] == "الموضوعة"  # columns mirrored: first one last
    assert fr.title == "Enseignants et leurs cours" and ARABIC.search(ar.title)


def test_pdf_text_keeps_arabic_and_accents():
    if not shutil.which("pdftotext"):
        return
    d = arabic_doc()
    path = Path(tempfile.mkdtemp()) / "a.pdf"
    with lang("ar"):
        write_pdf(reports.build(d, "Class timetables", 1), str(path))
    out = text_of(path)
    assert ARABIC.search(out) and "Français" in out and "2026/27" in out
    with lang("fr"):
        write_pdf(reports.build(d, "Teacher hours"), str(path))
    assert "Élodie" in text_of(path) and "Heures" in text_of(path)


def test_week_start_orders_days():
    from octt.ui.newdoc_dialog import NewDocumentDialog
    d = NewDocumentDialog()
    d.start.setCurrentIndex(2)  # Sunday first
    d.boxes[6].setChecked(True)
    d.boxes[4].setChecked(False)
    d.accept()
    assert d.document.days == ["Sun", "Mon", "Tue", "Wed", "Thu"], d.document.days


def test_arabic_uses_the_bundled_font_and_english_restores_the_default():
    default = APP.font().family()
    with lang("ar"):
        assert APP.font().family() == "Cairo"
    assert APP.font().family() == default


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    # leaving through interpreter teardown segfaults ~4% of the time (PySide destroying hundreds of windows); all tests passed
    import os
    import sys
    sys.stdout.flush()
    os._exit(0)
