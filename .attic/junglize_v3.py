#!/usr/bin/env python3
"""
junglize.py  (v4) — turn ANY audio into an experimental jungle break.

A BBCut-style cut engine, sibling to slice-machine. Lives in src/ alongside
the other tools and reuses the shared export layer (slc_io.py), so a generated
break drops straight onto the ER-301 (.slc) and Percussa SSP GRID (.kit).

    load wav -> [optional global tempo-stretch to target BPM]
             -> onset-slice into events
             -> classify each event (kick / snare / hat / other)
             -> resequence onto a jungle grid at a chosen BPM with swing,
                ring-out / time-stretch, feel (halftime/doubletime), ghost
                snares, stutters, 1/32 rolls, reversals, bar-repeats, sub layer
             -> render + optionally export wav/.slc/.kit

v4 adds:
  * HARDWARE EXPORT  --export STEM  -> STEM.wav + STEM.slc + STEM.kit via slc_io
  * BETTER CLASSIFIER (attack sharpness + spectral flatness + crest factor)
  * GLOBAL TEMPO-STRETCH  --source-bpm N  /  --detect-tempo  (whole source is
    stretched to the target BPM before slicing, so a real break locks to grid)
  * CUT PROCEDURES  --feel {straight,halftime,doubletime}, --bar-repeat P,
    --sub  (sub-bass layer on kicks / downbeats)

Modes:
  substitute : classify hits, slot into an amen-style pattern (drums in).
  impose     : ignore class, cut source to grid, fire every step (anything in).
  reorder    : near-sequential walk w/ repeats/jumps/cuts, keeps source
               character — best for tonal chains / vocals / field recordings.

Deps: numpy, scipy, librosa, soundfile, slc_io (same folder)
Examples:
  python3 junglize.py break.wav -o out.wav --bpm 170 --source-bpm 140 --seed 7
  python3 junglize.py chain.wav --mode reorder --stretch slot --sub \\
          --export output/mychain_jungle
"""

import argparse
import os
import sys
import numpy as np

try:
    import librosa
    import soundfile as sf
    from scipy.signal import butter, sosfilt
except ImportError as e:
    sys.exit(f"Missing dependency: {e}. pip install librosa soundfile scipy numpy")

# shared export layer (chain wav + .slc + .kit)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import slc_io
except ImportError:
    slc_io = None


# ----------------------------------------------------------------------------
# 1. LOAD + (optional) GLOBAL TEMPO-STRETCH + SLICE
# ----------------------------------------------------------------------------

def load_mono(path, sr=44100):
    y, _ = librosa.load(path, sr=sr, mono=True)
    if y.size == 0:
        sys.exit("Input audio is empty.")
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.9
    return y.astype(np.float32), sr


def tempo_align(y, sr, target_bpm, source_bpm=None, detect=False):
    """Stretch the whole source so its tempo matches target_bpm."""
    if source_bpm is None and detect:
        try:
            est, _ = librosa.beat.beat_track(y=y, sr=sr)
            source_bpm = float(np.atleast_1d(est)[0])
        except Exception:
            source_bpm = None
    if not source_bpm or source_bpm <= 0:
        return y, None
    rate = target_bpm / source_bpm          # >1 speeds up (source slower)
    if abs(rate - 1.0) < 1e-3:
        return y, source_bpm
    try:
        y2 = librosa.effects.time_stretch(y.astype(np.float32), rate=rate)
        return y2.astype(np.float32), source_bpm
    except Exception:
        return y, source_bpm


def slice_events(y, sr, min_len_ms=20, backtrack=True):
    hop = 256
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=hop, backtrack=backtrack, units="frames",
        pre_max=8, post_max=8, pre_avg=20, post_avg=20, delta=0.06, wait=4,
    )
    onsets = librosa.frames_to_samples(onset_frames, hop_length=hop)
    onsets = np.append(onsets, len(y))
    if len(onsets) < 2:
        onsets = np.linspace(0, len(y), 17).astype(int)
    min_len = int(sr * min_len_ms / 1000)
    events = [(int(onsets[i]), int(onsets[i + 1]))
              for i in range(len(onsets) - 1)
              if onsets[i + 1] - onsets[i] >= min_len]
    return events or [(0, len(y))]


# ----------------------------------------------------------------------------
# 2. CLASSIFY  (attack + flatness + band ratios + crest)
# ----------------------------------------------------------------------------

def _prev_pow2(n):
    return 1 << max(0, int(n).bit_length() - 1)


def _band_rms(seg, sr, lo, hi):
    hi = min(hi, sr / 2 - 1)
    lo = max(lo, 1)
    if hi <= lo:
        return 1e-9
    sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    return float(np.sqrt(np.mean(sosfilt(sos, seg) ** 2)) + 1e-9)


def classify(seg, sr):
    """kick|snare|hat|other from cheap perceptual features."""
    if len(seg) < 24:
        return "other"
    s = seg / (np.max(np.abs(seg)) + 1e-9)
    dur = len(s) / sr
    n_fft = min(2048, _prev_pow2(len(s)))
    hop = max(64, n_fft // 4)

    centroid = float(np.mean(librosa.feature.spectral_centroid(
        y=s, sr=sr, n_fft=n_fft, hop_length=hop)))
    flat = float(np.mean(librosa.feature.spectral_flatness(
        y=s, n_fft=n_fft, hop_length=hop)))          # high => noisy
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(
        s, frame_length=min(2048, max(64, _prev_pow2(len(s)))))))
    rms = float(np.sqrt(np.mean(s ** 2)) + 1e-9)
    crest = float(np.max(np.abs(s)) / rms)           # peaky => transient

    # attack sharpness: energy in first 8 ms vs whole slice
    a = max(1, int(sr * 0.008))
    attack = float(np.sum(s[:a] ** 2) / (np.sum(s ** 2) + 1e-9))

    low = _band_rms(s, sr, 30, 150)
    lomid = _band_rms(s, sr, 150, 500)
    mid = _band_rms(s, sr, 500, 3000)
    high = _band_rms(s, sr, 6000, 16000)
    total = low + lomid + mid + high
    lo_r, mid_r, hi_r = low / total, mid / total, high / total

    # hat: short, bright, noisy, fast attack
    if dur < 0.16 and centroid > 3200 and (hi_r > 0.28 or flat > 0.12) \
            and zcr > 0.12:
        return "hat"
    # kick: low-band dominant, dark, tonal (low flatness), punchy
    if lo_r > 0.38 and centroid < 1900 and flat < 0.10 and dur > 0.03:
        return "kick"
    # snare: broadband mid, noisy, sharp transient
    if mid_r > 0.26 and 1000 < centroid < 6500 and (flat > 0.06 or crest > 4) \
            and dur < 0.6:
        return "snare"
    if lo_r > 0.30 and centroid < 1100 and flat < 0.12:
        return "kick"
    return "other"


def build_palette(y, sr, events, labels):
    palette = {"kick": [], "snare": [], "hat": [], "other": []}
    for (a, b), lab in zip(events, labels):
        palette[lab].append(y[a:b])
    all_segs = [y[a:b] for a, b in events]
    for k in palette:
        if not palette[k]:
            palette[k] = list(all_segs)
    return palette, all_segs


# ----------------------------------------------------------------------------
# 3. TIME-STRETCH helpers
# ----------------------------------------------------------------------------

def _resample_fit(seg, target_n):
    if len(seg) < 2 or target_n < 1:
        return np.zeros(max(target_n, 1), dtype=np.float32)
    x = np.linspace(0, 1, len(seg))
    xi = np.linspace(0, 1, target_n)
    return np.interp(xi, x, seg).astype(np.float32)


def stretch_to(seg, target_n, sr):
    if target_n < 1:
        return np.zeros(1, dtype=np.float32)
    if len(seg) < 256 or target_n < 256:
        return _resample_fit(seg, target_n)
    rate = len(seg) / target_n
    try:
        out = librosa.effects.time_stretch(seg.astype(np.float32), rate=rate)
    except Exception:
        return _resample_fit(seg, target_n)
    if len(out) >= target_n:
        return out[:target_n]
    return np.pad(out, (0, target_n - len(out)))


# ----------------------------------------------------------------------------
# 4. RESEQUENCE  (the cut engine)
# ----------------------------------------------------------------------------

def release_fade(seg, sr, fade_ms=6):
    out = np.array(seg, dtype=np.float32)
    a = min(64, len(out))
    f = min(int(sr * fade_ms / 1000), len(out) // 2)
    if a > 0:
        out[:a] *= np.linspace(0, 1, a)
    if f > 0:
        out[-f:] *= np.linspace(1, 0, f)
    return out


def sub_hit(n, sr, freq=50.0, decay=0.16):
    t = np.arange(n) / sr
    body = np.sin(2 * np.pi * freq * t) * np.exp(-t / decay)
    return release_fade(body.astype(np.float32), sr, fade_ms=4)


def emit(buf, markers, seg, pos, slot_n, gain, sr, stretch, max_ring, reverse=False):
    s = seg[::-1] if reverse else seg
    if stretch:
        s = release_fade(stretch_to(s, slot_n, sr), sr, fade_ms=4)
    elif len(s) > max_ring:
        s = release_fade(s[:max_ring], sr)
    else:
        s = release_fade(s, sr)
    end = min(pos + len(s), len(buf))
    if end > pos:
        buf[pos:end] += s[:end - pos] * gain
        markers.append(pos)


def pick(rng, pool):
    return pool[rng.integers(0, len(pool))]


FEEL_BASE = {
    "straight": ["K", ".", ".", ".", "S", ".", ".", "K",
                 ".", ".", "K", ".", "S", ".", ".", "."],
    "halftime": ["K", ".", ".", ".", ".", ".", ".", ".",
                 "S", ".", ".", ".", ".", ".", "K", "."],
    "doubletime": ["K", ".", "h", ".", "S", ".", "K", "K",
                   ".", "h", "K", ".", "S", ".", "S", "h"],
}


def jungle_pattern(rng, bars, feel):
    base = FEEL_BASE.get(feel, FEEL_BASE["straight"])
    ghost = {"straight": 0.16, "halftime": 0.10, "doubletime": 0.22}[feel]
    hats = {"straight": 0.30, "halftime": 0.16, "doubletime": 0.40}[feel]
    out = []
    for b in range(bars):
        row = list(base)
        if b > 0 and rng.random() < 0.5:
            row[rng.choice([2, 3, 9, 11])] = "K"
        for i in range(16):
            if row[i] == "." and rng.random() < ghost:
                row[i] = "s"
        for i in range(16):
            if row[i] == "." and rng.random() < hats:
                row[i] = "h"
        if b == bars - 1 and rng.random() < 0.6:
            for i in range(rng.choice([12, 14]), 16):
                row[i] = "R"
        out.extend(row)
    return out


TOKEN_CLASS = {"K": "kick", "S": "snare", "s": "snare", "h": "hat", "R": "snare"}
TOKEN_GAIN = {"K": 1.0, "S": 0.95, "s": 0.4, "h": 0.55, "R": 0.8}


def step_positions(total_steps, step_n, swing):
    pos = np.arange(total_steps) * step_n
    odd = (np.arange(total_steps) % 2 == 1)
    return pos + (odd * swing * step_n).astype(int)


def resequence(palette, all_segs, sr, bpm, bars, mode, rng, feel="straight",
               swing=0.12, stutter_prob=0.2, reverse_prob=0.08, ring=1.6,
               humanize=0.12, stretch=False, bar_repeat=0.0, sub=False):
    step_n = int(round(60.0 / bpm / 4.0 * sr))
    total_steps = 16 * bars
    buf = np.zeros(total_steps * step_n + step_n * 4, dtype=np.float32)
    markers = []
    positions = step_positions(total_steps, step_n, swing)
    max_ring = int(step_n * ring)
    pattern = jungle_pattern(rng, bars, feel) if mode == "substitute" else None

    # feel controls firing density for the class-agnostic modes
    fire_every = {"straight": 1, "halftime": 2, "doubletime": 1}[feel]
    dt_boost = 0.25 if feel == "doubletime" else 0.0

    src_i = 0
    for i in range(total_steps):
        pos = int(positions[i])

        if mode == "substitute":
            tok = pattern[i]
            if tok == ".":
                continue
            seg = pick(rng, palette[TOKEN_CLASS[tok]])
            gain = TOKEN_GAIN.get(tok, 0.8)
        else:
            if i % fire_every != 0:
                continue
            tok = "X"
            if mode == "reorder":
                if rng.random() < 0.22:
                    src_i = int(rng.integers(0, len(all_segs)))
                seg = all_segs[src_i % len(all_segs)]
                src_i += 1
            else:  # impose
                seg = pick(rng, all_segs)
            gain = 0.9

        gain *= (1.0 + rng.uniform(-humanize, humanize))

        # sub-bass reinforcement on kicks / downbeats
        if sub and (tok in ("K", "R") or (tok == "X" and i % 4 == 0)):
            sh = sub_hit(min(step_n * 2, max_ring), sr)
            end = min(pos + len(sh), len(buf))
            buf[pos:end] += sh[:end - pos] * 0.6

        if tok == "R":
            subs = int(rng.choice([2, 4]))
            sub_n = step_n // subs
            for k in range(subs):
                emit(buf, markers, seg, pos + k * sub_n, sub_n, gain * 0.9,
                     sr, stretch, sub_n)
            continue

        if rng.random() < stutter_prob + dt_boost:
            subs = int(rng.choice([2, 3]))
            sub_n = step_n // subs
            for k in range(subs):
                emit(buf, markers, seg, pos + k * sub_n, sub_n, gain, sr,
                     stretch, sub_n)
            continue

        rev = rng.random() < reverse_prob
        emit(buf, markers, seg, pos, step_n, gain, sr, stretch, max_ring,
             reverse=rev)

    buf = buf[:total_steps * step_n]

    # bar-repeat glitch: overwrite a bar with the previous one
    if bar_repeat > 0 and bars > 1:
        bar_n = 16 * step_n
        for b in range(1, bars):
            if rng.random() < bar_repeat:
                buf[b * bar_n:(b + 1) * bar_n] = buf[(b - 1) * bar_n:b * bar_n]

    peak = np.max(np.abs(buf))
    if peak > 0:
        buf = buf / peak * 0.95
    markers = sorted(set(m for m in markers if m < len(buf)))
    return buf, markers


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Turn any audio into a jungle break.")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default="break.wav")
    ap.add_argument("--bpm", type=float, default=170.0)
    ap.add_argument("--bars", type=int, default=2)
    ap.add_argument("--mode", choices=["substitute", "impose", "reorder"],
                    default="substitute")
    ap.add_argument("--feel", choices=["straight", "halftime", "doubletime"],
                    default="straight")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--swing", type=float, default=0.12)
    ap.add_argument("--ring", type=float, default=1.6)
    ap.add_argument("--stretch", choices=["off", "slot"], default="off")
    ap.add_argument("--stutter", type=float, default=0.2)
    ap.add_argument("--reverse", type=float, default=0.08)
    ap.add_argument("--humanize", type=float, default=0.12)
    ap.add_argument("--bar-repeat", type=float, default=0.0, dest="bar_repeat",
                    help="probability a bar repeats the previous one (glitch)")
    ap.add_argument("--sub", action="store_true", help="add sub-bass on kicks")
    ap.add_argument("--source-bpm", type=float, default=None, dest="source_bpm",
                    help="stretch whole source from this BPM to --bpm before slicing")
    ap.add_argument("--detect-tempo", action="store_true", dest="detect_tempo",
                    help="auto-detect source tempo and stretch to --bpm")
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--export", metavar="STEM", default=None,
                    help="write STEM.wav + STEM.slc + STEM.kit (ER-301 / GRID)")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    y, sr = load_mono(args.input, sr=args.sr)

    y, src_bpm = tempo_align(y, sr, args.bpm, args.source_bpm, args.detect_tempo)
    if src_bpm:
        print(f"[junglize] tempo-aligned source {src_bpm:.1f} -> {args.bpm} BPM")

    events = slice_events(y, sr)
    labels = [classify(y[a:b], sr) for (a, b) in events]
    palette, all_segs = build_palette(y, sr, events, labels)

    counts = {c: labels.count(c) for c in ("kick", "snare", "hat", "other")}
    print(f"[junglize] sliced {len(events)} events  ->  {counts}")
    print(f"[junglize] mode={args.mode} feel={args.feel} bpm={args.bpm} "
          f"bars={args.bars} swing={args.swing} stretch={args.stretch} "
          f"seed={args.seed}")

    base, markers = resequence(
        palette, all_segs, sr, args.bpm, args.bars, args.mode, rng,
        feel=args.feel, swing=args.swing, stutter_prob=args.stutter,
        reverse_prob=args.reverse, ring=args.ring, humanize=args.humanize,
        stretch=(args.stretch == "slot"), bar_repeat=args.bar_repeat,
        sub=args.sub)

    out = np.tile(base, args.loops) if args.loops > 1 else base
    sf.write(args.output, out, sr)
    print(f"[junglize] wrote {args.output}  ({len(out)/sr:.2f}s, {args.loops}x)")

    if args.export:
        if slc_io is None:
            print("[junglize] slc_io.py not found next to junglize.py — "
                  "skipping .slc/.kit export.")
        else:
            wav_path = args.export if args.export.lower().endswith(".wav") \
                else args.export + ".wav"
            paths = slc_io.write_chain(wav_path, base, sr, markers)
            print(f"[junglize] exported {len(markers)} slice markers -> "
                  f"{', '.join(os.path.basename(p) for p in paths.values())}")


if __name__ == "__main__":
    main()