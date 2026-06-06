#!/usr/bin/env python3
"""
ER-301 Chain Merger
Combines multiple pre-sliced sample chains (.wav + .slc pairs) into one
combined chain, preserving existing slice positions. Missing slots are filled
with silence carrying evenly-spaced placeholder slice markers.

Run from the project root:
    venv/bin/python3 src/merge_chains.py
"""

import sys
import os
import struct
import numpy as np
import soundfile as sf

# ============================================================================
# SLC I/O
# ============================================================================

SLC_MAGIC   = 0xABCDDCBA
SLC_VERSION = 7
SLC_HEADER  = 27       # bytes
SLC_ENTRY   = 16       # bytes per slice


def read_slc_file(slc_path):
    """
    Read slice positions from an ER-301 .slc file.

    Returns:
        List of sample positions (int), one per slice entry.
        Raises ValueError on bad magic/version.
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


def write_slc_file(wav_path, positions):
    """
    Write an ER-301 .slc file for an arbitrary number of slices.

    Header byte 23-26 encodes the slice count as uint32 little-endian.
    Hardware files confirm: 128 slices -> 0x80 0x00 0x00 0x00 at byte 23.

    Args:
        wav_path:  Path to the paired .wav — .slc gets the same stem.
        positions: List of sample positions (int).

    Returns:
        Path to the written .slc file.
    """
    slc_path = os.path.splitext(wav_path)[0] + '.slc'
    n = len(positions)

    with open(slc_path, 'wb') as f:
        # Header (27 bytes)
        f.write(struct.pack('<I', SLC_MAGIC))       # bytes  0-3:  magic
        f.write(struct.pack('<I', SLC_VERSION))     # bytes  4-7:  version
        f.write(b'Slices')                          # bytes  8-13: label
        f.write(b'\x00' * 9)                        # bytes 14-22: padding
        f.write(struct.pack('<I', n))               # bytes 23-26: slice count (uint32 LE)

        # Entries
        for pos in positions:
            pos = max(0, min(pos, 0xFFFFFFFF))
            f.write(struct.pack('<I', pos))
            f.write(struct.pack('<f', 0.0))
            f.write(struct.pack('<f', 0.0))
            f.write(struct.pack('<f', 1.0))

    expected = SLC_HEADER + n * SLC_ENTRY
    actual   = os.path.getsize(slc_path)
    if actual != expected:
        print(f"⚠️  Size mismatch: wrote {actual} bytes, expected {expected}")
    else:
        print(f"✓ .slc written ({n} slices, {actual} bytes): {slc_path}")

    return slc_path

# ============================================================================
# Core merge logic
# ============================================================================

def build_silent_slot(num_slices, slot_duration_samples, sr):
    """
    Build a silent audio segment with evenly-spaced slice markers.

    Args:
        num_slices:             Number of slice markers to place.
        slot_duration_samples:  Total length of the silent segment in samples.
        sr:                     Sample rate (used only for reporting).

    Returns:
        (audio_array, positions_relative)
        positions_relative: slice positions relative to the start of this segment.
    """
    audio = np.zeros(slot_duration_samples, dtype=np.float32)

    # Space markers evenly across the silent block
    step = slot_duration_samples / num_slices
    positions = [int(i * step) for i in range(num_slices)]

    return audio, positions


def merge_chains(slots, output_path, sr):
    """
    Merge slot data into a single chain .wav + .slc.

    Args:
        slots: List of dicts, one per slot:
            {
              'label':     str,         # display name
              'audio':     np.ndarray,  # float32 mono
              'positions': [int, ...],  # slice positions relative to slot start
              'silent':    bool,        # True = synthesised silence
            }
        output_path: Destination .wav path.
        sr:          Sample rate.
    """
    print(f"\n🔗 Merging {len(slots)} slots...")

    combined_audio    = []
    combined_positions = []
    cursor = 0

    for i, slot in enumerate(slots):
        audio     = slot['audio']
        positions = slot['positions']
        label     = slot['label']
        tag       = '(silent)' if slot['silent'] else ''

        # Offset this slot's positions by the current cursor
        abs_positions = [cursor + p for p in positions]
        combined_positions.extend(abs_positions)

        combined_audio.append(audio)
        cursor += len(audio)

        dur_s = len(audio) / sr
        print(f"   Slot {i+1:2d}: {label} {tag}")
        print(f"           {len(positions)} slices | {len(audio):,} samples | {dur_s:.2f}s")

    full_audio = np.concatenate(combined_audio)
    print(f"\n✓ Combined: {len(full_audio):,} samples ({len(full_audio)/sr:.2f}s)")
    print(f"   Total slices: {len(combined_positions)}")

    # Write .wav
    sf.write(output_path, full_audio, sr)
    print(f"✓ .wav written: {output_path}")

    # Write .slc
    write_slc_file(output_path, combined_positions)

    return output_path


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


def ask_file(prompt, must_exist=True):
    """Prompt for a file path, optionally validating existence."""
    while True:
        path = input(f"{prompt}: ").strip()
        if path == "":
            return None
        path = os.path.expanduser(path)
        if must_exist and not os.path.isfile(path):
            print(f"  File not found: {path}")
            continue
        return path


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


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("🔗  ER-301 CHAIN MERGER")
    print("=" * 70)
    print("Combines pre-sliced chains (.wav + .slc pairs) into one chain.")
    print("Missing slots are filled with silence + evenly-spaced markers.")
    print("=" * 70)

    # ── Step 1: layout ───────────────────────────────────────────────────────
    print("\n📐 Step 1: Define Layout")
    print("-" * 70)

    num_slots   = ask("How many slots in total?", default=8,  cast=int)
    slices_each = ask("Slices per slot?",         default=128, cast=int)
    total       = num_slots * slices_each
    sample_rate = ask("Sample rate (Hz)",         default=48000, cast=int)

    print(f"\n   {num_slots} slots × {slices_each} slices = {total} total slices")

    # ── Step 2: input directory ───────────────────────────────────────────────
    print("\n📁 Step 2: Input Files")
    print("-" * 70)

    script_dir   = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir) if os.path.basename(script_dir) == 'src' else script_dir
    default_dir  = os.path.join(project_root, 'input')

    use_default = input(f"\nUse default input directory? ({default_dir}) [Y/n]: ").strip().lower()
    input_dir   = default_dir if use_default in ('', 'y', 'yes') else input("Input directory: ").strip()

    pairs = scan_wav_slc_pairs(input_dir)

    if pairs:
        print(f"\n✓ Found {len(pairs)} .wav/.slc pair(s):")
        for i, (wav, _) in enumerate(pairs, 1):
            size_mb = os.path.getsize(wav) / (1024 ** 2)
            print(f"  {i:2d}. {os.path.basename(wav)}  ({size_mb:.1f} MB)")
    else:
        print(f"  No paired files found in {input_dir}")

    # ── Step 3: assign files to slots ─────────────────────────────────────────
    print(f"\n🎛️  Step 3: Assign Files to Slots  (leave blank = silent)")
    print("-" * 70)
    print("Enter the number of a discovered pair, or a full path to a .wav")
    print("(its .slc must sit alongside it).  Press Enter to leave slot silent.\n")

    slot_assignments = []   # list of (wav_path, slc_path) or None

    for slot_num in range(1, num_slots + 1):
        while True:
            raw = input(f"  Slot {slot_num:2d}/{num_slots}: ").strip()

            if raw == "":
                slot_assignments.append(None)
                print(f"           → silent")
                break

            # Numeric selection from discovered pairs
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(pairs):
                    slot_assignments.append(pairs[idx])
                    print(f"           → {os.path.basename(pairs[idx][0])}")
                    break
                else:
                    print(f"  Please enter 1–{len(pairs)} or a file path.")
                    continue

            # Direct path
            wav_path = os.path.expanduser(raw)
            if not wav_path.lower().endswith('.wav'):
                wav_path += '.wav'
            slc_path = os.path.splitext(wav_path)[0] + '.slc'

            if not os.path.isfile(wav_path):
                print(f"  File not found: {wav_path}")
                continue
            if not os.path.isfile(slc_path):
                print(f"  No paired .slc found: {slc_path}")
                continue

            slot_assignments.append((wav_path, slc_path))
            print(f"           → {os.path.basename(wav_path)}")
            break

    # ── Step 4: output name ───────────────────────────────────────────────────
    print("\n💾 Step 4: Output")
    print("-" * 70)
    output_dir  = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_name = ask("Output filename (no extension)", default="merged_chain")
    output_path = os.path.join(output_dir, output_name + '.wav')

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    filled  = sum(1 for s in slot_assignments if s is not None)
    silent  = num_slots - filled
    print(f"  Slots:        {num_slots}  ({filled} loaded, {silent} silent)")
    print(f"  Slices/slot:  {slices_each}")
    print(f"  Total slices: {total}")
    print(f"  Sample rate:  {sample_rate} Hz")
    print(f"  Output:       {output_path}")
    print("=" * 70)

    confirm = input("\nProceed? [Y/n]: ").strip().lower()
    if confirm not in ('', 'y', 'yes'):
        print("❌ Cancelled")
        return

    # ── Build slots ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("⚙️  PROCESSING")
    print("=" * 70)

    # First pass: determine reference duration for silent slots
    # Use the duration of the first loaded file, or a fallback.
    reference_samples = None
    for assignment in slot_assignments:
        if assignment is not None:
            wav_path, _ = assignment
            info = sf.info(wav_path)
            ref_sr = info.samplerate
            reference_samples = int(info.frames * sample_rate / ref_sr)
            break

    if reference_samples is None:
        # All slots silent — default to 5 seconds per slot
        reference_samples = sample_rate * 5
        print(f"⚠️  No real files loaded; using {reference_samples/sample_rate:.1f}s per silent slot")

    # Second pass: build each slot
    slots = []
    for i, assignment in enumerate(slot_assignments):
        slot_num = i + 1

        if assignment is None:
            # ── Silent slot ───────────────────────────────────────────────
            audio, positions = build_silent_slot(slices_each, reference_samples, sample_rate)
            slots.append({
                'label':     f'(silent slot {slot_num})',
                'audio':     audio,
                'positions': positions,
                'silent':    True,
            })

        else:
            # ── Real file ─────────────────────────────────────────────────
            wav_path, slc_path = assignment

            print(f"\n  Loading slot {slot_num}: {os.path.basename(wav_path)}")

            # Load audio (resample to target sr if needed)
            audio, file_sr = sf.read(wav_path, dtype='float32', always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)          # stereo → mono
            if file_sr != sample_rate:
                import librosa
                audio = librosa.resample(audio, orig_sr=file_sr, target_sr=sample_rate)
                print(f"    Resampled {file_sr} → {sample_rate} Hz")

            # Read existing slice positions
            try:
                raw_positions = read_slc_file(slc_path)
            except ValueError as e:
                print(f"  ❌ Could not read .slc: {e}")
                print(f"     Falling back to evenly-spaced markers")
                _, raw_positions = build_silent_slot(slices_each, len(audio), sample_rate)
                raw_positions = raw_positions  # already relative

            # Validate / adjust count
            if len(raw_positions) != slices_each:
                print(f"    ⚠️  .slc has {len(raw_positions)} entries; expected {slices_each}")
                if len(raw_positions) > slices_each:
                    raw_positions = raw_positions[:slices_each]
                    print(f"    Trimmed to {slices_each}")
                else:
                    # Pad with evenly spaced positions up to end of audio
                    extra_needed = slices_each - len(raw_positions)
                    last = raw_positions[-1] if raw_positions else 0
                    end  = len(audio)
                    step = (end - last) / (extra_needed + 1)
                    for k in range(1, extra_needed + 1):
                        raw_positions.append(int(last + k * step))
                    print(f"    Padded to {slices_each}")

            # Update reference_samples from this file
            reference_samples = len(audio)

            slots.append({
                'label':     os.path.basename(wav_path),
                'audio':     audio,
                'positions': raw_positions,
                'silent':    False,
            })

    # ── Merge ─────────────────────────────────────────────────────────────────
    merge_chains(slots, output_path, sample_rate)

    print("\n" + "=" * 70)
    print("📊 RESULTS")
    print("=" * 70)
    wav_mb = os.path.getsize(output_path) / (1024 ** 2)
    slc_path = os.path.splitext(output_path)[0] + '.slc'
    slc_kb = os.path.getsize(slc_path) / 1024
    print(f"  Output .wav:  {output_path}  ({wav_mb:.1f} MB)")
    print(f"  Output .slc:  {slc_path}  ({slc_kb:.1f} KB)")
    print(f"  Total slices: {num_slots * slices_each}")
    print(f"  Slots filled: {filled}/{num_slots}")
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
