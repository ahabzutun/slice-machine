"""Slicer tab: interactive_slicer.py as a form. Pick files, set how to slice, preview the cuts,
write <name>_chain.wav + .slc (ER-301) + .kit (SSP GRID)."""
from __future__ import annotations

import json
import os
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QFileDialog, QLineEdit

from .. import draw, engine, store
from .. import widgets as W
from ..stage import Drawing
from ..theme import BOLD, HEAVY, MEDIUM, REGULAR, SEMIBOLD, Theme
from . import common as C

RATES = [(22050, "22.05 kHz"), (32000, "32 kHz"), (44100, "44.1 kHz"), (48000, "48 kHz"), (96000, "96 kHz")]
ORDER = [("sequential", "Original order"), ("similarity", "By sound (spectral)"), ("bank", "Banks: 8 × 16")]
BANK_SORT = [("chronological", "Original order"), ("pitch_ascending", "Pitch low → high"),
             ("pitch_descending", "Pitch high → low")]
PROCESSING = [("none", "None"), ("normalize", "Normalize"), ("compress", "Compress"), ("both", "Both")]


def _default_dir(env: str, sub: str) -> str:
    return os.environ.get(env) or str(store.REPO / sub)


class SlicerTool(C.Tool):
    key = "slicer"
    label = "Slicer"
    panel_tabs = ("Source", "Slices", "Sound & output")
    primary = "▶  Slice"
    primary_tip = "Write the chain .wav, the ER-301 .slc and the GRID .kit"
    secondary = "Preview"
    secondary_tip = "Show where it will cut, without writing anything"
    subtitle = "→ ER-301 .slc · SSP .kit"

    def __init__(self, main):
        defaults = dict(in_dir=_default_dir("SLICEMACHINE_INPUT", "input"), out_dir=_default_dir("SLICEMACHINE_OUTPUT", "output"),
                        added=[], checked=[], combine=True, name="", kit=True, thread_dir=str(store.SRC), cdp_path="")
        job = engine.SliceJob(files=[])
        for k in ("slices", "sr", "length", "organize", "direction", "bank_sort", "remove_silence", "silence_db",
                  "processing", "comp_threshold_db", "comp_ratio", "comp_attack_ms", "comp_release_ms", "norm_method",
                  "norm_target_db", "cdp_pre", "cdp_post"):
            defaults[k] = getattr(job, k)
        self.key = "slicer"
        self.s = main.s
        self.o = self.load_opts(defaults)
        if self.o["length"] not in engine.SLICE_MODES:
            self.o["length"] = next(iter(engine.SLICE_MODES))
        self.files: List[str] = []
        self.focus: Optional[str] = None
        self.view = "source"
        self.preview_sig = None
        self.preview_wave: Optional[engine.Wave] = None
        self.results: List[dict] = []
        self.res_i = 0
        self.sel: Optional[int] = None
        super().__init__(main)

    def make_drawing(self):
        return SliceDrawing(self)

    # ── state ──
    def set(self, rebuild: bool = False, **kw):
        self.o.update(kw)
        self.save_opts(self.o)
        self.changed(rebuild)

    def scan(self):
        found = engine.scan_audio(self.o["in_dir"])
        added = [f for f in self.o["added"] if os.path.isfile(f) and f not in found]
        self.files = found + added
        checked = [f for f in self.o["checked"] if f in self.files]
        if checked != self.o["checked"]:
            self.o["checked"] = checked
            self.save_opts(self.o)
        if self.focus not in self.files:
            self.focus = (checked or self.files or [None])[0]

    @property
    def checked(self) -> List[str]:
        return [f for f in self.files if f in self.o["checked"]]

    def bank_possible(self) -> bool:
        return len(self.checked) == 8 and self.o["combine"]

    def organize(self) -> str:
        o = self.o["organize"]
        return "similarity" if o == "bank" and not self.bank_possible() else o

    def job(self) -> engine.SliceJob:
        o = self.o
        return engine.SliceJob(files=self.checked, combine=o["combine"], name=o["name"], out_dir=o["out_dir"],
                               slices=int(o["slices"]), sr=int(o["sr"]), length=o["length"], organize=self.organize(),
                               direction=o["direction"], bank_sort=o["bank_sort"], remove_silence=bool(o["remove_silence"]),
                               silence_db=float(o["silence_db"]), processing=o["processing"],
                               comp_threshold_db=float(o["comp_threshold_db"]), comp_ratio=float(o["comp_ratio"]),
                               comp_attack_ms=float(o["comp_attack_ms"]), comp_release_ms=float(o["comp_release_ms"]),
                               norm_method=o["norm_method"], norm_target_db=float(o["norm_target_db"]),
                               cdp_pre=o["cdp_pre"] if o["cdp_pre"] and os.path.isfile(o["cdp_pre"]) else "",
                               cdp_post=o["cdp_post"] if o["cdp_post"] and os.path.isfile(o["cdp_post"]) else "",
                               cdp_path=o["cdp_path"], kit=bool(o["kit"]))

    def preview_signature(self) -> str:
        j = self.job()
        keys = ("files", "combine", "slices", "sr", "length", "organize", "remove_silence", "silence_db")
        return json.dumps([getattr(j, k) for k in keys] + [self.focus if not (j.combine and len(j.files) > 1 and not j.bank_mode) else ""])

    def shown(self):
        self.scan()
        self.changed(True)

    def can_run(self):
        if not self.checked:
            return False, "Tick at least one file under Source."
        if not self.o["out_dir"]:
            return False, "Choose an output folder."
        return True, ""

    # ── actions ──
    def run(self):
        job = self.job()
        n = len(job.files)
        what = f"Slicing {os.path.basename(job.files[0])}" if n == 1 else f"Slicing {n} files"

        def done(results):
            for r in results:
                r["bank"] = job.bank_mode
            self.results, self.res_i, self.sel, self.view = results, 0, None, "chain"
            if not results:
                return self.main.set_status("warn", "Nothing was written.")
            short = [r for r in results if r["count"] < job.slices]
            names = ", ".join(os.path.basename(r["wav"]) for r in results[:3]) + (" …" if len(results) > 3 else "")
            first = results[0]
            extra = " + .kit" if first["kit"] else ""
            text = (f"Wrote {names} (.slc{extra}) — {first['count']} slices, {C.ms(first['shortest'])}–{C.ms(first['longest'])}."
                    if len(results) == 1 else f"Wrote {len(results)} chains: {names} (.slc{extra}).")
            if short:
                r = short[0]
                text += (f"  Only {r['count']} of {job.slices} slices in {os.path.basename(r['wav'])}: the audio can't be cut "
                         f"finer than the {job.length} minimum ({engine.SLICE_MODES[job.length]['min_duration_ms']} ms).")
            if job.kit and job.slices > engine.GRID_MAX_SLICES:
                text += f"  GRID plays the first {engine.GRID_MAX_SLICES} slices per pad."
            self.main.set_status("warn" if short else "ok", text, results[0]["wav"])
            self.changed(True)

        self.main.run_tool(what, lambda step: engine.run_slicer(job, step), done)

    def run_secondary(self):
        job = self.job()
        focus = self.focus if self.focus in job.files else job.files[0]
        self.focus = focus
        sig = self.preview_signature()

        def done(wave):
            self.preview_wave, self.preview_sig, self.view, self.sel = wave, sig, "source", None
            self.main.set_status("ok", f"Preview: {len(wave.markers)} slices in {wave.title} (nothing written). "
                                       "Click a slice to hear it.")
            self.changed(True)

        self.main.run_tool(f"Preview of {os.path.basename(focus)}", lambda step: engine.preview(job, focus), done)

    def dropped(self, paths: List[str]):
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p) and p.lower().endswith(engine.AUDIO_EXTS)]
        if dirs:
            self.o["in_dir"] = dirs[0]
        for f in files:
            if f not in self.o["added"] and os.path.dirname(f) != self.o["in_dir"]:
                self.o["added"].append(f)
            if f not in self.o["checked"]:
                self.o["checked"].append(f)
        self.save_opts(self.o)
        self.scan()
        if files:
            self.focus = files[0]
        self.view = "source"
        self.main.set_status("info", f"Added {len(files)} file{'s' if len(files) != 1 else ''}." if files else f"Input folder: {dirs[0]}")
        self.changed(True)

    def set_focus(self, f: str):
        self.focus, self.view, self.sel = f, "source", None
        self.changed(True)

    def toggle(self, f: str, on: bool):
        ch = [x for x in self.o["checked"] if x != f] + ([f] if on else [])
        self.set(rebuild=True, checked=ch)
        if on:
            self.focus = f

    # ── what the stage shows ──
    def current_result(self) -> Optional[dict]:
        if not self.results:
            return None
        self.res_i = max(0, min(self.res_i, len(self.results) - 1))
        return self.results[self.res_i]

    def stage_wave(self):
        """(wave or None, playable file, sr of that file, title, meta)."""
        if self.view == "chain" and self.current_result():
            r = self.current_result()
            key = ("chain", r["wav"], os.path.getmtime(r["wav"]) if os.path.exists(r["wav"]) else 0)
            w = self.main.wave(key, lambda: engine.chain_wave(r["wav"], r["slc"]))
            return w, r["wav"]
        if self.preview_wave is not None and self.preview_sig == self.preview_signature():
            combined = self.preview_wave.title.endswith("combined")
            return self.preview_wave, (None if combined else self.focus)
        if self.focus and os.path.exists(self.focus):
            key = ("src", self.focus, os.path.getmtime(self.focus))
            return self.main.wave(key, lambda f=self.focus: engine.wave_of(f)), self.focus
        return None, None

    def play_slice(self, i: int):
        self.sel = i
        w, path = self.stage_wave()
        self.changed()
        if not isinstance(w, engine.Wave):
            return
        b = C.bounds(w.markers, w.frames)
        if not (0 <= i < len(b)):
            return
        if path is None:
            return self.main.set_status("info", f"Slice {i + 1}: the preview of combined files can't be played — slice first, "
                                                "then listen in the CHAIN view.")
        s, e = b[i]
        info = engine.file_info(path)
        k = info.sr / w.sr if info.sr and w.sr else 1.0           # preview markers are at the job's sample rate
        self.main.play(path, int(s * k), int(e * k), f"Slice {i + 1} of {os.path.basename(path)}  ·  {C.ms((e - s) / w.sr * 1000)}")

    def space(self):
        w, path = self.stage_wave()
        if self.sel is not None:
            self.play_slice(self.sel)
        elif path and isinstance(w, engine.Wave):
            self.main.play(path, 0, None, os.path.basename(path))

    # ── side panel ──
    def build_panel(self, tab: str, col):
        self.scan()
        if tab == "Source":
            self._panel_source(col)
        elif tab == "Slices":
            self._panel_slices(col)
        else:
            self._panel_output(col)

    def _panel_source(self, col):
        o = self.o
        c = C.card("Input folder", Theme.cv)
        c.add(C.folder_row(self.main, "Folder", o["in_dir"], lambda d: (self.set(rebuild=True, in_dir=d), self.scan(), self.changed(True)),
                           must_exist=True))

        def add_files():
            fs, _ = QFileDialog.getOpenFileNames(self.main, "Add audio files", o["in_dir"],
                                                 "Audio (" + " ".join("*" + e for e in engine.AUDIO_EXTS) + ")")
            if fs:
                self.dropped(fs)

        c.add(W.hbox(W.small_button("Add files…", add_files), W.small_button("Rescan", lambda: (self.scan(), self.changed(True))),
                     "stretch"))
        col.addWidget(c)

        c = C.card(f"Files  ·  {len(self.checked)} of {len(self.files)} ticked", Theme.cv)
        if not self.files:
            c.add(C.note("No audio in this folder. Choose another one, use “Add files…” or drop files onto the window."))
        for f in self.files:
            info = engine.file_info(f)
            meta = "can't read" if info.error else f"{C.secs(info.duration)}  {C.mb(info.size)}"
            tip = f + ("" if info.error else f"\n{C.khz(info.sr)} · {info.channels} ch")
            c.add(C.FileRow(os.path.basename(f), meta, f in o["checked"], f == self.focus,
                            lambda on, f=f: self.toggle(f, on), lambda f=f: self.set_focus(f), tip, bool(info.error)))
        if self.files:
            extra = []
            if self.o["added"]:
                extra.append(W.small_button("Forget added", lambda: (self.set(added=[], rebuild=True), self.scan(), self.changed(True))))
            c.add(C.check_all_row(lambda: self.set(rebuild=True, checked=list(self.files)),
                                  lambda: self.set(rebuild=True, checked=[]), extra))
        col.addWidget(c)

        n = len(self.checked)
        if n > 1:
            c = C.card("Several files", Theme.special)
            c.add(W.Segmented([(True, "One chain"), (False, "A chain each")], o["combine"],
                              lambda v: self.set(rebuild=True, combine=v)))
            c.add(C.note("All ticked files are joined and sliced as one chain." if o["combine"] else
                         "Every file becomes its own chain, named after the file."))
            col.addWidget(c)
        if n == 1 or (n > 1 and o["combine"]):
            c = C.card("Name")
            e = QLineEdit(o["name"])
            default = "combined" if n > 1 else engine.clean_name(os.path.splitext(os.path.basename(self.checked[0]))[0])
            e.setPlaceholderText(default)
            e.textEdited.connect(lambda t: (self.o.update(name=t), self.save_opts(self.o), self.changed()))
            c.add(e)
            c.add(C.note("Spaces become _ and letters lower case, like in the terminal version."))
            col.addWidget(c)

    def _panel_slices(self, col):
        o = self.o
        c = C.card("Slices", Theme.cv)
        nf = W.NumberField(int(o["slices"]), 1, 4096, lambda v: self.set(slices=v), 46)
        nf.setEnabled(self.organize() != "bank")
        c.add(W.row("Number of slices", nf))
        if self.organize() == "bank":
            c.add(C.note("Bank mode always makes 128 slices: 16 from each of the 8 files.", Theme.special))
        rates = list(RATES) if any(r == int(o["sr"]) for r, _ in RATES) else list(RATES) + [(int(o["sr"]), f"{int(o['sr'])} Hz")]
        c.add(W.row("Sample rate", W.Picker(rates, int(o["sr"]), lambda v: self.set(sr=v), 120)))
        c.add(C.note("Forced exactly: long slices are split until the count is reached (never below the mode's minimum length)."
                     + (f" The GRID .kit holds {engine.GRID_MAX_SLICES} slices per pad." if int(o["slices"]) > engine.GRID_MAX_SLICES and o["kit"] else "")))
        col.addWidget(c)

        c = C.card("Slice length", Theme.cv)
        c.add(W.Segmented([(k, k.capitalize()) for k in engine.SLICE_MODES], o["length"], lambda v: self.set(rebuild=True, length=v)))
        m = engine.SLICE_MODES[o["length"]]
        c.add(C.note(m["description"]))
        c.add(W.label(f"min {m['min_duration_ms']} ms  ·  target {m['target_duration_ms']} ms  ·  hop {m['hop_length']}",
                      10.5, SEMIBOLD, "mono", Theme.dim))
        col.addWidget(c)

        c = C.card("Order in the chain", Theme.special)
        bank_ok = self.bank_possible()
        opts = ORDER if bank_ok else ORDER[:2]
        cur = self.organize()
        c.add(W.row("Order", W.Picker(opts, cur, lambda v: self.set(rebuild=True, organize=v), 170)))
        if cur == "similarity":
            c.add(W.Segmented([("low_to_high", "Low → high"), ("high_to_low", "High → low")], o["direction"],
                              lambda v: self.set(direction=v)))
            c.add(C.note("Low → high: kicks and bass first, hats last. High → low: the other way round."))
        elif cur == "bank":
            c.add(W.row("Within each bank", W.Picker(BANK_SORT, o["bank_sort"], lambda v: self.set(bank_sort=v), 170)))
            c.add(C.note("One file per bank: 16 slices from each of the 8 files, for controllers with 8 banks of 16 pads."))
        if not bank_ok:
            c.add(C.note("Banks (8 × 16) need exactly 8 ticked files joined into one chain."))
        col.addWidget(c)

        c = C.card("Silence", Theme.trig)
        c.add(W.switch_row("Remove silent slices", bool(o["remove_silence"]), lambda v: self.set(rebuild=True, remove_silence=v)))
        if o["remove_silence"]:
            c.add(W.row("Threshold (dB)", W.NumberField(int(o["silence_db"]), -90, -6, lambda v: self.set(silence_db=float(v)), 46)))
            c.add(C.note("−60 only complete silence · −50 room tone · −40 tails and decay (recommended) · −30 only loud hits. "
                         "Checked after slicing; the count is filled up again afterwards."))
        col.addWidget(c)

    def _panel_output(self, col):
        o = self.o
        c = C.card("Processing", Theme.octave)
        c.add(W.Segmented(PROCESSING, o["processing"], lambda v: self.set(rebuild=True, processing=v)))
        if o["processing"] in ("compress", "both"):
            c.add(W.row("Compressor threshold (dB)", W.NumberField(int(o["comp_threshold_db"]), -60, 0, lambda v: self.set(comp_threshold_db=float(v)), 46)))
            c.add(W.row("Ratio", W.DecimalField(float(o["comp_ratio"]), 1.0, 20.0, lambda v: self.set(comp_ratio=v), 60)))
            c.add(W.row("Attack (ms)", W.NumberField(int(o["comp_attack_ms"]), 0, 500, lambda v: self.set(comp_attack_ms=float(v)), 46)))
            c.add(W.row("Release (ms)", W.NumberField(int(o["comp_release_ms"]), 1, 2000, lambda v: self.set(comp_release_ms=float(v)), 46)))
        if o["processing"] in ("normalize", "both"):
            c.add(W.row("Normalize", W.Picker([("peak", "Peak"), ("rms", "RMS")], o["norm_method"], lambda v: self.set(norm_method=v), 100)))
            c.add(W.row("Target (dB)", W.DecimalField(float(o["norm_target_db"]), -30.0, 0.0, lambda v: self.set(norm_target_db=v), 60)))
        c.add(C.note("Applied to the finished chain (compressor first, then normalizing)."))
        col.addWidget(c)

        c = C.card("CDP / SoundThread", Theme.special)
        cdp_dir = o["cdp_path"] or engine.default_cdp_path()
        have_cdp = bool(cdp_dir) and os.path.isdir(os.path.expanduser(cdp_dir))
        threads = engine.scan_threads(o["thread_dir"])
        topts = [("", "Off")] + [(t, os.path.basename(t)) for t in threads]
        c.add(W.row("Before slicing", W.Picker(topts, o["cdp_pre"] if o["cdp_pre"] in threads else "",
                                                lambda v: self.set(rebuild=True, cdp_pre=v), 190)))
        c.add(W.row("Every slice", W.Picker(topts, o["cdp_post"] if o["cdp_post"] in threads else "",
                                             lambda v: self.set(rebuild=True, cdp_post=v), 190)))
        if not threads:
            c.add(C.note("No .thd threads in the thread folder."))
        elif not have_cdp and (o["cdp_pre"] or o["cdp_post"]):
            c.add(C.note("The CDP programs folder below doesn't exist on this computer: slicing will stop with an error.", Theme.trig))
        else:
            c.add(C.note("Before slicing: the whole file once (granular, spectral). Every slice: each slice on its own (ring mod, distortion)."))
        c.add(C.folder_row(self.main, "Thread folder (.thd)", o["thread_dir"], lambda d: self.set(rebuild=True, thread_dir=d), True))
        e = QLineEdit(o["cdp_path"])
        e.setPlaceholderText(engine.default_cdp_path() or "…/_cdp/_cdprogs")
        e.setToolTip("Folder with the CDP programs (empty: the default from cdp_processor.py)")
        e.editingFinished.connect(lambda: self.set(rebuild=True, cdp_path=e.text().strip()))
        c.add(W.label("CDP programs", 12, MEDIUM))
        c.add(e)
        col.addWidget(c)

        c = C.card("Files written", Theme.cv)
        c.add(C.folder_row(self.main, "Output folder", o["out_dir"], lambda d: self.set(rebuild=True, out_dir=d)))
        c.add(W.switch_row("GRID .kit for the Percussa SSP", bool(o["kit"]), lambda v: self.set(rebuild=True, kit=v)))
        if self.checked:
            outs = self.job().outputs()
            for p in outs[:6]:
                stem = os.path.splitext(os.path.basename(p))[0]
                c.add(W.label(f"{stem}.wav  .slc{'  .kit' if o['kit'] else ''}", 10.5, SEMIBOLD, "mono", Theme.dim))
            if len(outs) > 6:
                c.add(W.label(f"… and {len(outs) - 6} more", 10.5, REGULAR, "mono", Theme.dim))
            if any(os.path.exists(p) for p in outs):
                c.add(C.note("Files with these names are already there and will be replaced.", Theme.trig))
        col.addWidget(c)


class SliceDrawing(Drawing):
    base = (1100.0, 640.0)

    def __init__(self, tool: SlicerTool):
        super().__init__()
        self.t = tool

    def paint(self, p, w, h):
        t = self.t
        hits = self.hits
        has_res = bool(t.results)
        C.view_pills(p, hits, 40, 24, [("source", "SOURCE", True), ("chain", "CHAIN", has_res)],
                     t.view if has_res else "source", lambda k: (setattr(t, "view", k), setattr(t, "sel", None), t.changed()))
        wave, path = t.stage_wave()
        r = t.current_result() if t.view == "chain" else None
        if r and len(t.results) > 1:
            self._result_switch(p, w)

        # title + facts
        rect = QRectF(40, 160, w - 80, 290)
        if isinstance(wave, Exception):
            title, meta = os.path.basename(path or ""), f"can't read: {wave}"
            wave = None
        elif r:
            title = os.path.basename(r["wav"])
            meta = (f"{r['count']} slices  ·  {C.ms(r['shortest'])} – {C.ms(r['longest'])}  (avg {C.ms(r['average'])})  ·  "
                    f"{C.secs(r['seconds'])} @ {C.khz(r['sr'])}")
        elif wave is not None:
            title = wave.title
            info = engine.file_info(path) if path else None
            meta = f"{C.secs(wave.duration)}"
            if info and not info.error:
                meta += f"  ·  {C.khz(info.sr)}  ·  {'mono' if info.channels == 1 else f'{info.channels} ch'}  ·  {C.mb(info.size)}"
            if wave.markers:
                meta += f"  ·  preview: {len(wave.markers)} slices"
        elif t.focus:
            title, meta = os.path.basename(t.focus), "loading …"
        else:
            title, meta = "No file", "Tick files on the right, or drop audio files onto the window."
        draw.Text(title, Theme.font(22, BOLD, "title"), Theme.ink, max_w=w - 80 - 260).paint(p, 40, 64)
        draw.Text(meta, Theme.font(11, SEMIBOLD, "mono"), Theme.dim, max_w=w - 80).paint(p, 40, 100)

        # selected slice, top right
        if isinstance(wave, engine.Wave) and t.sel is not None:
            b = C.bounds(wave.markers, wave.frames)
            if 0 <= t.sel < len(b):
                s0, e0 = b[t.sel]
                txt = draw.Text(f"SLICE {t.sel + 1}  ·  {C.ms((e0 - s0) / wave.sr * 1000)}  ·  {e0 - s0:,} samples",
                                Theme.font(10, HEAVY, "mono"), Theme.cv, tracking=0.8)
                pill = draw.Pill(txt, 9, 4, Theme.c("cv", 0.14), Theme.c("cv", 0.5))
                pill.paint(p, w - 40 - pill.w, 104)

        banks = 8 if (r and r.get("bank") and r["count"] == 128) else 0
        stale = (t.view == "source" and t.preview_wave is not None and t.preview_sig != t.preview_signature()
                 and wave is not t.preview_wave)
        accent = Theme.cv if t.view == "chain" or (isinstance(wave, engine.Wave) and wave.markers) else Theme.body
        C.paint_wave(p, rect, wave if isinstance(wave, engine.Wave) else None, accent, hits=hits, sel=t.sel,
                     on_slice=t.play_slice, banks=banks,
                     empty_text="loading …" if (t.focus and wave is None) else "Nothing to show yet")

        # the chain of settings, as pills
        self._settings_flow(p, 40, 492, w - 80)
        hint = ("Click a slice to hear it (Space plays it again).  ↓ files are in " + C.short_path(os.path.dirname(r["wav"])) if r else
                "Settings changed since the preview: press Preview again." if stale else
                "Preview shows where it will cut. Click a slice to hear it." if not (isinstance(wave, engine.Wave) and wave.markers) else
                "Click a slice to hear it. “Slice” writes the files.")
        draw.Text(hint, Theme.font(11, REGULAR), Theme.trig if stale else Theme.dim, max_w=w - 80).paint(p, 40, 590)

    def _result_switch(self, p, w):
        t = self.t
        n = len(t.results)
        txt = draw.Text(f"{t.res_i + 1} / {n}", Theme.font(10, HEAVY, "mono"), Theme.ink)
        x = w - 40
        for label, d in (("▸", 1), (None, 0), ("◂", -1)):
            item = txt if label is None else draw.Text(label, Theme.font(12, HEAVY, "mono"), Theme.cv)
            pill = draw.Pill(item, 9, 4, Theme.c("card", 0.6), Theme.line)
            x -= pill.w
            pill.paint(p, x, 24)
            if d:
                self.hits.add(QRectF(x, 24, pill.w, pill.h),
                              lambda d=d: (setattr(t, "res_i", (t.res_i + d) % n), setattr(t, "sel", None), t.changed()),
                              "Next chain" if d > 0 else "Previous chain")
            x -= 6

    def _settings_flow(self, p, x, y, width):
        t, o = self.t, self.t.o
        j = t.job()
        m = engine.SLICE_MODES[o["length"]]
        steps = []
        n = len(j.files)
        steps.append((f"{n} FILE{'S' if n != 1 else ''}" + (" → 1 CHAIN" if n > 1 and j.combine else " → A CHAIN EACH" if n > 1 else ""), Theme.ink))
        if j.cdp_pre:
            steps.append(("CDP " + os.path.splitext(os.path.basename(j.cdp_pre))[0], Theme.special))
        steps.append((f"{o['length'].upper()} ≥{m['min_duration_ms']} MS", Theme.cv))
        steps.append(("8 × 16 SLICES" if j.bank_mode else f"{int(o['slices'])} SLICES", Theme.cv))
        if j.remove_silence:
            steps.append((f"SILENCE {j.silence_db:g} DB", Theme.trig))
        if j.cdp_post:
            steps.append(("CDP/SLICE " + os.path.splitext(os.path.basename(j.cdp_post))[0], Theme.special))
        org = {"sequential": "ORIGINAL ORDER", "bank": "8 BANKS × 16",
               "similarity": "LOW → HIGH" if j.direction == "low_to_high" else "HIGH → LOW"}[j.organize]
        steps.append((org, Theme.special))
        if j.processing != "none":
            steps.append(({"normalize": "NORMALIZE", "compress": "COMPRESS", "both": "COMPRESS + NORMALIZE"}[j.processing], Theme.octave))
        steps.append((".WAV .SLC" + (" .KIT" if j.kit else ""), Theme.function))
        cx, cy = x, y
        arrow = draw.Text("→", Theme.font(11, BOLD, "mono"), Theme.dim)
        for k, (s, col) in enumerate(steps):
            pill = C.pill_text(s, col)
            if cx + pill.w > x + width:
                cx, cy = x, cy + pill.h + 10
            pill.paint(p, cx, cy)
            cx += pill.w + 5
            if k < len(steps) - 1:
                arrow.paint(p, cx, cy + (pill.h - arrow.h) / 2)
                cx += arrow.w + 5
