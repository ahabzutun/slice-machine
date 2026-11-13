"""Split tab: split_chain.py as a form — a chain back into one .wav per slice."""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import QRectF

from .. import draw, engine
from .. import widgets as W
from ..stage import Drawing
from ..theme import BOLD, HEAVY, REGULAR, SEMIBOLD, Theme
from . import common as C
from .slicer import _default_dir


class PairsTool(C.Tool):
    """Shared by Split and GRID kit: a folder of chains (.wav + .slc), some ticked, one shown."""
    extra_defaults: dict = {}

    def __init__(self, main):
        self.s = main.s
        d = dict(chain_dir=_default_dir("SLICEMACHINE_OUTPUT", "output"), checked=[])
        d.update(self.extra_defaults)
        self.o = self.load_opts(d)
        self.pairs: List[tuple] = []
        self.focus: Optional[str] = None
        self.sel: Optional[int] = None
        self.done: List[dict] = []
        super().__init__(main)

    def set(self, rebuild=False, **kw):
        self.o.update(kw)
        self.save_opts(self.o)
        self.changed(rebuild)

    def shown(self):
        self.pairs = engine.scan_pairs(self.o["chain_dir"])
        wavs = [w for w, _ in self.pairs]
        self.o["checked"] = [c for c in self.o["checked"] if c in wavs]
        if self.focus not in wavs:
            self.focus = (self.o["checked"] or wavs or [None])[0]
        self.changed(True)

    @property
    def checked(self) -> List[tuple]:
        return [(w, s) for w, s in self.pairs if w in self.o["checked"]]

    def toggle(self, wav, on):
        ch = [c for c in self.o["checked"] if c != wav] + ([wav] if on else [])
        if on:
            self.focus = wav
        self.set(rebuild=True, checked=ch)

    def set_focus(self, wav):
        self.focus, self.sel = wav, None
        self.changed(True)

    def dropped(self, paths):
        dirs = [p for p in paths if os.path.isdir(p)]
        wavs = [p for p in paths if p.lower().endswith(".wav") and engine.pair_for(p)]
        if dirs or wavs:
            self.o["chain_dir"] = dirs[0] if dirs else os.path.dirname(wavs[0])
            self.o["checked"] = list(dict.fromkeys(self.o["checked"] + wavs))
            self.save_opts(self.o)
            if wavs:
                self.focus = wavs[0]
            self.shown()

    def can_run(self):
        if not self.checked:
            return False, "Tick at least one chain."
        return True, ""

    def focus_wave(self):
        if not self.focus or not os.path.exists(self.focus):
            return None
        slc = os.path.splitext(self.focus)[0] + ".slc"
        key = ("chain", self.focus, os.path.getmtime(self.focus), os.path.getmtime(slc) if os.path.exists(slc) else 0)
        return self.main.wave(key, lambda f=self.focus: engine.chain_wave(f, slc))

    def play_slice(self, i: int):
        self.sel = i
        self.changed()
        w = self.focus_wave()
        if isinstance(w, engine.Wave):
            b = C.bounds(w.markers, w.frames)
            if 0 <= i < len(b):
                s, e = b[i]
                self.main.play(self.focus, s, e, f"Slice {i + 1} of {os.path.basename(self.focus)}  ·  {C.ms((e - s) / w.sr * 1000)}")

    def space(self):
        if self.sel is not None:
            self.play_slice(self.sel)
        elif self.focus:
            self.main.play(self.focus, 0, None, os.path.basename(self.focus))

    def chains_card(self, col, title="Chains"):
        c = C.card(f"{title}  ·  {len(self.checked)} of {len(self.pairs)} ticked", Theme.cv)
        c.add(C.folder_row(self.main, "Folder", self.o["chain_dir"], lambda d: (self.set(chain_dir=d), self.shown()), True))
        if not self.pairs:
            c.add(C.note("No chains here: a chain is a .wav with a .slc of the same name next to it."))
        for wav, slc in self.pairs:
            n = engine.slc_count(slc)
            info = engine.file_info(wav)
            c.add(C.FileRow(os.path.basename(wav), f"{n} sl  {C.secs(info.duration)}", wav in self.o["checked"], wav == self.focus,
                            lambda on, w=wav: self.toggle(w, on), lambda w=wav: self.set_focus(w), wav))
        if self.pairs:
            c.add(C.check_all_row(lambda: self.set(rebuild=True, checked=[w for w, _ in self.pairs]),
                                  lambda: self.set(rebuild=True, checked=[])))
        col.addWidget(c)

    def paint_focus(self, p, hits, w, accent, top=160.0, height=290.0):
        wave = self.focus_wave()
        title = os.path.basename(self.focus) if self.focus else "No chain"
        draw.Text(title, Theme.font(22, BOLD, "title"), Theme.ink, max_w=w - 80).paint(p, 40, 64)
        if isinstance(wave, engine.Wave):
            b = C.bounds(wave.markers, wave.frames)
            d = [(e - s) / wave.sr * 1000 for s, e in b] or [0]
            meta = (f"{len(wave.markers)} markers  ·  {len(b)} slices  ·  {C.ms(min(d))} – {C.ms(max(d))}  ·  "
                    f"{C.secs(wave.duration)} @ {C.khz(wave.sr)}")
        elif isinstance(wave, Exception):
            meta, wave = f"can't read: {wave}", None
        else:
            meta = "loading …" if self.focus else "Choose a folder with chains on the right."
        draw.Text(meta, Theme.font(11, SEMIBOLD, "mono"), Theme.dim, max_w=w - 80).paint(p, 40, 100)
        rect = QRectF(40, top, w - 80, height)
        C.paint_wave(p, rect, wave, accent, hits=hits, sel=self.sel, on_slice=self.play_slice,
                     empty_text="loading …" if self.focus else "No chain")
        return wave


class SplitTool(PairsTool):
    key = "split"
    label = "Split"
    panel_tabs = ("Chains",)
    primary = "▶  Split"
    primary_tip = "Write every slice of the ticked chains as its own .wav"
    subtitle = "chain → one file per slice"
    extra_defaults = {"out_dir": _default_dir("SLICEMACHINE_OUTPUT", "output")}

    def make_drawing(self):
        return SplitDrawing(self)

    def build_panel(self, tab, col):
        self.chains_card(col)
        c = C.card("Output")
        c.add(C.folder_row(self.main, "Output folder", self.o["out_dir"], lambda d: self.set(rebuild=True, out_dir=d)))
        c.add(C.note("Each chain gets its own folder: <chain>/<chain>_slice_001.wav … Slices run from one marker to the next; "
                     "the sample rate and channels stay as they are."))
        col.addWidget(c)

    def run(self):
        pairs, out = self.checked, self.o["out_dir"]

        def done(res):
            self.done = res
            ok = [r for r in res if r["count"]]
            bad = [r for r in res if not r["count"]]
            text = f"Split {len(ok)} chain{'s' if len(ok) != 1 else ''} into {sum(r['count'] for r in ok)} files."
            if bad:
                text += f"  Failed: {', '.join(os.path.basename(r['wav']) for r in bad)} (see the log)."
            self.main.set_status("warn" if bad else "ok", text, ok[0]["dir"] if len(ok) == 1 else out)
            self.changed(True)

        self.main.run_tool(f"Splitting {len(pairs)} chain{'s' if len(pairs) != 1 else ''}",
                           lambda step: engine.run_split(pairs, out, step), done)


class SplitDrawing(Drawing):
    base = (1100.0, 640.0)

    def __init__(self, tool):
        super().__init__()
        self.t = tool

    def paint(self, p, w, h):
        t = self.t
        C.caption("chain", Theme.dim, 10).paint(p, 40, 30)
        wave = t.paint_focus(p, self.hits, w, Theme.cv)
        if not t.focus:
            return
        stem = os.path.splitext(os.path.basename(t.focus))[0]
        n = len(C.bounds(wave.markers, wave.frames)) if isinstance(wave, engine.Wave) else engine.slc_count(os.path.splitext(t.focus)[0] + ".slc")
        pad = max(3, len(str(n)))
        y = 490.0
        C.caption("writes", Theme.dim, 9.5).paint(p, 40, y)
        folder = C.short_path(os.path.join(t.o["out_dir"], stem)) + "/"
        draw.Text(folder, Theme.font(11, SEMIBOLD, "mono"), Theme.cv, max_w=w - 160).paint(p, 110, y - 1)
        names = [f"{stem}_slice_{i:0{pad}d}.wav" for i in ([1, 2, 3, n] if n > 4 else range(1, n + 1))]
        x = 110.0
        for k, nm in enumerate(names):
            if n > 4 and k == 3:
                dots = draw.Text("…", Theme.font(11, BOLD, "mono"), Theme.dim)
                dots.paint(p, x, y + 26)
                x += dots.w + 8
            pill = C.pill_text(nm, Theme.ink, 0.08, 9.5, SEMIBOLD)
            if x + pill.w > w - 40:
                break
            pill.paint(p, x, y + 24)
            x += pill.w + 8
        done = next((r for r in t.done if r["wav"] == t.focus and r["count"]), None)
        hint = (f"✓ Written: {done['count']} files in {C.short_path(done['dir'])}. Click a slice to hear it." if done
                else "Click a slice to hear it. Every ticked chain is split; the stage shows the one you clicked.")
        draw.Text(hint, Theme.font(11, REGULAR), Theme.special if done else Theme.dim, max_w=w - 80).paint(p, 40, 590)
