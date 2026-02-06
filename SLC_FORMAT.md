# ER-301 .SLC File Format Specification

**Version:** 7
**Reverse-engineered:** February 2026

## Overview

The `.slc` (slice) file format stores sample slice positions for the Orthogonal Devices ER-301 eurorack module. When a `.wav` and `.slc` file with matching names are present, the ER-301 automatically loads the slice positions.

## File Structure

```
┌─────────────────────────────────────┐
│  Header (40 bytes)                  │
├─────────────────────────────────────┤
│  Slice Entry 0 (16 bytes)           │
├─────────────────────────────────────┤
│  Slice Entry 1 (16 bytes)           │
├─────────────────────────────────────┤
│  ...                                │
├─────────────────────────────────────┤
│  Slice Entry N-1 (16 bytes)         │
└─────────────────────────────────────┘
```

**Total Size:** `40 + (N × 16)` bytes, where N = number of slices

## Header Format (40 bytes)

| Offset | Size | Type    | Value         | Description                    |
|--------|------|---------|---------------|--------------------------------|
| 0      | 4    | uint32  | 0xABCDDCBA    | Magic number (little-endian)   |
| 4      | 4    | uint32  | 7             | Format version                 |
| 8      | 6    | char[6] | "Slices"      | ASCII marker                   |
| 14     | 9    | byte[9] | 0x00...       | Padding (all zeros)            |
| 23     | 1    | uint8   | N             | Number of slices               |
| 24     | 16   | byte[16]| 0x00...       | Padding (all zeros)            |

**Header in C:**
```c
struct SLCHeader {
    uint32_t magic;        // 0xABCDDCBA
    uint32_t version;      // 7
    char marker[6];        // "Slices"
    uint8_t padding1[9];   // zeros
    uint8_t slice_count;   // N
    uint8_t padding2[16];  // zeros
} __attribute__((packed));
```

## Slice Entry Format (16 bytes)

| Offset | Size | Type     | Description                              |
|--------|------|----------|------------------------------------------|
| 0      | 4    | byte[4]  | Pattern: `00 80 3F XX`                   |
| 4      | 2    | uint16   | Sample position ÷ 256 (little-endian)   |
| 6      | 10   | byte[10] | Padding (all zeros)                      |

**Notes:**
- The 4th byte (XX) alternates: `0x80` for even slices, `0x00` for odd slices
- Sample positions are stored divided by 256 for compression
- To get actual sample position: `position = uint16_value × 256`

**Slice Entry in C:**
```c
struct SLCSlice {
    uint8_t pattern[3];    // 00 80 3F
    uint8_t alternating;   // 0x80 (even) or 0x00 (odd)
    uint16_t position;     // sample_pos / 256
    uint8_t padding[10];   // zeros
} __attribute__((packed));
```

## Example

For a file with 4 slices at sample positions 0, 48000, 96000, 144000:

**Hex Dump:**
```
Offset  00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F  ASCII
------  -----------------------------------------------  ----------------
0x0000  BA DC CD AB 07 00 00 00 53 6C 69 63 65 73 00 00  ....Slices..
0x0010  00 00 00 00 00 00 00 04 00 00 00 00 00 00 00 00  ................
0x0020  00 00 00 00 00 00 00 00 00 80 3F 80 00 00 00 00  ..........?.....
0x0030  00 00 00 00 00 00 00 00 00 80 3F 00 BB 00 00 00  ..........?.....
0x0040  00 00 00 00 00 00 00 00 00 80 3F 80 77 01 00 00  ..........?.w...
0x0050  00 00 00 00 00 00 00 00 00 80 3F 00 32 02 00 00  ..........?.2...
0x0060  00 00 00 00 00 00 00 00                          ........
```

**Decoded Slices:**
- Slice 0: position = 0 × 256 = 0 samples (0.00s @ 48kHz)
- Slice 1: position = 187 × 256 = 47,872 samples (0.997s @ 48kHz)
- Slice 2: position = 375 × 256 = 96,000 samples (2.00s @ 48kHz)
- Slice 3: position = 562 × 256 = 143,872 samples (2.997s @ 48kHz)

## Python Implementation

```python
import struct

def write_slc_file(output_path, slice_positions):
    """Generate a .slc file from sample positions"""

    data = bytearray()

    # Header
    data.extend(struct.pack('<I', 0xABCDDCBA))  # Magic
    data.extend(struct.pack('<I', 7))            # Version
    data.extend(b'Slices')                       # Marker
    data.extend(b'\x00' * 9)                     # Padding
    data.extend(struct.pack('B', len(slice_positions)))  # Count
    data.extend(b'\x00' * 16)                    # Padding

    # Slice entries
    for i, pos in enumerate(slice_positions):
        pattern_byte = 0x80 if i % 2 == 0 else 0x00
        data.extend(bytes([0x00, 0x80, 0x3F, pattern_byte]))
        data.extend(struct.pack('<H', int(pos / 256)))
        data.extend(b'\x00' * 10)

    with open(output_path, 'wb') as f:
        f.write(data)
```

## Limitations

- **Maximum slices:** 255 (uint8 slice count)
- **Maximum sample position:** 16,776,960 (65535 × 256)
  - At 48kHz: ~349 seconds / ~5.8 minutes
  - At 96kHz: ~174 seconds / ~2.9 minutes
- **Position resolution:** 256 samples
  - At 48kHz: ~5.3ms granularity
  - At 96kHz: ~2.7ms granularity

## Notes

- The alternating pattern byte (0x80/0x00) may encode additional information, but slices work without interpreting it
- Files appear to sometimes be incomplete (missing final bytes) but still function
- The ER-301 also supports reading WAV cue markers as an alternative to .slc files (firmware v0.6.00+), though this feature appears unreliable

## Reverse Engineering Process

This specification was discovered by:
1. Creating sample chains manually on the ER-301
2. Extracting the generated .slc files
3. Analyzing known sample positions vs. binary data
4. Testing hypothesis with generated files
5. Verifying on actual hardware

## Related Resources

- [ER-301 Firmware](https://github.com/odevices/er-301)
- [Orthogonal Devices Forum](https://forum.orthogonaldevices.com/)

---

**Last Updated:** February 2026
**Specification Version:** 1.0
