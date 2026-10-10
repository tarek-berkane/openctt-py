# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
import copy

from PySide6.QtGui import QUndoCommand

from octt.model import Document, Placement


class PlacementEdit(QUndoCommand):
    """Remove some placements, add others. Place = add only, unplace = remove only, move = both."""

    def __init__(self, doc: Document, remove: list[Placement], add: list[Placement], text: str, refresh):
        super().__init__(text)
        self.doc, self.remove, self.add, self.refresh = doc, remove, add, refresh

    def redo(self):
        for p in self.remove:
            self.doc.placements.remove(p)
        self.doc.placements.extend(self.add)
        self.refresh()

    def undo(self):
        for p in self.add:
            self.doc.placements.remove(p)
        self.doc.placements.extend(self.remove)
        self.refresh()


FIELDS = ("institution", "year", "days", "terms", "epgs", "eps", "teachers", "rooms", "courses", "placements", "params", "weights")


def snapshot(doc: Document) -> dict:
    return {f: copy.deepcopy(getattr(doc, f)) for f in FIELDS}


class StateEdit(QUndoCommand):
    """Any structural edit (teachers/rooms/courses/...): swap whole entity tables before <-> after."""

    def __init__(self, doc: Document, before: dict, after: dict, text: str, refresh):
        super().__init__(text)
        self.doc, self.before, self.after, self.refresh = doc, before, after, refresh

    def _set(self, state):
        for f, v in state.items():
            setattr(self.doc, f, copy.deepcopy(v))
        self.refresh()

    def redo(self):
        self._set(self.after)

    def undo(self):
        self._set(self.before)
