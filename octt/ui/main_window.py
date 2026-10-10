# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
import os

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QPalette, QShortcut, QUndoStack
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHeaderView, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
                               QStyle, QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from octt import i18n, io, ops, views
from octt.i18n import LANGUAGES, N_, t as tr
from octt.ui.properties_dialog import PropertiesDialog
from octt.commands import PlacementEdit, StateEdit, snapshot
from octt.model import Document
from octt.rules.place import bad_slots, plan_place, plan_unplace, set_locked
from octt.rules.soft import label as soft_label, score, total
from octt.ui import language
from octt.ui.dialogs import CourseDialog, EpDialog, RoomDialog, SettingsDialog, TeacherDialog
from octt.ui.grid import Block, Grid, LessonList, swatch
from octt.ui.newdoc_dialog import NewDocumentDialog
from octt.ui.report_dialog import ReportDialog
from octt.ui.solve_dialog import SolveDialog

KIND = Qt.UserRole + 1  # tree/list item -> (kind, id)
FILTER = "Timetable (*.json *.octt *.xml)"
MAX_RECENT = 8


def push_recent(recent: list[str], path: str, limit: int = MAX_RECENT) -> list[str]:
    return [path, *[p for p in recent if p != path]][:limit]


class MainWindow(QMainWindow):
    def __init__(self, doc: Document | None = None, path: str | None = None, settings: QSettings | None = None):
        super().__init__()
        self.prefs = settings or QSettings("OpenCTT", "OpenCTT")
        self.view: views.View | None = None
        self._actions: list[QAction] = []
        self.path: str | None = None
        self.undo = QUndoStack(self)
        self.undo.cleanChanged.connect(self._modified)
        self._build_widgets()
        self._build_actions()
        self.retranslate(rebuild_actions=False)
        self.restore_geometry()
        self.load(doc or Document(), path)

    # --- widgets ------------------------------------------------------------------------------
    def _build_widgets(self):
        self.tree = QTreeWidget(headerHidden=True)
        self.teachers, self.rooms = QListWidget(), QListWidget()
        self.tabs = QTabWidget()
        for w in (self.tree, self.teachers, self.rooms):
            self.tabs.addTab(w, "")  # titles are set in retranslate()
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(self._menu)
        self.todo_title = QLabel()
        bold = self.todo_title.font()
        bold.setBold(True)
        self.todo_title.setFont(bold)
        self.todo = LessonList()
        left = QWidget()
        lay = self.left_lay = QVBoxLayout(left)
        lay.addWidget(self.tabs, 3)
        lay.addWidget(self.todo_title)
        lay.addWidget(self.todo, 2)

        self.title_lbl, self.summary_lbl, self.banner = QLabel(), QLabel(), QLabel()
        f = self.title_lbl.font()
        f.setPointSizeF(f.pointSizeF() * 1.5)
        f.setBold(True)
        self.title_lbl.setFont(f)
        for lbl in (self.title_lbl, self.summary_lbl):
            lbl.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)  # follows the layout direction, even for Latin text
        self.summary_lbl.setForegroundRole(QPalette.PlaceholderText)  # palette roles, not stylesheets: they follow the theme
        self.banner.setWordWrap(True)
        self.banner.setFrameShape(QFrame.StyledPanel)
        self.banner.setMargin(7)
        self.banner.setAutoFillBackground(True)
        self.banner.setBackgroundRole(QPalette.ToolTipBase)
        self.banner.setForegroundRole(QPalette.ToolTipText)
        self.grid = Grid()
        right = QWidget()
        rl = self.right_lay = QVBoxLayout(right)
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(self.title_lbl)
        hl.addWidget(self.summary_lbl)
        rl.addWidget(head)
        rl.addWidget(self.banner)
        rl.addWidget(self.grid, 1)

        self.split = QSplitter()
        self.split.addWidget(left)
        self.split.addWidget(right)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([300, 800])
        self.split.setChildrenCollapsible(False)
        self.setCentralWidget(self.split)

        self.score_btn = QPushButton(flat=True)
        self.score_btn.clicked.connect(self.show_score)
        self.statusBar().addPermanentWidget(self.score_btn)

        self.tree.currentItemChanged.connect(lambda *_: self.refresh())
        self.teachers.currentItemChanged.connect(lambda *_: self.refresh())
        self.rooms.currentItemChanged.connect(lambda *_: self.refresh())
        self.tabs.currentChanged.connect(self._tab_changed)
        for w in (self.tree, self.teachers, self.rooms):
            w.itemDoubleClicked.connect(lambda *_: self.edit_selected())
        sc = QShortcut(QKeySequence.Delete, self.tabs, activated=self.delete_selected)
        sc.setContext(Qt.WidgetWithChildrenShortcut)

        self.todo.drag_begin.connect(self._tint)
        self.grid.drag_begin.connect(self._tint)
        self.todo.drag_end.connect(self.refresh)
        self.grid.drag_end.connect(self.refresh)
        self.grid.dropped.connect(self.place)
        self.todo.unplaced.connect(self.unplace)
        self.grid.remove.connect(self.unplace)
        self.grid.edit_course.connect(self.edit_course)
        self.grid.hint.connect(lambda t: self.statusBar().showMessage(t) if t else self.statusBar().clearMessage())
        self.grid.menu.connect(self._cell_menu)

    @property
    def language(self) -> str:
        return i18n.language()

    def set_language(self, code: str):
        """Switch the UI language live: persists the choice, mirrors the layout for Arabic, rebuilds the texts."""
        language.apply(code)
        self.prefs.setValue("language", i18n.language())
        self.retranslate()

    def retranslate(self, rebuild_actions: bool = True):
        if rebuild_actions:
            self.menuBar().clear()
            self.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            for a in self._actions:
                a.deleteLater()
            self._actions.clear()
            self._build_actions()
        # contents margins are physical (left/right), so mirror them by hand: no gap at the window edge, gap at the splitter
        rtl = i18n.is_rtl()
        self.left_lay.setContentsMargins(*((0, 6, 6, 6) if rtl else (6, 6, 0, 6)))
        self.right_lay.setContentsMargins(*((6, 6, 0, 6) if rtl else (0, 6, 6, 6)))
        for i, key in enumerate((N_("Classes"), N_("Teachers"), N_("Rooms"))):
            self.tabs.setTabText(i, tr(key))
        for w in (self.tree, self.teachers, self.rooms):
            w.setToolTip(tr("Double-click to edit · right-click for actions"))
        self.score_btn.setToolTip(tr("Soft-constraint penalty of the whole timetable (lower is better). Click for the breakdown."))
        if hasattr(self, "doc"):
            self._retitle()
            self.refresh()

    def _act(self, text, fn, keys=None, icon=None, tip=None) -> QAction:
        """`text` / `tip` are N_("...") keys; translated here so a language switch only has to rebuild the menus."""
        a = QAction(tr(text), self)
        self._actions.append(a)
        if icon:
            a.setIcon(QIcon.fromTheme(icon[0], self.style().standardIcon(icon[1])))
        if keys is not None:
            a.setShortcut(keys)
        if tip:
            a.setStatusTip(tr(tip))
        a.triggered.connect(lambda *_: fn())
        return a

    def _build_actions(self):
        S = QStyle
        new = self._act(N_("&New…"), self.new, QKeySequence.New, ("document-new", S.SP_FileIcon), N_("Start an empty timetable"))
        opn = self._act(N_("&Open…"), self.open, QKeySequence.Open, ("document-open", S.SP_DialogOpenButton))
        save = self._act(N_("&Save"), self.save, QKeySequence.Save, ("document-save", S.SP_DialogSaveButton))
        save_as = self._act(N_("Save &As…"), self.save_as, QKeySequence.SaveAs)
        pdf = self._act(N_("&Export…"), self.export_pdf, "Ctrl+P", ("document-print", S.SP_FileDialogDetailedView),
                        N_("Timetables, master timetable and lists as PDF, HTML or Excel"))
        demo = self._act(N_("Open &example"), self.open_example, tip=N_("Load a small sample timetable"))
        quit_ = self._act(N_("&Quit"), self.close, QKeySequence.Quit)
        undo = self.undo.createUndoAction(self, tr("&Undo"))
        redo = self.undo.createRedoAction(self, tr("&Redo"))
        self._actions += [undo, redo]
        undo.setShortcut(QKeySequence.Undo)
        redo.setShortcut(QKeySequence.Redo)
        undo.setIcon(QIcon.fromTheme("edit-undo", self.style().standardIcon(S.SP_ArrowBack)))
        redo.setIcon(QIcon.fromTheme("edit-redo", self.style().standardIcon(S.SP_ArrowForward)))
        edit = self._act(N_("&Edit selected…"), self.edit_selected, "F2")
        delete = self._act(N_("&Delete selected"), self.delete_selected)
        solve = self._act(N_("&Solve automatically…"), self.solve, "F5", ("system-run", S.SP_MediaPlay),
                          N_("Let the solver place the remaining lessons"))
        settings = self._act(N_("S&ettings…"), self.settings, "Ctrl+,")
        props = self._act(N_("Timetable &properties…"), self.properties)
        breakdown = self._act(N_("Score &breakdown…"), self.show_score)

        mb = self.menuBar()
        f = mb.addMenu(tr("&File"))
        self.recent_menu = QMenu(tr("Open &Recent"), self)
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        for x in (new, opn, self.recent_menu, demo, None, save, save_as, pdf, None, quit_):
            f.addSeparator() if x is None else (f.addMenu(x) if isinstance(x, QMenu) else f.addAction(x))
        e = mb.addMenu(tr("&Edit"))
        e.addActions([undo, redo])
        e.addSeparator()
        e.addActions([edit, delete, props])
        dm = mb.addMenu(tr("&Data"))
        for text, fn in ((N_("Add &group"), self.add_group), (N_("Add &class"), self.add_class),
                         (N_("Add c&ourse"), self.add_course), (N_("Add &teacher"), self.add_teacher),
                         (N_("Add &room"), self.add_room)):
            dm.addAction(self._act(text, fn))
        dm.setMinimumWidth(max(dm.fontMetrics().horizontalAdvance(a.text()) for a in dm.actions()) + 80)  # no icon/shortcut column here, so some styles size it too tight
        tm = mb.addMenu(tr("&Tools"))
        tm.addActions([solve, settings, breakdown])
        lm = tm.addMenu(tr("&Language"))  # names stay in their own script so a lost user can always find theirs
        group = QActionGroup(lm)
        for code, name in LANGUAGES.items():
            a = lm.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == self.language)
            a.triggered.connect(lambda _=False, code=code: self.set_language(code))
            group.addAction(a)
            self._actions.append(a)

        hm = mb.addMenu(tr("&Help"))
        hm.addAction(self._act(N_("About &Qt"), QApplication.aboutQt))

        tb = QToolBar(tr("Main"), self)
        self.toolbar = tb
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for x in (new, opn, save, None, undo, redo, None, solve, pdf):
            tb.addSeparator() if x is None else tb.addAction(x)
        self.addToolBar(tb)

    # --- window state -------------------------------------------------------------------------
    def restore_geometry(self):
        g, s = self.prefs.value("geometry"), self.prefs.value("splitter")
        if g:
            self.restoreGeometry(g)
        else:
            self.resize(1200, 720)
        if s:
            self.split.restoreState(s)

    def closeEvent(self, e):
        if self.maybe_save():
            self.prefs.setValue("geometry", self.saveGeometry())
            self.prefs.setValue("splitter", self.split.saveState())
            e.accept()
        else:
            e.ignore()

    def _modified(self, *_):
        self.setWindowModified(not self.undo.isClean())

    def _retitle(self):
        name = os.path.basename(self.path) if self.path else tr("Untitled")
        self.setWindowTitle(f"{name}[*] — OpenCTT")
        self._modified()

    # --- documents / files --------------------------------------------------------------------
    def load(self, doc: Document, path: str | None = None):
        self.doc, self.path = doc, path
        self.undo.clear()
        self.undo.setClean()
        self.grid.set_dims(doc.days, doc.terms)
        self._build()
        if path:
            self.prefs.setValue("recent", push_recent(self.recent(), path))
        self.refresh()
        self._retitle()

    def recent(self) -> list[str]:
        v = self.prefs.value("recent") or []
        return [v] if isinstance(v, str) else list(v)

    def _fill_recent(self):
        self.recent_menu.clear()
        files = [p for p in self.recent() if os.path.exists(p)]
        for p in files:
            self.recent_menu.addAction(self._act(os.path.basename(p), lambda p=p: self.open(p), tip=p))
        self.recent_menu.setEnabled(bool(files))

    def maybe_save(self) -> bool:
        """True when it is OK to throw the current document away (saved, discarded, or unchanged)."""
        if self.undo.isClean():
            return True
        name = os.path.basename(self.path) if self.path else tr("Untitled")
        box = QMessageBox(QMessageBox.Warning, tr("Unsaved changes"), tr("Save changes to {name}?", name=name),
                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
        box.setInformativeText(tr("Your changes will be lost if you don't save them."))
        r = box.exec()
        return self.save() if r == QMessageBox.Save else r == QMessageBox.Discard

    def new(self):
        if self.maybe_save() and (dlg := NewDocumentDialog(self)).exec():
            self.load(dlg.document)

    def open(self, path: str | None = None):
        if not self.maybe_save():
            return
        path = path or QFileDialog.getOpenFileName(self, tr("Open timetable"), os.path.dirname(self.path or ""), FILTER)[0]
        if not path:
            return
        try:
            doc = io.load(path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            QMessageBox.critical(self, tr("Cannot open file"),
                                 tr("{name} is not a valid timetable.", name=os.path.basename(path)) + f"\n\n{e}")
            return
        imported = not path.lower().endswith(".json") and open(path, "rb").read(64).lstrip(b"\xef\xbb\xbf \r\n").startswith(b"<")
        self.load(doc, None if imported else path)  # an OpenCTT file is converted: Save asks for a new .json, never overwrites the original
        if imported:
            self.undo.resetClean()
            self._retitle()
            self.statusBar().showMessage(tr("Imported {name}. Save it as a new file.", name=os.path.basename(path)), 8000)

    def open_example(self):
        from octt.demo import demo
        if self.maybe_save():
            self.load(demo())

    def save(self) -> bool:
        return self._write(self.path) if self.path else self.save_as()

    def save_as(self) -> bool:
        path = QFileDialog.getSaveFileName(self, tr("Save timetable"), self.path or "timetable.json", FILTER)[0]
        if not path:
            return False
        return self._write(path if path.endswith(".json") else path + ".json")

    def _write(self, path: str) -> bool:
        try:
            io.save(self.doc, path)
        except OSError as e:
            QMessageBox.critical(self, tr("Cannot save"), f"{path}\n\n{e}")
            return False
        self.path = path
        self.prefs.setValue("recent", push_recent(self.recent(), path))
        self.undo.setClean()
        self._retitle()
        self.statusBar().showMessage(tr("Saved {path}", path=path), 4000)
        return True

    def export_pdf(self):
        dlg = ReportDialog(self, self.doc, self.view[1] if self.view and self.view[0] == "class" else None)
        if dlg.exec() and dlg.saved:
            self.statusBar().showMessage(tr("Saved {path}", path=dlg.saved), 6000)

    # --- tree / lists -------------------------------------------------------------------------
    def _build(self):
        """(Re)create the tree and the teacher / room lists; keeps what was selected."""
        d, keep = self.doc, self.view
        for w in (self.tree, self.teachers, self.rooms):
            w.blockSignals(True)
        self.tree.clear()
        self.items, self.ep_items = {}, {}
        for g in d.epgs.values():
            gi = QTreeWidgetItem(self.tree, [g.name])
            gi.setData(0, KIND, ("epg", g.id))
            for ep in (x for x in d.eps.values() if x.epg_id == g.id):
                ei = self.ep_items[ep.id] = QTreeWidgetItem(gi, [ep.name])
                ei.setData(0, KIND, ("ep", ep.id))
                for c in (c for c in d.courses.values() if c.ep_id == ep.id):
                    self.items[c.id] = ci = QTreeWidgetItem(ei)
                    ci.setIcon(0, swatch(views.color(c.id)))
                    ci.setData(0, KIND, ("course", c.id))
        self.tree.expandAll()
        for w, rows, kind in ((self.teachers, [(t.id, t.name) for t in d.teachers.values()], "teacher"),
                              (self.rooms, [(r.id, f"{r.name} · {r.capacity} seats") for r in d.rooms.values()], "room")):
            w.clear()
            for id_, text in rows:
                QListWidgetItem(text, w).setData(KIND, (kind, id_))
        # restore the selection of the view that was open, else pick something so the grid is never blank
        pick = {"class": (self.tree, self.ep_items), "teacher": (self.teachers, None), "room": (self.rooms, None)}
        if keep and keep[0] == "class" and keep[1] in self.ep_items:
            self.tree.setCurrentItem(self.ep_items[keep[1]])
        elif keep and keep[0] in ("teacher", "room"):
            lst = pick[keep[0]][0]
            for i in range(lst.count()):
                if lst.item(i).data(KIND)[1] == keep[1]:
                    lst.setCurrentRow(i)
        elif self.ep_items:
            self.tree.setCurrentItem(next(iter(self.ep_items.values())))
        for w in (self.tree, self.teachers, self.rooms):
            w.blockSignals(False)

    def structure_changed(self):
        self.grid.set_dims(self.doc.days, self.doc.terms)
        self._build()
        self.refresh()

    def _tab_changed(self, i: int):
        w = self.tabs.widget(i)
        if isinstance(w, QListWidget) and w.currentRow() < 0 and w.count():
            w.setCurrentRow(0)  # emits currentItemChanged -> refresh
        else:
            self.refresh()

    def _current_view(self) -> views.View | None:
        i = self.tabs.currentIndex()
        if i == 0:
            it = self.tree.currentItem()
            kind, id_ = it.data(0, KIND) if it else (None, None)
            if kind == "course":
                return "class", self.doc.courses[id_].ep_id
            return ("class", id_) if kind == "ep" else None
        it = (self.teachers, self.rooms)[i - 1].currentItem()
        return (("teacher", "room")[i - 1], it.data(KIND)[1]) if it else None

    def _current(self):
        w = self.tabs.currentWidget()
        it = w.currentItem()
        if it:
            return it.data(0, KIND) if w is self.tree else it.data(KIND)

    # --- the view (grid, to-place list, header) -----------------------------------------------
    def refresh(self):
        d = self.doc
        self.view = v = self._current_view()
        for cid, item in self.items.items():
            left = d.unallocated(cid)
            item.setText(0, tr("{name}  · {n} to place", name=views.course_name(d.courses[cid]), n=left) if left > 0
                         else views.course_name(d.courses[cid]))
        for eid, item in self.ep_items.items():
            left = sum(max(d.unallocated(c.id), 0) for c in d.courses.values() if c.ep_id == eid)
            item.setText(0, tr("{name}  · {n} to place", name=d.eps[eid].name, n=left) if left else d.eps[eid].name)

        for lst, kind in ((self.teachers, "teacher"), (self.rooms, "room")):
            for i in range(lst.count()):
                it = lst.item(i)
                id_ = it.data(KIND)[1]
                if kind == "teacher":
                    left = sum(max(d.unallocated(c.id), 0) for c in d.courses.values() if c.teacher_id == id_)
                    it.setText(tr("{name}  · {n} to place", name=d.teachers[id_].name, n=left) if left else d.teachers[id_].name)
                else:
                    it.setText(tr("{name} · {n} seats", name=d.rooms[id_].name, n=d.rooms[id_].capacity))

        cells: dict = {}
        if v:
            for p in views.lessons(d, v):
                t, det = views.cell(d, v, p)
                cells.setdefault((p.term, p.day), []).append(
                    Block(p.course_id, t, det, views.color(p.course_id), views.tooltip(d, p), p.locked))
        self.grid.fill(cells, views.blocked(d, v) if v else set())
        self.grid.setEnabled(v is not None)

        ids = views.todo(d, v) if v else []
        self.todo.fill([(c, views.todo_label(d, v, c), views.color(c)) for c in ids])
        self.todo.empty_text = (tr("Select a class, teacher or room") if not v else
                                tr("Nothing left to place") if not d.courses else
                                tr("Nothing left to place here ✓"))
        self.todo_title.setText(tr("To place ({n}) — drag onto the grid", n=len(ids)) if ids else tr("To place ({n})", n=0))

        self.title_lbl.setText(views.title(d, v) if v else tr("Nothing selected"))
        self.summary_lbl.setText(views.summary(d, v) if v else
                                 tr("Pick a class, teacher or room on the side panel to see its timetable."))
        hint = views.next_step(d)
        self.banner.setText(hint or "")
        self.banner.setVisible(bool(hint))
        pens = score(d)
        self.score_btn.setText(tr("Penalty {n} · {m} issue(s)", n=f"{total(pens):g}", m=len(pens)) if pens
                               else tr("Penalty {n} ✓", n=f"{total(pens):g}"))

    def _room(self) -> int | None:
        return self.view[1] if self.view and self.view[0] == "room" else None

    def _tint(self, cid, src):
        """A drag started: tell the grid which cells accept the lesson (green) and which refuse it (red)."""
        title, detail = views.preview(self.doc, self.view, cid)
        self.grid.show_drag(Block(cid, title, detail, views.color(cid)), src, bad_slots(self.doc, cid, src, self._room()))
        self.todo.set_target(src is not None)  # a placed lesson can be dropped on the list to take it off

    # --- data dialogs -------------------------------------------------------------------------
    def apply(self, text, mutate) -> bool:
        problems = ops.trial(self.doc, mutate)
        if problems:
            self.statusBar().showMessage("; ".join(problems[:3]), 6000)
            return False
        before = snapshot(self.doc)
        mutate(self.doc)
        self.undo.push(StateEdit(self.doc, before, snapshot(self.doc), text, self.structure_changed))
        return True

    def _group_id(self):
        sel = self.tree.currentItem()
        while sel and sel.data(0, KIND)[0] != "epg":
            sel = sel.parent()
        if sel:
            return sel.data(0, KIND)[1]
        names = {g.name: g.id for g in self.doc.epgs.values()}
        if not names:
            self.statusBar().showMessage(tr("Add a group first"), 4000)
            return None
        if len(names) == 1:
            return next(iter(names.values()))
        name, ok = QInputDialog.getItem(self, tr("Class"), tr("Group:"), list(names), editable=False)
        return names[name] if ok else None

    def add_group(self):
        name, ok = QInputDialog.getText(self, tr("Add group"), tr("Name (a grade, year or faculty):"))
        if ok:
            self.apply(tr("Add group"), lambda d: ops.add_group(d, name.strip()))

    def add_class(self):
        if (gid := self._group_id()) is None:
            return
        name, ok = QInputDialog.getText(self, tr("Add class"), tr("Name (e.g. 5A):"))
        if ok:
            self.apply(tr("Add class"), lambda d: ops.add_ep(d, gid, name.strip()))

    def add_course(self):
        if not self.doc.eps or not self.doc.teachers:
            self.statusBar().showMessage(tr("A course needs a class and a teacher first"), 4000)
        elif (dlg := CourseDialog(self, self.doc, ep_id=self.view[1] if self.view and self.view[0] == "class" else None)).exec():
            self.apply(tr("Add course"), lambda d: ops.save_course(d, dlg.entity))

    def add_teacher(self):
        if (dlg := TeacherDialog(self, self.doc)).exec():
            self.apply(tr("Add teacher"), lambda d: ops.save_teacher(d, dlg.entity))

    def add_room(self):
        if (dlg := RoomDialog(self, self.doc)).exec():
            self.apply(tr("Add room"), lambda d: ops.save_room(d, dlg.entity))

    def edit_course(self, cid: int):
        if (dlg := CourseDialog(self, self.doc, self.doc.courses[cid])).exec():
            self.apply(tr("Edit course"), lambda d: ops.save_course(d, dlg.entity))

    def edit_selected(self):
        kind, id_ = self._current() or (None, None)
        doc = self.doc
        if kind == "course":
            self.edit_course(id_)
        elif kind == "ep" and (dlg := EpDialog(self, doc, doc.eps[id_])).exec():
            self.apply(tr("Edit class"), lambda d: ops.save_ep(d, dlg.entity))
        elif kind == "teacher" and (dlg := TeacherDialog(self, doc, doc.teachers[id_])).exec():
            self.apply(tr("Edit teacher"), lambda d: ops.save_teacher(d, dlg.entity))
        elif kind == "room" and (dlg := RoomDialog(self, doc, doc.rooms[id_])).exec():
            self.apply(tr("Edit room"), lambda d: ops.save_room(d, dlg.entity))

    def delete_selected(self):
        kind, id_ = self._current() or (None, None)
        fn = {"course": ops.delete_course, "teacher": ops.delete_teacher, "room": ops.delete_room}.get(kind)
        if not fn:
            return
        if kind == "course" and any(p.course_id == id_ for p in self.doc.placements):
            if QMessageBox.question(self, tr("Delete"), tr("This course has placed lessons. Delete anyway?")) != QMessageBox.Yes:
                return
        self.apply(tr({"course": N_("Delete course"), "teacher": N_("Delete teacher"), "room": N_("Delete room")}[kind]),
                   lambda d: fn(d, id_))

    def _menu(self, pos):
        w = self.tabs.currentWidget()
        m = QMenu(self)
        kind = (self._current() or (None,))[0]
        add = {0: [(N_("Add group…"), self.add_group), (N_("Add class…"), self.add_class), (N_("Add course…"), self.add_course)],
               1: [(N_("Add teacher…"), self.add_teacher)], 2: [(N_("Add room…"), self.add_room)]}[self.tabs.currentIndex()]
        for text, fn in add:
            m.addAction(self._act(text, fn))
        if kind in ("course", "teacher", "room", "ep"):
            m.addSeparator()
            m.addAction(self._act(N_("Edit…"), self.edit_selected))
            if kind != "ep":
                m.addAction(self._act(N_("Delete"), self.delete_selected))
        m.exec(w.viewport().mapToGlobal(pos))

    # --- tools --------------------------------------------------------------------------------
    def settings_dialog(self):
        return SettingsDialog(self, self.doc)

    def settings(self):
        dlg = self.settings_dialog()
        if dlg.exec() and dlg.values() != (self.doc.params, self.doc.weights):
            before = snapshot(self.doc)
            self.doc.params, self.doc.weights = dlg.values()
            self.undo.push(StateEdit(self.doc, before, snapshot(self.doc), tr("Change settings"), self.refresh))

    def properties_dialog(self):
        return PropertiesDialog(self.doc, self)

    def properties(self):
        dlg = self.properties_dialog()
        if not dlg.exec():
            return
        n = len(self.doc.placements)
        if self.apply(tr("Timetable properties"), lambda d: ops.set_schedule(
                d, dlg.institution.text().strip(), dlg.year.text().strip(), dlg.days(), dlg.terms())):
            if len(self.doc.placements) < n:
                self.statusBar().showMessage(tr("{n} lesson(s) unplaced", n=n - len(self.doc.placements)), 6000)

    def solve(self):
        dlg = SolveDialog(self, self.doc)
        if dlg.exec() and dlg.result:
            res = dlg.result
            remove = list(res.removes)
            self.undo.push(PlacementEdit(self.doc, remove, res.placements, tr("Automatic timetable"), self.refresh))

    def show_score(self):
        pens = sorted(score(self.doc), key=lambda p: -p.amount)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Score breakdown — penalty {n} (lower is better)", n=f"{total(pens):g}"))
        dlg.resize(620, 420)
        tbl = QTableWidget(len(pens), 4, dlg)
        tbl.setHorizontalHeaderLabels([tr("Constraint"), tr("Who"), tr("Penalty"), tr("Detail")])
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for r, p in enumerate(pens):
            for c, v in enumerate((soft_label(p.key), p.subject, f"{p.amount:g}", p.why)):
                tbl.setItem(r, c, QTableWidgetItem(v))
        QVBoxLayout(dlg).addWidget(tbl)
        dlg.exec()

    # --- placing lessons ----------------------------------------------------------------------
    def place(self, cid, src, term, day):
        remove, add, errors = plan_place(self.doc, cid, term, day, src, self._room())
        if errors:
            self.statusBar().showMessage("; ".join(errors), 5000)
        elif add:
            text = tr("Move {course}" if src else "Place {course}", course=views.course_name(self.doc.courses[cid]))
            self.undo.push(PlacementEdit(self.doc, remove, add, text, self.refresh))

    def unplace(self, cid, src):
        remove = plan_unplace(self.doc, cid, *src)
        if any(p.locked for p in remove):
            self.statusBar().showMessage(tr("locked: unlock it first"), 5000)
        elif remove:
            self.undo.push(PlacementEdit(self.doc, remove, [],
                                         tr("Remove {course}", course=views.course_name(self.doc.courses[cid])), self.refresh))

    def lock(self, cid, term, day, locked):
        before = snapshot(self.doc)
        set_locked(self.doc, cid, term, day, locked)
        name = views.course_name(self.doc.courses[cid])
        self.undo.push(StateEdit(self.doc, before, snapshot(self.doc),
                                 tr("Lock {course}" if locked else "Unlock {course}", course=name), self.refresh))

    def cell_actions(self, row: int, col: int, cid: int | None) -> list[tuple[str, bool, object]]:
        """What the right-click menu of a grid cell offers: (text, enabled, callback)."""
        if cid is not None:
            locked = any(p.locked for p in plan_unplace(self.doc, cid, row, col))
            return [(tr("Unlock lesson") if locked else tr("Lock lesson"), True, lambda: self.lock(cid, row, col, not locked)),
                    (tr("Remove from timetable"), True, lambda: self.unplace(cid, (row, col))),
                    (tr("Edit course…"), True, lambda: self.edit_course(cid))]
        out, seen = [], set()
        for c in views.todo(self.doc, self.view) if self.view else []:
            if c in seen:
                continue
            seen.add(c)
            errs = plan_place(self.doc, c, row, col, None, self._room())[2]
            label = views.todo_label(self.doc, self.view, c)
            out.append((tr("Place {label}", label=label) if not errs else tr("{label} — {reason}", label=label, reason=errs[0]), not errs,
                        lambda c=c: self.place(c, None, row, col)))
        return out or [(tr("Nothing to place"), False, lambda: None)]

    def _cell_menu(self, row, col, cid, gpos):
        m = QMenu(self)
        for text, enabled, fn in self.cell_actions(row, col, cid):
            a = m.addAction(text)
            a.setEnabled(enabled)
            a.triggered.connect(lambda *_, fn=fn: fn())
        m.exec(gpos)
