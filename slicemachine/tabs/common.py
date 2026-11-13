"""Pieces every tool tab uses: the tool base class, the waveform drawing, folder rows, file lists."""
from __future__ import annotations

import json
import os
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .. import draw, engine
from .. import widgets as W
from ..stage import Drawing
from ..theme import BOLD, HEAVY, MEDIUM, REGULAR, SEMIBOLD, Theme


class Tool:
    """One tab of the app: a drawing on the stage, a side panel, a main action."""
    key = ""
    label = ""
    panel_tabs: Sequence[str] = ("Settings",)
    primary = "Run"
    primary_tip = ""
    secondary: Optional[str] = None
    secondary_tip = ""
    subtitle = ""

    def __init__(self, main):
        self.main = main
        self.s = main.s
        self.drawing = self.make_drawing()

    # settings of this tab, kept between starts
    def load_opts(self, defaults: dict) -> dict:
        raw = self.s.value(f"{self.key}/options")
        d = dict(defaults)
        try:
            d.update({k: v for k, v in json.loads(raw).items() if k in defaults} if raw else {})
        except Exception:
            pass
        return d

    def save_opts(self, d: dict):
        self.s.setValue(f"{self.key}/options", json.dumps(d))

    def make_drawing(self) -> Drawing:
        return Drawing()

    def build_panel(self, tab: str, col):
        pass

    def shown(self):
        """The tab became visible: rescan folders etc."""

    def run(self):
        pass

    def run_secondary(self):
        pass

    def can_run(self) -> Tuple[bool, str]:
        return True, ""

    def changed(self, rebuild: bool = False):
        self.main.changed(rebuild)

    def space(self):
        """Space bar: play the selected slice, if this tab has one."""


# ── text helpers ───────────────────────────────────────────────────────────────────────────────

def ms(v: float) -> str:
    return f"{v:.0f} ms" if v >= 10 else f"{v:.1f} ms"


def secs(v: float) -> str:
    if v >= 60:
        return f"{int(v // 60)}:{v % 60:05.2f}"
    return f"{v:.2f} s"


def khz(sr: int) -> str:
    return f"{sr / 1000:g} kHz"


def kb(b: float) -> str:
    return f"{b / 1024:.1f} kB"


def mb(b: float) -> str:
    return f"{b / 1024 / 1024:.1f} MB"


def short_path(p: str) -> str:
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p.startswith(home) else p


# ── panel widgets ──────────────────────────────────────────────────────────────────────────────

def folder_row(main, title: str, path: str, on_pick: Callable[[str], None], must_exist: bool = False) -> QWidget:
    """A folder: its path (shortened), Choose… and a button that opens it."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(5)
    head = QHBoxLayout()
    head.setSpacing(6)
    head.addWidget(W.label(title, 12, MEDIUM), 1)

    def choose():
        d = QFileDialog.getExistingDirectory(main, title, path if os.path.isdir(path) else os.path.expanduser("~"))
        if d:
            on_pick(d)

    head.addWidget(W.small_button("Choose…", choose))
    rv = W.small_button("Open", lambda: main.reveal(path), os.path.isdir(path))
    rv.setToolTip("Show this folder in the file manager")
    head.addWidget(rv)
    v.addLayout(head)
    exists = os.path.isdir(path)
    lb = W.label(short_path(path) + ("" if exists or not must_exist else "   (missing)"), 10.5, REGULAR, "mono",
                 Theme.dim if exists or not must_exist else Theme.trig)
    lb.setToolTip(path)
    lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    v.addWidget(lb)
    return w


class FileRow(QWidget):
    """[x] name ………… meta   — the checkbox picks the file, clicking the name shows it on the stage."""

    def __init__(self, name: str, meta: str, checked: bool, focused: bool, on_check: Callable[[bool], None],
                 on_focus: Callable[[], None], tip: str = "", warn: bool = False):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        cb = QCheckBox()
        cb.setChecked(checked)
        cb.setCursor(Qt.PointingHandCursor)
        cb.setFocusPolicy(Qt.NoFocus)
        cb.toggled.connect(on_check)
        h.addWidget(cb)
        b = QPushButton(name)
        b.setObjectName("flat")
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.setToolTip(tip or "Show it on the stage")
        b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        col = Theme.cv if focused else Theme.ink
        b.setStyleSheet(f"QPushButton#flat {{ text-align: left; color: {W.css(col)}; font-weight: {700 if focused else 500}; }}")
        b.clicked.connect(lambda: on_focus())
        h.addWidget(b, 1)
        m = W.label(meta, 10.5, REGULAR, "mono", Theme.trig if warn else Theme.dim)
        h.addWidget(m)


def check_all_row(on_all: Callable[[], None], on_none: Callable[[], None], extra: Sequence[QWidget] = ()) -> QWidget:
    return W.hbox(W.small_button("All", on_all), W.small_button("None", on_none), *extra, "stretch")


def card(title: str, accent: Optional[QColor] = None) -> W.Card:
    return W.Card(title, accent)


def note(text: str, color: Optional[QColor] = None) -> QLabel:
    lb = W.label(text, 11, REGULAR, "ui", color or Theme.dim, wrap=True)
    return lb


# ── drawing a waveform with its slices ─────────────────────────────────────────────────────────

def bounds(markers: Sequence[int], frames: int) -> List[Tuple[int, int]]:
    m = sorted(set(max(0, min(int(x), frames)) for x in markers))
    if not m or m[0] != 0:
        m = [0] + m
    out = []
    for i, s in enumerate(m):
        e = m[i + 1] if i + 1 < len(m) else frames
        if e > s:
            out.append((s, e))
    return out


def _columns(wave: engine.Wave, n: int) -> Tuple[np.ndarray, np.ndarray]:
    lo, hi = wave.lo, wave.hi
    if len(lo) <= n:
        return lo, hi
    edges = np.linspace(0, len(lo), n + 1).astype(np.int64)[:-1]
    return np.minimum.reduceat(lo, edges), np.maximum.reduceat(hi, edges)


def paint_wave(p: QPainter, rect: QRectF, wave: Optional[engine.Wave], accent: QColor, *, hits=None,
               sel: Optional[int] = None, on_slice: Optional[Callable[[int], None]] = None, banks: int = 0,
               show_markers: bool = True, empty_text: str = "", numbers: bool = True, compact: bool = False):
    """The waveform panel. Returns the slice bounds (in samples) it drew."""
    draw.rounded(p, rect, 10, Theme.c("card", 0.55), Theme.line)
    if wave is None or wave.frames == 0:
        if empty_text:
            t = draw.Text(empty_text, Theme.font(12, MEDIUM, "mono"), Theme.dim, max_w=rect.width() - 40)
            t.paint_center(p, rect.center().x(), rect.center().y())
        return []
    inner = rect.adjusted(10, 12, -10, -12)
    x0, wpx = inner.left(), inner.width()
    cy, amp = inner.center().y(), inner.height() / 2 * 0.94
    sl = bounds(wave.markers, wave.frames) if (show_markers and wave.markers) else []

    def X(sample: float) -> float:
        return x0 + sample / wave.frames * wpx

    # bank bands (bank mode: 8 × 16)
    if banks and len(sl) >= banks * 16:
        for b in range(banks):
            s0, e0 = sl[b * 16][0], sl[min(len(sl), (b + 1) * 16) - 1][1]
            r = QRectF(X(s0), rect.top() + 1, X(e0) - X(s0), rect.height() - 2)
            if b % 2 == 0:
                p.fillRect(r, Theme.c("special", 0.06))
            if not compact:
                t = draw.Text(f"BANK {b + 1}", Theme.font(8.5, HEAVY, "mono"), Theme.c("special", 0.85), tracking=1)
                t.paint(p, r.center().x() - t.w / 2, rect.top() - t.h - 3)

    # selected slice
    if sel is not None and 0 <= sel < len(sl):
        s0, e0 = sl[sel]
        r = QRectF(X(s0), rect.top() + 1, max(1.5, X(e0) - X(s0)), rect.height() - 2)
        p.fillRect(r, Theme.c("cv", 0.16))
        path = QPainterPath()
        path.addRect(r)
        draw.glow(p, path, Theme.c("cv", 0.6), 6)

    # centre line + waveform
    p.setPen(draw.pen(Theme.c("body", 0.18), 0.6))
    p.drawLine(QPointF(inner.left(), cy), QPointF(inner.right(), cy))
    n = max(2, int(wpx * 1.5))
    lo, hi = _columns(wave, n)
    k = len(lo)
    xs = x0 + (np.arange(k) + 0.5) / k * wpx
    top = [QPointF(float(x), float(cy - max(h, 0.0015) * amp)) for x, h in zip(xs, hi)]
    bot = [QPointF(float(x), float(cy - min(l, -0.0015) * amp)) for x, l in zip(xs[::-1], lo[::-1])]
    poly = QPolygonF(top + bot)
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    p.fillPath(path, QColor(accent.red(), accent.green(), accent.blue(), int(accent.alpha() * 0.55)))
    p.strokePath(path, draw.pen(QColor(accent.red(), accent.green(), accent.blue(), int(accent.alpha() * 0.9)), 0.6))

    # slice markers
    if sl:
        many = len(sl) > 200
        mk = Theme.c("trig", 0.3 if (many or (compact and len(sl) > 48)) else 0.75)
        for i, (s0, _e) in enumerate(sl):
            if i == 0:
                continue
            x = X(s0)
            strong = (banks and i % 16 == 0)
            p.setPen(draw.pen(Theme.c("special", 0.9) if strong else mk, 1.2 if strong else 0.7))
            p.drawLine(QPointF(x, rect.top() + 4), QPointF(x, rect.bottom() - 4))
        if numbers and not compact:
            every = 1 if len(sl) <= 32 else 4 if len(sl) <= 64 else 8 if len(sl) <= 160 else 16 if len(sl) <= 400 else 64
            f = Theme.font(8.5, SEMIBOLD, "mono")
            for i, (s0, e0) in enumerate(sl):
                if i % every and i != len(sl) - 1:
                    continue
                t = draw.Text(str(i + 1), f, Theme.cv if i == sel else Theme.dim)
                cx = (X(s0) + X(e0)) / 2 if every == 1 else X(s0) + 2
                t.paint(p, cx - (t.w / 2 if every == 1 else 0), rect.bottom() + 4)
        if hits is not None and on_slice is not None:
            for i, (s0, e0) in enumerate(sl):
                r = QRectF(X(s0), rect.top(), max(2.0, X(e0) - X(s0)), rect.height())
                d = (e0 - s0) / wave.sr * 1000 if wave.sr else 0
                hits.add(r, lambda i=i: on_slice(i), f"Slice {i + 1}  ·  {ms(d)}")
    return sl


def pill_text(text: str, color: QColor, fill_alpha: float = 0.14, size: float = 9.5, weight: int = HEAVY) -> draw.Pill:
    t = draw.Text(text, Theme.font(size, weight, "mono"), color, tracking=0.6)
    f = QColor(color)
    f.setAlphaF(fill_alpha)
    return draw.Pill(t, 7, 3, f, None)


def caption(text: str, color: Optional[QColor] = None, size: float = 9.5) -> draw.Text:
    return draw.Text(text.upper(), Theme.font(size, HEAVY, "mono"), color or Theme.dim, tracking=1.2)


def view_pills(p: QPainter, hits, x: float, y: float, options: Sequence[Tuple[str, str, bool]], current: str,
               on_pick: Callable[[str], None]) -> float:
    """SOURCE | CHAIN style switches drawn on the stage. options: (key, label, enabled)."""
    cx = x
    for key, text, enabled in options:
        on = key == current
        col = Theme.cv if on else (Theme.dim if enabled else Theme.c("dim", 0.4))
        t = draw.Text(text, Theme.font(10, HEAVY, "mono"), col, tracking=1.2)
        pill = draw.Pill(t, 9, 4, Theme.c("cv", 0.16) if on else Theme.c("card", 0.6),
                         Theme.c("cv", 0.55) if on else Theme.line, 1)
        pill.paint(p, cx, y)
        if enabled:
            hits.add(QRectF(cx, y, pill.w, pill.h), lambda k=key: on_pick(k), None)
        cx += pill.w + 6
    return cx
