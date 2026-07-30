#!/usr/bin/env python3
"""
ER-301 Chain Splitter
Inverse of merge_chains.py: takes a pre-sliced sample chain (.wav + .slc pair)
and cuts it apart at its slice markers, writing every slice out as its own
individual .wav file.

Each source chain is exported into its own subfolder under output/:

    output/<chainname>/<chainname>_slice_001.wav
    output/<chainname>/<chainname>_slice_002.wav
    ...

Run from the project root:
    venv/bin/python3 src/split_chain.py
"""

import sys
import os
import struct
import numpy as np
import soundfile as sf

# ============================================================================
# SLC I/O  (format matches interactive_slicer.py / merge_chains.py)
# ============================================================================

SLC_MAGIC   = 0xABCDDCBA
SLC_VERSION = 7
SLC_HEADER  = 27       # bytes
SLC_ENTRY   = 16       # bytes per slice


def read_slc_file(slc_path):
    """
    Read slice positions from an ER-301 .slc file.

    Returns:
        List of sample positions (int), one per slice entry, in file order.
        Raises ValueError on bad magic/version or truncated file.
    """
    with open(slc_path, 'rb') as f:
        data = f.read()

    if len(data) < SLC_HEADER + SLC_ENTRY:
        raise ValueError(f"File too small to be a valid .slc: {slc_path}")

    magic   = struct.unpack_from('<I', data, 0)[0]
    version = struct.unpack_from('<I', data, 4)[0]

    if magic != SLC_MAGIC:
        raise ValueError(f"Bad magic 0x{magic:08X} in {slc_path} (expected 0x{SLC_MAGIC:08X})")
    if version != SLC_VERSION:
        raise ValueError(f"Unexpected version {version} in {slc_path} (expected {SLC_VERSION})")

    num_entries = (len(data) - SLC_HEADER) // SLC_ENTRY
    positions = []
    offset = SLC_HEADER
    for _ in range(num_entries):
        pos = struct.unpack_from('<I', data, offset)[0]
        positions.append(pos)
        offset += SLC_ENTRY

    return positions


# ============================================================================
# Core split logic
# ============================================================================

def slice_bounds(positions, total_samples):
    """
    Turn a list of slice start positions into (start, end) sample pairs.

    Each slice runs from its own marker up to the next marker; the final slice
    runs to the end of the audio. Positions are sorted and clamped to the audio
    length, and zero-length slices are dropped.

    Returns:
        List of (start, end) tuples.
    """
    # Sort and clamp into range, keep unique-in-order-of-position
    clean = sorted(set(max(0, min(p, total_samples)) for p in positions))

    # Ensure a marker exists at the very start so nothing before the first
    # marker is silently discarded.
    if not clean or clean[0] != 0:
        clean = [0] + clean

    bounds = []
    for i, start in enumerate(clean):
        end = clean[i + 1] if i + 1 < len(clean) else total_samples
        if end > start:
            bounds.append((start, end))

    return bounds


def split_chain(wav_path, slc_path, output_dir, chain_name=None, verbose=True):
    """
    Split one .wav/.slc pair into individual slice .wav files.

    Args:
        wav_path:   Path to the chain .wav.
        slc_path:   Path to the paired .slc.
        output_dir: Project output directory. A subfolder named after the chain
                    is created inside it.
        chain_name: Override for the subfolder / file stem (defaults to the wav
                    filename without extension).
        verbose:    Print progress.

    Returns:
        (slice_dir, [written_paths]) — the created subfolder and the list of
        slice files written.
    """
    if chain_name is None:
        chain_name = os.path.splitext(os.path.basename(wav_path))[0]

    # Load audio (keep native sample rate; preserve channel layout)
    audio, sr = sf.read(wav_path, dtype='float32', always_2d=False)
    total_samples = audio.shape[0]

    # Read slice markers
    positions = read_slc_file(slc_path)
    bounds = slice_bounds(positions, total_samples)

    if verbose:
        dur = total_samples / sr
        print(f"\n✂️  Splitting: {os.path.basename(wav_path)}")
        print(f"   Audio:   {total_samples:,} samples ({dur:.2f}s @ {sr} Hz)")
        print(f"   Markers: {len(positions)} in .slc  →  {len(bounds)} slices to write")

    if not bounds:
        print(f"   ⚠️  No slices to write (empty or zero-length audio). Skipping.")
        return None, []

    # Zero-pad width based on slice count (min 3 digits: slice_001)
    pad = max(3, len(str(len(bounds))))

    slice_dir = os.path.join(output_dir, chain_name)
    os.makedirs(slice_dir, exist_ok=True)

    written = []
    for i, (start, end) in enumerate(bounds, 1):
        segment = audio[start:end]
        out_name = f"{chain_name}_slice_{i:0{pad}d}.wav"
        out_path = os.path.join(slice_dir, out_name)
        sf.write(out_path, segment, sr)
        written.append(out_path)

        if verbose and (i <= 3 or i == len(bounds)):
            seg_ms = (end - start) / sr * 1000
            print(f"   {out_name}: samples {start:,}–{end:,} ({seg_ms:.1f} ms)")
        elif verbose and i == 4 and len(bounds) > 4:
            print(f"   ...")

    if verbose:
        print(f"✓ Wrote {len(written)} slices → {slice_dir}")

    return slice_dir, written


# ============================================================================
# UI helpers
# ============================================================================

def ask(prompt, default=None, cast=str):
    """Prompt with optional default, cast result."""
    suffix = f" (default: {default})" if default is not None else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if raw == "" and default is not None:
        return default
    try:
        return cast(raw)
    except ValueError:
        print(f"  Invalid input, expected {cast.__name__}. Try again.")
        return ask(prompt, default, cast)


def scan_wav_slc_pairs(directory):
    """Return list of (wav_path, slc_path) for every .wav that has a paired .slc."""
    pairs = []
    if not os.path.isdir(directory):
        return pairs
    for fname in sorted(os.listdir(directory)):
        if fname.lower().endswith('.wav'):
            wav = os.path.join(directory, fname)
            slc = os.path.splitext(wav)[0] + '.slc'
            if os.path.isfile(slc):
                pairs.append((wav, slc))
    return pairs


def get_multiple_choices(prompt, options):
    """Get multiple selections (comma separated, or 'all')."""
    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        print(f"  {i:2d}. {option}")

    while True:
        raw = input(f"\nEnter choices [1-{len(options)}] (comma-separated, or 'all'): ").strip().lower()
        if raw == 'all':
            return list(range(1, len(options) + 1))
        try:
            choices = [int(c.strip()) for c in raw.split(',') if c.strip()]
            if choices and all(1 <= c <= len(options) for c in choices):
                return sorted(set(choices))
            print(f"  Please enter numbers between 1 and {len(options)}")
        except ValueError:
            print("  Please enter valid numbers separated by commas, or 'all'")


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("✂️   ER-301 CHAIN SPLITTER")
    print("=" * 70)
    print("Breaks a sliced chain (.wav + .slc) into individual slice .wav files.")
    print("Each chain is exported to its own subfolder under output/.")
    print("=" * 70)

    # ── Step 1: input directory ───────────────────────────────────────────────
    print("\n📁 Step 1: Input Files")
    print("-" * 70)

    script_dir   = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir) if os.path.basename(script_dir) == 'src' else script_dir
    default_dir  = os.path.join(project_root, 'input')

    use_default = input(f"\nUse default input directory? ({default_dir}) [Y/n]: ").strip().lower()
    input_dir   = default_dir if use_default in ('', 'y', 'yes') else input("Input directory: ").strip()
    input_dir   = os.path.expanduser(input_dir)

    pairs = scan_wav_slc_pairs(input_dir)

    if not pairs:
        print(f"\n❌ No .wav/.slc pairs found in: {input_dir}")
        print("   A chain needs both a .wav and a matching .slc alongside it.")
        return

    print(f"\n✓ Found {len(pairs)} .wav/.slc pair(s):")
    labels = []
    for wav, _ in pairs:
        size_mb = os.path.getsize(wav) / (1024 ** 2)
        labels.append(f"{os.path.basename(wav)}  ({size_mb:.1f} MB)")

    # ── Step 2: choose chains ─────────────────────────────────────────────────
    choices = get_multiple_choices("Select chain(s) to split:", labels)
    selected = [pairs[i - 1] for i in choices]

    # ── Step 3: output ────────────────────────────────────────────────────────
    output_dir = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print(f"  Chains to split: {len(selected)}")
    for wav, _ in selected:
        print(f"    • {os.path.basename(wav)}")
    print(f"  Output root:     {output_dir}")
    print(f"  Layout:          output/<chainname>/<chainname>_slice_001.wav ...")
    print("=" * 70)

    confirm = input("\nProceed? [Y/n]: ").strip().lower()
    if confirm not in ('', 'y', 'yes'):
        print("❌ Cancelled")
        return

    # ── Split ─────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("⚙️  PROCESSING")
    print("=" * 70)

    total_slices = 0
    total_chains = 0
    for wav_path, slc_path in selected:
        try:
            slice_dir, written = split_chain(wav_path, slc_path, output_dir)
            if written:
                total_slices += len(written)
                total_chains += 1
        except Exception as e:
            print(f"\n❌ Failed to split {os.path.basename(wav_path)}: {e}")

    # ── Results ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📊 RESULTS")
    print("=" * 70)
    print(f"  Chains split:  {total_chains}/{len(selected)}")
    print(f"  Slices written: {total_slices}")
    print(f"  Output root:   {output_dir}")
    print("=" * 70)
    print("\n🎉 Done!\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled")
        sys.exit(0)
    except Exception as e:
        import traceback
        print(f"\n❌ Error: {e}")
        traceback.print_exc()
        sys.exit(1)
