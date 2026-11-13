"""
The work behind the buttons. Every tool calls the same functions as the command-line scripts in
src/ (interactive_slicer, merge_chains, split_chain, prepare_nerdseq, chain_to_grid_kit), with the
answers to their prompts coming from the app instead of input(). Their printed progress is caught
line by line and shown in the app's log.

Runs in a worker thread: nothing here touches Qt widgets.
"""
from __future__ import annotations

import ast
import contextlib
import io
import os
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .store import SRC

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".aif", ".aiff", ".m4a")     # as scan_audio_files()
NERDSEQ_EXTS = AUDIO_EXTS + (".wave",)                                       # as prepare_nerdseq.INPUT_EXTS


# ── reading the scripts' constants without importing librosa (slow) ────────────────────────────

def _constant(module: str, name: str):
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(f"{name} not found in {module}.py")


SLICE_MODES: Dict[str, dict] = _constant("interactive_slicer", "SLICE_MODES")
NERDSEQ_MEM = 190 * 1024
NERDSEQ_SLOTS = 12
NERDSEQ_SR = 44100
GRID_PADS = 8
GRID_MAX_SLICES = 128
try:
    NERDSEQ_SLOTS = _constant("prepare_nerdseq", "NUM_SLOTS")
    NERDSEQ_SR = _constant("prepare_nerdseq", "REFERENCE_SR")
    GRID_PADS = _constant("chain_to_grid_kit", "GRID_NUM_PADS")
    GRID_MAX_SLICES = _constant("chain_to_grid_kit", "GRID_MAX_SLICES")
except Exception:
    pass


def slicer():
    """interactive_slicer, imported on first use (pulls in librosa)."""
    import interactive_slicer
    return interactive_slicer


def warm_up():
    """Import the heavy modules in the background so the first run starts right away."""
    with capture(lambda line: None):
        slicer()
        import merge_chains, split_chain, prepare_nerdseq, chain_to_grid_kit  # noqa: F401,E401


# ── catching the scripts' output ───────────────────────────────────────────────────────────────

class LineWriter(io.TextIOBase):
    def __init__(self, emit: Callable[[str], None]):
        self.emit, self.buf = emit, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.emit(line)
        return len(s)

    def flush(self):
        if self.buf:
            self.emit(self.buf)
            self.buf = ""


class _ThreadRouter(io.TextIOBase):
    """sys.stdout that sends each thread's prints where that thread wants them, so jobs running at the
    same time (warm-up, a slice run, a waveform) never swap each other's output."""

    def __init__(self, orig):
        self.orig = orig
        self.local = threading.local()

    def _target(self):
        return getattr(self.local, "w", None) or self.orig

    def write(self, s):
        return self._target().write(s)

    def flush(self):
        self._target().flush()

    def __getattr__(self, name):
        return getattr(self.orig, name)


_router_lock = threading.Lock()


@contextlib.contextmanager
def capture(emit: Callable[[str], None]):
    """Lines this thread prints go to emit() while inside the block."""
    with _router_lock:
        if not isinstance(sys.stdout, _ThreadRouter):
            sys.stdout = _ThreadRouter(sys.stdout)
        router = sys.stdout
    w = LineWriter(emit)
    prev = getattr(router.local, "w", None)
    router.local.w = w
    try:
        yield
    finally:
        w.flush()
        router.local.w = prev


# ── files ──────────────────────────────────────────────────────────────────────────────────────

def scan_audio(directory: str, exts=AUDIO_EXTS) -> List[str]:
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, f) for f in os.listdir(directory)
                  if f.lower().endswith(exts) and not f.startswith("."))


def scan_pairs(directory: str) -> List[Tuple[str, str]]:
    """Every .wav with a .slc next to it (same rule as the scripts)."""
    out = []
    for wav in scan_audio(directory, (".wav",)):
        slc = os.path.splitext(wav)[0] + ".slc"
        if os.path.isfile(slc):
            out.append((wav, slc))
    return out


def pair_for(wav: str) -> Optional[Tuple[str, str]]:
    slc = os.path.splitext(wav)[0] + ".slc"
    return (wav, slc) if os.path.isfile(slc) else None


def scan_threads(directory: str) -> List[str]:
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, f) for f in os.listdir(directory) if f.lower().endswith(".thd"))


def default_cdp_path() -> str:
    try:
        import inspect
        from cdp_processor import CDPProcessor
        return inspect.signature(CDPProcessor.__init__).parameters["cdp_path"].default
    except Exception:
        return ""


def clean_name(s: str) -> str:
    """Output names the way the slicer makes them: spaces → _, lower case."""
    return s.strip().replace(" ", "_").replace("/", "_").replace("\\", "_").lower()


@dataclass
class FileInfo:
    path: str
    frames: int = 0
    sr: int = 0
    channels: int = 0
    size: int = 0
    error: str = ""

    @property
    def duration(self) -> float:
        return self.frames / self.sr if self.sr else 0.0


_info_cache: Dict[tuple, FileInfo] = {}


def file_info(path: str) -> FileInfo:
    try:
        st = os.stat(path)
    except OSError as e:
        return FileInfo(path, error=str(e))
    key = (path, st.st_mtime, st.st_size)
    if key in _info_cache:
        return _info_cache[key]
    fi = FileInfo(path, size=st.st_size)
    try:
        import soundfile as sf
        i = sf.info(path)
        fi.frames, fi.sr, fi.channels = int(i.frames), int(i.samplerate), int(i.channels)
    except Exception:
        try:
            import librosa
            with contextlib.redirect_stderr(io.StringIO()):
                y, sr = librosa.load(path, sr=None, mono=False)
            fi.sr = int(sr)
            fi.channels = 1 if y.ndim == 1 else int(y.shape[0])
            fi.frames = int(y.shape[-1])
        except Exception as e:
            fi.error = str(e) or "can't read"
    _info_cache[key] = fi
    return fi


# ── waveforms for the stage ────────────────────────────────────────────────────────────────────

@dataclass
class Wave:
    """Min / max per column of a (mono) signal, plus where slices start."""
    lo: np.ndarray
    hi: np.ndarray
    frames: int
    sr: int
    markers: List[int] = field(default_factory=list)     # sample positions of slice starts
    title: str = ""
    banks: int = 0                                       # >0: draw bank bands (bank mode)

    @property
    def duration(self) -> float:
        return self.frames / self.sr if self.sr else 0.0


def peaks(audio: np.ndarray, sr: int, columns: int = 2400, title: str = "") -> Wave:
    a = np.asarray(audio, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=1)
    n = len(a)
    if n == 0:
        z = np.zeros(1, np.float32)
        return Wave(z, z, 0, sr, title=title)
    cols = max(1, min(columns, n))
    edges = np.linspace(0, n, cols + 1).astype(np.int64)
    lo = np.minimum.reduceat(a, edges[:-1])
    hi = np.maximum.reduceat(a, edges[:-1])
    return Wave(lo, hi, n, sr, title=title)


def load_mono(path: str) -> Tuple[np.ndarray, int]:
    try:
        import soundfile as sf
        a, sr = sf.read(path, dtype="float32", always_2d=False)
        if a.ndim > 1:
            a = a.mean(axis=1)
        return a, int(sr)
    except Exception:
        import librosa
        a, sr = librosa.load(path, sr=None, mono=True)
        return a, int(sr)


_wave_cache: Dict[tuple, Wave] = {}


def wave_of(path: str) -> Wave:
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    if key not in _wave_cache:
        a, sr = load_mono(path)
        _wave_cache[key] = peaks(a, sr, title=os.path.basename(path))
        if len(_wave_cache) > 40:
            _wave_cache.pop(next(iter(_wave_cache)))
    w = _wave_cache[key]
    return Wave(w.lo, w.hi, w.frames, w.sr, [], w.title)


def chain_wave(wav: str, slc: str) -> Wave:
    """A chain with its .slc markers."""
    import split_chain
    w = wave_of(wav)
    w.markers = list(split_chain.read_slc_file(slc))
    return w


# ── slicer ─────────────────────────────────────────────────────────────────────────────────────

@dataclass
class SliceJob:
    files: List[str]
    combine: bool = True                 # several files: one chain (True) or one chain per file
    name: str = ""                       # output name for one file / a combined chain
    out_dir: str = ""
    slices: int = 128
    sr: int = 48000
    length: str = "percussive"           # key of SLICE_MODES
    organize: str = "similarity"         # sequential | similarity | bank
    direction: str = "high_to_low"       # similarity: low_to_high | high_to_low
    bank_sort: str = "chronological"     # chronological | pitch_ascending | pitch_descending
    remove_silence: bool = True
    silence_db: float = -40.0
    processing: str = "both"             # none | normalize | compress | both
    comp_threshold_db: float = -20.0
    comp_ratio: float = 4.0
    comp_attack_ms: float = 5.0
    comp_release_ms: float = 50.0
    norm_method: str = "peak"
    norm_target_db: float = -3.0
    cdp_pre: str = ""                    # .thd file, "" = off
    cdp_post: str = ""
    cdp_path: str = ""
    kit: bool = True

    @property
    def bank_mode(self) -> bool:
        return self.organize == "bank" and self.combine and len(self.files) == 8

    def processing_config(self) -> dict:
        m = self.processing
        return {"mode": m, "compress": m in ("compress", "both"), "normalize": m in ("normalize", "both"),
                "sr": self.sr, "threshold_db": self.comp_threshold_db, "ratio": self.comp_ratio,
                "attack_ms": self.comp_attack_ms, "release_ms": self.comp_release_ms,
                "normalize_method": self.norm_method, "normalize_target_db": self.norm_target_db}

    def outputs(self) -> List[str]:
        """The chain .wav files this job writes."""
        if len(self.files) > 1 and not self.combine:
            names = [clean_name(Path(f).stem) for f in self.files]
        else:
            default = "combined" if len(self.files) > 1 else (clean_name(Path(self.files[0]).stem) if self.files else "chain")
            names = [clean_name(self.name) or default]
        return [os.path.join(self.out_dir, f"{n}_chain.wav") for n in names]


def _onset_slices(sl, audio, sr, hop) -> list:
    import librosa
    onsets = librosa.onset.onset_detect(y=audio, sr=sr, hop_length=hop, units="samples", backtrack=True)
    onsets = np.append(onsets, len(audio))
    out = []
    for j in range(len(onsets) - 1):
        s, e = int(onsets[j]), int(onsets[j + 1])
        out.append({"index": j, "start": s, "end": e, "length": e - s, "duration_ms": (e - s) / sr * 1000})
    print(f"Found {len(out)} slices from onset detection")
    return out


def detect(audio: np.ndarray, job: SliceJob) -> list:
    """Onsets → minimum length → exactly `slices` → silence passes. Same steps as the slicer's main()."""
    sl = slicer()
    cfg = SLICE_MODES[job.length]
    sr, target, mind = job.sr, job.slices, cfg["min_duration_ms"]
    print(f"\n🔍 Detecting onsets using {job.length.upper()} mode...")
    print(f"   Hop length: {cfg['hop_length']} (sensitivity)")
    found = _onset_slices(sl, audio, sr, cfg["hop_length"])
    found = sl.filter_slices_by_duration(found, mind, sr)
    if len(found) > target:
        print(f"\n✂️  Reducing {len(found)} slices to {target}...")
        step = len(found) / target
        slices = [found[int(i * step)] for i in range(target)]
        for i, s in enumerate(slices):
            s["index"] = i
        print(f"✓ Selected {len(slices)} slices")
    else:
        slices = found
    if not slices:
        raise RuntimeError("No slices found: the audio is shorter than the minimum slice length of this mode.")
    print(f"\n🎯 Forcing exactly {target} slices...")
    slices = sl.force_target_slices(slices, target, len(audio), sr, min_duration_ms=mind)
    if job.remove_silence:
        print("\n🔇 Final silence check after subdivision...")
        slices = sl.remove_silent_slices(audio, slices, sr, job.silence_db)
        if not slices:
            raise RuntimeError(f"Every slice is quieter than {job.silence_db:g} dB. Lower the silence threshold.")
        if len(slices) < target:
            print(f"\n🎯 Re-subdividing to reach {target} after silence removal...")
            slices = sl.force_target_slices(slices, target, len(audio), sr, min_duration_ms=mind)
            print("\n🔇 Final cleanup pass...")
            before = len(slices)
            slices = sl.remove_silent_slices(audio, slices, sr, job.silence_db)
            if not slices:
                raise RuntimeError(f"Every slice is quieter than {job.silence_db:g} dB. Lower the silence threshold.")
            if len(slices) < target:
                print(f"\n🎯 Final subdivision to reach {target}...")
                slices = sl.force_target_slices(slices, target, len(audio), sr, min_duration_ms=mind)
            elif len(slices) == before:
                print("✓ No additional silent slices found - we're done!")
    return slices


def _use_cdp(sl, job: SliceJob):
    """Point the slicer's CDP calls at the configured CDP programs folder."""
    if not (job.cdp_pre or job.cdp_post):
        return
    if not getattr(sl, "CDP_AVAILABLE", False):
        raise RuntimeError("CDP processing is unavailable (cdp_processor.py could not be imported).")
    from cdp_processor import CDPProcessor
    path = job.cdp_path or default_cdp_path()
    if not os.path.isdir(os.path.expanduser(path)):
        raise RuntimeError(f"CDP programs folder not found: {path}")
    sl.CDPProcessor = lambda: CDPProcessor(cdp_path=os.path.expanduser(path))


def _stats(wav: str, slc: str, kit: Optional[str], sources: List[str], sr: int) -> dict:
    import split_chain
    import soundfile as sf
    pos = split_chain.read_slc_file(slc)
    total = sf.info(wav).frames
    bounds = split_chain.slice_bounds(pos, total)
    ms = [(e - s) / sr * 1000 for s, e in bounds] or [0.0]
    return {"wav": wav, "slc": slc, "kit": kit if kit and os.path.exists(kit) else None, "count": len(pos),
            "sources": [os.path.basename(s) for s in sources], "shortest": min(ms), "longest": max(ms),
            "average": sum(ms) / len(ms), "seconds": total / sr, "sr": sr}


def run_slicer(job: SliceJob, step: Callable[[str], None] = lambda s: None) -> List[dict]:
    """Writes <name>_chain.wav / .slc / .kit for the job; returns one summary per chain."""
    import librosa
    sl = slicer()
    _use_cdp(sl, job)
    os.makedirs(job.out_dir, exist_ok=True)
    pc = job.processing_config()
    reorganize = job.organize == "similarity"
    tmp = tempfile.mkdtemp(prefix="slice_machine_")
    results = []

    def export(audio, slices, out, sources, reorg):
        step(f"Writing {os.path.basename(out)}")
        sl.export_slices_custom(audio, slices, out, job.sr, generate_slc=True, reorganize=reorg,
                                spectral_direction=job.direction if reorg else None,
                                processing_config=pc, generate_kit=job.kit)
        results.append(_stats(out, os.path.splitext(out)[0] + ".slc", os.path.splitext(out)[0] + ".kit",
                              sources, job.sr))

    def load(path, k, n):
        step(f"Loading {os.path.basename(path)}" + (f" ({k}/{n})" if n > 1 else ""))
        print(f"\n📂 Loading: {os.path.basename(path)}")
        a, _ = librosa.load(path, sr=job.sr, mono=True)
        print(f"✓ Loaded {len(a)} samples ({len(a) / job.sr:.2f}s)")
        if job.cdp_pre:
            step(f"CDP pre-processing {os.path.basename(path)}")
            a = sl.process_full_audio_with_cdp(a, job.sr, job.cdp_pre, tmp)
        return a

    def post(audio, slices):
        if job.cdp_post:
            step("CDP post-processing every slice")
            audio, slices = sl.process_slices_with_cdp(audio, slices, job.sr, job.cdp_post, tmp)
        return audio, slices

    try:
        outs = job.outputs()
        if len(job.files) > 1 and job.combine and job.bank_mode:
            results_bank(job, sl, load, post, export, outs[0])
        elif len(job.files) > 1 and job.combine:
            step(f"Combining {len(job.files)} files")
            audio = sl.combine_audio_files(job.files, job.sr)
            if job.cdp_pre:
                step("CDP pre-processing the combined audio")
                audio = sl.process_full_audio_with_cdp(audio, job.sr, job.cdp_pre, tmp)
            step("Finding slices")
            slices = detect(audio, job)
            audio, slices = post(audio, slices)
            export(audio, slices, outs[0], job.files, reorganize)
        else:
            for k, (path, out) in enumerate(zip(job.files, outs), 1):
                if len(job.files) > 1:
                    print(f"\n{'=' * 70}\nProcessing file {k}/{len(job.files)}\n{'=' * 70}")
                audio = load(path, k, len(job.files))
                step("Finding slices" + (f" ({k}/{len(job.files)})" if len(job.files) > 1 else ""))
                slices = detect(audio, job)
                audio, slices = post(audio, slices)
                export(audio, slices, out, [path], reorganize)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return results


def results_bank(job, sl, load, post, export, out):
    """Bank mode: 8 files → 8 banks × 16 slices, one bank per file."""
    cfg = SLICE_MODES[job.length]
    data = []
    for i, path in enumerate(job.files):
        print(f"\n{'=' * 70}\nProcessing file {i + 1}/8 for Bank {i + 1}\n{'=' * 70}")
        audio = load(path, i + 1, 8)
        print(f"\n🔍 Detecting onsets using {job.length.upper()} mode...")
        found = _onset_slices(sl, audio, job.sr, cfg["hop_length"])
        found = sl.filter_slices_by_duration(found, cfg["min_duration_ms"], job.sr)
        if job.remove_silence:
            found = sl.remove_silent_slices(audio, found, job.sr, job.silence_db)
        if not found:      # nothing left: the whole file as one slice (the banker repeats it)
            found = [{"index": 0, "start": 0, "end": len(audio), "length": len(audio),
                      "duration_ms": len(audio) / job.sr * 1000}]
        data.append({"audio": audio, "slices": [dict(s) for s in found], "sr": job.sr,
                     "filename": os.path.basename(path)})
        print(f"✓ Bank {i + 1}: {len(found)} slices ready")
    organized = sl.organize_slices_by_banks(data, bank_sort=job.bank_sort)
    print(f"\n🔗 Building combined audio from {len(organized)} organized slices...")
    parts, slices, pos = [], [], 0
    for k, s in enumerate(organized):
        seg = data[k // 16]["audio"][s["start"]:s["end"]]     # bank k//16 holds file k//16's slices
        parts.append(seg)
        slices.append({"index": k, "start": pos, "end": pos + len(seg), "length": len(seg),
                       "duration_ms": len(seg) / job.sr * 1000})
        pos += len(seg)
    audio = np.concatenate(parts)
    print(f"✓ Combined audio: {len(audio)} samples ({len(audio) / job.sr:.2f}s)")
    audio, slices = post(audio, slices)
    export(audio, slices, out, job.files, False)


def preview(job: SliceJob, focus: str) -> Wave:
    """Where the slicer would cut, drawn on the source (no CDP, nothing written)."""
    import librosa
    sl = slicer()
    if len(job.files) > 1 and job.combine and not job.bank_mode:
        audio = sl.combine_audio_files(job.files, job.sr)
        title = f"{len(job.files)} files combined"
    else:
        audio, _ = librosa.load(focus, sr=job.sr, mono=True)
        title = os.path.basename(focus)
    if job.bank_mode:
        cfg = SLICE_MODES[job.length]
        found = _onset_slices(sl, audio, job.sr, cfg["hop_length"])
        found = sl.filter_slices_by_duration(found, cfg["min_duration_ms"], job.sr)
        if job.remove_silence:
            found = sl.remove_silent_slices(audio, found, job.sr, job.silence_db)
        if len(found) > 16:
            st = len(found) / 16
            found = [found[int(i * st)] for i in range(16)]
        slices = found
    else:
        slices = detect(audio, job)
    w = peaks(audio, job.sr, title=title)
    w.markers = sorted(int(s["start"]) for s in slices)
    return w


# ── merge ──────────────────────────────────────────────────────────────────────────────────────

def run_merge(slots: List[Optional[str]], slices_each: int, sr: int, out_path: str,
              step: Callable[[str], None] = lambda s: None) -> dict:
    """slots: one chain .wav (with its .slc) per slot, None = silent. Same steps as merge_chains.main()."""
    import merge_chains as mc
    import soundfile as sf
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    ref = None
    for wav in slots:
        if wav:
            i = sf.info(wav)
            ref = int(i.frames * sr / i.samplerate)
            break
    if ref is None:
        ref = sr * 5
        print(f"⚠️  No real files loaded; using {ref / sr:.1f}s per silent slot")
    built = []
    for n, wav in enumerate(slots, 1):
        if not wav:
            audio, pos = mc.build_silent_slot(slices_each, ref, sr)
            built.append({"label": f"(silent slot {n})", "audio": audio, "positions": pos, "silent": True})
            continue
        step(f"Loading slot {n}: {os.path.basename(wav)}")
        print(f"\n  Loading slot {n}: {os.path.basename(wav)}")
        audio, fsr = sf.read(wav, dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if fsr != sr:
            import librosa
            audio = librosa.resample(audio, orig_sr=fsr, target_sr=sr)
            print(f"    Resampled {fsr} → {sr} Hz")
        slc = os.path.splitext(wav)[0] + ".slc"
        try:
            pos = mc.read_slc_file(slc)
        except (ValueError, OSError) as e:
            print(f"  ❌ Could not read .slc: {e}\n     Falling back to evenly-spaced markers")
            _, pos = mc.build_silent_slot(slices_each, len(audio), sr)
        if len(pos) != slices_each:
            print(f"    ⚠️  .slc has {len(pos)} entries; expected {slices_each}")
            if len(pos) > slices_each:
                pos = pos[:slices_each]
                print(f"    Trimmed to {slices_each}")
            else:
                extra = slices_each - len(pos)
                last = pos[-1] if pos else 0
                stp = (len(audio) - last) / (extra + 1)
                pos = list(pos) + [int(last + k * stp) for k in range(1, extra + 1)]
                print(f"    Padded to {slices_each}")
        ref = len(audio)
        built.append({"label": os.path.basename(wav), "audio": audio, "positions": pos, "silent": False})
    step("Merging")
    mc.merge_chains(built, out_path, sr)
    slc = os.path.splitext(out_path)[0] + ".slc"
    return {"wav": out_path, "slc": slc, "slots": len(slots), "filled": sum(1 for s in slots if s),
            "count": len(slots) * slices_each}


# ── split / NerdSEQ / GRID ─────────────────────────────────────────────────────────────────────

def run_split(pairs: List[Tuple[str, str]], out_dir: str, step=lambda s: None) -> List[dict]:
    import split_chain
    os.makedirs(out_dir, exist_ok=True)
    out = []
    for k, (wav, slc) in enumerate(pairs, 1):
        step(f"Splitting {os.path.basename(wav)} ({k}/{len(pairs)})")
        try:
            d, written = split_chain.split_chain(wav, slc, out_dir)
            out.append({"wav": wav, "dir": d, "count": len(written)})
        except Exception as e:
            print(f"\n❌ Failed to split {os.path.basename(wav)}: {e}")
            out.append({"wav": wav, "dir": None, "count": 0, "error": str(e)})
    return out


def nerdseq_estimate(info: FileInfo, fmt: str, channels: str, sr: int) -> int:
    """Bytes the NerdSEQ will need for this file after conversion (same rules as prepare_nerdseq)."""
    if not info.sr or not info.frames:
        return 0
    frames = int(round(info.frames * sr / info.sr))
    if fmt == "raw8" or channels == "mono":
        ch = 1
    elif channels == "stereo":
        ch = 2
    else:
        ch = min(info.channels, 2) if info.channels > 2 else info.channels
    bps = 2 if fmt == "wav16" else 1
    return frames * ch * bps


def run_nerdseq(files: List[str], out_dir: str, fmt: str, channels: str, sr: int, normalize: bool,
                step=lambda s: None) -> List[dict]:
    import prepare_nerdseq as pn
    os.makedirs(out_dir, exist_ok=True)
    out = []
    for k, f in enumerate(files, 1):
        step(f"Converting {os.path.basename(f)} ({k}/{len(files)})")
        r = pn.convert_file(f, out_dir, fmt, channels, sr, normalize)
        if r:
            out.append(r)
    return out


def nerdseq_subfolder(name: str) -> str:
    import re
    s = name.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9 _-]+", "", s)
    s = re.sub(r"\s+", " ", s).strip().replace(" ", "_")
    return (s or "sample")[:24]


def run_grid(pairs: List[Tuple[str, str]], out_dir: str, pad: int, step=lambda s: None) -> List[dict]:
    import chain_to_grid_kit as g
    os.makedirs(out_dir, exist_ok=True)
    out = []
    for wav, slc in pairs:
        stem = os.path.splitext(os.path.basename(wav))[0]
        kit = os.path.join(out_dir, stem + ".kit")
        step(f"Writing {stem}.kit")
        try:
            _, n = g.chain_to_kit(wav, slc, kit, kit_name=stem, pad_index=pad)
            out.append({"wav": wav, "kit": kit, "count": n})
        except Exception as e:
            print(f"   ❌ {os.path.basename(wav)}: {e}")
            out.append({"wav": wav, "kit": None, "count": 0, "error": str(e)})
    return out


def slc_count(slc: str) -> int:
    try:
        return max(0, (os.path.getsize(slc) - 27) // 16)
    except OSError:
        return 0


# ── junglize ──────────────────────────────────────────────────────────────────────────────────

JUNGLE_MODES = {
    "substitute": "Classifies the hits and slots them into an amen-style pattern. Drums in.",
    "impose": "Ignores the classes, cuts the source to the grid and fires every step. Anything in.",
    "reorder": "A near-sequential walk with repeats and jumps that keeps the source's character. "
               "Best for tonal chains, vocals, field recordings.",
}
JUNGLE_FEELS = ("straight", "halftime", "doubletime")
JUNGLE_CLASSES = ("kick", "snare", "hat", "other")


def jungle_available() -> bool:
    return (SRC / "junglize.py").exists()


@dataclass
class JungleJob:
    source: str
    out_dir: str = ""
    name: str = ""
    bpm: float = 170.0
    bars: int = 2
    mode: str = "substitute"
    feel: str = "straight"
    seed: int = 1
    sr: int = 44100
    swing: float = 0.12
    ring: float = 1.6
    stretch: bool = False
    stutter: float = 0.2
    reverse: float = 0.08
    humanize: float = 0.12
    bar_repeat: float = 0.0
    sub: bool = False
    source_bpm: float = 0.0              # 0 = leave the source's tempo alone
    detect_tempo: bool = False
    loops: int = 1
    kit: bool = True

    def stem(self) -> str:
        return clean_name(self.name) or (clean_name(Path(self.source).stem) + "_jungle")

    def out_path(self) -> str:
        return os.path.join(self.out_dir, self.stem() + ".wav")

    def cli(self) -> str:
        """The same break from the terminal."""
        parts = [f"python3 src/junglize.py \"{os.path.basename(self.source)}\"", f"--bpm {self.bpm:g}", f"--bars {self.bars}",
                 f"--mode {self.mode}", f"--feel {self.feel}", f"--seed {self.seed}", f"--sr {self.sr}",
                 f"--swing {self.swing:g}", f"--ring {self.ring:g}", f"--stutter {self.stutter:g}",
                 f"--reverse {self.reverse:g}", f"--humanize {self.humanize:g}"]
        if self.stretch:
            parts.append("--stretch slot")
        if self.bar_repeat:
            parts.append(f"--bar-repeat {self.bar_repeat:g}")
        if self.sub:
            parts.append("--sub")
        if self.source_bpm:
            parts.append(f"--source-bpm {self.source_bpm:g}")
        elif self.detect_tempo:
            parts.append("--detect-tempo")
        parts.append(f"--export output/{self.stem()}")
        return " ".join(parts)


_jungle_cache: Dict[tuple, dict] = {}


def jungle_analysis(job: JungleJob) -> dict:
    """Load → tempo-align → slice → classify: the slow part, kept so a new roll is quick."""
    import junglize as J
    st = os.stat(job.source)
    aligned = bool(job.source_bpm) or job.detect_tempo
    key = (job.source, st.st_mtime, st.st_size, job.sr, float(job.bpm) if aligned else None,
           float(job.source_bpm or 0), bool(job.detect_tempo and not job.source_bpm))
    if key not in _jungle_cache:
        print(f"[junglize] loading {os.path.basename(job.source)}")
        try:
            y, sr = J.load_mono(job.source, sr=job.sr)
        except SystemExit as e:                      # junglize exits on empty audio
            raise RuntimeError(str(e) or "The audio is empty.")
        y, src_bpm = J.tempo_align(y, sr, job.bpm, job.source_bpm or None, job.detect_tempo)
        if src_bpm:
            print(f"[junglize] tempo-aligned source {src_bpm:.1f} -> {job.bpm:g} BPM")
        events = J.slice_events(y, sr)
        labels = [J.classify(y[a:b], sr) for (a, b) in events]
        palette, all_segs = J.build_palette(y, sr, events, labels)
        counts = {c: labels.count(c) for c in JUNGLE_CLASSES}
        print(f"[junglize] sliced {len(events)} events  ->  {counts}")
        src = peaks(y, sr, title=os.path.basename(job.source))
        src.markers = [a for a, _ in events]
        _jungle_cache[key] = {"sr": sr, "src_bpm": src_bpm, "events": events, "labels": labels, "palette": palette,
                              "all_segs": all_segs, "counts": counts, "wave": src}
        while len(_jungle_cache) > 4:
            _jungle_cache.pop(next(iter(_jungle_cache)))
    return _jungle_cache[key]


def jungle_render(job: JungleJob) -> dict:
    """One break, exactly as `junglize.py … --seed N` makes it (nothing written)."""
    import junglize as J
    a = jungle_analysis(job)
    print(f"[junglize] mode={job.mode} feel={job.feel} bpm={job.bpm:g} bars={job.bars} swing={job.swing:g} "
          f"stretch={'slot' if job.stretch else 'off'} seed={job.seed}")
    rng = np.random.default_rng(job.seed)
    base, markers = J.resequence(a["palette"], a["all_segs"], a["sr"], job.bpm, job.bars, job.mode, rng,
                                 feel=job.feel, swing=job.swing, stutter_prob=job.stutter, reverse_prob=job.reverse,
                                 ring=job.ring, humanize=job.humanize, stretch=job.stretch,
                                 bar_repeat=job.bar_repeat, sub=job.sub)
    w = peaks(base, a["sr"], title=job.stem() + ".wav")
    w.markers = list(markers)
    return {"audio": base, "markers": markers, "sr": a["sr"], "wave": w, "analysis": a, "seed": job.seed,
            "step": int(round(60.0 / job.bpm / 4.0 * a["sr"])), "bars": job.bars}


def jungle_preview(job: JungleJob, path: str) -> dict:
    """Renders the break and writes it to `path` for listening."""
    import soundfile as sf
    r = jungle_render(job)
    sf.write(path, r["audio"], r["sr"], subtype="PCM_16")
    r["play"] = path
    return r


def run_junglize(job: JungleJob, step: Callable[[str], None] = lambda s: None) -> dict:
    """Writes <name>.wav + .slc (+ .kit) through slc_io, like `--export`; with loops > 1 also <name>_xN.wav."""
    import slc_io
    import soundfile as sf
    step(f"Analysing {os.path.basename(job.source)}")
    jungle_analysis(job)
    step(f"Cutting the break (seed {job.seed})")
    r = jungle_render(job)
    os.makedirs(job.out_dir, exist_ok=True)
    step(f"Writing {job.stem()}.wav")
    paths = slc_io.write_chain(job.out_path(), r["audio"], r["sr"], r["markers"], make_kit=job.kit)
    if job.loops > 1:
        lp = os.path.join(job.out_dir, f"{job.stem()}_x{job.loops}.wav")
        sf.write(lp, np.tile(r["audio"], job.loops), r["sr"])
        print(f"[junglize] wrote {lp}  ({len(r['audio']) * job.loops / r['sr']:.2f}s, {job.loops}x)")
        paths["loop"] = lp
    print(f"[junglize] exported {len(set(r['markers']))} slice markers -> "
          f"{', '.join(os.path.basename(p) for p in paths.values())}")
    r["paths"] = paths
    r["play"] = paths["wav"]
    return r
