#!/usr/bin/env python3
"""
Chain → GRID Kit
Turns an ER-301 sample chain (.wav + .slc pair) into a GRID .kit file for the
Percussa SSP, so the SAME sample carries the SAME slices on both instruments.

The ER-301 reads slice markers as absolute sample positions from the .slc.
GRID (github.com/kuttor/Percussa-SSP--GRID) stores slices as normalized
[0,1] start/end pairs inside a plain-XML .kit file (root <GRID_KIT>, one
<PAD> per pad). Converting between them is just:

    normalized_start[i] = position[i]      / total_samples
    normalized_end[i]   = position[i + 1]  / total_samples   (last → 1.0)

i.e. each slice runs from its own marker to the next — identical boundary
logic to the ER-301. The audio file itself is untouched and shared by both.

Workflow on the SSP:
    • copy the chain .wav to  /media/BOOT/samples/
    • copy the .kit       to  /media/BOOT/samples/kits/
    • load the kit in GRID — the pad shows the chain with all its slices.

Run from the project root:
    venv/bin/python3 src/chain_to_grid_kit.py
"""

import sys
import os
import struct
import xml.etree.ElementTree as ET
from xml.dom import minidom
import soundfile as sf

# ============================================================================
# SLC I/O  (format matches interactive_slicer.py / merge_chains.py)
# ============================================================================

SLC_MAGIC   = 0xABCDDCBA
SLC_VERSION = 7
SLC_HEADER  = 27       # bytes
SLC_ENTRY   = 16       # bytes per slice

# GRID stores slices per pad. kMaxSlices in the plugin is 128.
GRID_MAX_SLICES = 128
GRID_NUM_PADS   = 8


def read_slc_file(slc_path):
    """Read slice sample positions from an ER-301 .slc file (in file order)."""
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
        positions.append(struct.unpack_from('<I', data, offset)[0])
        offset += SLC_ENTRY
    return positions


# ============================================================================
# Slice conversion
# ============================================================================

def slice_pairs_normalized(positions, total_samples):
    """
    Convert absolute .slc positions into normalized [0,1] (start, end) pairs.

    Each slice runs from its marker to the next; the final slice ends at 1.0.
    Positions are sorted/clamped, a start-of-file marker is ensured, and
    zero-length slices are dropped — matching split_chain's boundary logic.
    """
    clean = sorted(set(max(0, min(p, total_samples)) for p in positions))
    if not clean or clean[0] != 0:
        clean = [0] + clean

    pairs = []
    for i, start in enumerate(clean):
        end = clean[i + 1] if i + 1 < len(clean) else total_samples
        if end > start:
            pairs.append((start / total_samples, end / total_samples))
    return pairs


# ============================================================================
# GRID kit writing
# ============================================================================

def _fmt_list(values, decimals):
    return ",".join(f"{v:.{decimals}f}" for v in values)


def build_kit_xml(kit_name, sample_ref, pairs, pad_index=0, num_pads=GRID_NUM_PADS):
    """
    Build a GRID_KIT XML tree with the chain (and its slices) on `pad_index`.

    Attribute names/formatting mirror KitData::saveToFile in the GRID source:
    starts/ends at 6 decimals, pitches at 2. All 8 pads are written; unused
    pads are empty (file=""), just like a kit saved on the device.
    """
    starts = [s for s, _ in pairs]
    ends   = [e for _, e in pairs]
    pitches = [0.0] * len(pairs)

    root = ET.Element("GRID_KIT")
    root.set("name", kit_name)

    for i in range(num_pads):
        pad = ET.SubElement(root, "PAD")
        pad.set("index", str(i))

        if i == pad_index:
            pad.set("file", sample_ref)
        else:
            pad.set("file", "")
        pad.set("stack", "")

        # Playback defaults (GRID's own defaults)
        pad.set("volume", "1.0")
        pad.set("pan", "0.0")
        pad.set("start", "0.0")
        pad.set("end", "1.0")
        pad.set("pitch", "0.0")
        pad.set("stretch", "1.0")
        pad.set("mode", "0")            # OneShot
        pad.set("choke", "0")
        pad.set("reversed", "0")
        pad.set("midiCh", "0")
        pad.set("clockBeats", "4")
        pad.set("voiceMode", "0")
        pad.set("filterType", "0")
        pad.set("filterCutoff", "20000.0")
        pad.set("filterReso", "0.0")
        pad.set("lofiMode", "0")
        pad.set("compSend", "0.0")
        pad.set("compBypass", "0")
        pad.set("pitchMode", "0")
        pad.set("outputChannel", "-1")
        pad.set("sendToMix", "1")
        # Tape settings (neutral)
        pad.set("tapeRate", "1.0")
        pad.set("tapeWow", "0.0")
        pad.set("tapeFlutter", "0.0")
        pad.set("tapeHFRolloff", "0.0")
        pad.set("tapeHeadBump", "0.0")
        pad.set("tapeSaturation", "0.0")

        if i == pad_index and pairs:
            pad.set("sliceMode", "1")
            pad.set("sliceStarts", _fmt_list(starts, 6))
            pad.set("sliceEnds", _fmt_list(ends, 6))
            pad.set("slicePitches", _fmt_list(pitches, 2))
        else:
            pad.set("sliceMode", "0")

    return root


def write_kit(root, kit_path):
    """Write the XML tree to disk, pretty-printed with a declaration."""
    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    with open(kit_path, "wb") as f:
        f.write(pretty)
    return kit_path


def chain_to_kit(wav_path, slc_path, kit_path, kit_name=None,
                 sample_ref=None, pad_index=0, verbose=True):
    """
    Convert one .wav/.slc pair into a GRID .kit file.

    sample_ref: the path GRID uses to find the audio, relative to its sample
                root (/media/BOOT/samples). Defaults to the wav's basename.

    Returns (kit_path, num_slices).
    """
    if kit_name is None:
        kit_name = os.path.splitext(os.path.basename(wav_path))[0]
    if sample_ref is None:
        sample_ref = os.path.basename(wav_path)

    info = sf.info(wav_path)
    total_samples = info.frames

    positions = read_slc_file(slc_path)
    pairs = slice_pairs_normalized(positions, total_samples)

    if verbose:
        print(f"\n🎛️  {os.path.basename(wav_path)}")
        print(f"   Audio:   {total_samples:,} samples "
              f"({total_samples / info.samplerate:.2f}s @ {info.samplerate} Hz)")
        print(f"   Markers: {len(positions)} in .slc  →  {len(pairs)} slice pairs")

    if len(pairs) > GRID_MAX_SLICES:
        print(f"   ⚠️  {len(pairs)} slices exceeds GRID's {GRID_MAX_SLICES}/pad — "
              f"extra slices past {GRID_MAX_SLICES} will be ignored on load.")

    root = build_kit_xml(kit_name, sample_ref, pairs, pad_index=pad_index)
    write_kit(root, kit_path)

    if verbose:
        print(f"   ✓ Kit: {kit_path}")
        print(f"     Sample reference (relative to GRID sample root): {sample_ref}")

    return kit_path, len(pairs)


# ============================================================================
# UI helpers
# ============================================================================

def ask(prompt, default=None, cast=str):
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
    print("🎛️   CHAIN → GRID KIT")
    print("=" * 70)
    print("Writes a GRID .kit (Percussa SSP) with the SAME slices as the .slc,")
    print("so one chain .wav plays identically on the ER-301 and GRID.")
    print("=" * 70)

    # ── Step 1: input ─────────────────────────────────────────────────────────
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

    print(f"\n✓ Found {len(pairs)} .wav/.slc pair(s).")
    labels = []
    for wav, _ in pairs:
        size_mb = os.path.getsize(wav) / (1024 ** 2)
        labels.append(f"{os.path.basename(wav)}  ({size_mb:.1f} MB)")

    choices = get_multiple_choices("Select chain(s) to convert:", labels)
    selected = [pairs[i - 1] for i in choices]

    # ── Step 2: pad ───────────────────────────────────────────────────────────
    print("\n🎚️  Step 2: Target Pad")
    print("-" * 70)
    pad_index = ask("Which GRID pad should hold the chain? (1-8)", default=1, cast=int)
    pad_index = max(1, min(GRID_NUM_PADS, pad_index)) - 1   # to 0-based

    # ── Step 3: output ────────────────────────────────────────────────────────
    output_dir = os.path.join(project_root, 'output', 'grid')
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print(f"  Chains:     {len(selected)}")
    print(f"  Target pad: {pad_index + 1}")
    print(f"  Output:     {output_dir}")
    print("=" * 70)

    if input("\nProceed? [Y/n]: ").strip().lower() not in ('', 'y', 'yes'):
        print("❌ Cancelled")
        return

    # ── Convert ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("⚙️  PROCESSING")
    print("=" * 70)

    made = 0
    for wav_path, slc_path in selected:
        stem = os.path.splitext(os.path.basename(wav_path))[0]
        kit_path = os.path.join(output_dir, stem + '.kit')
        try:
            chain_to_kit(wav_path, slc_path, kit_path, kit_name=stem)
            made += 1
        except Exception as e:
            print(f"   ❌ {os.path.basename(wav_path)}: {e}")

    # ── Results ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📊 RESULTS")
    print("=" * 70)
    print(f"  Kits written: {made}/{len(selected)}")
    print(f"  Output:       {output_dir}")
    print("\n  To use on the SSP:")
    print("    1. Copy the chain .wav → /media/BOOT/samples/")
    print("    2. Copy the .kit       → /media/BOOT/samples/kits/")
    print("    3. Load the kit in GRID.")
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
