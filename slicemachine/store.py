"""Where Slice Machine keeps its settings and files on this computer (the shared look modules use
settings() and data_dir() from here, the same way they do in Kontrolleur)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings

APP = "SliceMachine"
REPO = Path(__file__).resolve().parents[1]          # the slice-machine checkout
SRC = REPO / "src"                                   # the command-line tools the app drives


def settings() -> QSettings:
    return QSettings(APP, APP)


def data_dir() -> Path:
    if os.environ.get("SLICEMACHINE_DATA"):
        d = Path(os.environ["SLICEMACHINE_DATA"])
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / APP
    else:
        d = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "slicemachine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def inherit_kontrolleur_look(force: bool = False) -> bool:
    """Take Kontrolleur's appearance (colours, fonts, text size), so the apps look alike.
    Without `force` only on the first start, before a look was picked here."""
    mine = settings()
    if mine.value("appearance") and not force:
        return False
    theirs = QSettings("Kontrolleur", "Kontrolleur").value("appearance")
    if not theirs:
        return False
    mine.setValue("appearance", theirs)
    return True


def kontrolleur_look():
    return QSettings("Kontrolleur", "Kontrolleur").value("appearance")


class NotesStore:
    """draw.note_badge (shared with Kontrolleur) formats notes with this."""

    @staticmethod
    def one_line(s: str) -> str:
        return s.replace("\n", " ").replace("  ", " ")
