#!/usr/bin/env python3
"""
Flexible slicer that works with any audio file
Usage: python slice_any_file.py <input_file> [output_name]
"""

import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from audio_slicer import AudioSlicer

def main():
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: python slice_any_file.py <input_file> [output_name]")
        print("\nExample:")
        print("  python slice_any_file.py ../input/song.mp3 song")
        return

    input_file = sys.argv[1]

    # Get output name from argument or derive from filename
    if len(sys.argv) >= 3:
        output_name = sys.argv[2]
    else:
        # Use the input filename without extension
        output_name = os.path.splitext(os.path.basename(input_file))[0]
        # Clean up the name (remove spaces, special chars)
        output_name = output_name.replace(' ', '_').replace("'", '').lower()

    print("=" * 60)
    print("ER-301 Slice Generator")
    print("=" * 60)
    print(f"Input:  {input_file}")
    print(f"Output: {output_name}")
    print("=" * 60)

    # Check if file exists
    if not os.path.exists(input_file):
        print(f"\n❌ ERROR: File not found: {input_file}")
        return

    # Create the slicer
    slicer = AudioSlicer(target_slices=128, sr=48000)

    # Load the audio file
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

    output_path = slicer.export_slices(
        slices,
        output_dir=output_dir,
        prefix=output_name,
        export_mode='chain'
    )

    print("\n" + "=" * 60)
    print(f"Summary")
    print("=" * 60)
    print(f"Total slices: {len(slices)}")
    print(f"Organized into: {len(groups)} groups of 8")

    # Statistics
    lengths = [s['length'] for s in slices]
    durations = [s['duration_ms'] for s in slices]

    print(f"\nSlice Statistics:")
    print(f"  Shortest: {min(lengths)} samples ({min(durations):.2f}ms)")
    print(f"  Longest:  {max(lengths)} samples ({max(durations):.2f}ms)")
    print(f"  Average:  {sum(lengths)//len(lengths)} samples ({sum(durations)/len(durations):.2f}ms)")

    # Show group info
    print(f"\nGroup Duration Ranges:")
    for i, group in enumerate(groups):
        avg_duration = sum(s['duration_ms'] for s in group) / len(group)
        print(f"  Group {i+1:2d}: {avg_duration:7.2f}ms average")

    print(f"\n🎉 Success! Your sample chain is ready:")
    print(f"   {output_path}")
    print(f"\nTo use in ER-301:")
    print(f"   1. Copy {os.path.basename(output_path)} to your SD card")
    print(f"   2. Load it into a Sample Player unit")
    print(f"   3. (Soon) Use the .slc file for automatic slicing!")

if __name__ == '__main__':
    main()
