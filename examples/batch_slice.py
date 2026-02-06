#!/usr/bin/env python3
"""
Batch slicer - process multiple audio files at once!
Usage: python batch_slice.py <input_file1> <input_file2> ... [options]
       python batch_slice.py input/*.wav  (process all WAV files)
"""

import sys
import os
import glob

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from audio_slicer import AudioSlicer

def process_file(input_file, output_dir, options=None):
    """Process a single file"""

    # Get output name from filename
    output_name = os.path.splitext(os.path.basename(input_file))[0]
    # Clean up the name (remove spaces, special chars)
    output_name = output_name.replace(' ', '_').replace("'", '').replace(':', '').lower()

    print("\n" + "=" * 60)
    print(f"Processing: {os.path.basename(input_file)}")
    print("=" * 60)

    try:
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

        # Export
        output_path = slicer.export_slices(
            slices,
            output_dir=output_dir,
            prefix=output_name,
            export_mode='chain'
        )

        # Summary
        lengths = [s['length'] for s in slices]
        durations = [s['duration_ms'] for s in slices]

        print(f"\n✅ Success!")
        print(f"   Output: {os.path.basename(output_path)}")
        print(f"   Slices: {len(slices)} in {len(groups)} groups")
        print(f"   Range: {min(durations):.1f}ms - {max(durations):.1f}ms")

        return {
            'input': input_file,
            'output': output_path,
            'success': True,
            'slices': len(slices)
        }

    except Exception as e:
        print(f"\n❌ Error processing {os.path.basename(input_file)}: {e}")
        return {
            'input': input_file,
            'output': None,
            'success': False,
            'error': str(e)
        }

def main():
    if len(sys.argv) < 2:
        print("=" * 60)
        print("Batch Audio Slicer for ER-301")
        print("=" * 60)
        print("\nUsage:")
        print("  python batch_slice.py <file1> <file2> <file3> ...")
        print("  python batch_slice.py input/*.wav")
        print("  python batch_slice.py input/*.mp3")
        print("\nExamples:")
        print('  python batch_slice.py "/path/to/song1.mp3" "/path/to/song2.wav"')
        print("  python batch_slice.py ~/Music/*.wav")
        return

    # Collect all input files
    input_files = []
    for arg in sys.argv[1:]:
        # Expand wildcards
        expanded = glob.glob(arg)
        if expanded:
            input_files.extend(expanded)
        else:
            # Not a wildcard, add as-is if it exists
            if os.path.exists(arg):
                input_files.append(arg)
            else:
                print(f"⚠️  Warning: File not found: {arg}")

    if not input_files:
        print("❌ No valid input files found!")
        return

    # Remove duplicates and sort
    input_files = sorted(list(set(input_files)))

    # Setup output directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_dir = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("Batch Audio Slicer for ER-301")
    print("=" * 60)
    print(f"Files to process: {len(input_files)}")
    print(f"Output directory: {output_dir}")
    print("=" * 60)

    # List files
    for i, f in enumerate(input_files, 1):
        print(f"  {i}. {os.path.basename(f)}")

    # Process each file
    results = []
    for i, input_file in enumerate(input_files, 1):
        print(f"\n[{i}/{len(input_files)}]", end=" ")
        result = process_file(input_file, output_dir)
        results.append(result)

    # Final summary
    print("\n" + "=" * 60)
    print("Batch Processing Complete!")
    print("=" * 60)

    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]

    print(f"\n✅ Successful: {len(successful)}/{len(results)}")
    for r in successful:
        print(f"   • {os.path.basename(r['output'])}")

    if failed:
        print(f"\n❌ Failed: {len(failed)}")
        for r in failed:
            print(f"   • {os.path.basename(r['input'])}: {r.get('error', 'Unknown error')}")

    print(f"\n📁 All output files are in: {output_dir}")
    print("\n🎉 Done!")

if __name__ == '__main__':
    main()
