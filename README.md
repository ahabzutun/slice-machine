# Slice Machine 🎵

**Intelligent audio slicer for the Orthogonal Devices ER-301 — with cross-device export for the NerdSEQ and the Percussa SSP (GRID).**

Slice audio into organized sample chains with accompanying `.slc` metadata, then reuse the exact same slices across multiple Eurorack samplers.

## Features

✨ **Intelligent Onset Detection** — Finds transients in your audio
🎯 **Forced Slice Count** — Exactly 128 (or any target) slices per chain
🥁 **Slice Length Modes** — Percussive / Hybrid / Melodic presets tune slice length to your material
🧠 **Similarity Grouping** — Reorganizes slices by spectral character (low→high or high→low)
🏦 **Bank Mode** — Organize 8 files into 8×16 slice banks for MIDI controllers
🔇 **Silence Removal** — Strips dead air after slicing
🎛️ **CDP Integration** — Optional SoundThread pre/post processing
📄 **Native `.slc` Support** — Generates ER-301-compatible slice metadata
🎛️ **GRID `.kit` Export** — Same slices, ready for the Percussa SSP GRID plugin (produced automatically)
🔗 **Chain Merger** — Combine pre-sliced chains into one
✂️ **Chain Splitter** — Explode a chain back into individual slice files
🎚️ **NerdSEQ Preparer** — Convert any audio into NerdSEQ-ready samples

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/ahabzutun/slice-machine.git
cd slice-machine

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

Place your audio in `input/` and run any of the tools below. Generated files land in `output/`.

## Tools

All tools are interactive — run them and follow the prompts.

### Slicer — `src/interactive_slicer.py`

The main tool. Detects onsets, forces an exact slice count, optionally reorganizes,
removes silence, and exports a sample chain.

```bash
venv/bin/python3 src/interactive_slicer.py
```

Each export produces three files in one pass, sharing the same audio and the same cut points:

- `<name>_chain.wav` — the concatenated slice chain
- `<name>_chain.slc` — ER-301 slice metadata (absolute sample positions)
- `<name>_chain.kit` — Percussa SSP GRID kit (normalized `[0,1]` slice pairs)

Slice length modes let you match the cut length to the material:

| Mode | Min | Target | Best for |
|------|-----|--------|----------|
| Percussive | 30 ms | 80 ms | Drums, percussion |
| Hybrid | 100 ms | 300 ms | Mixed content |
| Melodic | 200 ms | 600 ms | Melodic / harmonic phrases |

### Chain Merger — `src/merge_chains.py`

Combine multiple pre-sliced chains (`.wav` + `.slc` pairs) into one, preserving
existing slice positions. Empty slots are filled with silence carrying evenly
spaced placeholder markers.

```bash
venv/bin/python3 src/merge_chains.py
```

### Chain Splitter — `src/split_chain.py`

The inverse of the merger: cut a chain at its slice markers and write every slice
as its own file into `output/<chainname>/<chainname>_slice_001.wav`, etc.

```bash
venv/bin/python3 src/split_chain.py
```

### NerdSEQ Preparer — `src/prepare_nerdseq.py`

Convert any input audio into samples ready for the XOR Electronics NerdSEQ. Choose
format (WAV 16-bit, WAV 8-bit, or RAW 8-bit unsigned), channels (mono/stereo/keep),
and sample rate. Reports the memory each sample uses against the NerdSEQ's ~190 kB
budget. Output goes to `output/nerdseq/<subfolder>/`.

```bash
venv/bin/python3 src/prepare_nerdseq.py
```

### Chain → GRID Kit — `src/chain_to_grid_kit.py`

Generate a GRID `.kit` from an existing `.wav` + `.slc` pair (useful for chains made
before kit export was built into the slicer). The chain `.wav` is untouched and
shared; only the `.kit` sidecar is added. Output goes to `output/grid/`.

```bash
venv/bin/python3 src/chain_to_grid_kit.py
```

## Using the Output

### ER-301 (Orthogonal Devices)

1. Copy the `.wav` and `.slc` to your SD card.
2. Load the WAV into the Sample Pool (Admin mode).
3. Create a Variable Speed Player and assign the sample — slices appear automatically.

### Percussa SSP (GRID plugin)

1. Copy the chain `.wav` to `/media/BOOT/samples/`.
2. Copy the `.kit` to `/media/BOOT/samples/kits/`.
3. Load the kit in GRID — the pad shows the chain with all its slices.

GRID stores slices as normalized `[0,1]` start/end pairs inside a plain-XML `.kit`
(root `<GRID_KIT>`, one `<PAD>` per pad). Slice Machine converts the ER-301's
absolute sample positions with `normalized = position / total_samples`, each slice
running from its marker to the next — the same boundary logic as the `.slc`.

### NerdSEQ (XOR Electronics)

Use `prepare_nerdseq.py` to produce WAV 8/16-bit or RAW 8-bit unsigned files, then
copy them to the SD card's samples folder and load them into a sample slot. Sample
memory is ~190 kB shared across all 12 slots, so keep individual samples short.

## The .slc Format

The ER-301's binary `.slc` format:

**Header (27 bytes):**
- Bytes 0–3: Magic `0xABCDDCBA` (uint32 LE)
- Bytes 4–7: Version `7` (uint32 LE)
- Bytes 8–13: Label `"Slices"`
- Bytes 14–22: Null padding
- Bytes 23–26: Slice count (uint32 LE)

**Per-Slice Entry (16 bytes):**
- Bytes 0–3: Sample position (uint32 LE)
- Bytes 4–7: Float `0.0`
- Bytes 8–11: Float `0.0`
- Bytes 12–15: Float `1.0`

## Project Structure

```
slice-machine/
├── src/
│   ├── interactive_slicer.py   # Main slicer (onsets, forcing, banks, CDP, exports)
│   ├── merge_chains.py         # Combine pre-sliced chains into one
│   ├── split_chain.py          # Explode a chain into individual slice files
│   ├── prepare_nerdseq.py      # Convert audio into NerdSEQ-ready samples
│   ├── chain_to_grid_kit.py    # Generate a Percussa SSP GRID .kit from a chain
│   └── cdp_processor.py        # CDP SoundThread integration
├── input/                       # Place audio files here
├── output/                      # Generated chains appear here
└── requirements.txt
```

## Requirements

- Python 3.7+
- librosa
- numpy
- soundfile
- scipy

## Credits

Developed through reverse engineering the ER-301's binary format.

Special thanks to:
- Orthogonal Devices for the ER-301
- XOR Electronics for the NerdSEQ
- Andy Kuttor ([@kuttor](https://github.com/kuttor)) for the Percussa SSP GRID plugin
- The Eurorack sampling community for inspiration

## License

MIT License — See LICENSE file for details

## Contributing

Pull requests welcome! Found a bug? Open an issue.

---

**Made with ❤️ for the Eurorack community**
