#!/usr/bin/env python3
"""
slc_io.py — shared slice/sidecar export layer for slice-machine.

Single source of truth for writing a chain's companion metadata:

    .slc  (ER-301)          -> generate_slc_file(wav_path, slices, total_samples)
    .kit  (Percussa SSP)    -> generate_grid_kit_file(wav_path, slices, total_samples)

Both writers are the exact, hardware-tested versions previously inlined in
interactive_slicer.py — moved here verbatim so every tool (interactive_slicer,
merge_chains, junglize, …) shares one implementation. The GRID primitives
themselves still live in chain_to_grid_kit.py; this module orchestrates them.

`slices` is a list of dicts, each with an integer 'start' sample position —
the same structure interactive_slicer already passes around.

For generators that only have a flat list of marker positions (e.g. junglize),
use the convenience wrapper:

    slc_io.write_chain(wav_path, audio, sr, markers)   # wav + .slc + .kit

Deps: numpy, soundfile, struct; chain_to_grid_kit.py alongside (for .kit).
"""

import os
import sys
import struct
import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# GRID kit primitives (Percussa SSP). Same import the slicer used.
try:
    from chain_to_grid_kit import slice_pairs_normalized, build_kit_xml, write_kit
    GRID_KIT_AVAILABLE = True
except ImportError:
    GRID_KIT_AVAILABLE = False
    print("⚠️  GRID kit export unavailable (chain_to_grid_kit.py not found)")


# ============================================================================
# BUILT-IN SLC GENERATOR   (verbatim from interactive_slicer.py)
# ============================================================================

def generate_slc_file(wav_path, slices, total_samples):
    """
    Generate .slc file for ER-301 using the ACTUAL format from hardware.

    HEADER (27 bytes):
    - Bytes  0-3:  Magic number 0xABCDDCBA (uint32 LE)
    - Bytes  4-7:  Version 7 (uint32 LE)
    - Bytes  8-13: Label "Slices"
    - Bytes 14-22: Null padding
    - Bytes 23-26: Slice count (uint32 LE)  ← was mistaken as a constant 0x80

    ENTRIES (N × 16 bytes):
    - Bytes 0-3:   Sample position (uint32 LE)
    - Bytes 4-7:   Float 0.0
    - Bytes 8-11:  Float 0.0
    - Bytes 12-15: Float 1.0
    """
    slc_path = wav_path.replace('.wav', '.slc')
    n = len(slices)

    print(f"\n📄 Generating .slc file: {slc_path}")
    print(f"   Slices: {n}")

    with open(slc_path, 'wb') as f:
        # Header
        f.write(struct.pack('<I', 0xABCDDCBA))  # bytes  0-3:  magic
        f.write(struct.pack('<I', 7))            # bytes  4-7:  version
        f.write(b'Slices')                       # bytes  8-13: label
        f.write(b'\x00' * 9)                     # bytes 14-22: padding
        f.write(struct.pack('<I', n))            # bytes 23-26: slice count

        # Entries
        for i, s in enumerate(slices):
            position = max(0, min(s['start'], 0xFFFFFFFF))
            f.write(struct.pack('<I', position))
            f.write(struct.pack('<f', 0.0))
            f.write(struct.pack('<f', 0.0))
            f.write(struct.pack('<f', 1.0))

    expected = 27 + n * 16
    actual   = os.path.getsize(slc_path)

    print(f"✓ Generated {slc_path}")
    print(f"   File size: {actual} bytes (expected {expected})")

    if actual == expected:
        print(f"   ✓ Size correct")
        with open(slc_path, 'rb') as f:
            f.seek(27)
            first_pos = struct.unpack('<I', f.read(4))[0]
            f.seek(27 + (n - 1) * 16)
            last_pos  = struct.unpack('<I', f.read(4))[0]
        print(f"   First slice: sample {first_pos:,}")
        print(f"   Last slice:  sample {last_pos:,}")
    else:
        print(f"   ❌ ERROR: size mismatch!")

    return slc_path


def generate_grid_kit_file(wav_path, chain_slices, total_samples):
    """
    Generate a GRID .kit file (Percussa SSP) alongside the chain, carrying the
    SAME slices as the .slc. GRID stores slices as normalized [0,1] start/end
    pairs; we derive them from the chain's absolute slice start positions.
    """
    kit_path = os.path.splitext(wav_path)[0] + '.kit'
    positions = [s['start'] for s in chain_slices]
    pairs = slice_pairs_normalized(positions, total_samples)

    stem = os.path.splitext(os.path.basename(wav_path))[0]
    root = build_kit_xml(stem, os.path.basename(wav_path), pairs, pad_index=0)
    write_kit(root, kit_path)

    print(f"\n🎛️  Generating GRID .kit file: {kit_path}")
    print(f"   Slices: {len(pairs)} (normalized for Percussa SSP GRID)")
    print(f"   ✓ Generated {kit_path}")
    return kit_path


# ============================================================================
# Convenience for generators that hold a flat marker list (e.g. junglize)
# ============================================================================

def write_wav(wav_path, audio, sr):
    """Write a normalized 16-bit PCM wav."""
    a = np.asarray(audio, dtype=np.float32)
    peak = np.max(np.abs(a)) if a.size else 0.0
    if peak > 1.0:
        a = a / peak
    sf.write(wav_path, a, sr, subtype='PCM_16')
    return wav_path


def markers_to_slices(markers, total_samples):
    """Flat marker positions -> sorted/deduped/clamped [{'start': pos}, ...]."""
    m = sorted({int(x) for x in markers if 0 <= int(x) < total_samples})
    if not m or m[0] != 0:
        m = [0] + m
    return [{'start': p} for p in m]


def write_chain(wav_path, audio, sr, markers, make_kit=True):
    """
    Write <wav_path> + its .slc (+ .kit) as one aligned set, reusing the exact
    same writers the interactive slicer uses.

    Returns a dict of the written paths.
    """
    if not wav_path.lower().endswith('.wav'):
        wav_path += '.wav'
    total = int(len(audio))

    write_wav(wav_path, audio, sr)
    slices = markers_to_slices(markers, total)

    paths = {'wav': wav_path,
             'slc': generate_slc_file(wav_path, slices, total)}
    if make_kit and GRID_KIT_AVAILABLE:
        paths['kit'] = generate_grid_kit_file(wav_path, slices, total)
    return paths


# --- self-test --------------------------------------------------------------
if __name__ == "__main__":
    sr = 44100
    audio = np.zeros(sr, dtype=np.float32)
    markers = [0, sr // 4, sr // 2, 3 * sr // 4]
    paths = write_chain("/tmp/slc_selftest.wav", audio, sr, markers)
    with open(paths['slc'], 'rb') as f:
        head = f.read(27)
    assert struct.unpack('<I', head[:4])[0] == 0xABCDDCBA
    assert struct.unpack('<I', head[23:27])[0] == 4
    print(f"\n[slc_io] self-test ok — GRID available: {GRID_KIT_AVAILABLE}")
    print(f"[slc_io] wrote: {paths}")
