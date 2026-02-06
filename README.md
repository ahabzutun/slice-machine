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
3. Create a Variable Speed Player
4. Assign the sample
5. Slices appear automatically! 🎉

## The .slc Format

We reverse-engineered the ER-301's binary .slc format:

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
