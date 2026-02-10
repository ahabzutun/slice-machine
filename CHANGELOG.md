# Changelog

All notable changes to Slice Machine will be documented in this file.

## [1.1.0] - 2026-02-10

### 🎵 Configurable Slice Length Modes

Major feature addition allowing users to choose slice length based on content type!

### Added
- **Three slice length modes:**
  - **PERCUSSIVE** (default): 30-80ms slices for drums/percussion
  - **HYBRID**: 100-300ms slices for mixed content
  - **MELODIC**: 200-600ms slices for melodic/harmonic content
- **Intelligent duration filtering:**
  - Removes slices below minimum duration threshold
  - Prevents unusably short slices in final output
  - Debug info for rejected slices
- **Smart subdivision respecting minimums:**
  - Won't create slices below minimum duration
  - Graceful handling when target count can't be reached
  - Clear user feedback when limits hit
- **Mode-specific onset detection:**
  - Configurable hop_length for each mode
  - More sensitive for percussive content
  - Less sensitive for melodic content
  - Better slice boundaries for each content type
- **Enhanced UI with mode selection:**
  - New Step 3a for choosing slice mode
  - Clear descriptions of each mode
  - Visual feedback of selected parameters
- **Updated summary and results:**
  - Shows selected slice mode
  - Displays min/target durations
  - Confirms hop_length setting

### Technical Implementation
- New `SLICE_MODES` configuration dictionary
- New `filter_slices_by_duration()` function
- Updated `force_target_slices()` with min_duration_ms parameter
- Mode-specific onset detection with configurable hop_length
- Maintains backward compatibility (percussive mode is default)

### Benefits
- Better results for different audio types
- User control over slice characteristics
- Quality assurance through minimum durations
- Intelligent subdivision respecting musical boundaries
- Flexibility for various use cases

### Documentation
- Added SLICE_LENGTH_FEATURE.md with complete documentation
- Updated README (pending)
- In-code comments explaining new functionality

---

## [1.0.0] - 2026-02-06

### 🎉 Initial Release

The first working version with full .slc format support!

### Added
- **Core audio slicing engine** with librosa onset detection
- **Intelligent slice reduction** to exactly 128 slices
  - Even distribution method (default)
  - Energy-based selection
  - Duration-based selection
- **Smart grouping** into 16 groups of 8 slices
  - Similarity-based grouping using spectral features (default)
  - Duration-based grouping
  - Sequential grouping
- **Native .slc file generation** for ER-301
  - Reverse-engineered binary format
  - Verified working on hardware
- **Three usage modes:**
  - Single file processing
  - Batch processing
  - Multi-file combination
- **Comprehensive examples** with CLI scripts
- **Full documentation** including format specification

### Technical Details
- Sample rate: 48kHz
- Output format: 16-bit mono WAV
- Slice count: Always 128
- Groups: 16 groups of 8 slices

### Format Discovery
Successfully reverse-engineered the ER-301 .slc format:
- Header: 40 bytes
- Per-slice: 16 bytes
- Position encoding: sample_position ÷ 256 stored as uint16
- Verified through hardware testing

### Known Issues
- WAV cue markers are not read by ER-301 (despite firmware support)
  - Workaround: Use native .slc files instead
- Spectral analysis warnings for very short slices (< 2048 samples)
  - Does not affect functionality

---

## Development Notes

### Reverse Engineering Process
1. Created test audio with known slice positions
2. Manually sliced on ER-301 hardware
3. Extracted and analyzed generated .slc files
4. Identified position encoding pattern
5. Implemented and verified generator
6. Confirmed working on actual hardware

### Contributors
- Format reverse engineering and implementation
- Core audio processing
- Documentation and examples

---

**Format:** [Keep a Changelog](https://keepachangelog.com/)
**Versioning:** [Semantic Versioning](https://semver.org/)
