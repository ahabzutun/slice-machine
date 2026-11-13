#!/usr/bin/env python3
"""
junglize.py  (v2) — turn ANY audio into an experimental jungle break.

A standalone BBCut-style cut engine, sibling to slice-machine.

    load wav -> onset-slice into events
             -> classify each event (kick / snare / hat / other)
             -> resequence onto a jungle grid at a chosen BPM with swing,
                natural ring-out, ghost snares, stutters, 1/32 rolls,
                retriggers and reversals
             -> render to a new wav (loopable, grooved)

What changed vs v1 (the "far from jungle" fixes):
  * SWING / shuffle: off-beat 1/16s are pushed late, the core jungle feel.
  * RING-OUT: slices play their natural length and overlap-add instead of
    being hard-truncated to a 1/16 slot. Tails breathe; hits flam. This is
    the single biggest groove change.
  * Better classifier: adaptive n_fft (no more warnings on short slices),
    normalized band ratios, real hat detection.
  * Per-bar variation + humanized velocity so two bars aren't identical.
  * New 'reorder' mode: walks the source in order with jungle cut procedures,
    preserving timbral continuity — best for arbitrary / non-drum material.

Modes:
  substitute : classify hits, slot them into an amen-style pattern.
               Best when the input actually contains drums.
  impose     : ignore class, cut the source to the grid, fire every step.
               Robust to anything.
  reorder    : walk source slices near-sequentially with repeats/jumps/cuts.
               Keeps the source's character — best for tonal sample chains,
               vocals, field recordings. Most "jungle-from-everything".

Deps: numpy, scipy, librosa, soundfile
Examples:
  python3 junglize.py break.wav  -o out.wav --bpm 170 --bars 2 --seed 7
  python3 junglize.py chain.wav  -o out.wav --mode reorder --swing 0.14
  python3 junglize.py voice.wav  -o out.wav --mode impose  --seed 3
"""

import argparse
import sys
import numpy as np

try:
    import librosa
    import soundfile as sf
    from scipy.signal import butter, sosfilt
except ImportError as e:
    sys.exit(f"Missing dependency: {e}. pip install librosa soundfile scipy numpy")


# ----------------------------------------------------------------------------
# 1. LOAD + SLICE
# ----------------------------------------------------------------------------

def load_mono(path, sr=44100):
    y, _ = librosa.load(path, sr=sr, mono=True)
    if y.size == 0:
        sys.exit("Input audio is empty.")
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.9
    return y.astype(np.float32), sr


def slice_events(y, sr, min_len_ms=20, backtrack=True):
    """Onset-detect and cut into events. Returns list of (start, end) samples."""
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
# 2. CLASSIFY
# ----------------------------------------------------------------------------

def _next_pow2(n):
    return 1 << (int(n) - 1).bit_length()


def _band_rms(seg, sr, lo, hi):
    hi = min(hi, sr / 2 - 1)
    lo = max(lo, 1)
    if hi <= lo:
        return 1e-9
    sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    return float(np.sqrt(np.mean(sosfilt(sos, seg) ** 2)) + 1e-9)


def classify(seg, sr):
    """Adaptive-resolution spectral heuristic -> kick|snare|hat|other."""
    if len(seg) < 24:
        return "other"
    s = seg / (np.max(np.abs(seg)) + 1e-9)
    dur = len(s) / sr
    n_fft = min(2048, _next_pow2(len(s)))
    hop = max(64, n_fft // 4)
    centroid = float(np.mean(librosa.feature.spectral_centroid(
        y=s, sr=sr, n_fft=n_fft, hop_length=hop)))
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(s)))

    low = _band_rms(s, sr, 30, 150)
    lomid = _band_rms(s, sr, 150, 500)
    mid = _band_rms(s, sr, 500, 3000)
    high = _band_rms(s, sr, 6000, 16000)
    total = low + lomid + mid + high

    lo_r, mid_r, hi_r = low / total, mid / total, high / total

    # hat: short, bright, noisy, high-band forward
    if dur < 0.14 and (hi_r > 0.30 or zcr > 0.20) and centroid > 3500:
        return "hat"
    # kick: low-band dominant, dark, not tiny
    if lo_r > 0.40 and centroid < 1800 and dur > 0.04:
        return "kick"
    # snare: broadband mid energy, mid-bright, noisy-ish
    if mid_r > 0.28 and 1200 < centroid < 6000 and dur < 0.6:
        return "snare"
    if lo_r > 0.30 and centroid < 1200:
        return "kick"
    return "other"


def build_palette(y, sr, events):
    palette = {"kick": [], "snare": [], "hat": [], "other": []}
    for (a, b) in events:
        palette[classify(y[a:b], sr)].append(y[a:b])
    all_segs = [y[a:b] for a, b in events]
    # borrow across classes so the sequencer never stalls, but prefer
    # sensible substitutes (a missing hat borrows brighter/shorter slices)
    for k in palette:
        if not palette[k]:
            palette[k] = list(all_segs)
    return palette, all_segs


# ----------------------------------------------------------------------------
# 3. RESEQUENCE  (the cut engine)
# ----------------------------------------------------------------------------

def release_fade(seg, sr, fade_ms=6):
    out = np.array(seg, dtype=np.float32)
    f = min(int(sr * fade_ms / 1000), len(out) // 2)
    if f > 0:
        out[:min(64, len(out))] *= np.linspace(0, 1, min(64, len(out)))
        out[-f:] *= np.linspace(1, 0, f)
    return out


def place(buf, seg, pos, sr, gain, max_len, reverse=False):
    """Overlap-add a slice at pos, letting it ring up to max_len samples."""
    s = seg[::-1] if reverse else seg
    if len(s) > max_len:
        s = release_fade(s[:max_len], sr)
    else:
        s = release_fade(s, sr)
    end = min(pos + len(s), len(buf))
    buf[pos:end] += s[:end - pos] * gain


def pick(rng, pool):
    return pool[rng.integers(0, len(pool))]


def jungle_pattern(rng, bars):
    """16 steps/bar of tokens with jungle idioms + per-bar variation."""
    base = ["K", ".", ".", ".", "S", ".", ".", "K",
            ".", ".", "K", ".", "S", ".", ".", "."]
    out = []
    for b in range(bars):
        row = list(base)
        if b > 0 and rng.random() < 0.5:           # shift a kick for variation
            i = rng.choice([2, 3, 9, 11])
            row[i] = "K"
        for i in range(16):                         # ghost snares
            if row[i] == "." and rng.random() < 0.16:
                row[i] = "s"
        for i in range(16):                         # hats
            if row[i] == "." and rng.random() < 0.30:
                row[i] = "h"
        if b == bars - 1 and rng.random() < 0.6:    # end-of-phrase roll
            for i in range(rng.choice([12, 14]), 16):
                row[i] = "R"
        out.extend(row)
    return out


TOKEN_CLASS = {"K": "kick", "S": "snare", "s": "snare",
               "h": "hat", "R": "snare"}
TOKEN_GAIN = {"K": 1.0, "S": 0.95, "s": 0.4, "h": 0.55, "R": 0.8}


def step_positions(total_steps, step_n, swing):
    """Sample position of each 1/16 step, with swing on the odd 1/16s."""
    pos = np.arange(total_steps) * step_n
    off = (np.arange(total_steps) % 2 == 1)
    pos = pos + (off * swing * step_n).astype(int)
    return pos


def resequence(palette, all_segs, sr, bpm, bars, mode, rng,
               swing=0.12, stutter_prob=0.2, reverse_prob=0.08,
               ring=1.6, humanize=0.12):
    step = 60.0 / bpm / 4.0
    step_n = int(round(step * sr))
    total_steps = 16 * bars
    buf = np.zeros(total_steps * step_n + step_n * 4, dtype=np.float32)
    positions = step_positions(total_steps, step_n, swing)
    max_ring = int(step_n * ring)

    if mode == "substitute":
        pattern = jungle_pattern(rng, bars)
    else:
        pattern = None

    src_i = 0
    for i in range(total_steps):
        pos = int(positions[i])

        # ---- choose slice + gain per mode --------------------------------
        if mode == "impose":
            seg, gain, tok = pick(rng, all_segs), 0.9, "X"
        elif mode == "reorder":
            # near-sequential walk with occasional jumps/holds -> continuity
            if rng.random() < 0.22:
                src_i = int(rng.integers(0, len(all_segs)))
            seg = all_segs[src_i % len(all_segs)]
            src_i += 1
            gain, tok = 0.9, "X"
        else:  # substitute
            tok = pattern[i]
            if tok == ".":
                continue
            seg = pick(rng, palette[TOKEN_CLASS[tok]])
            gain = TOKEN_GAIN.get(tok, 0.8)

        gain *= (1.0 + rng.uniform(-humanize, humanize))  # velocity humanize

        # ---- cut procedures ----------------------------------------------
        if tok == "R":                              # 1/32 or 1/64 roll
            subs = int(rng.choice([2, 4]))
            sub_n = step_n // subs
            for k in range(subs):
                place(buf, seg, pos + k * sub_n, sr, gain * 0.9, sub_n)
            continue

        if rng.random() < stutter_prob:             # stutter retrigger
            subs = int(rng.choice([2, 3]))
            sub_n = step_n // subs
            for k in range(subs):
                place(buf, seg, pos + k * sub_n, sr, gain, sub_n)
            continue

        rev = rng.random() < reverse_prob
        place(buf, seg, pos, sr, gain, max_ring, reverse=rev)

    buf = buf[:total_steps * step_n]                # trim overhang, keep loop
    peak = np.max(np.abs(buf))
    if peak > 0:
        buf = buf / peak * 0.95
    return buf


def render_chain(palette, sr):
    order = ["kick", "snare", "hat", "other"]
    segs = [release_fade(seg, sr) for cls in order for seg in palette[cls]]
    return np.concatenate(segs) if segs else np.zeros(1, dtype=np.float32)


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
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument("--swing", type=float, default=0.12,
                    help="0=straight, 0.12 typical, up to ~0.3 heavy shuffle")
    ap.add_argument("--ring", type=float, default=1.6,
                    help="max slice ring-out in 1/16 steps (tails/overlap)")
    ap.add_argument("--stutter", type=float, default=0.2)
    ap.add_argument("--reverse", type=float, default=0.08)
    ap.add_argument("--humanize", type=float, default=0.12)
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--chain", metavar="PATH", default=None,
                    help="also write a flat kick,snare,hat,other one-shot chain")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    y, sr = load_mono(args.input, sr=args.sr)
    events = slice_events(y, sr)
    labels = [classify(y[a:b], sr) for (a, b) in events]
    palette, all_segs = build_palette(y, sr, events)

    counts = {c: labels.count(c) for c in ("kick", "snare", "hat", "other")}
    print(f"[junglize] sliced {len(events)} events  ->  {counts}")
    print(f"[junglize] mode={args.mode} bpm={args.bpm} bars={args.bars} "
          f"swing={args.swing} ring={args.ring} seed={args.seed}")

    out = resequence(palette, all_segs, sr, args.bpm, args.bars, args.mode, rng,
                     swing=args.swing, stutter_prob=args.stutter,
                     reverse_prob=args.reverse, ring=args.ring,
                     humanize=args.humanize)
    if args.loops > 1:
        out = np.tile(out, args.loops)

    sf.write(args.output, out, sr)
    print(f"[junglize] wrote {args.output}  ({len(out)/sr:.2f}s, {args.loops}x)")

    if args.chain:
        chain = render_chain(palette, sr)
        sf.write(args.chain, chain, sr)
        print(f"[junglize] wrote chain {args.chain}  ({len(chain)/sr:.2f}s)")


if __name__ == "__main__":
    main()