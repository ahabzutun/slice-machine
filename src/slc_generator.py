"""
ER-301 .SLC Generator - FINAL VERSION
Based on reverse-engineered format from actual ER-301 files
"""

import struct
import os

class SLCGenerator:
    """
    Generate .slc files in the exact format the ER-301 expects

    Format discovered through reverse engineering:
    - Header: 40 bytes
    - Each slice: 16 bytes
      - Bytes 0-3: Pattern (00 80 3f XX)
      - Bytes 4-5: uint16 = sample_position / 256
      - Bytes 6-15: All zeros
    """

    def __init__(self):
        self.magic = 0xABCDDCBA
        self.version = 7
        self.marker = b'Slices'

    def generate_from_slice_list(self, output_path, slice_positions, num_slices=None):
        """
        Generate a .slc file from a list of sample positions

        Args:
            output_path: Path where to save the .slc file
            slice_positions: List of sample positions (start of each slice)
            num_slices: Override slice count (useful for incomplete files)

        Returns:
            Path to the generated .slc file
        """

        if num_slices is None:
            num_slices = len(slice_positions)

        print(f"\n📄 Generating .slc file: {output_path}")
        print(f"   Slices: {num_slices}")

        # Build the file
        data = bytearray()

        # HEADER (40 bytes)
        data.extend(struct.pack('<I', self.magic))       # Magic: 0xABCDDCBA
        data.extend(struct.pack('<I', self.version))     # Version: 7
        data.extend(self.marker)                         # "Slices"
        data.extend(b'\x00' * 9)                         # Padding
        data.extend(struct.pack('B', num_slices))        # Slice count at byte 23
        data.extend(b'\x00' * 16)                        # Padding to 40 bytes

        # SLICE DATA (16 bytes per slice)
        for i, pos in enumerate(slice_positions):
            # Bytes 0-3: Pattern "00 80 3f XX"
            # XX alternates: 80, 00, 80, 00...
            pattern_byte = 0x80 if i % 2 == 0 else 0x00
            data.extend(bytes([0x00, 0x80, 0x3F, pattern_byte]))

            # Bytes 4-5: uint16 = sample_position / 256
            value = int(pos / 256)
            data.extend(struct.pack('<H', value))

            # Bytes 6-15: All zeros
            data.extend(b'\x00' * 10)

        # Write the file
        with open(output_path, 'wb') as f:
            f.write(data)

        file_size = os.path.getsize(output_path)
        expected_size = 40 + (len(slice_positions) * 16)

        print(f"✓ Generated {output_path}")
        print(f"   File size: {file_size} bytes")
        print(f"   Expected: {expected_size} bytes")

        return output_path

    def generate_from_audio_file(self, wav_path, slice_data, total_samples):
        """
        Generate a .slc file for a WAV file

        Args:
            wav_path: Path to the WAV file
            slice_data: List of dicts with 'start' key (sample positions)
            total_samples: Total samples in the audio file

        Returns:
            Path to the generated .slc file
        """

        slc_path = wav_path.replace('.wav', '.slc')

        # Extract sample positions
        slice_positions = [s['start'] for s in slice_data]

        return self.generate_from_slice_list(slc_path, slice_positions)


if __name__ == '__main__':
    print("ER-301 .SLC Generator - Ready!")
    print("Format: 16 bytes per slice")
    print("  Bytes 0-3: Pattern (00 80 3f XX)")
    print("  Bytes 4-5: uint16 = sample_position / 256")
    print("  Bytes 6-15: Zeros")
