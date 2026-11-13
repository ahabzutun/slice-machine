"""NerdSEQ tab: prepare_nerdseq.py as a form, with the ~190 kB sample memory drawn as a bar."""
from __future__ import annotations

import datetime as dt
import os
from typing import List, Optional

from PySide6.QtCore import QLineF, QRectF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLineEdit

from .. import draw, engine
from .. import widgets as W
from ..stage import Drawing
from ..theme import BOLD, HEAVY, MEDIUM, REGULAR, SEMIBOLD, Theme
from . import common as C
from .slicer import _default_dir

FORMATS = [("wav16", "WAV 16-bit"), ("wav8", "WAV 8-bit"), ("raw8", "RAW 8-bit")]
FORMAT_NOTES = {"wav16": "Best quality, 2 bytes per sample.", "wav8": "Half the memory, lo-fi grit (unsigned 8-bit).",
                "raw8": "Headerless unsigned 8-bit, always mono."}
CHANNELS = [("mono", "Mono"), ("stereo", "Stereo"), ("keep", "As is")]
RATES = [(11025, "11.025 kHz"), (22050, "22.05 kHz"), (32000, "32 kHz"), (44100, "44.1 kHz"), (48000, "48 kHz")]


class NerdseqTool(C.Tool):
    key = "nerdseq"
    label = "NerdSEQ"
    panel_tabs = ("Samples", "Format")
    primary = "▶  Convert"
    primary_tip = "Write NerdSEQ-ready samples into a new subfolder"
    subtitle = "audio → NerdSEQ samples"

    def __init__(self, main):
        self.s = main.s
        self.o = self.load_opts(dict(in_dir=_default_dir("SLICEMACHINE_INPUT", "input"), checked=[], fmt="wav16", channels="mono",
                                     sr=engine.NERDSEQ_SR, normalize=False, sub="",
                                     out_root=os.path.join(_default_dir("SLICEMACHINE_OUTPUT", "output"), "nerdseq")))
        self.files: List[str] = []
        self.focus: Optional[str] = None
        self.last: Optional[dict] = None
        super().__init__(main)

    def make_drawing(self):
        return NerdseqDrawing(self)

    def set(self, rebuild=False, **kw):
        self.o.update(kw)
        self.save_opts(self.o)
        self.changed(rebuild)

    def shown(self):
        self.files = engine.scan_audio(self.o["in_dir"], engine.NERDSEQ_EXTS)
        self.o["checked"] = [c for c in self.o["checked"] if c in self.files]
        if self.focus not in self.files:
            self.focus = (self.o["checked"] or [None])[0]
        self.changed(True)

    @property
    def checked(self) -> List[str]:
        return [f for f in self.files if f in self.o["checked"]]

    def channels(self) -> str:
        return "mono" if self.o["fmt"] == "raw8" else self.o["channels"]

    def estimate(self, f: str) -> int:
        return engine.nerdseq_estimate(engine.file_info(f), self.o["fmt"], self.channels(), int(self.o["sr"]))

    def toggle(self, f, on):
        ch = [c for c in self.o["checked"] if c != f] + ([f] if on else [])
        if on:
            self.focus = f
        self.set(rebuild=True, checked=ch)

    def subfolder(self) -> str:
        return engine.nerdseq_subfolder(self.o["sub"]) if self.o["sub"].strip() else dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    def can_run(self):
        if not self.checked:
            return False, "Tick at least one file under Samples."
        return True, ""

    def dropped(self, paths):
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p) and p.lower().endswith(engine.NERDSEQ_EXTS)]
        if dirs:
            self.o["in_dir"] = dirs[0]
        elif files:
            self.o["in_dir"] = os.path.dirname(files[0])
        self.o["checked"] = list(dict.fromkeys(self.o["checked"] + files))
        self.save_opts(self.o)
        self.shown()

    def space(self):
        if self.focus:
            self.main.play(self.focus, 0, None, os.path.basename(self.focus))

    def run(self):
        files = self.checked
        out = os.path.join(self.o["out_root"], self.subfolder())
        fmt, ch, sr, norm = self.o["fmt"], self.channels(), int(self.o["sr"]), bool(self.o["normalize"])

        def done(res):
            total = sum(r["bytes"] for r in res)
            big = [r for r in res if r["too_big"]]
            self.last = {"dir": out, "count": len(res), "bytes": total}
            text = f"Converted {len(res)} of {len(files)} into {C.short_path(out)} — {C.kb(total)} of {C.kb(engine.NERDSEQ_MEM)}."
            kind = "ok"
            if total > engine.NERDSEQ_MEM:
                text += " The whole set won't fit at once: load a subset."
                kind = "warn"
            if big:
                text += f" {len(big)} sample{'s' if len(big) != 1 else ''} {'is' if len(big) == 1 else 'are'} bigger than the whole memory."
                kind = "warn"
            if len(res) < len(files):
                kind = "warn"
            self.main.set_status(kind, text, out)
            self.changed(True)

        self.main.run_tool(f"Converting {len(files)} file{'s' if len(files) != 1 else ''} for the NerdSEQ",
                           lambda step: engine.run_nerdseq(files, out, fmt, ch, sr, norm, step), done)

    def build_panel(self, tab, col):
        o = self.o
        if tab == "Samples":
            c = C.card(f"Files  ·  {len(self.checked)} of {len(self.files)} ticked", Theme.cv)
            c.add(C.folder_row(self.main, "Folder", o["in_dir"], lambda d: (self.set(in_dir=d), self.shown()), True))
            if not self.files:
                c.add(C.note("No audio in this folder. Choose another one or drop files onto the window."))
            for f in self.files:
                info = engine.file_info(f)
                est = self.estimate(f)
                big = est > engine.NERDSEQ_MEM
                meta = "can't read" if info.error else f"{C.secs(info.duration)}  {C.kb(est)}"
                c.add(C.FileRow(os.path.basename(f), meta, f in o["checked"], f == self.focus, lambda on, f=f: self.toggle(f, on),
                                lambda f=f: (setattr(self, "focus", f), self.changed(True)), f, big or bool(info.error)))
            if self.files:
                c.add(C.check_all_row(lambda: self.set(rebuild=True, checked=list(self.files)),
                                      lambda: self.set(rebuild=True, checked=[])))
            col.addWidget(c)
        else:
            c = C.card("Format", Theme.cv)
            c.add(W.Segmented(FORMATS, o["fmt"], lambda v: self.set(rebuild=True, fmt=v)))
            c.add(C.note(FORMAT_NOTES[o["fmt"]]))
            if o["fmt"] == "raw8":
                c.add(C.note("RAW is mono only, so channels are set to mono."))
            else:
                c.add(W.label("Channels", 12, MEDIUM))
                c.add(W.Segmented(CHANNELS, o["channels"], lambda v: self.set(rebuild=True, channels=v)))
            rates = RATES if any(r == int(o["sr"]) for r, _ in RATES) else RATES + [(int(o["sr"]), f"{int(o['sr'])} Hz")]
            c.add(W.row("Sample rate", W.Picker(rates, int(o["sr"]), lambda v: self.set(rebuild=True, sr=v), 120)))
            c.add(C.note(f"The NerdSEQ doesn't resample on load; {engine.NERDSEQ_SR} Hz is the manual's reference."))
            c.add(W.switch_row("Peak-normalize each sample", bool(o["normalize"]), lambda v: self.set(normalize=v)))
            col.addWidget(c)
            c = C.card("Output")
            c.add(C.folder_row(self.main, "Folder", o["out_root"], lambda d: self.set(rebuild=True, out_root=d)))
            e = QLineEdit(o["sub"])
            e.setPlaceholderText("date and time of the run")
            e.textEdited.connect(lambda t: (self.o.update(sub=t), self.save_opts(self.o), self.changed()))
            c.add(W.label("Subfolder for this run", 12, MEDIUM))
            c.add(e)
            c.add(C.note("Names are made SD-card safe (ASCII, ≤ 24 characters); existing files are never overwritten."))
            col.addWidget(c)


class NerdseqDrawing(Drawing):
    base = (1100.0, 640.0)

    def __init__(self, tool):
        super().__init__()
        self.t = tool

    def paint(self, p, w, h):
        t = self.t
        files = t.checked
        sizes = [t.estimate(f) for f in files]
        total = sum(sizes)
        mem = engine.NERDSEQ_MEM
        C.caption("nerdseq sample memory", Theme.dim, 10).paint(p, 40, 30)
        col = Theme.trig if total > mem else Theme.ink
        draw.Text(f"{C.kb(total)} of {C.kb(mem)}", Theme.font(22, BOLD, "title"), col).paint(p, 40, 64)
        fmt = dict(FORMATS)[t.o["fmt"]]
        draw.Text(f"{len(files)} sample{'s' if len(files) != 1 else ''}  ·  {fmt}  ·  {t.channels()}  ·  {C.khz(int(t.o['sr']))}"
                  f"  ·  {engine.NERDSEQ_SLOTS} slots share the memory", Theme.font(11, SEMIBOLD, "mono"), Theme.dim,
                  max_w=w - 80).paint(p, 40, 100)

        # the memory bar
        bar = QRectF(40, 160, w - 80, 64)
        scale = max(total, mem)
        draw.rounded(p, bar, 10, Theme.c("card", 0.55), Theme.line)
        inner = bar.adjusted(4, 4, -4, -4)
        x = inner.left()
        for k, (f, b) in enumerate(zip(files, sizes)):
            seg_w = inner.width() * b / scale if scale else 0
            r = QRectF(x, inner.top(), max(1.0, seg_w - 2), inner.height())
            big = b > mem
            base = Theme.trig if big else (Theme.cv if k % 2 == 0 else Theme.octave)
            fill = QColor(base)
            fill.setAlphaF(0.55 if f == t.focus else 0.3)
            draw.rounded(p, r, 6, fill, base if f == t.focus else None, 1.2)
            if seg_w > 70:
                draw.Text(os.path.splitext(os.path.basename(f))[0], Theme.font(9.5, SEMIBOLD, "mono"), Theme.ink,
                          max_w=seg_w - 12).paint(p, x + 6, inner.top() + 8)
                draw.Text(C.kb(b), Theme.font(9, REGULAR, "mono"), Theme.dim).paint(p, x + 6, inner.bottom() - 18)
            self.hits.add(r, lambda f=f: (setattr(t, "focus", f), t.changed(True), t.space()),
                          f"{os.path.basename(f)}  ·  {C.kb(b)}  (click to hear it)")
            x += seg_w
        # where the memory ends
        mx = inner.left() + inner.width() * mem / scale
        p.setPen(draw.pen(Theme.trig if total > mem else Theme.c("dim", 0.8), 1.5, [4, 3]))
        p.drawLine(QLineF(mx, bar.top() - 8, mx, bar.bottom() + 8))
        lbl = draw.Text(f"{C.kb(mem)}", Theme.font(9, HEAVY, "mono"), Theme.trig if total > mem else Theme.dim)
        lbl.paint(p, min(mx - lbl.w / 2, w - 40 - lbl.w), bar.bottom() + 12)
        if total > mem:
            draw.Text(f"{C.kb(total - mem)} too much for all at once", Theme.font(10, SEMIBOLD, "mono"), Theme.trig
                      ).paint(p, 40, bar.bottom() + 12)

        # the 12 slots
        C.caption(f"{engine.NERDSEQ_SLOTS} sample slots", Theme.dim, 9.5).paint(p, 40, 290)
        cols, gx, gy = 6, 10.0, 10.0
        sw = (w - 80 - (cols - 1) * gx) / cols
        sh = 92.0
        for i in range(engine.NERDSEQ_SLOTS):
            r = QRectF(40 + (i % cols) * (sw + gx), 312 + (i // cols) * (sh + gy), sw, sh)
            f = files[i] if i < len(files) else None
            on = f is not None and f == t.focus
            draw.rounded(p, r, 9, Theme.c("card", 0.7 if f else 0.25), Theme.c("cv", 0.8) if on else Theme.line,
                         1.3 if on else 1, None if f else [4, 4])
            C.caption(f"{i:02d}", Theme.cv if on else Theme.dim, 9).paint(p, r.left() + 9, r.top() + 8)
            if f:
                b = sizes[i]
                info = engine.file_info(f)
                draw.Text(os.path.splitext(os.path.basename(f))[0], Theme.font(11, SEMIBOLD), Theme.ink,
                          max_w=r.width() - 18).paint(p, r.left() + 9, r.top() + 28)
                draw.Text(f"{C.kb(b)}  ·  {C.secs(info.duration * 1.0)}", Theme.font(9.5, REGULAR, "mono"),
                          Theme.trig if b > mem else Theme.dim, max_w=r.width() - 18).paint(p, r.left() + 9, r.top() + 50)
                share = QRectF(r.left() + 9, r.bottom() - 14, (r.width() - 18) * min(1.0, b / mem), 4)
                p.fillRect(share, Theme.c("trig" if b > mem else "cv", 0.7))
                self.hits.add(r, lambda f=f: (setattr(t, "focus", f), t.changed(True), t.space()), f"{os.path.basename(f)} (click to hear it)")
            else:
                draw.Text("empty", Theme.font(10, REGULAR, "mono"), Theme.c("dim", 0.7)).paint(p, r.left() + 9, r.top() + 30)
        more = len(files) - engine.NERDSEQ_SLOTS
        hint = (f"{more} more file{'s' if more != 1 else ''} than slots: they're converted too, load them as you need them."
                if more > 0 else
                f"✓ Last run: {t.last['count']} files in {C.short_path(t.last['dir'])}" if t.last else
                "Sizes are estimated from the files; 8-bit, mono or a lower sample rate make samples smaller.")
        draw.Text(hint, Theme.font(11, REGULAR), Theme.special if (t.last and more <= 0) else Theme.dim, max_w=w - 80).paint(p, 40, 590)
