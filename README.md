# Slice Machine 🎵

**Intelligent audio slicer for the Orthogonal Devices ER-301**

Automatically slice audio files into 128 organized slices with accompanying .slc metadata files for seamless ER-301 integration.

## Features

✨ **Intelligent Onset Detection** - Automatically finds transients in your audio
🎯 **128-Slice Organization** - Perfectly sized for ER-301 sample chains
🧠 **Similarity Grouping** - Groups similar slices together (16 groups of 8)
📄 **Native .slc Support** - Generates ER-301-compatible slice metadata
⚡ **Batch Processing** - Process multiple files at once
🔗 **File Combining** - Merge multiple sources into one chain

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/slice-machine.git
cd slice-machine

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

**Slice a single file:**
```bash
python3 examples/slice_any_file.py "input/audio.wav" output_name
```

**Batch process multiple files:**
```bash
python3 examples/batch_slice.py input/*.wav
```

**Combine multiple files into one chain:**
```bash
python3 examples/combine_files.py "drums.wav" "bass.wav" "combined"
```

## Desktop App

All tools (and junglize) also come as one desktop app for **macOS** and **Linux** (Python + Qt / PySide6), with the
same look as [Kontrolleur](https://github.com/ahabzutun/dualsense-eurorack-midi): same appearance
presets, fonts and layout. A tab per tool, the settings in the side panel, and the audio on the stage:

- **Slicer** — tick files (or drop them onto the window), set slices / length mode / order / silence /
  processing / CDP, press **Preview** to see the cuts on the waveform, **Slice** to write
  `.wav` + `.slc` + `.kit`. Click any slice to hear it (Space plays it again, Esc stops).
  Bank mode draws the 8 banks.
- **Junglize** — `src/junglize.py` as a form: pick any audio, set tempo, bars, mode, feel and cuts; **Roll** makes and plays
  a break with a new seed, **Junglize** writes that exact break as `.wav` + `.slc` + `.kit`. The source's hits are shown
  coloured by class (kick / snare / hat / other), the break on its bar grid, and the matching terminal command is shown too.
- **Merge** — chains into slots (empty slots = silence with evenly spaced markers), drawn slot by slot.
- **Split** — a chain into one `.wav` per slice, with the file names it will write.
- **NerdSEQ** — the ~190 kB sample memory as a bar, filled live as you tick files or change the format.
- **GRID kit** — the SSP's 8 pads; click the one that should hold the chain.

Everything the tools print is in the **Log** drawer. Settings are kept between starts.

```bash
./install-mac.sh      # macOS: venv + ~/Applications/Slice Machine.app
./install-linux.sh    # Linux: venv + `slicemachine` launcher + menu entry
# or straight from the checkout, with PySide6-Essentials installed:
venv/bin/pip install -r requirements-app.txt && venv/bin/python3 slicemachine.py
```

Listening to slices uses the system player (`afplay` on macOS; `pw-play`, `paplay` or `aplay` on Linux).
On its first start the app takes over Kontrolleur's current look if Kontrolleur is installed (and
**Look → Same as Kontrolleur** does it again later). `theme.py`, `widgets.py`, `stage.py` and `draw.py` in
`slicemachine/` are copies of Kontrolleur's: `scripts/sync-look.sh` copies them over again after they change there.

For checking the UI without a screen: `QT_QPA_PLATFORM=offscreen SLICEMACHINE_SNAPSHOT=out.png`
(+ `SLICEMACHINE_MODE`, `_TAB`, `_SIZE`, `KONTROLLEUR_PRESET`) renders the window to a PNG and quits;
`SLICEMACHINE_INPUT` / `SLICEMACHINE_OUTPUT` set the default folders.

## How It Works

1. **Load Audio** - Reads any audio format (WAV, MP3, FLAC, etc.)
2. **Detect Onsets** - Finds transients using energy-based detection
3. **Select 128 Slices** - Intelligently reduces to exactly 128 slices
4. **Group by Similarity** - Organizes into 16 groups using spectral analysis
5. **Export** - Creates WAV chain + .slc metadata file

### Grouping Methods

- `similarity` (default) - Groups by spectral features
- `duration` - Groups by slice length
- `sequential` - Groups in order

### Reduction Methods

- `even` (default) - Evenly distributed selection
- `energy` - Keeps loudest slices
- `duration` - Keeps longest slices

## Output Files

For each input, you get:

- `output_name_chain.wav` - 128 slices concatenated
- `output_name_chain.slc` - ER-301 slice metadata

## Using with ER-301

1. Copy both `.wav` and `.slc` files to your SD card
2. Load the WAV into the Sample Pool (Admin mode)
3. Load a unit that uses samples
4. Assign the sample from the sample pool
5. Slices appear automatically

## The .slc Format

I reverse-engineered the ER-301's binary .slc format:

**Header (40 bytes):**
- Magic: `0xABCDDCBA`
- Version: `7`
- Marker: `"Slices"`
- Slice count at byte 23

**Per-Slice Entry (16 bytes):**
- Bytes 0-3: Pattern `00 80 3f XX`
- Bytes 4-5: `uint16` = sample_position ÷ 256
- Bytes 6-15: Zeros

See [docs/SLC_FORMAT.md](docs/SLC_FORMAT.md) for full specification.

## Project Structure

```
slice-machine/
├── src/
│   ├── audio_slicer.py      # Core slicing engine
│   ├── slc_generator.py     # .slc file writer
│   └── utils.py             # Utilities
├── examples/
│   ├── slice_any_file.py    # Single file processor
│   ├── batch_slice.py       # Batch processor
│   └── combine_files.py     # Multi-file combiner
├── slicemachine/             # Desktop app (PySide6) — start with slicemachine.py
├── input/                    # Place audio files here
├── output/                   # Generated chains appear here
├── docs/
│   └── SLC_FORMAT.md        # Format specification
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
- The ER-301 community for inspiration

## License

MIT License - See LICENSE file for details

## Contributing

Pull requests welcome! Found a bug? Open an issue.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

---

**Made with ❤️ for the ER-301 community**
