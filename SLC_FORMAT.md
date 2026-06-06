# ER-301 .SLC File Format Specification

**Specification version:** 2.0
**Last updated:** June 2026

## Overview

The `.slc` file stores slice (cue) positions for the Orthogonal Devices ER-301
eurorack module. When a `.wav` and `.slc` with matching stems are present in the
same directory, the ER-301 automatically loads the slice positions from the `.slc`.

The format supports an arbitrary number of slices (confirmed working with 1024+
on firmware 0.6.16). The slice count is encoded in the header, so the ER-301
knows exactly how many entries to read.

---

## File Structure

```
┌──────────────────────────────────┐
│  Header  (27 bytes)              │
├──────────────────────────────────┤
│  Slice Entry 0  (16 bytes)       │
│  Slice Entry 1  (16 bytes)       │
│  ...                             │
│  Slice Entry N-1  (16 bytes)     │
└──────────────────────────────────┘
```

**Total size:** `27 + (N × 16)` bytes

---

## Header (27 bytes)

| Offset | Size | Type      | Value      | Description                  |
|--------|------|-----------|------------|------------------------------|
| 0      | 4    | uint32 LE | 0xABCDDCBA | Magic number                 |
| 4      | 4    | uint32 LE | 7          | Format version               |
| 8      | 6    | char[6]   | "Slices"   | ASCII label                  |
| 14     | 9    | byte[9]   | 0x00…      | Null padding                 |
| 23     | 4    | uint32 LE | N          | **Slice count**              |

> **Note on byte 23:** Early reverse-engineering mistook this field for an
> "unknown constant 0x80" because all reference files happened to have 128
> slices (0x80 = 128). It is actually a **uint32 LE slice count** spanning
> bytes 23–26. Hardware files with 128 slices read as `80 00 00 00` = 128.
> Writing the wrong value here causes the ER-301 to load only that many
> entries regardless of how many are present in the file.

**Header bytes (128-slice example):**
```
BA DC CD AB  07 00 00 00  53 6C 69 63  65 73 00 00
00 00 00 00  00 00 00 00  80 00 00 00
^magic       ^version     ^"Slices"   ^padding     ^count=128
```

---

## Slice Entry (16 bytes each)

| Offset | Size | Type      | Description            |
|--------|------|-----------|------------------------|
| 0      | 4    | uint32 LE | Sample position        |
| 4      | 4    | float32   | 0.0 (constant)         |
| 8      | 4    | float32   | 0.0 (constant)         |
| 12     | 4    | float32   | 1.0 (constant)         |

- **Sample position** is the full integer sample offset from the start of the
  paired `.wav` file — **not** divided by 256 or any other factor.
- The three float fields are always `0.0, 0.0, 1.0` in every observed file.
  Their meaning is unknown but they must be present.
- Entries must be in ascending order of sample position.

---

## Constraints

| Property              | Value                                      |
|-----------------------|--------------------------------------------|
| Magic                 | `0xABCDDCBA`                               |
| Version               | `7`                                        |
| Min slice count       | 1                                          |
| Max slice count       | >2000 (confirmed on firmware 0.6.16)       |
| Max sample position   | 4,294,967,295 (uint32 max, ~24h @ 48kHz)  |
| Position resolution   | 1 sample (exact)                           |

---

## Python Implementation

```python
import struct

SLC_MAGIC   = 0xABCDDCBA
SLC_VERSION = 7

def write_slc(path, positions):
    """
    Write an ER-301 .slc file.

    Args:
        path:      Output file path (e.g. 'chain.slc').
        positions: List of integer sample positions, ascending.
    """
    n = len(positions)
    with open(path, 'wb') as f:
        # Header (27 bytes)
        f.write(struct.pack('<I', SLC_MAGIC))    # magic
        f.write(struct.pack('<I', SLC_VERSION))  # version
        f.write(b'Slices')                       # label
        f.write(b'\x00' * 9)                     # padding
        f.write(struct.pack('<I', n))            # slice count

        # Entries (16 bytes each)
        for pos in positions:
            f.write(struct.pack('<I', pos))      # sample position
            f.write(struct.pack('<f', 0.0))
            f.write(struct.pack('<f', 0.0))
            f.write(struct.pack('<f', 1.0))


def read_slc(path):
    """
    Read slice positions from an ER-301 .slc file.

    Returns:
        List of integer sample positions.
    """
    with open(path, 'rb') as f:
        data = f.read()

    magic   = struct.unpack_from('<I', data, 0)[0]
    version = struct.unpack_from('<I', data, 4)[0]
    count   = struct.unpack_from('<I', data, 23)[0]

    assert magic   == SLC_MAGIC,   f"Bad magic: 0x{magic:08X}"
    assert version == SLC_VERSION, f"Unknown version: {version}"

    positions = []
    for i in range(count):
        offset = 27 + i * 16
        pos = struct.unpack_from('<I', data, offset)[0]
        positions.append(pos)

    return positions
```

---

## Reverse Engineering History

| Date          | Discovery                                                    |
|---------------|--------------------------------------------------------------|
| February 2026 | Initial format decoded: magic, version, label, entry layout  |
| February 2026 | Positions confirmed as full sample values (not ÷256)         |
| June 2026     | Byte 23 identified as uint32 LE slice count, not a constant  |

The byte-23 correction was discovered when a merged 1024-slice chain loaded
only 128 slices on hardware. Inspecting the header of a hardware-generated
128-slice file showed `0x80 0x00 0x00 0x00` at offset 23, which had previously
been misread as a one-byte constant `0x80`. Re-interpreting it as a uint32 LE
field storing the count (128 = 0x80) resolved the issue and confirmed that the
ER-301 uses this field to determine how many entries to read.

---

## Related Resources

- [ER-301 Firmware source](https://github.com/odevices/er-301)
- [Orthogonal Devices Forum](https://forum.orthogonaldevices.com/)
