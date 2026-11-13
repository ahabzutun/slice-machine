"""Merge tab: merge_chains.py as a form — put sliced chains into slots, empty slots become silence."""
from __future__ import annotations

import math
import os
from typing import List, Optional

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtWidgets import QFileDialog, QLineEdit

from .. import draw, engine, store
from .. import widgets as W
from ..stage import Drawing
from ..theme import BOLD, HEAVY, MEDIUM, REGULAR, SEMIBOLD, Theme
from . import common as C
from .slicer import RATES, _default_dir


class MergeTool(C.Tool):
    key = "merge"
    label = "Merge"
    panel_tabs = ("Slots", "Output")
    primary = "▶  Merge"
    primary_tip = "Join the chains in the slots into one .wav + .slc"
    subtitle = "chains → one big chain"

    def __init__(self, main):
        self.s = main.s
        self.o = self.load_opts(dict(chain_dir=_default_dir("SLICEMACHINE_OUTPUT", "output"), slots=8, per=128, sr=48000,
                                     assign=[], name="merged_chain", out_dir=_default_dir("SLICEMACHINE_OUTPUT", "output")))
        self.pairs: List[tuple] = []
        self.sel = 0
        self.view = "slots"
        self.result: Optional[dict] = None
        self.rsel: Optional[int] = None
        super().__init__(main)

    def make_drawing(self):
        return MergeDrawing(self)

    def set(self, rebuild=False, **kw):
        self.o.update(kw)
        self.save_opts(self.o)
        self.changed(rebuild)

    def assignments(self) -> List[str]:
        a = list(self.o["assign"])[: int(self.o["slots"])]
        a += [""] * (int(self.o["slots"]) - len(a))
        return [x if x and engine.pair_for(x) else "" for x in a]

    def assign(self, i: int, wav: str):
        a = self.assignments()
        a[i] = wav
        self.sel = i
        self.set(rebuild=True, assign=a)

    def shown(self):
        self.pairs = engine.scan_pairs(self.o["chain_dir"])
        self.changed(True)

    def out_path(self) -> str:
        name = (self.o["name"] or "merged_chain").strip()
        return os.path.join(self.o["out_dir"], (name[:-4] if name.lower().endswith(".wav") else name) + ".wav")

    def can_run(self):
        if not any(self.assignments()):
            return False, "Put at least one chain into a slot (empty slots become silence)."
        return True, ""

    def run(self):
        slots = [a or None for a in self.assignments()]
        per, sr, out = int(self.o["per"]), int(self.o["sr"]), self.out_path()

        def done(r):
            self.result, self.view, self.rsel = r, "result", None
            self.main.set_status("ok", f"Wrote {os.path.basename(r['wav'])} + .slc — {r['slots']} slots × {per} = {r['count']} slices "
                                       f"({r['filled']} filled, {r['slots'] - r['filled']} silent).", r["wav"])
            self.changed(True)

        self.main.run_tool(f"Merging {sum(1 for s in slots if s)} chains", lambda step: engine.run_merge(slots, per, sr, out, step), done)

    def dropped(self, paths):
        wavs = [p for p in paths if p.lower().endswith(".wav") and engine.pair_for(p)]
        dirs = [p for p in paths if os.path.isdir(p)]
        if dirs:
            self.o["chain_dir"] = dirs[0]
            self.save_opts(self.o)
        a = self.assignments()
        i = self.sel
        for wv in wavs:
            free = [k for k in range(len(a)) if not a[k]]
            k = i if not a[i] else (free[0] if free else None)
            if k is None:
                break
            a[k] = wv
        self.set(assign=a)
        self.shown()

    def space(self):
        a = self.assignments()
        if self.view == "result" and self.result and self.rsel is not None:
            return self.play_result(self.rsel)
        if 0 <= self.sel < len(a) and a[self.sel]:
            self.main.play(a[self.sel], 0, None, os.path.basename(a[self.sel]))

    def play_result(self, i: int):
        self.rsel = i
        r = self.result
        w = self.main.wave(("chain", r["wav"], os.path.getmtime(r["wav"])), lambda: engine.chain_wave(r["wav"], r["slc"]))
        self.changed()
        if isinstance(w, engine.Wave):
            b = C.bounds(w.markers, w.frames)
            if 0 <= i < len(b):
                s, e = b[i]
                self.main.play(r["wav"], s, e, f"Slice {i + 1} of {os.path.basename(r['wav'])}")

    # ── panel ──
    def build_panel(self, tab, col):
        o = self.o
        if tab == "Slots":
            c = C.card("Layout", Theme.cv)
            c.add(W.row("Slots", W.NumberField(int(o["slots"]), 1, 32, lambda v: self.set(rebuild=True, slots=v), 40)))
            c.add(W.row("Slices per slot", W.NumberField(int(o["per"]), 1, 1024, lambda v: self.set(per=v), 46)))
            c.add(W.row("Sample rate", W.Picker(RATES, int(o["sr"]), lambda v: self.set(sr=v), 120)))
            c.add(W.label(f"{int(o['slots'])} × {int(o['per'])} = {int(o['slots']) * int(o['per'])} slices", 10.5, SEMIBOLD, "mono", Theme.dim))
            col.addWidget(c)

            c = C.card("Chains to choose from")
            c.add(C.folder_row(self.main, "Folder", o["chain_dir"], lambda d: (self.set(chain_dir=d), self.shown()), True))
            c.add(C.note(f"{len(self.pairs)} chain{'s' if len(self.pairs) != 1 else ''} (.wav with a .slc next to it) in this folder."))
            col.addWidget(c)

            c = C.card("Slots", Theme.special)
            a = self.assignments()
            opts = [("", "— silent —")] + [(wv, os.path.basename(wv)) for wv, _ in self.pairs]
            known = {v for v, _ in opts}
            for i in range(int(o["slots"])):
                cur = a[i]
                oi = opts + ([(cur, os.path.basename(cur))] if cur and cur not in known else [])
                pk = W.Picker(oi, cur, lambda v, i=i: self.assign(i, v), 196)
                pk.setToolTip(cur or "Silence with evenly spaced markers, as long as the slot before it")

                def browse(i=i):
                    f, _ = QFileDialog.getOpenFileName(self.main, f"Chain for slot {i + 1}", o["chain_dir"], "Chain (*.wav)")
                    if f:
                        if not engine.pair_for(f):
                            return self.main.set_status("warn", f"{os.path.basename(f)} has no .slc next to it.")
                        self.assign(i, f)

                b = W.small_button("…", browse)
                b.setToolTip("Pick a chain from anywhere")
                lb = W.label(f"{i + 1}", 12, BOLD if i == self.sel else MEDIUM, "mono", Theme.cv if i == self.sel else Theme.dim)
                lb.setFixedWidth(22)
                c.add(W.hbox(lb, "stretch", pk, b))
            c.add(W.hbox(W.small_button("Fill in order", self.fill_in_order), W.small_button("Clear", lambda: self.set(rebuild=True, assign=[])),
                         "stretch"))
            c.add(C.note("A slot left silent gets silence as long as the chain before it, with evenly spaced markers. "
                         "Chains with more markers are cut to the slot size; fewer are padded."))
            col.addWidget(c)
        else:
            c = C.card("Output", Theme.cv)
            e = QLineEdit(o["name"])
            e.setPlaceholderText("merged_chain")
            e.textEdited.connect(lambda t: (self.o.update(name=t), self.save_opts(self.o), self.changed()))
            c.add(W.label("File name", 12, MEDIUM))
            c.add(e)
            c.add(C.folder_row(self.main, "Output folder", o["out_dir"], lambda d: self.set(rebuild=True, out_dir=d)))
            c.add(W.label(os.path.basename(self.out_path()) + "  .slc", 10.5, SEMIBOLD, "mono", Theme.dim))
            if os.path.exists(self.out_path()):
                c.add(C.note("A file with this name is already there and will be replaced.", Theme.trig))
            col.addWidget(c)

    def fill_in_order(self):
        a = [wv for wv, _ in self.pairs][: int(self.o["slots"])]
        self.set(rebuild=True, assign=a)


class MergeDrawing(Drawing):
    base = (1100.0, 640.0)

    def __init__(self, tool: MergeTool):
        super().__init__()
        self.t = tool

    def paint(self, p, w, h):
        t, o = self.t, self.t.o
        C.view_pills(p, self.hits, 40, 24, [("slots", "SLOTS", True), ("result", "MERGED", t.result is not None)],
                     t.view if t.result else "slots", lambda k: (setattr(t, "view", k), t.changed()))
        if t.view == "result" and t.result:
            return self._result(p, w, h)
        a = t.assignments()
        n = len(a)
        per = int(o["per"])
        draw.Text(os.path.basename(t.out_path()), Theme.font(22, BOLD, "title"), Theme.ink, max_w=w - 80).paint(p, 40, 64)
        filled = sum(1 for x in a if x)
        draw.Text(f"{n} slots × {per} slices = {n * per} slices  ·  {filled} filled, {n - filled} silent",
                  Theme.font(11, SEMIBOLD, "mono"), Theme.dim).paint(p, 40, 100)
        cols = min(8, n)
        rows = math.ceil(n / cols)
        gx, gy = 12.0, 16.0
        top, bottom = 150.0, 560.0
        bw = (w - 80 - (cols - 1) * gx) / cols
        bh = min(190.0, (bottom - top - (rows - 1) * gy) / rows)
        for i, wav in enumerate(a):
            x = 40 + (i % cols) * (bw + gx)
            y = top + (i // cols) * (bh + gy)
            self._slot(p, QRectF(x, y, bw, bh), i, wav, per)
        draw.Text("Click a slot to pick it in the list on the right; drop chains onto the window to fill empty slots.",
                  Theme.font(11, REGULAR), Theme.dim, max_w=w - 80).paint(p, 40, 590)

    def _slot(self, p, r: QRectF, i: int, wav: str, per: int):
        t = self.t
        on = i == t.sel
        fill = Theme.c("card", 0.75) if wav else Theme.c("card", 0.25)
        path = draw.rounded(p, r, 10, fill, Theme.c("cv", 0.8) if on else Theme.line, 1.4 if on else 1,
                            None if wav else [4, 4])
        if on:
            draw.glow(p, path, Theme.c("cv", 0.5), 8)
        C.caption(f"slot {i + 1}", Theme.cv if on else Theme.dim, 9).paint(p, r.left() + 10, r.top() + 8)
        name = os.path.splitext(os.path.basename(wav))[0] if wav else "silent"
        compact = r.height() < 110
        draw.Text(name, Theme.font(11 if not compact else 10, SEMIBOLD), Theme.ink if wav else Theme.dim,
                  max_w=r.width() - 20).paint(p, r.left() + 10, r.top() + 24)
        inner = QRectF(r.left() + 8, r.top() + (44 if not compact else 40), r.width() - 16, r.height() - (66 if not compact else 48))
        if inner.height() > 12:
            if wav:
                key = ("chain", wav, os.path.getmtime(wav) if os.path.exists(wav) else 0)
                wave = t.main.wave(key, lambda: engine.chain_wave(wav, os.path.splitext(wav)[0] + ".slc"))
                C.paint_wave(p, inner, wave if isinstance(wave, engine.Wave) else None, Theme.cv, numbers=False, compact=True,
                             empty_text="…")
            else:
                p.setPen(draw.pen(Theme.c("dim", 0.3), 0.6, [2, 3]))
                ticks = min(per, 16)
                for k in range(1, ticks):
                    x = inner.left() + inner.width() * k / ticks
                    p.drawLine(QLineF(x, inner.top() + 6, x, inner.bottom() - 6))
        if not compact:
            cnt = engine.slc_count(os.path.splitext(wav)[0] + ".slc") if wav else per
            msg = f"{cnt} markers" + (f" → {per}" if wav and cnt != per else "")
            draw.Text(msg, Theme.font(9, SEMIBOLD, "mono"), Theme.trig if wav and cnt != per else Theme.dim).paint(
                p, r.left() + 10, r.bottom() - 18)
        self.hits.add(r, lambda: (setattr(t, "sel", i), t.changed(True)), wav or "Silent slot")

    def _result(self, p, w, h):
        t = self.t
        r = t.result
        draw.Text(os.path.basename(r["wav"]), Theme.font(22, BOLD, "title"), Theme.ink, max_w=w - 80).paint(p, 40, 64)
        draw.Text(f"{r['count']} slices  ·  {r['filled']} chains + {r['slots'] - r['filled']} silent slots",
                  Theme.font(11, SEMIBOLD, "mono"), Theme.dim).paint(p, 40, 100)
        key = ("chain", r["wav"], os.path.getmtime(r["wav"]) if os.path.exists(r["wav"]) else 0)
        wave = t.main.wave(key, lambda: engine.chain_wave(r["wav"], r["slc"]))
        rect = QRectF(40, 160, w - 80, 290)
        C.paint_wave(p, rect, wave if isinstance(wave, engine.Wave) else None, Theme.cv, hits=self.hits, sel=t.rsel,
                     on_slice=t.play_result, empty_text="loading …")
        if isinstance(wave, engine.Wave) and wave.frames:
            per = int(t.o["per"])
            X = lambda s: rect.left() + 10 + s / wave.frames * (rect.width() - 20)   # noqa: E731
            free_x = -1e9
            for k in range(0, len(wave.markers), per):            # every slot starts at its first marker
                x = X(wave.markers[k])
                cap = C.caption(f"slot {k // per + 1}", Theme.special, 8.5)
                if x + 3 >= free_x:
                    cap.paint(p, x + 3, rect.top() - 16)
                    free_x = x + 3 + cap.w + 6
                if k:
                    p.setPen(draw.pen(Theme.c("special", 0.9), 1.3))
                    p.drawLine(QLineF(x, rect.top() + 2, x, rect.bottom() - 2))
        draw.Text("Click a slice to hear it.", Theme.font(11, REGULAR), Theme.dim).paint(p, 40, 590)
