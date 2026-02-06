#!/usr/bin/env python3
"""
Combine multiple audio files into a single 128-slice chain
Usage: python combine_files.py <file1> <file2> ... <output_name>
"""

import sys
import os
import numpy as np
from collections import Counter
import soundfile as sf

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from audio_slicer import AudioSlicer
from slc_generator import SLCGenerator

def main():
    if len(sys.argv) < 3:
        print("=" * 60)
        print("Combine Multiple Files into One Sample Chain")
        print("=" * 60)
        print("\nUsage:")
        print("  python combine_files.py <file1> <file2> [file3...] <output_name>")
        print("\nExample:")
        print('  python combine_files.py "input/drums.wav" "input/bass.wav" "mixed"')
        print("\nThis will:")
        print("  • Split 128 slices proportionally across all input files")
        print("  • Combine them into one sample chain")
        print("  • Organize into 16 groups of 8")
        return

    # Last argument is the output name
    output_name = sys.argv[-1]

    # Everything else is input files
    input_files = sys.argv[1:-1]

    # Validate files
    for f in input_files:
        if not os.path.exists(f):
            print(f"❌ File not found: {f}")
            return

    print("=" * 60)
    print("Combining Multiple Files into One Chain")
    print("=" * 60)
    print(f"Input files: {len(input_files)}")
    for i, f in enumerate(input_files, 1):
        print(f"  {i}. {os.path.basename(f)}")
    print(f"\nOutput name: {output_name}")
    print(f"Target: 128 slices total")
    print("=" * 60)

    # Calculate slices per file (distribute evenly)
    slices_per_file = 128 // len(input_files)
    remaining_slices = 128 % len(input_files)

    print(f"\nDistribution:")
    for i in range(len(input_files)):
        # Give extra slices to first files if there's a remainder
        file_slices = slices_per_file + (1 if i < remaining_slices else 0)
        print(f"  {os.path.basename(input_files[i])}: {file_slices} slices")

    # Process each file
    all_slices = []
    all_audio_segments = []
    cumulative_offset = 0

    for i, input_file in enumerate(input_files):
        print(f"\n--- Processing file {i+1}/{len(input_files)} ---")

        # Calculate slices for this file
        file_slices = slices_per_file + (1 if i < remaining_slices else 0)

        # Create slicer for this file
        slicer = AudioSlicer(target_slices=file_slices, sr=48000)
        slicer.load_audio(input_file)
        slicer.detect_onsets(method='energy')

        # Get exactly the right number of slices
        slices = slicer.adjust_to_target_slices(method='even')

        # Extract audio segments and adjust positions
        for slice_info in slices:
            audio_segment = slicer.audio[slice_info['start']:slice_info['end']]
            all_audio_segments.append(audio_segment)

            # Store slice info with adjusted positions for combined chain
            adjusted_slice = {
                'index': len(all_slices),
                'start': cumulative_offset,
                'end': cumulative_offset + len(audio_segment),
                'length': len(audio_segment),
                'duration_ms': (len(audio_segment) / 48000) * 1000,
                'source_file': os.path.basename(input_file)
            }
            all_slices.append(adjusted_slice)
            cumulative_offset += len(audio_segment)

        print(f"✓ Extracted {len(slices)} slices from {os.path.basename(input_file)}")

    # Combine all audio segments
    print(f"\n--- Combining {len(all_slices)} slices ---")
    combined_audio = np.concatenate(all_audio_segments)

    print(f"✓ Combined audio: {len(combined_audio)} samples ({len(combined_audio)/48000:.2f}s)")

    # Organize into groups of 8 (simplified - by source file first, then similarity)
    print(f"\n--- Organizing into groups ---")

    # Group by source file for easier navigation
    groups = []
    for i in range(0, len(all_slices), 8):
        group = all_slices[i:i+8]
        groups.append(group)

    print(f"✓ Created {len(groups)} groups of 8 slices")

    # Show group breakdown
    for i, group in enumerate(groups):
        sources = set(s['source_file'] for s in group)
        avg_dur = sum(s['duration_ms'] for s in group) / len(group)
        print(f"  Group {i+1:2d}: {avg_dur:6.2f}ms avg - sources: {', '.join(sources)}")

    # Export the combined chain
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_dir = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, f'{output_name}_combined_chain.wav')

    sf.write(output_path, combined_audio, 48000)

    # Generate .slc file
    print(f"\n--- Generating .slc file ---")
    slc_gen = SLCGenerator()
    slc_path = slc_gen.generate_from_audio_file(output_path, all_slices, len(combined_audio))


    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total slices: {len(all_slices)}")
    print(f"Total groups: {len(groups)}")
    print(f"Total duration: {len(combined_audio)/48000:.2f}s")

    # Statistics per source file
    print(f"\nSlices per source file:")
    source_counts = Counter(s['source_file'] for s in all_slices)
    for source, count in source_counts.items():
        print(f"  {source}: {count} slices")

    # Duration stats
    durations = [s['duration_ms'] for s in all_slices]
    print(f"\nSlice durations:")
    print(f"  Shortest: {min(durations):.2f}ms")
    print(f"  Longest:  {max(durations):.2f}ms")
    print(f"  Average:  {sum(durations)/len(durations):.2f}ms")

    print(f"\n🎉 Success! Combined chain saved:")
    print(f"   {output_path}")
    print(f"   {slc_path}")
    print(f"\nTo use in ER-301:")
    print(f"   1. Copy both .wav and .slc files to your SD card")
    print(f"   2. Load the .wav into a Sample Player unit")
    print(f"   3. Load the .slc file for automatic slice detection!")

if __name__ == '__main__':
    main()
