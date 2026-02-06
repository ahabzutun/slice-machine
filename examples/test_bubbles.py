#!/usr/bin/env python3
"""
Test script to try out the AudioSlicer with BUBBLES.wav
"""

import sys
import os

# Add the src directory to the path so we can import our module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from audio_slicer import AudioSlicer

def main():
    print("=" * 60)
    print("Testing AudioSlicer with BUBBLES.wav")
    print("=" * 60)

    # Create the slicer
    slicer = AudioSlicer(target_slices=128, sr=48000)

    # Load the audio file
    input_file = os.path.join(os.path.dirname(__file__), '..', 'input', 'BUBBLES.wav')

    slicer.load_audio(input_file)

    # Detect onsets
    slicer.detect_onsets(method='energy')

    # Adjust to exactly 128 slices
    slices = slicer.adjust_to_target_slices(method='even')

    # Organize into groups of 8
    groups = slicer.organize_into_groups(slices, method='similarity')

    # Export with absolute path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_dir = os.path.join(project_root, 'output')

    print(f"\n📁 Output directory: {output_dir}")

    output_path = slicer.export_slices(
        slices,
        output_dir=output_dir,
        prefix='bubbles',
        export_mode='chain'
    )

    print("\n" + "=" * 60)
    print(f"Slice Analysis Results")
    print("=" * 60)
    print(f"Total slices: {len(slices)}")
    print(f"Organized into: {len(groups)} groups of 8")

    print("\n" + "=" * 60)
    print(f"Slice Analysis Results")
    print("=" * 60)
    print(f"Total slices detected: {len(slices)}")

    # Show first 10 slices
    print("\nFirst 10 slices:")
    for slice_info in slices[:10]:
        print(f"  Slice {slice_info['index']:3d}: "
              f"start={slice_info['start']:8d} samples, "
              f"length={slice_info['length']:8d} samples, "
              f"duration={slice_info['duration_ms']:7.2f}ms")

    if len(slices) > 10:
        print(f"\n  ... and {len(slices) - 10} more slices")

    # Statistics
    lengths = [s['length'] for s in slices]
    print(f"\nStatistics:")
    print(f"  Shortest slice: {min(lengths)} samples ({min(lengths)/48000*1000:.2f}ms)")
    print(f"  Longest slice: {max(lengths)} samples ({max(lengths)/48000*1000:.2f}ms)")
    print(f"  Average slice: {sum(lengths)//len(lengths)} samples ({sum(lengths)/len(lengths)/48000*1000:.2f}ms)")

if __name__ == '__main__':
    main()
