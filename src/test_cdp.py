#!/usr/bin/env python3
"""
Test CDP Integration
====================
Quick test to verify CDP commands work from Python.
"""

import subprocess
from pathlib import Path


def test_cdp_installation(cdp_path="/Users/maxe/cdpr8/_cdp/_cdprogs"):
    """Verify CDP is installed and accessible."""
    print("\n" + "="*70)
    print("TESTING CDP INSTALLATION")
    print("="*70)

    cdp_dir = Path(cdp_path)

    # Check directory exists
    print(f"\n1. Checking CDP directory: {cdp_path}")
    if not cdp_dir.exists():
        print("   ✗ Directory not found!")
        return False
    print("   ✓ Found")

    # Check key programs exist
    print("\n2. Checking essential programs:")
    essential = ['pvoc', 'modify', 'focus', 'sndinfo']

    for prog in essential:
        prog_path = cdp_dir / prog
        if prog_path.exists():
            print(f"   ✓ {prog}")
        else:
            print(f"   ✗ {prog} not found")
            return False

    # Test running a simple command
    print("\n3. Testing command execution:")
    try:
        result = subprocess.run(
            [str(cdp_dir / 'sndinfo')],
            capture_output=True,
            text=True,
            timeout=5
        )
        print(f"   ✓ sndinfo executed (exit code: {result.returncode})")
        return True

    except Exception as e:
        print(f"   ✗ Failed to execute: {e}")
        return False


def test_thread_parsing():
    """Test parsing your stepped_resynthesis thread."""
    print("\n" + "="*70)
    print("TESTING THREAD PARSING")
    print("="*70)

    thread_path = "/Users/maxe/projects/slice-machine/src/stepped_resynthesis.thd"

    print(f"\n1. Loading thread: {Path(thread_path).name}")

    try:
        from cdp_processor import CDPProcessor
        processor = CDPProcessor()
        chain = processor.load_thread(thread_path)

        print(f"   ✓ Parsed successfully")
        print(f"\n2. Processing chain ({len(chain)} steps):")

        for i, cmd in enumerate(chain, 1):
            print(f"   {i}. {cmd['program']}", end="")
            if cmd['process']:
                print(f" {cmd['process']}", end="")
            if cmd['mode']:
                print(f" [mode {cmd['mode']}]", end="")
            if cmd['params']:
                print(f" ({', '.join(cmd['params'])})", end="")
            print()

        return True

    except FileNotFoundError:
        print(f"   ✗ Thread file not found: {thread_path}")
        return False

    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False


def test_simple_processing():
    """Test processing a simple audio file (if you have one)."""
    print("\n" + "="*70)
    print("TESTING AUDIO PROCESSING")
    print("="*70)

    print("\nTo test actual audio processing:")
    print("1. Create a short test audio file (1-2 seconds)")
    print("2. Run:")
    print()
    print("   from cdp_processor import CDPProcessor")
    print("   processor = CDPProcessor()")
    print("   processor.process_file(")
    print("       'test.wav',")
    print("       'test_out.wav',")
    print("       'stepped_resynthesis.thd'")
    print("   )")


def show_next_steps():
    """Show what to do next."""
    print("\n" + "="*70)
    print("NEXT STEPS")
    print("="*70)

    print("""
1. ADD TO YOUR SLICE MACHINE:

   Copy cdp_processor.py to your slice-machine/src/ directory:

   cp cdp_processor.py /path/to/slice-machine/src/


2. MODIFY YOUR SLICE MACHINE:

   Add CDP as an optional processing step. See example_integration.py
   for detailed integration patterns.


3. RECOMMENDED WORKFLOW:

   Option A: Process individual slices (most flexible)

   • Slice audio normally
   • Apply CDP to each slice
   • Reorganize and create ER-301 chain


   Option B: Process before slicing (fastest)

   • Apply CDP to source audio
   • Slice the processed audio
   • Create ER-301 chain


4. CREATE MORE THREADS:

   Build different processing chains in SoundThread:

   • Granular smearing
   • Spectral freezing
   • Rhythmic stuttering
   • Harmonic distortion

   Save as .thd files and use them in your slicer!


5. BATCH PROCESSING:

   Process multiple files at once:

   from cdp_processor import integrate_with_slicer

   slices = ['slice_001.wav', 'slice_002.wav', ...]
   processed = integrate_with_slicer(
       slices,
       'your_thread.thd',
       'output_dir/'
   )
""")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("CDP INTEGRATION TEST SUITE")
    print("="*70)

    # Run tests
    tests = [
        ("CDP Installation", test_cdp_installation),
        ("Thread Parsing", test_thread_parsing),
        ("Audio Processing Info", test_simple_processing)
    ]

    results = []
    for name, test_func in tests:
        result = test_func()
        results.append((name, result))

    # Show summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)

    for name, result in results:
        if result is True:
            print(f"✓ {name}")
        elif result is False:
            print(f"✗ {name}")
        else:
            print(f"ℹ {name}")

    # Show next steps
    show_next_steps()

    print("\n" + "="*70)
    print("Ready to integrate CDP into your slice machine! 🎵")
    print("="*70)
