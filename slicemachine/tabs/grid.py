"""GRID kit tab: chain_to_grid_kit.py as a form — a .kit for the Percussa SSP's GRID with the same
slices as the .slc, so one chain .wav plays the same on the ER-301 and in GRID."""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF

from .. import draw, engine
from .. import widgets as W
from ..stage import Drawing
from ..theme import BOLD, HEAVY, REGULAR, SEMIBOLD, Theme
from . import common as C
from .slicer import _default_dir
from .split import PairsTool


class GridTool(PairsTool):
    key = "grid"
    label = "GRID kit"
    panel_tabs = ("Chains",)
    primary = "▶  Write kits"
    primary_tip = "Write a GRID .kit (Percussa SSP) for every ticked chain"
    subtitle = "chain → Percussa SSP GRID .kit"
    extra_defaults = {"out_dir": os.path.join(_default_dir("SLICEMACHINE_OUTPUT", "output"), "grid"), "pad": 0}

    def make_drawing(self):
        return GridDrawing(self)

    def build_panel(self, tab, col):
        self.chains_card(col)
        c = C.card("Pad", Theme.special)
        c.add(W.Segmented([(i, str(i + 1)) for i in range(engine.GRID_PADS)], int(self.o["pad"]),
                          lambda v: self.set(pad=v)))
        c.add(C.note("The GRID pad that holds the chain. The other pads of the kit stay empty."))
        col.addWidget(c)
        c = C.card("Output")
        c.add(C.folder_row(self.main, "Output folder", self.o["out_dir"], lambda d: self.set(rebuild=True, out_dir=d)))
        c.add(C.note("Only the .kit is written; the chain .wav is shared with the ER-301. On the SSP: the .wav goes to "
                     "/media/BOOT/samples/, the .kit to /media/BOOT/samples/kits/."))
        col.addWidget(c)

    def run(self):
        pairs, out, pad = self.checked, self.o["out_dir"], int(self.o["pad"])

        def done(res):
            self.done = res
            ok = [r for r in res if r["kit"]]
            bad = [r for r in res if not r["kit"]]
            over = [r for r in ok if r["count"] > engine.GRID_MAX_SLICES]
            text = f"Wrote {len(ok)} kit{'s' if len(ok) != 1 else ''} with the chain on pad {pad + 1}."
            if over:
                text += f"  {os.path.basename(over[0]['wav'])} has {over[0]['count']} slices; GRID uses the first {engine.GRID_MAX_SLICES}."
            if bad:
                text += f"  Failed: {', '.join(os.path.basename(r['wav']) for r in bad)} (see the log)."
            self.main.set_status("warn" if (bad or over) else "ok", text, ok[0]["kit"] if len(ok) == 1 else out)
            self.changed(True)

        self.main.run_tool(f"Writing {len(pairs)} GRID kit{'s' if len(pairs) != 1 else ''}",
                           lambda step: engine.run_grid(pairs, out, pad, step), done)


class GridDrawing(Drawing):
    base = (1100.0, 640.0)

    def __init__(self, tool):
        super().__init__()
        self.t = tool

    def paint(self, p, w, h):
        t = self.t
        C.caption("chain", Theme.dim, 10).paint(p, 40, 30)
        wave = t.paint_focus(p, self.hits, w, Theme.cv, top=150, height=170)
        pad = int(t.o["pad"])
        # GRID's 8 pads, 4 × 2
        cols, gx, gy = 4, 14.0, 14.0
        top = 372.0
        pw = (w - 80 - (cols - 1) * gx) / cols
        ph = 84.0
        C.caption("grid kit", Theme.dim, 9.5).paint(p, 40, top - 22)
        stem = os.path.splitext(os.path.basename(t.focus))[0] if t.focus else ""
        n = len(C.bounds(wave.markers, wave.frames)) if isinstance(wave, engine.Wave) else 0
        for i in range(engine.GRID_PADS):
            r = QRectF(40 + (i % cols) * (pw + gx), top + (i // cols) * (ph + gy), pw, ph)
            on = i == pad
            path = draw.rounded(p, r, 9, Theme.c("special", 0.13) if on else Theme.c("card", 0.35),
                                Theme.c("special", 0.85) if on else Theme.line, 1.4 if on else 1, None if on else [4, 4])
            if on:
                draw.glow(p, path, Theme.c("special", 0.5), 8)
            C.caption(f"pad {i + 1}", Theme.special if on else Theme.dim, 9).paint(p, r.left() + 10, r.top() + 8)
            if on and stem:
                draw.Text(stem + ".wav", Theme.font(11.5, SEMIBOLD), Theme.ink, max_w=r.width() - 20).paint(p, r.left() + 10, r.top() + 26)
                cap = min(n, engine.GRID_MAX_SLICES)
                txt = f"{cap} slices" + (f"  (of {n})" if n > engine.GRID_MAX_SLICES else "")
                draw.Text(txt, Theme.font(9.5, SEMIBOLD, "mono"), Theme.trig if n > engine.GRID_MAX_SLICES else Theme.dim
                          ).paint(p, r.left() + 10, r.top() + 46)
                # the slices as GRID stores them: normalized start/end pairs
                bar = QRectF(r.left() + 10, r.bottom() - 16, r.width() - 20, 6)
                if isinstance(wave, engine.Wave) and wave.frames:
                    for k, (s0, e0) in enumerate(C.bounds(wave.markers, wave.frames)[: engine.GRID_MAX_SLICES]):
                        seg = QRectF(bar.left() + bar.width() * s0 / wave.frames, bar.top(),
                                     max(0.6, bar.width() * (e0 - s0) / wave.frames - 0.6), bar.height())
                        p.fillRect(seg, Theme.c("special", 0.85 if k % 2 == 0 else 0.45))
            else:
                draw.Text("empty", Theme.font(10, REGULAR, "mono"), Theme.c("dim", 0.7)).paint(p, r.left() + 10, r.top() + 28)
            self.hits.add(r, lambda i=i: (t.set(rebuild=True, pad=i)), f"Put the chain on pad {i + 1}")
        done = next((r for r in t.done if r["wav"] == t.focus and r["kit"]), None)
        hint = (f"✓ Written: {C.short_path(done['kit'])}" if done else
                "Click a pad to put the chain on it. Every ticked chain gets its own .kit with the same pad.")
        draw.Text(hint, Theme.font(11, REGULAR), Theme.special if done else Theme.dim, max_w=w - 80).paint(p, 40, 590)
