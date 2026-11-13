"""Junglize tab: src/junglize.py as a form. Pick a source, set the groove, Roll for a new break
(new seed, played right away), Junglize writes it as a chain: .wav + .slc (ER-301) + .kit (SSP GRID)."""
from __future__ import annotations

import os
import random
from typing import List, Optional

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLineEdit

from .. import draw, engine, store
from .. import widgets as W
from ..stage import Drawing
from ..theme import BOLD, HEAVY, MEDIUM, REGULAR, SEMIBOLD, Theme
from . import common as C
from .slicer import _default_dir

FEEL_LABELS = [("straight", "Straight"), ("halftime", "Halftime"), ("doubletime", "Doubletime")]
RATES = [(22050, "22.05 kHz"), (32000, "32 kHz"), (44100, "44.1 kHz"), (48000, "48 kHz")]
TEMPO = [("as_is", "As is"), ("set", "Source BPM"), ("detect", "Detect")]
# (key, label, lo, hi, step, note)
AMOUNTS = [("swing", "Swing", 0.0, 0.5, 0.02, "Delay of every second 16th"),
           ("ring", "Ring-out (steps)", 0.25, 4.0, 0.1, "How long a hit may ring into the next steps"),
           ("stutter", "Stutter", 0.0, 1.0, 0.05, "Chance a step splits into 2 or 3 retriggers"),
           ("reverse", "Reverse", 0.0, 1.0, 0.02, "Chance a hit plays backwards"),
           ("humanize", "Humanize", 0.0, 0.5, 0.02, "Random loudness per hit"),
           ("bar_repeat", "Bar repeat", 0.0, 1.0, 0.05, "Chance a bar repeats the one before (glitch)")]


def class_color(c: str) -> QColor:
    return {"kick": Theme.cv, "snare": Theme.trig, "hat": Theme.special}.get(c, Theme.octave)


def new_seed() -> int:
    return random.randint(1, 99999)


class JungleTool(C.Tool):
    key = "jungle"
    label = "Junglize"
    panel_tabs = ("Source", "Groove", "Output")
    primary = "▶  Junglize"
    primary_tip = "Write the break as a chain: .wav + .slc + .kit (the seed shown on the stage)"
    secondary = "Roll"
    secondary_tip = "A new break with a new seed: rendered and played, nothing written"
    subtitle = "any audio → jungle break → ER-301 · SSP"

    def __init__(self, main):
        self.s = main.s
        job = engine.JungleJob(source="")
        d = dict(in_dir=_default_dir("SLICEMACHINE_INPUT", "input"), out_dir=_default_dir("SLICEMACHINE_OUTPUT", "output"),
                 source="", name="", tempo="as_is")
        for k in ("bpm", "bars", "mode", "feel", "seed", "sr", "swing", "ring", "stretch", "stutter", "reverse", "humanize",
                  "bar_repeat", "sub", "source_bpm", "loops", "kit"):
            d[k] = getattr(job, k)
        d["source_bpm"] = 140.0
        self.o = self.load_opts(d)
        if self.o["mode"] not in engine.JUNGLE_MODES:
            self.o["mode"] = "substitute"
        self.files: List[str] = []
        self.render: Optional[dict] = None      # last rendered break (preview or written)
        self.render_sig: Optional[str] = None
        self.written: Optional[dict] = None
        self.sel: Optional[int] = None
        super().__init__(main)

    def make_drawing(self):
        return JungleDrawing(self)

    def set(self, rebuild=False, **kw):
        self.o.update(kw)
        self.save_opts(self.o)
        self.changed(rebuild)

    def shown(self):
        self.files = engine.scan_audio(self.o["in_dir"])
        src = self.o["source"]
        if src and not os.path.isfile(src):
            self.o["source"] = ""
        if not self.o["source"] and self.files:
            self.o["source"] = self.files[0]
        self.changed(True)

    def job(self, seed: Optional[int] = None) -> engine.JungleJob:
        o = self.o
        t = o["tempo"]
        return engine.JungleJob(source=o["source"], out_dir=o["out_dir"], name=o["name"], bpm=float(o["bpm"]), bars=int(o["bars"]),
                                mode=o["mode"], feel=o["feel"], seed=int(o["seed"] if seed is None else seed), sr=int(o["sr"]),
                                swing=float(o["swing"]), ring=float(o["ring"]), stretch=bool(o["stretch"]),
                                stutter=float(o["stutter"]), reverse=float(o["reverse"]), humanize=float(o["humanize"]),
                                bar_repeat=float(o["bar_repeat"]), sub=bool(o["sub"]),
                                source_bpm=float(o["source_bpm"]) if t == "set" else 0.0, detect_tempo=t == "detect",
                                loops=int(o["loops"]), kit=bool(o["kit"]))

    def signature(self) -> str:
        j = self.job()
        return repr({k: v for k, v in j.__dict__.items() if k not in ("out_dir", "name", "loops", "kit")})

    def can_run(self):
        if not self.o["source"] or not os.path.isfile(self.o["source"]):
            return False, "Pick a source file under Source."
        return True, ""

    def preview_path(self) -> str:
        return str(store.data_dir() / "jungle-preview.wav")

    # ── actions ──
    def run_secondary(self):
        """Roll: new seed, render, play."""
        self.o["seed"] = new_seed()
        self.save_opts(self.o)
        self.preview()

    def preview(self):
        job, sig, path = self.job(), self.signature(), self.preview_path()

        def done(r):
            self.render, self.render_sig, self.sel = r, sig, None
            self.main.play(path, 0, None, f"Seed {job.seed}  ·  {job.bpm:g} BPM  ·  {job.bars} bar{'s' if job.bars != 1 else ''}")
            self.changed(True)

        self.main.run_tool(f"Rolling a break (seed {job.seed})", lambda step: engine.jungle_preview(job, path), done)

    def run(self):
        job, sig = self.job(), self.signature()

        def done(r):
            self.render, self.render_sig, self.written, self.sel = r, sig, r["paths"], None
            p = r["paths"]
            exts = " ".join(os.path.splitext(x)[1] for k, x in p.items() if k != "loop")
            loop = f" and {os.path.basename(p['loop'])}" if "loop" in p else ""
            self.main.set_status("ok", f"Wrote {job.stem()} {exts}{loop} — {len(set(r['markers']))} slices, seed {job.seed}.", p["wav"])
            self.changed(True)

        self.main.run_tool(f"Junglizing {os.path.basename(job.source)}", lambda step: engine.run_junglize(job, step), done)

    def dropped(self, paths):
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p) and p.lower().endswith(engine.AUDIO_EXTS)]
        if dirs:
            self.o["in_dir"] = dirs[0]
        if files:
            self.o["in_dir"] = os.path.dirname(files[0])
            self.o["source"] = files[0]
        self.save_opts(self.o)
        self.shown()

    def pick_source(self, f: str):
        self.set(rebuild=True, source=f)

    def fresh(self) -> bool:
        return self.render is not None and self.render_sig == self.signature()

    def play_slice(self, i: int):
        self.sel = i
        self.changed()
        r = self.render
        if not r:
            return
        b = C.bounds(r["wave"].markers, r["wave"].frames)
        if 0 <= i < len(b):
            s, e = b[i]
            self.main.play(r["play"], s, e, f"Slice {i + 1}  ·  {C.ms((e - s) / r['sr'] * 1000)}")

    def play_event(self, i: int):
        """A hit of the (tempo-aligned) source, as the cut engine sees it."""
        a = self.render["analysis"] if self.render else None
        if not a or not (0 <= i < len(a["all_segs"])):
            return
        import soundfile as sf
        tmp = str(store.data_dir() / "jungle-hit.wav")
        try:
            sf.write(tmp, a["all_segs"][i], a["sr"], subtype="PCM_16")
        except Exception as ex:   # noqa: BLE001
            return self.main.set_status("warn", f"Could not play it: {ex}")
        s0, e0 = a["events"][i]
        self.main.play(tmp, 0, None, f"Source hit {i + 1}: {a['labels'][i]}  ·  {C.ms((e0 - s0) / a['sr'] * 1000)}")

    def space(self):
        if self.sel is not None:
            return self.play_slice(self.sel)
        if self.render:
            self.main.play(self.render["play"], 0, None, f"Seed {self.render['seed']}")

    # ── panel ──
    def build_panel(self, tab, col):
        o = self.o
        if tab == "Source":
            c = C.card("Source", Theme.cv)
            c.add(C.folder_row(self.main, "Folder", o["in_dir"], lambda d: (self.set(in_dir=d, source=""), self.shown()), True))
            if not self.files:
                c.add(C.note("No audio here. Choose another folder or drop a file onto the window."))
            for f in self.files:
                info = engine.file_info(f)
                pair = engine.pair_for(f) if f.lower().endswith(".wav") else None
                meta = "can't read" if info.error else C.secs(info.duration) + ("  chain" if pair else "")
                c.add(C.FileRow(os.path.basename(f), meta, f == o["source"], f == o["source"],
                                lambda on, f=f: self.pick_source(f), lambda f=f: self.pick_source(f), f, bool(info.error)))
            c.add(C.note("One file at a time: a break, a sliced chain, a field recording, a vocal …"))
            col.addWidget(c)

            c = C.card("Source tempo", Theme.special)
            c.add(W.Segmented(TEMPO, o["tempo"], lambda v: self.set(rebuild=True, tempo=v)))
            if o["tempo"] == "set":
                c.add(W.row("Source BPM", W.DecimalField(float(o["source_bpm"]), 40.0, 300.0, lambda v: self.set(source_bpm=v), 70)))
            c.add(C.note({"as_is": "The source is sliced as it is.",
                          "set": "The whole source is stretched from this tempo to the target BPM before slicing, so a real break locks to the grid.",
                          "detect": "The source's tempo is detected and stretched to the target BPM before slicing."}[o["tempo"]]))
            c.add(W.row("Sample rate", W.Picker(RATES, int(o["sr"]), lambda v: self.set(sr=v), 120)))
            col.addWidget(c)
        elif tab == "Groove":
            c = C.card("Groove", Theme.cv)
            c.add(W.row("Tempo (BPM)", W.DecimalField(float(o["bpm"]), 60.0, 260.0, lambda v: self.set(bpm=v), 70)))
            c.add(W.row("Bars", W.NumberField(int(o["bars"]), 1, 64, lambda v: self.set(bars=v), 40)))
            c.add(W.label("Mode", 12, MEDIUM))
            c.add(W.Segmented([(k, k.capitalize()) for k in engine.JUNGLE_MODES], o["mode"], lambda v: self.set(rebuild=True, mode=v)))
            c.add(C.note(engine.JUNGLE_MODES[o["mode"]]))
            c.add(W.label("Feel", 12, MEDIUM))
            c.add(W.Segmented(FEEL_LABELS, o["feel"], lambda v: self.set(feel=v)))
            col.addWidget(c)

            c = C.card("Seed", Theme.function)
            seed = W.NumberField(int(o["seed"]), 0, 999999, lambda v: self.set(seed=v), 70)
            c.add(W.row("Seed", seed))
            c.add(W.hbox(W.small_button("Listen to this seed", self.preview), W.small_button("New seed", lambda: self.set(rebuild=True, seed=new_seed())),
                         "stretch"))
            c.add(C.note("Same seed + same settings = the same break, here and in the terminal. “Roll” in the bar picks a new one and plays it."))
            col.addWidget(c)

            c = C.card("Cuts", Theme.trig)
            for k, text, lo, hi, step, tip in AMOUNTS:
                f = W.DecimalField(float(o[k]), lo, hi, lambda v, k=k: self.set(**{k: v}), 60)
                f.setSingleStep(step)
                r = W.row(text, f)
                r.setToolTip(tip)
                c.add(r)
            c.add(W.switch_row("Stretch hits to fill their step", bool(o["stretch"]), lambda v: self.set(stretch=v)))
            c.add(W.switch_row("Sub-bass on kicks and downbeats", bool(o["sub"]), lambda v: self.set(sub=v)))
            col.addWidget(c)
        else:
            c = C.card("Output", Theme.cv)
            job = self.job()
            e = QLineEdit(o["name"])
            e.setPlaceholderText(job.stem() if o["source"] else "name")
            e.textEdited.connect(lambda t: (self.o.update(name=t), self.save_opts(self.o), self.changed()))
            c.add(W.label("Name", 12, MEDIUM))
            c.add(e)
            c.add(C.folder_row(self.main, "Output folder", o["out_dir"], lambda d: self.set(rebuild=True, out_dir=d)))
            c.add(W.switch_row("GRID .kit for the Percussa SSP", bool(o["kit"]), lambda v: self.set(rebuild=True, kit=v)))
            c.add(W.row("Also a looped .wav (×)", W.NumberField(int(o["loops"]), 1, 64, lambda v: self.set(rebuild=True, loops=v), 40)))
            files = f"{job.stem()}.wav  .slc" + ("  .kit" if o["kit"] else "") + (f"\n{job.stem()}_x{int(o['loops'])}.wav" if int(o["loops"]) > 1 else "")
            c.add(W.label(files, 10.5, SEMIBOLD, "mono", Theme.dim))
            if o["source"] and os.path.exists(job.out_path()):
                c.add(C.note("A break with this name is already there and will be replaced.", Theme.trig))
            col.addWidget(c)
            if o["source"]:
                c = C.card("Same break from the terminal")
                lb = W.label(job.cli(), 10, REGULAR, "mono", Theme.dim, wrap=True)
                lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
                c.add(lb)
                col.addWidget(c)


class JungleDrawing(Drawing):
    base = (1100.0, 640.0)

    def __init__(self, tool: JungleTool):
        super().__init__()
        self.t = tool

    def paint(self, p, w, h):
        t, o = self.t, self.t.o
        r = t.render
        job = t.job()
        C.caption("junglize", Theme.dim, 10).paint(p, 40, 30)
        title = os.path.basename(t.written["wav"]) if (t.written and t.fresh()) else (job.stem() + ".wav" if o["source"] else "No source")
        draw.Text(title, Theme.font(22, BOLD, "title"), Theme.ink, max_w=w - 300).paint(p, 40, 52)
        meta = (f"{job.bpm:g} BPM  ·  {job.bars} bar{'s' if job.bars != 1 else ''}  ·  {job.mode}  ·  {job.feel}  ·  seed {job.seed}"
                + (f"  ·  {C.secs(r['wave'].duration)}  ·  {len(set(r['markers']))} slices" if r and t.fresh() else ""))
        draw.Text(meta, Theme.font(11, SEMIBOLD, "mono"), Theme.dim, max_w=w - 80).paint(p, 40, 86)

        # the source with its hits, coloured by class
        src_rect = QRectF(40, 136, w - 80, 92)
        a = r["analysis"] if r else None
        same_src = a is not None and a["wave"].title == os.path.basename(o["source"])
        if same_src:
            C.paint_wave(p, src_rect, a["wave"], Theme.body, show_markers=False, compact=True)
            X = lambda s: src_rect.left() + 10 + s / a["wave"].frames * (src_rect.width() - 20)   # noqa: E731
            for i, ((s0, e0), lab) in enumerate(zip(a["events"], a["labels"])):
                col = class_color(lab)
                p.setPen(draw.pen(col, 1.2))
                p.drawLine(QLineF(X(s0), src_rect.top() + 3, X(s0), src_rect.top() + 14))
                self.hits.add(QRectF(X(s0), src_rect.top(), max(2.0, X(e0) - X(s0)), src_rect.height()),
                              lambda i=i: t.play_event(i), f"{lab}  ·  {C.ms((e0 - s0) / a['sr'] * 1000)}  (click to hear it)")
            cap = f"source  ·  {len(a['events'])} hits" + (f"  ·  stretched {a['src_bpm']:.1f} → {job.bpm:g} bpm" if a["src_bpm"] else "")
        else:
            wave = None
            if o["source"] and os.path.exists(o["source"]):
                key = ("src", o["source"], os.path.getmtime(o["source"]))
                wv = t.main.wave(key, lambda f=o["source"]: engine.wave_of(f))
                wave = wv if isinstance(wv, engine.Wave) else None
            C.paint_wave(p, src_rect, wave, Theme.body, compact=True, empty_text="loading …" if o["source"] else "")
            cap = "source  ·  " + (os.path.basename(o["source"]) if o["source"] else "pick one on the right")
        C.caption(cap, Theme.dim, 9).paint(p, 40, src_rect.top() - 16)
        x = w - 40
        if same_src:
            for c in reversed(engine.JUNGLE_CLASSES):
                pill = C.pill_text(f"{c} {a['counts'][c]}", class_color(c), 0.16, 9)
                x -= pill.w
                pill.paint(p, x, src_rect.top() - 20)
                x -= 6

        # the break on its grid
        rect = QRectF(40, 276, w - 80, 220)
        C.caption("break" + ("" if not r or t.fresh() else "  ·  settings changed: Roll, or “Listen to this seed”"),
                  Theme.dim if not r or t.fresh() else Theme.trig, 9).paint(p, 40, rect.top() - 16)
        if r:
            wave = r["wave"]
            C.paint_wave(p, rect, wave, Theme.cv, hits=self.hits, sel=t.sel, on_slice=t.play_slice, numbers=False)
            inner_l, inner_w = rect.left() + 10, rect.width() - 20
            stepn = r["step"]
            for k in range(1, 16 * r["bars"]):
                xx = inner_l + k * stepn / wave.frames * inner_w
                bar = k % 16 == 0
                beat = k % 4 == 0
                p.setPen(draw.pen(Theme.c("special", 0.75) if bar else Theme.c("body", 0.22 if beat else 0.08), 1.3 if bar else 0.6))
                p.drawLine(QLineF(xx, rect.top() + 2, xx, rect.bottom() - 2))
            if r["bars"] > 1:
                for b in range(r["bars"]):
                    xx = inner_l + b * 16 * stepn / wave.frames * inner_w
                    C.caption(f"bar {b + 1}", Theme.special, 8.5).paint(p, xx + 3, rect.bottom() + 18)
            pr = C.pill_text("▶ PLAY BREAK", Theme.cv, 0.18, 10)
            pr.paint(p, w - 40 - pr.w, rect.bottom() + 14)
            self.hits.add(QRectF(w - 40 - pr.w, rect.bottom() + 14, pr.w, pr.h), lambda: t.space() if t.sel is None else
                          (setattr(t, "sel", None), t.space()), "Play the whole break (Space)")
        else:
            C.paint_wave(p, rect, None, Theme.cv, empty_text="Press “Roll” for a break" if o["source"] else "Pick a source on the right")

        # the settings as pills
        steps = [(f"{job.mode}", Theme.cv), (f"{job.feel}", Theme.cv), (f"swing {job.swing:g}", Theme.special),
                 (f"ring {job.ring:g}", Theme.special), (f"stutter {job.stutter:g}", Theme.trig), (f"reverse {job.reverse:g}", Theme.trig)]
        if job.bar_repeat:
            steps.append((f"bar repeat {job.bar_repeat:g}", Theme.trig))
        if job.stretch:
            steps.append(("stretch", Theme.octave))
        if job.sub:
            steps.append(("sub", Theme.octave))
        steps.append((".wav .slc" + (" .kit" if job.kit else ""), Theme.function))
        cx = 40.0
        for s, col in steps:
            pill = C.pill_text(s.upper(), col)
            if cx + pill.w > w - 40:
                break
            pill.paint(p, cx, 548)
            cx += pill.w + 6
        hint = ("✓ Written: " + C.short_path(t.written["wav"]) + ". Click a slice to hear it." if (t.written and t.fresh() and r and r.get("paths"))
                else "Click a slice or a source hit to hear it. Space plays the break, Esc stops." if r
                else "“Roll” makes a break with a new seed and plays it; “Junglize” writes the one you hear.")
        draw.Text(hint, Theme.font(11, REGULAR), Theme.special if hint.startswith("✓") else Theme.dim, max_w=w - 80).paint(p, 40, 590)
