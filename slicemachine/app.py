"""Slice Machine main window: one tab per tool, built like Kontrolleur (bar, stage, side panel, status)."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QDialog, QFrame, QHBoxLayout, QMainWindow,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from . import audition, engine, store, theme
from . import widgets as W
from .stage import Stage
from .theme import BOLD, HEAVY, REGULAR, SEMIBOLD, Theme

ICON = Path(__file__).resolve().parent / "icon.png"


class Status:
    def __init__(self, kind: str, text: str):
        self.kind, self.text, self.time = kind, text, dt.datetime.now()


# ── background work ─────────────────────────────────────────────────────────────────────────────

class _Signals(QObject):
    line = Signal(str)
    step = Signal(str)
    done = Signal(object, object)


class _Job(QRunnable):
    def __init__(self, fn: Callable, log: bool):
        super().__init__()
        self.fn, self.log = fn, log
        self.signals = _Signals()

    def run(self):
        try:
            if self.log:
                with engine.capture(self.signals.line.emit):
                    r = self.fn(self.signals.step.emit)
            else:
                r = self.fn()
            self.signals.done.emit(r, None)
        except BaseException as e:  # noqa: BLE001 — shown in the status line and the log; a tool's
            if isinstance(e, SystemExit):  # sys.exit() must not leave the app stuck "busy"
                e = RuntimeError(str(e) or "the tool stopped")
            if self.log:
                for ln in traceback.format_exc().rstrip().splitlines():
                    self.signals.line.emit(ln)
            self.signals.done.emit(None, e)


_jobs = set()


def background(fn: Callable, done: Callable, log: bool = False, on_line=None, on_step=None):
    job = _Job(fn, log)
    _jobs.add(job)
    if on_line:
        job.signals.line.connect(on_line)
    if on_step:
        job.signals.step.connect(on_step)

    def finish(r, e):
        _jobs.discard(job)
        done(r, e)

    job.signals.done.connect(finish)
    job.setAutoDelete(False)
    QThreadPool.globalInstance().start(job)


# ── window ──────────────────────────────────────────────────────────────────────────────────────

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Slice Machine")
        if ICON.exists():
            self.setWindowIcon(QIcon(str(ICON)))
        self.s = store.settings()
        self.busy = False
        self.status = Status("info", "")
        self.reveal_path: Optional[str] = None
        self._waves: Dict[object, object] = {}        # key → Wave | "loading" | Exception
        self.setAcceptDrops(True)

        from .tabs import grid, jungle, merge, nerdseq, slicer, split
        tools = [slicer.SlicerTool(self), merge.MergeTool(self), split.SplitTool(self),
                 nerdseq.NerdseqTool(self), grid.GridTool(self)]
        if engine.jungle_available():
            tools.insert(1, jungle.JungleTool(self))
        self.tools = {t.key: t for t in tools}
        self.mode = os.environ.get("SLICEMACHINE_MODE") or self.s.value("mode", "slicer")
        if self.mode not in self.tools:
            self.mode = "slicer"

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.bar = QWidget()
        self.bar.setObjectName("bar")
        self.bar.setAttribute(Qt.WA_StyledBackground, True)
        v.addWidget(self.bar)
        v.addWidget(W.divider())
        self.pages = QStackedWidget()
        v.addWidget(self.pages, 1)
        self.log_wrap = QWidget()
        lw = QVBoxLayout(self.log_wrap)
        lw.setContentsMargins(0, 0, 0, 0)
        lw.setSpacing(0)
        lw.addWidget(W.divider())
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setMaximumBlockCount(5000)
        self.log.setFixedHeight(190)
        lw.addWidget(self.log)
        self.log_wrap.setVisible(self.s.value("logOpen", "false") in (True, "true"))
        v.addWidget(self.log_wrap)
        v.addWidget(W.divider())
        self.status_bar = QWidget()
        self.status_bar.setObjectName("status")
        self.status_bar.setAttribute(Qt.WA_StyledBackground, True)
        v.addWidget(self.status_bar)

        self._build_pages()
        self._build_bar()
        self._build_status()
        self._shortcuts()
        self.apply_appearance()
        self.resize(1400, 840)
        self.setMinimumSize(980, 640)
        QTimer.singleShot(0, self._startup)

    # ── pages ──
    def _build_pages(self):
        self.tabs = {}
        for key, tool in self.tools.items():
            page = QWidget()
            h = QHBoxLayout(page)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            stage = Stage(tool.drawing)
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(18, 14, 18, 14)
            hl.addWidget(stage)
            holder.setStyleSheet("background: transparent;")
            h.addWidget(holder, 1)
            h.addWidget(W.vdivider())
            tab0 = os.environ.get("SLICEMACHINE_TAB") if os.environ.get("SLICEMACHINE_TAB") in tool.panel_tabs else None
            insp = W.Inspector(list(tool.panel_tabs), lambda t, col, tool=tool: tool.build_panel(t, col), tab0)
            h.addWidget(insp)
            self.pages.addWidget(page)
            self.tabs[key] = (page, stage, insp)
        self.pages.setCurrentWidget(self.tabs[self.mode][0])

    @property
    def tool(self):
        return self.tools[self.mode]

    @property
    def stage(self) -> Stage:
        return self.tabs[self.mode][1]

    @property
    def inspector(self) -> W.Inspector:
        return self.tabs[self.mode][2]

    def changed(self, rebuild: bool = False):
        """A tool's state changed: redraw its stage (and its panel)."""
        self.stage.update()
        if rebuild:
            self.inspector.rebuild()
        self._update_bar()

    def redraw(self):
        for _, stage, _ in self.tabs.values():
            stage.update()

    # ── bar ──
    def _build_bar(self):
        h = QHBoxLayout(self.bar)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(10)
        tb = QVBoxLayout()
        tb.setSpacing(1)
        self.title_lb = W.label("Slice Machine", 17, BOLD, "title")
        self.sub_lb = W.label("→ ER-301 · SSP GRID · NerdSEQ", 10, SEMIBOLD, "mono", Theme.dim, tracking=1)
        tb.addWidget(self.title_lb)
        tb.addWidget(self.sub_lb)
        h.addLayout(tb)
        h.addSpacing(8)
        self.mode_seg = W.Segmented([(k, t.label) for k, t in self.tools.items()], self.mode, self.set_mode,
                                    tips={k: t.primary_tip for k, t in self.tools.items()})
        h.addWidget(self.mode_seg)
        h.addStretch(1)
        self.log_btn = QPushButton("Log")
        self.log_btn.setToolTip("What the tools printed while working (Ctrl+L)")
        self.log_btn.setCheckable(True)
        self.log_btn.setChecked(self.log_wrap.isVisible())
        self.log_btn.clicked.connect(self.toggle_log)
        h.addWidget(self.log_btn)
        self.look_btn = QPushButton("Look")
        self.look_btn.setToolTip("Appearance: colours, fonts, text size (shared presets with Kontrolleur)")
        self.look_btn.clicked.connect(lambda: AppearanceDialog(self).show())
        h.addWidget(self.look_btn)
        self.sec_btn = QPushButton("")
        self.sec_btn.clicked.connect(self.secondary_clicked)
        h.addWidget(self.sec_btn)
        self.run_btn = QPushButton("")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self.run_clicked)
        h.addWidget(self.run_btn)
        for b in (self.log_btn, self.look_btn, self.sec_btn, self.run_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
        self._update_bar()

    def _update_bar(self):
        if not hasattr(self, "run_btn"):
            return
        t = self.tool
        self.run_btn.setText(t.primary)
        ok, why = t.can_run()
        self.run_btn.setEnabled(ok and not self.busy)
        self.run_btn.setToolTip((t.primary_tip + " (Ctrl+Return)") if ok else why)
        self.sec_btn.setVisible(bool(t.secondary))
        if t.secondary:
            self.sec_btn.setText(t.secondary)
            self.sec_btn.setToolTip(t.secondary_tip + " (Ctrl+P)")
            self.sec_btn.setEnabled(ok and not self.busy)
        self.sub_lb.setText(t.subtitle or "→ ER-301 · SSP GRID · NerdSEQ")

    def resizeEvent(self, ev):
        self.sub_lb.setVisible(self.width() >= 1200)
        super().resizeEvent(ev)

    # ── status line ──
    def _build_status(self):
        h = QHBoxLayout(self.status_bar)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(8)
        self.st_icon = W.label("ⓘ", 13)
        self.st_text = W.label("", 12)
        self.st_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.st_show = W.small_button("Show files", lambda: self.reveal(self.reveal_path))
        self.st_show.setVisible(False)
        self.st_time = W.label("", 11, REGULAR, "mono", Theme.dim)
        h.addWidget(self.st_icon)
        h.addWidget(self.st_text, 1)
        h.addWidget(self.st_show)
        h.addWidget(self.st_time)
        self._spin = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick)
        self._spin_timer.start(120)

    def _tick(self):
        if self.busy:
            self._spin = (self._spin + 1) % 8
            self.st_icon.setText("⠋⠙⠹⠸⠼⠴⠦⠧"[self._spin])
            self.st_icon.setStyleSheet(f"color: {W.css(Theme.dim)}")

    def set_status(self, kind: str, text: str, reveal: Optional[str] = None):
        self.status = Status(kind, text)
        icon, col = {"info": ("ⓘ", Theme.dim), "ok": ("✓", Theme.special), "warn": ("⚠", Theme.trig),
                     "error": ("✕", QColor.fromRgbF(1, 0.38, 0.38))}[kind]
        if not self.busy:
            self.st_icon.setText(icon)
        self.st_icon.setStyleSheet(f"color: {W.css(col)}; background: transparent;")
        self.st_text.setText(text)
        self.st_text.setToolTip(text)
        self.st_time.setText(self.status.time.strftime("%H:%M"))
        self.reveal_path = reveal
        self.st_show.setVisible(bool(reveal) and not self.busy)

    def set_busy(self, b: bool):
        self.busy = b
        self._update_bar()
        self.st_show.setVisible(bool(self.reveal_path) and not b)
        if not b:
            self.set_status(self.status.kind, self.status.text, self.reveal_path)

    # ── log ──
    def toggle_log(self, on: Optional[bool] = None):
        if not isinstance(on, bool):
            on = not self.log_wrap.isVisible()
        self.log_wrap.setVisible(on)
        self.log_btn.setChecked(on)
        self.s.setValue("logOpen", on)

    def log_line(self, line: str):
        self.log.appendPlainText(line)
        self.log.moveCursor(QTextCursor.End)

    # ── running a tool ──
    def run_tool(self, title: str, fn: Callable, done: Callable):
        """Runs fn(step) in the background with the log attached; done(result, error) afterwards."""
        if self.busy:
            return
        self.set_busy(True)
        self.reveal_path = None
        self.log_line("")
        self.log_line(f"── {title} · {dt.datetime.now():%H:%M:%S} " + "─" * 40)
        self.set_status("info", title + " …")

        def step(s):
            self.set_status("info", s + " …")

        def finish(r, e):
            self.busy = False
            try:
                if e is not None:
                    self.log_line(f"✕ {e}")
                    self.set_status("error", f"{title} failed: {e}  (details in the log)")
                else:
                    done(r)
            finally:
                self.set_busy(False)
                self.redraw()

        background(fn, finish, log=True, on_line=self.log_line, on_step=step)

    def wave(self, key, loader: Callable, on_ready: Optional[Callable] = None):
        """A waveform for the stage, loaded in the background. None while loading, an Exception if it failed."""
        w = self._waves.get(key)
        if w == "loading":
            return None
        if w is not None:
            return w
        self._waves[key] = "loading"

        def done(r, e):
            self._waves[key] = e if e is not None else r
            if len(self._waves) > 60:
                for k in list(self._waves)[:20]:
                    if self._waves[k] != "loading":
                        self._waves.pop(k, None)
            if on_ready:
                on_ready()
            self.redraw()

        background(loader, done)
        return None

    def forget_waves(self):
        self._waves = {k: v for k, v in self._waves.items() if v == "loading"}

    # ── tabs ──
    def set_mode(self, mode: str):
        if mode == self.mode:
            return
        audition.stop()
        self.mode = mode
        self.s.setValue("mode", mode)
        self.mode_seg.set_current(mode)
        self.pages.setCurrentWidget(self.tabs[mode][0])
        self.tool.shown()
        self.inspector.rebuild()
        self._update_bar()

    def run_clicked(self):
        if self.busy:
            return
        ok, why = self.tool.can_run()
        if not ok:
            return self.set_status("warn", why)
        self.tool.run()

    def secondary_clicked(self):
        if self.busy or not self.tool.secondary:
            return
        ok, why = self.tool.can_run()
        if not ok:
            return self.set_status("warn", why)
        self.tool.run_secondary()

    def _startup(self):
        background(engine.warm_up, lambda r, e: None)
        for t in self.tools.values():
            t.shown()
        self.inspector.rebuild()
        self._update_bar()
        if not self.status.text:
            self.set_status("info", "Pick files on the right, then press “" + self.tool.primary.strip("▶ ") + "”. "
                            "Drop audio files or folders onto the window to add them.")
        snap = os.environ.get("SLICEMACHINE_SNAPSHOT")
        if snap:
            QTimer.singleShot(int(float(os.environ.get("SLICEMACHINE_WAIT", "2")) * 1000), lambda: self._snapshot(snap))

    def _snapshot(self, path: str):
        w, h = (int(x) for x in os.environ.get("SLICEMACHINE_SIZE", "1400x840").split("x"))
        self.resize(w, h)
        QApplication.processEvents()
        QTimer.singleShot(300, lambda: (self.grab().save(path), QApplication.quit()))

    def _shortcuts(self):
        def sc(keys, fn):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(Qt.ApplicationShortcut)
            s.activated.connect(fn)

        sc("Ctrl+Return", self.run_clicked)
        sc("Ctrl+Enter", self.run_clicked)
        sc("Ctrl+P", self.secondary_clicked)
        sc("Ctrl+L", lambda: self.toggle_log())
        sc("Escape", audition.stop)
        for k, key in enumerate(self.tools, 1):
            sc(f"Ctrl+{k}", lambda key=key: self.set_mode(key))
        sc(QKeySequence.ZoomIn, lambda: self.stage.step(1.25))
        sc("Ctrl+=", lambda: self.stage.step(1.25))
        sc(QKeySequence.ZoomOut, lambda: self.stage.step(1 / 1.25))
        sc("Ctrl+0", lambda: self.stage.reset())

    def keyPressEvent(self, ev):
        # Space plays (only when no text field has the key: those keep their spaces)
        if ev.key() == Qt.Key_Space and not ev.modifiers():
            self.tool.space()
            return
        super().keyPressEvent(ev)

    # ── drag & drop ──
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths and hasattr(self.tool, "dropped"):
            self.tool.dropped(paths)
            ev.acceptProposedAction()

    # ── misc ──
    def reveal(self, path: Optional[str]):
        if not path:
            return
        if os.path.isfile(path) and sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
            return
        d = path if os.path.isdir(path) else os.path.dirname(path)
        if sys.platform == "darwin":
            subprocess.Popen(["open", d])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", d])
        else:
            os.startfile(d)   # noqa

    def play(self, path: str, start: int, end: int, label: str):
        err = audition.play(path, start, end)
        if err:
            self.set_status("warn", err)
        else:
            self.set_status("info", f"▶ {label}   (Space plays it again, Esc stops)")

    def closeEvent(self, ev):
        audition.cleanup()
        super().closeEvent(ev)

    def apply_appearance(self):
        QApplication.instance().setFont(Theme.font(12))
        QApplication.instance().setStyleSheet(theme.A.stylesheet() + f"""
            QPlainTextEdit#log {{ background: {W.css(Theme.c('bg', 0.9))}; border: none; border-radius: 0;
                padding: 6px 12px; color: {W.css(Theme.dim)}; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {W.css(Theme.c('dim', 0.7))};
                border-radius: 4px; background: {W.css(Theme.c('bg', 0.6))}; }}
            QCheckBox::indicator:hover {{ border: 1px solid {W.css(Theme.c('cv', 0.8))}; }}
            QCheckBox::indicator:checked {{ background: {W.css(Theme.c('cv', 0.85))}; border: 1px solid {W.css(Theme.c('cv'))};
                image: url("{_check_svg()}"); }}""")
        self.log.setFont(Theme.font(10.5, REGULAR, "mono"))
        self.title_lb.setFont(Theme.font(17, BOLD, "title"))
        self.title_lb.setStyleSheet(f"color: {W.css(Theme.ink)}")
        self.sub_lb.setFont(Theme.font(10, SEMIBOLD, "mono"))
        self.sub_lb.setStyleSheet(f"color: {W.css(Theme.dim)}")
        self.st_time.setStyleSheet(f"color: {W.css(Theme.dim)}")
        for _, stage, insp in self.tabs.values():
            stage.restyle()
            stage.update()
            insp.rebuild()
        self.set_status(self.status.kind, self.status.text, self.reveal_path)


def _check_svg() -> str:
    """A tick in the background colour, for ticked checkboxes (like theme.py's arrows)."""
    col = Theme.bg
    f = store.data_dir() / "ui" / f"check-{col.name()[1:]}.svg"
    if not f.exists():
        f.parent.mkdir(exist_ok=True)
        f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">'
                     f'<polyline points="3,7.5 6,10.5 11,4" fill="none" stroke="{col.name()}" stroke-width="2.2" '
                     f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return f.as_posix()


class AppearanceDialog(QDialog):
    """Kontrolleur's appearance panel, plus taking over Kontrolleur's current look."""

    def __init__(self, main: Main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Appearance")
        self.setMinimumSize(400, 560)
        self.resize(400, 680)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        outer.addWidget(sc)
        self.sc = sc
        from PySide6.QtGui import QFontDatabase
        self.families = sorted(set(QFontDatabase.families()))
        self.fill()

    def fill(self):
        A = theme.A
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 18, 18, 18)
        v.setSpacing(12)
        v.addWidget(W.label("Appearance", 20, BOLD))
        presets = QComboBox()
        presets.addItem("Choose a preset …")
        for name, _ in theme.PRESETS:
            presets.addItem(name)
        presets.currentIndexChanged.connect(lambda k: k > 0 and self.apply(json.loads(json.dumps(theme.PRESETS[k - 1][1]))))
        v.addWidget(W.row("Preset", presets))
        same = W.small_button("Same as Kontrolleur", self.from_kontrolleur, bool(store.kontrolleur_look()))
        same.setToolTip("Take the colours, fonts and text size currently set in Kontrolleur"
                        if store.kontrolleur_look() else "Kontrolleur has no saved look on this computer yet")
        v.addWidget(W.row("Kontrolleur", same))
        for group in ("Surfaces", "Text & lines", "Accents"):
            v.addWidget(W.label(group.upper(), 10, HEAVY, "mono", Theme.dim, tracking=1.2))
            for slot, text, g in theme.SLOTS:
                if g != group:
                    continue
                b = QPushButton()
                b.setFixedSize(56, 22)
                b.setStyleSheet(f"background: {W.css(A.color(slot))}; border: 1px solid {W.css(Theme.line)}; border-radius: 5px;")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, s=slot: self.pick_color(s))
                v.addWidget(W.row(text, b))
        v.addWidget(W.label("FONTS", 10, HEAVY, "mono", Theme.dim, tracking=1.2))
        for text, key in (("Interface", "uiFont"), ("Labels & numbers", "monoFont"), ("Titles", "titleFont")):
            cb = QComboBox()
            items = theme.BUILTIN_FONTS + self.families
            cb.addItems(items)
            cur = A.data.get(key, "System")
            if cur in items:
                cb.setCurrentIndex(items.index(cur))
            cb.setMaxVisibleItems(20)
            cb.setFixedWidth(200)
            cb.currentTextChanged.connect(lambda t, k=key: self.apply_kw(**{k: t}))
            v.addWidget(W.row(text, cb))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(16, 27)
        sl.setValue(round(A.scale * 20))
        val = W.label(f"{round(A.scale * 100)}%", 12, SEMIBOLD, "mono")
        sl.valueChanged.connect(lambda x: val.setText(f"{x * 5}%"))
        sl.sliderReleased.connect(lambda: self.apply_kw(scale=sl.value() / 20))
        sl.setFixedWidth(160)
        v.addWidget(W.row("Text size", W.hbox(sl, val)))
        v.addWidget(W.hint("Same presets and settings as Kontrolleur. Changes apply right away and are kept on this computer."))
        reset = QPushButton("Reset to Blueprint")
        reset.clicked.connect(lambda: self.apply(json.loads(json.dumps(theme.PRESETS[0][1]))))
        v.addWidget(reset, 0, Qt.AlignRight)
        v.addStretch(1)
        old = self.sc.takeWidget()
        self.sc.setWidget(w)
        if old:
            old.deleteLater()

    def from_kontrolleur(self):
        raw = store.kontrolleur_look()
        try:
            self.apply(json.loads(raw))
        except Exception:
            pass

    def pick_color(self, slot):
        c = QColorDialog.getColor(theme.A.color(slot), self, "Colour", QColorDialog.ShowAlphaChannel)
        if c.isValid():
            theme.A.set_color(slot, c)
            self.refresh()

    def apply(self, data):
        theme.A.set(data)
        self.refresh()

    def apply_kw(self, **kw):
        theme.A.update(**kw)
        self.refresh()

    def refresh(self):
        self.main.apply_appearance()
        QTimer.singleShot(0, self.fill)


def main():
    if sys.platform.startswith("linux") and not os.environ.get("QT_QPA_PLATFORM") and os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
    app = QApplication(sys.argv)
    app.setApplicationName("Slice Machine")
    app.setOrganizationName(store.APP)
    app.setDesktopFileName("slicemachine")
    store.inherit_kontrolleur_look()
    theme.init()
    w = Main()
    w.show()
    sys.exit(app.exec())
