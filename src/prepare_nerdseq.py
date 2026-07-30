#!/usr/bin/env python3
"""
NerdSEQ Sample Preparer
Converts arbitrary audio files (a single file, several files, or a whole folder)
into samples ready to drop onto the NerdSEQ's microSD card.

Per the NerdSEQ V3.0 manual (Load Sample window, p.156), the sampler accepts:
    • WAV, 8 or 16 bit, mono or stereo
    • RAW 8 bit unsigned (mono)
Sample memory is ~190 kB shared across all 12 slots, and the device does NOT
resample on load — files must already be at the intended playback rate
(44.1 kHz is the manual's reference; C-4 plays a sample at its original speed).

This tool lets you choose the output format, channel layout and sample rate,
cleans filenames so they behave on the SD card's FAT filesystem, and reports
the memory each sample will consume (warning, never blocking).

Run from the project root:
    venv/bin/python3 src/prepare_nerdseq.py
"""

import sys
import os
import re
import struct
import warnings
import numpy as np
import soundfile as sf

warnings.filterwarnings('ignore', category=UserWarning, module='librosa')
import librosa

# ============================================================================
# NerdSEQ constants (from the V3.0 manual)
# ============================================================================

# Total sample memory shared across all 12 slots. The manual quotes ~190 kB
# ("190kB" on p.47); we use 190 * 1024 as the byte budget.
MEM_TOTAL_BYTES = 190 * 1024          # 194,560 bytes
NUM_SLOTS       = 12
REFERENCE_SR    = 44100               # manual's reference playback rate

INPUT_EXTS = ('.wav', '.mp3', '.flac', '.ogg', '.aif', '.aiff', '.m4a', '.wave')

# Output format keys
FMT_WAV16 = 'wav16'
FMT_WAV8  = 'wav8'
FMT_RAW8  = 'raw8'

FORMAT_INFO = {
    FMT_WAV16: {'label': 'WAV 16-bit', 'ext': '.wav', 'bytes_per_sample': 2},
    FMT_WAV8:  {'label': 'WAV 8-bit (unsigned)', 'ext': '.wav', 'bytes_per_sample': 1},
    FMT_RAW8:  {'label': 'RAW 8-bit unsigned (mono)', 'ext': '.raw', 'bytes_per_sample': 1},
}

# ============================================================================
# Conversion core
# ============================================================================

def sanitize_name(stem):
    """
    Make a filename stem safe for the NerdSEQ SD card (FAT) and readable in the
    device's uppercase browser. Keeps ASCII letters/digits/space/_/-, collapses
    whitespace, strips the rest, and trims length.
    """
    # Transliterate common accented chars to ASCII, drop anything else non-ASCII
    stem = stem.encode('ascii', 'ignore').decode('ascii')
    stem = re.sub(r'[^A-Za-z0-9 _-]+', '', stem)   # keep safe set
    stem = re.sub(r'\s+', ' ', stem).strip()
    stem = stem.replace(' ', '_')
    if not stem:
        stem = 'sample'
    return stem[:24]                                # keep names short & tidy


def unique_path(directory, stem, ext):
    """Return a non-colliding path <directory>/<stem><ext>, adding _2, _3 ..."""
    candidate = os.path.join(directory, stem + ext)
    if not os.path.exists(candidate):
        return candidate
    i = 2
    while True:
        candidate = os.path.join(directory, f"{stem}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def load_audio(path, target_sr, channels):
    """
    Load an audio file at target_sr with the requested channel layout.

    channels: 'mono', 'stereo', or 'keep'.

    Returns:
        data — for mono: 1-D float32 array
               for stereo: 2-D float32 array shaped (frames, 2)
    """
    if channels == 'mono':
        data = librosa.load(path, sr=target_sr, mono=True)[0]
        return np.asarray(data, dtype=np.float32)

    # Load preserving channels
    data = librosa.load(path, sr=target_sr, mono=False)[0]
    data = np.asarray(data, dtype=np.float32)

    # librosa returns (channels, frames) when multi-channel; make it (frames, ch)
    if data.ndim == 1:
        n_src_ch = 1
        frames = data.shape[0]
    else:
        n_src_ch = data.shape[0]
        data = data.T                      # → (frames, channels)
        frames = data.shape[0]

    if channels == 'keep':
        return data

    # channels == 'stereo': force exactly 2 channels
    if n_src_ch == 1:
        mono = data if data.ndim == 1 else data[:, 0]
        return np.stack([mono, mono], axis=1)
    if n_src_ch == 2:
        return data
    # >2 channels: keep first two
    return data[:, :2]


def data_bytes(num_frames, num_channels, fmt):
    """Bytes of PCM sample data the NerdSEQ will hold in memory."""
    return num_frames * num_channels * FORMAT_INFO[fmt]['bytes_per_sample']


def float_to_u8(data):
    """Convert float [-1, 1] audio to unsigned 8-bit [0, 255]."""
    clipped = np.clip(data, -1.0, 1.0)
    return np.round((clipped * 0.5 + 0.5) * 255.0).astype(np.uint8)


def write_output(data, sr, fmt, out_path):
    """Write converted audio in the chosen NerdSEQ format."""
    if fmt == FMT_WAV16:
        sf.write(out_path, data, sr, subtype='PCM_16')
    elif fmt == FMT_WAV8:
        sf.write(out_path, data, sr, subtype='PCM_U8')   # WAV 8-bit is unsigned
    elif fmt == FMT_RAW8:
        # RAW is documented as 8-bit unsigned mono: flatten to mono first.
        mono = data if data.ndim == 1 else data.mean(axis=1)
        float_to_u8(mono).tofile(out_path)
    else:
        raise ValueError(f"Unknown format: {fmt}")


def convert_file(in_path, out_dir, fmt, channels, target_sr, normalize, verbose=True):
    """
    Convert one input file to a NerdSEQ-ready sample.

    Returns a dict with conversion info, or None on failure.
    """
    name = os.path.basename(in_path)

    # RAW is mono-only per the manual
    eff_channels = 'mono' if fmt == FMT_RAW8 else channels

    try:
        data = load_audio(in_path, target_sr, eff_channels)
    except Exception as e:
        print(f"   ❌ {name}: could not load ({e})")
        return None

    if data.size == 0:
        print(f"   ⚠️  {name}: empty audio, skipped")
        return None

    if normalize:
        peak = float(np.max(np.abs(data)))
        if peak > 0:
            data = data * (0.99 / peak)

    num_frames   = data.shape[0]
    num_channels = 1 if data.ndim == 1 else data.shape[1]
    size_bytes   = data_bytes(num_frames, num_channels, fmt)

    stem = sanitize_name(os.path.splitext(name)[0])
    ext  = FORMAT_INFO[fmt]['ext']
    out_path = unique_path(out_dir, stem, ext)

    write_output(data, target_sr, fmt, out_path)

    dur_s   = num_frames / target_sr
    too_big = size_bytes > MEM_TOTAL_BYTES

    if verbose:
        warn = "  ⚠️  exceeds full memory!" if too_big else ""
        ch_txt = 'mono' if num_channels == 1 else f'{num_channels}ch'
        print(f"   ✓ {os.path.basename(out_path):<28} "
              f"{dur_s:5.2f}s  {ch_txt:>5}  {size_bytes/1024:6.1f} kB{warn}")

    return {
        'in': in_path,
        'out': out_path,
        'bytes': size_bytes,
        'frames': num_frames,
        'channels': num_channels,
        'duration_s': dur_s,
        'too_big': too_big,
    }


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


def get_user_choice(prompt, options, default=None):
    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        mark = " (default)" if default == i else ""
        print(f"  {i}. {option}{mark}")
    while True:
        raw = input(f"\nEnter choice [1-{len(options)}]"
                    + (f" (default: {default})" if default else "") + ": ").strip()
        if raw == "" and default:
            return default
        try:
            c = int(raw)
            if 1 <= c <= len(options):
                return c
        except ValueError:
            pass
        print(f"  Please enter a number between 1 and {len(options)}")


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


def scan_audio_files(directory):
    files = []
    if not os.path.isdir(directory):
        return files
    for fname in sorted(os.listdir(directory)):
        if fname.lower().endswith(INPUT_EXTS):
            files.append(os.path.join(directory, fname))
    return files


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("🎛️   NERDSEQ SAMPLE PREPARER")
    print("=" * 70)
    print("Converts audio into NerdSEQ-ready samples (WAV 8/16-bit or RAW 8-bit).")
    print(f"Sample memory is ~{MEM_TOTAL_BYTES/1024:.0f} kB shared across {NUM_SLOTS} slots.")
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

    audio_files = scan_audio_files(input_dir)
    if not audio_files:
        print(f"\n❌ No audio files found in: {input_dir}")
        print(f"   Supported inputs: {', '.join(INPUT_EXTS)}")
        return

    labels = []
    for f in audio_files:
        size_mb = os.path.getsize(f) / (1024 ** 2)
        labels.append(f"{os.path.basename(f)}  ({size_mb:.1f} MB)")

    print(f"\n✓ Found {len(audio_files)} audio file(s).")
    choices = get_multiple_choices("Select file(s) to prepare:", labels)
    selected = [audio_files[i - 1] for i in choices]

    # ── Step 2: format ────────────────────────────────────────────────────────
    print("\n🎚️  Step 2: Output Format")
    print("-" * 70)
    fmt_choice = get_user_choice("Choose sample format:", [
        "WAV 16-bit  — best quality (2 bytes/sample)",
        "WAV 8-bit   — half the memory, lo-fi grit (1 byte/sample)",
        "RAW 8-bit unsigned — headerless, mono only (1 byte/sample)",
    ], default=1)
    fmt = {1: FMT_WAV16, 2: FMT_WAV8, 3: FMT_RAW8}[fmt_choice]

    # ── Step 3: channels ──────────────────────────────────────────────────────
    if fmt == FMT_RAW8:
        channels = 'mono'
        print("\n🔊 RAW format is mono-only → channels forced to MONO.")
    else:
        print("\n🔊 Step 3: Channels")
        print("-" * 70)
        ch_choice = get_user_choice("Channel layout:", [
            "Mono — halves memory (recommended)",
            "Stereo — keeps stereo image, 2× memory",
            "Keep original — mono stays mono, stereo stays stereo",
        ], default=1)
        channels = {1: 'mono', 2: 'stereo', 3: 'keep'}[ch_choice]

    # ── Step 4: sample rate ───────────────────────────────────────────────────
    print("\n🎯 Step 4: Sample Rate")
    print("-" * 70)
    print(f"The NerdSEQ does not resample on load; {REFERENCE_SR} Hz is the manual's reference.")
    target_sr = ask("Target sample rate (Hz)", default=REFERENCE_SR, cast=int)

    # ── Step 5: normalize ─────────────────────────────────────────────────────
    print("\n📊 Step 5: Normalize")
    print("-" * 70)
    normalize = input("Peak-normalize each sample to -0.1 dB? [y/N]: ").strip().lower() in ('y', 'yes')

    # ── Step 6: output subfolder ──────────────────────────────────────────────
    print("\n📂 Step 6: Output Subfolder")
    print("-" * 70)
    print("Each run is saved in its own subfolder inside output/nerdseq/.")
    from datetime import datetime
    default_subfolder = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    subfolder = ask("Subfolder name", default=default_subfolder)
    subfolder = sanitize_name(subfolder)

    # ── Summary ───────────────────────────────────────────────────────────────
    output_dir = os.path.join(project_root, 'output', 'nerdseq', subfolder)
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print(f"  Files:       {len(selected)}")
    print(f"  Format:      {FORMAT_INFO[fmt]['label']}")
    print(f"  Channels:    {channels}")
    print(f"  Sample rate: {target_sr} Hz")
    print(f"  Normalize:   {'yes' if normalize else 'no'}")
    print(f"  Output:      {output_dir}")
    print("=" * 70)

    if input("\nProceed? [Y/n]: ").strip().lower() not in ('', 'y', 'yes'):
        print("❌ Cancelled")
        return

    # ── Convert ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("⚙️  PROCESSING")
    print("=" * 70)

    results = []
    for in_path in selected:
        r = convert_file(in_path, output_dir, fmt, channels, target_sr, normalize)
        if r:
            results.append(r)

    # ── Results & memory report ───────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("📊 RESULTS")
    print("=" * 70)
    print(f"  Converted: {len(results)}/{len(selected)}")
    print(f"  Output:    {output_dir}")

    if results:
        total_bytes = sum(r['bytes'] for r in results)
        oversized   = [r for r in results if r['too_big']]
        print(f"\n  Memory budget: {MEM_TOTAL_BYTES/1024:.0f} kB total "
              f"(shared across {NUM_SLOTS} slots)")
        print(f"  Combined size of these {len(results)} sample(s): "
              f"{total_bytes/1024:.1f} kB")

        if total_bytes > MEM_TOTAL_BYTES:
            print(f"  ⚠️  The full set won't fit in memory at once — load a subset,")
            print(f"      or shorten/downgrade some samples.")
        else:
            print(f"  ✓ The full set fits within memory.")

        if oversized:
            print(f"\n  ⚠️  {len(oversized)} sample(s) individually exceed the full "
                  f"{MEM_TOTAL_BYTES/1024:.0f} kB memory and will not load as-is:")
            for r in oversized:
                print(f"       • {os.path.basename(r['out'])} "
                      f"({r['bytes']/1024:.1f} kB, {r['duration_s']:.2f}s)")
            print(f"      Tip: trim them, use 8-bit, mono, or a lower sample rate.")

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
