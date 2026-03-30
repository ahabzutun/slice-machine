#!/usr/bin/env python3
"""
Interactive Audio Slicer for ER-301 - WITH CDP INTEGRATION
Self-contained with built-in .slc generator + SoundThread/CDP processing
Forces target slice count and generates valid .slc files
"""

import sys
import os
import numpy as np
import struct
import warnings
from scipy.signal import lfilter

# Suppress librosa warnings
warnings.filterwarnings('ignore', category=UserWarning, module='librosa')

# Determine the correct path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(script_dir) == 'src':
    sys.path.insert(0, script_dir)
else:
    sys.path.insert(0, os.path.join(script_dir, 'src'))

import librosa
import soundfile as sf

# CDP Integration
try:
    from cdp_processor import CDPProcessor
    CDP_AVAILABLE = True
except ImportError:
    CDP_AVAILABLE = False
    print("⚠️  CDP processor not available (cdp_processor.py not found)")

# ============================================================================
# SLICE LENGTH CONFIGURATION
# ============================================================================

SLICE_MODES = {
    'percussive': {
        'min_duration_ms': 30,       # Very short slices OK
        'target_duration_ms': 80,    # Sweet spot for drums
        'hop_length': 256,           # Sensitive onset detection
        'description': 'Short, tight slices for drums/percussion (30-150ms)'
    },
    'hybrid': {
        'min_duration_ms': 100,      # Medium slices
        'target_duration_ms': 300,   # Good for both
        'hop_length': 512,           # Medium sensitivity
        'description': 'Medium slices for mixed content (100-400ms)'
    },
    'melodic': {
        'min_duration_ms': 200,      # Capture full notes
        'target_duration_ms': 600,   # Long enough for phrases
        'hop_length': 1024,          # Less sensitive (fewer cuts)
        'description': 'Long slices for melodic/harmonic content (200-800ms)'
    }
}

# ============================================================================
# BUILT-IN SLC GENERATOR (no external dependencies)
# ============================================================================

import struct
import os

import struct
import os

def generate_slc_file(wav_path, slices, total_samples):
    """
    Generate .slc file for ER-301 using the ACTUAL format from hardware

    REAL Format (reverse-engineered from working ER-301 file):

    HEADER (27 bytes):
    - Bytes 0-3:   Magic number: 0xABCDDCBA (little-endian)
    - Bytes 4-7:   Version: 7 (uint32 little-endian)
    - Bytes 8-23:  Label: "Slices" null-padded to 16 bytes
    - Bytes 24-26: Unknown (3 zero bytes)

    ENTRIES (128 entries × 16 bytes = 2048 bytes):
    Each entry:
    - Bytes 0-3:   Sample position (uint32 little-endian, FULL position, NOT divided by 256!)
    - Bytes 4-7:   Float 0.0 (4 bytes)
    - Bytes 8-11:  Float 0.0 (4 bytes)
    - Bytes 12-15: Float 1.0 (4 bytes)

    Total file size: 27 + 2048 = 2075 bytes

    Args:
        wav_path: Path to the .wav file
        slices: List of slice dictionaries with 'start' positions (in samples)
        total_samples: Total audio length (not used in .slc)
    """
    slc_path = wav_path.replace('.wav', '.slc')

    print(f"\n📄 Generating .slc file (CORRECT FORMAT): {slc_path}")
    print(f"   Input slices: {len(slices)}")

    # Ensure exactly 128 slices
    if len(slices) != 128:
        print(f"⚠️  WARNING: Expected 128 slices, got {len(slices)}")
        print(f"   ER-301 requires EXACTLY 128 slice markers!")

        if len(slices) < 128:
            print(f"   Padding with final position to reach 128...")
            while len(slices) < 128:
                slices.append(slices[-1])
        else:
            print(f"   Trimming to first 128 slices...")
            slices = slices[:128]

    with open(slc_path, 'wb') as f:
        # ============================================================
        # HEADER (27 bytes)
        # ============================================================

        # Magic number: 0xABCDDCBA in little-endian
        f.write(struct.pack('<I', 0xABCDDCBA))

        # Version: 7
        f.write(struct.pack('<I', 7))

        # Label: "Slices" + padding (19 bytes total to complete header)
        # Bytes 8-13: "Slices" (6 bytes)
        # Bytes 14-22: nulls (9 bytes)
        # Byte 23: 0x80
        # Bytes 24-26: nulls (3 bytes)
        f.write(b'Slices')              # 6 bytes
        f.write(b'\x00' * 9)             # 9 null bytes
        f.write(b'\x80')                 # 1 byte: 0x80
        f.write(b'\x00' * 3)             # 3 null bytes
        # Total: 6 + 9 + 1 + 3 = 19 bytes (completes 27-byte header)

        # ============================================================
        # ENTRIES (128 × 16 bytes)
        # ============================================================

        for i, s in enumerate(slices):
            position = s['start']

            # Safety check
            if position < 0:
                print(f"⚠️  Warning: Slice {i} has negative position, using 0")
                position = 0

            if position > 0xFFFFFFFF:
                print(f"⚠️  Warning: Slice {i} position too large, clamping")
                position = 0xFFFFFFFF

            # Write 16-byte entry
            f.write(struct.pack('<I', position))    # Sample position (uint32)
            f.write(struct.pack('<f', 0.0))         # Float 0.0
            f.write(struct.pack('<f', 0.0))         # Float 0.0
            f.write(struct.pack('<f', 1.0))         # Float 1.0

    # ============================================================
    # VERIFY
    # ============================================================

    if os.path.exists(slc_path):
        file_size = os.path.getsize(slc_path)
        expected_size = 27 + (128 * 16)  # 2075 bytes

        print(f"✓ Generated {slc_path}")
        print(f"   File size: {file_size} bytes")
        print(f"   Expected: {expected_size} bytes")

        if file_size == expected_size:
            print(f"   ✓ File size is CORRECT!")

            # Verify first and last positions
            with open(slc_path, 'rb') as f:
                f.seek(27)  # Skip header

                # First entry
                first_pos = struct.unpack('<I', f.read(4))[0]

                # Last entry
                f.seek(27 + (127 * 16))
                last_pos = struct.unpack('<I', f.read(4))[0]

                print(f"   First slice: sample {first_pos:,}")
                print(f"   Last slice: sample {last_pos:,}")
        else:
            print(f"   ❌ ERROR: Size mismatch!")

        return slc_path
    else:
        print(f"❌ Failed to create .slc file")
        return None


# Test
if __name__ == '__main__':
    # Create test slices
    test_slices = []
    for i in range(128):
        test_slices.append({
            'index': i,
            'start': i * 1000,  # 1000 samples apart
            'end': (i + 1) * 1000,
            'length': 1000
        })

    generate_slc_file('/tmp/test_chain.wav', test_slices, 128000)

    print("\n" + "="*70)
    print("VERIFICATION")
    print("="*70)

    # Verify against hardware format
    with open('/tmp/test_chain.slc', 'rb') as f:
        # Check header
        magic = struct.unpack('<I', f.read(4))[0]
        version = struct.unpack('<I', f.read(4))[0]
        label = f.read(16)
        unknown = f.read(3)

        print(f"Magic: 0x{magic:08X} (should be 0xABCDDCBA)")
        print(f"Version: {version} (should be 7)")
        print(f"Label: '{label.decode('ascii', errors='replace').rstrip(chr(0))}'")
        print(f"Unknown bytes: {unknown.hex()}")

        # Check entries
        print(f"\nFirst 5 entries:")
        for i in range(5):
            pos = struct.unpack('<I', f.read(4))[0]
            f0 = struct.unpack('<f', f.read(4))[0]
            f1 = struct.unpack('<f', f.read(4))[0]
            f2 = struct.unpack('<f', f.read(4))[0]
            print(f"  Slice {i}: pos={pos:6d}, floats=[{f0:.1f}, {f1:.1f}, {f2:.1f}]")

# ============================================================================
# Audio Processing Functions
# ============================================================================

def compress_audio(audio, threshold_db=-20, ratio=4.0, attack_ms=5, release_ms=50, sr=48000):
    """Apply dynamic range compression (vectorized - no Python loops)"""
    threshold = 10 ** (threshold_db / 20)
    hop_length = int(sr * 0.001)
    rms = librosa.feature.rms(y=audio, hop_length=hop_length)[0]
    times = librosa.frames_to_samples(np.arange(len(rms)), hop_length=hop_length)
    envelope = np.interp(np.arange(len(audio)), times, rms)

    gain = np.ones_like(envelope)
    above_threshold = envelope > threshold
    gain[above_threshold] = (threshold / envelope[above_threshold]) ** (1 - 1/ratio)

    # Vectorized smoothing via scipy lfilter (two-pass: attack then release)
    # Attack: smooth gain reductions (gain going down = compressor engaging)
    attack_coef = 1 - np.exp(-1 / max(1, int(sr * attack_ms / 1000)))
    release_coef = 1 - np.exp(-1 / max(1, int(sr * release_ms / 1000)))

    # Forward pass with release coefficient (gain increasing = release)
    b_rel = [release_coef]
    a_rel = [1, -(1 - release_coef)]
    smoothed_release = lfilter(b_rel, a_rel, gain)

    # Forward pass with attack coefficient (gain decreasing = attack)
    b_att = [attack_coef]
    a_att = [1, -(1 - attack_coef)]
    smoothed_attack = lfilter(b_att, a_att, gain)

    # Use the more conservative (higher) gain at each point
    # When gain drops (attack): use the slower attack-smoothed version
    # When gain rises (release): use the slower release-smoothed version
    smoothed_gain = np.where(smoothed_attack < smoothed_release, smoothed_attack, smoothed_release)

    return audio * smoothed_gain

def normalize_audio(audio, method='peak', target_db=-3):
    """Normalize audio"""
    if method == 'peak':
        peak = np.max(np.abs(audio))
        if peak > 0:
            target_amplitude = 10 ** (target_db / 20)
            normalized = audio * (target_amplitude / peak)
        else:
            normalized = audio
    elif method == 'rms':
        rms = np.sqrt(np.mean(audio ** 2))
        if rms > 0:
            target_amplitude = 10 ** (target_db / 20)
            normalized = audio * (target_amplitude / rms)
        else:
            normalized = audio
    else:
        normalized = audio

    peak = np.max(np.abs(normalized))
    if peak > 1.0:
        normalized = normalized / peak * 0.99

    return normalized

def process_audio_chain(audio, processing_config):
    """Apply audio processing"""
    if processing_config['mode'] == 'none':
        return audio

    processed = np.copy(audio)

    if processing_config['compress']:
        print(f"  🎚️  Applying compression (threshold: {processing_config['threshold_db']}dB, ratio: {processing_config['ratio']}:1)...")
        processed = compress_audio(
            processed,
            threshold_db=processing_config['threshold_db'],
            ratio=processing_config['ratio'],
            attack_ms=processing_config['attack_ms'],
            release_ms=processing_config['release_ms'],
            sr=processing_config['sr']
        )

    if processing_config['normalize']:
        method = processing_config['normalize_method']
        target = processing_config['normalize_target_db']
        print(f"  📊 Applying {method.upper()} normalization (target: {target}dB)...")
        processed = normalize_audio(processed, method=method, target_db=target)

    return processed

# ============================================================================
# CDP Processing Functions
# ============================================================================

# ============================================================================
# CDP Processing Functions
# ============================================================================

def process_full_audio_with_cdp(audio, sr, thread_path, temp_dir):
    """
    Process entire audio file through CDP thread (pre-processing)

    Args:
        audio: Full audio array
        sr: Sample rate
        thread_path: Path to .thd file
        temp_dir: Temporary directory for processing

    Returns:
        Processed audio array
    """
    print(f"\n🎨 Pre-processing full audio through CDP...")
    print(f"   Thread: {os.path.basename(thread_path)}")
    print(f"   Audio length: {len(audio)} samples ({len(audio)/sr:.2f}s)")

    # Initialize CDP processor
    processor = CDPProcessor()

    # Create temp files
    input_file = os.path.join(temp_dir, 'cdp_pre_input.wav')
    output_file = os.path.join(temp_dir, 'cdp_pre_output.wav')

    # Write full audio to temp file
    sf.write(input_file, audio, sr)

    # Process through CDP
    try:
        processor.process_file(
            input_file,
            output_file,
            thread_path,
            verbose=True  # Show CDP progress
        )

        # Load processed audio
        processed_audio, _ = librosa.load(output_file, sr=sr, mono=True)

        print(f"✓ Pre-processing complete")
        print(f"   Output length: {len(processed_audio)} samples ({len(processed_audio)/sr:.2f}s)")

        return processed_audio

    except Exception as e:
        print(f"\n❌ Pre-processing failed: {e}")
        print(f"   Continuing with original audio...")
        return audio

def scan_thread_files(directory):
    """Scan directory for .thd files"""
    thread_files = []

    if not os.path.exists(directory):
        return []

    for filename in os.listdir(directory):
        if filename.lower().endswith('.thd'):
            thread_files.append(os.path.join(directory, filename))

    return sorted(thread_files)

def process_slices_with_cdp(audio, slices, sr, thread_path, temp_dir):
    """
    Process individual slices through CDP thread

    Returns:
        Modified audio array with processed slices and updated slice info
    """
    print(f"\n🎨 Processing slices through CDP...")
    print(f"   Thread: {os.path.basename(thread_path)}")
    print(f"   Slices to process: {len(slices)}")

    # Initialize CDP processor
    processor = CDPProcessor()

    # Create temp directory for slices
    slice_temp_dir = os.path.join(temp_dir, 'cdp_slices')
    os.makedirs(slice_temp_dir, exist_ok=True)

    processed_slices = []
    processed_audio_segments = []
    failed_count = 0

    for i, s in enumerate(slices):
        # Extract slice audio
        audio_segment = audio[s['start']:s['end']]

        # Create temp files
        input_slice = os.path.join(slice_temp_dir, f'slice_{i:03d}_input.wav')
        output_slice = os.path.join(slice_temp_dir, f'slice_{i:03d}_output.wav')

        # Write slice to temp file
        sf.write(input_slice, audio_segment, sr)

        # Process through CDP
        try:
            processor.process_file(
                input_slice,
                output_slice,
                thread_path,
                verbose=False
            )

            # Load processed audio
            processed_segment, _ = librosa.load(output_slice, sr=sr, mono=True)
            processed_audio_segments.append(processed_segment)

            # Update slice info with new length
            processed_slices.append({
                'index': i,
                'start': 0,  # Will be recalculated when building chain
                'end': len(processed_segment),
                'length': len(processed_segment),
                'duration_ms': (len(processed_segment) / sr) * 1000
            })

            # Progress indicator
            if (i + 1) % 10 == 0 or (i + 1) == len(slices):
                print(f"   Progress: {i + 1}/{len(slices)} slices processed")

        except Exception as e:
            print(f"   ⚠️  Failed to process slice {i}: {e}")
            # Use original slice as fallback
            processed_audio_segments.append(audio_segment)
            processed_slices.append(s)
            failed_count += 1

    print(f"✓ CDP processing complete")
    if failed_count > 0:
        print(f"   ⚠️  {failed_count} slices failed (kept original)")

    # Rebuild audio array from processed segments
    processed_audio = np.concatenate(processed_audio_segments)

    # Recalculate slice positions in new audio array
    cumulative_pos = 0
    for s in processed_slices:
        s['start'] = cumulative_pos
        s['end'] = cumulative_pos + s['length']
        cumulative_pos = s['end']

    return processed_audio, processed_slices

# ============================================================================
# Slice Management Functions
# ============================================================================

def remove_silent_slices(audio, slices, sr, silence_threshold_db=-60):
    """
    Remove slices that are mostly silent

    Args:
        audio: Full audio array
        slices: List of slice dictionaries
        sr: Sample rate
        silence_threshold_db: Threshold in dB below which slice is considered silent

    Returns:
        Filtered list of slices without silent ones
    """
    print(f"\n🔇 Detecting and removing silent slices...")
    print(f"   Silence threshold: {silence_threshold_db}dB")
    print(f"   Checking {len(slices)} slices...")

    threshold_amplitude = 10 ** (silence_threshold_db / 20)

    filtered_slices = []
    silent_count = 0

    for s in slices:
        audio_segment = audio[s['start']:s['end']]

        # Calculate RMS and peak
        rms = np.sqrt(np.mean(audio_segment ** 2))
        peak = np.max(np.abs(audio_segment))

        # More aggressive: require BOTH RMS and peak above threshold
        # AND at least 10% of samples above threshold
        above_threshold = np.sum(np.abs(audio_segment) > threshold_amplitude)
        percent_above = above_threshold / len(audio_segment) * 100

        # Keep slice if it has significant energy
        if rms > threshold_amplitude and peak > threshold_amplitude and percent_above > 5:
            filtered_slices.append(s)
        else:
            silent_count += 1
            # Debug: show first few rejected slices
            if silent_count <= 3:
                print(f"   Rejecting slice {s['index']}: RMS={rms:.6f}, peak={peak:.6f}, {percent_above:.1f}% above threshold")

    print(f"✓ Removed {silent_count} silent slices")
    print(f"✓ Kept {len(filtered_slices)} slices with content")

    if silent_count == 0:
        print(f"⚠️  WARNING: No slices were removed!")
        print(f"   This might indicate that the threshold is too sensitive.")
        print(f"   Try a higher threshold like -40dB or -30dB")

    return filtered_slices

def filter_slices_by_duration(slices, min_duration_ms, sr=48000):
    """
    Filter out slices shorter than minimum duration

    Args:
        slices: List of slice dictionaries
        min_duration_ms: Minimum duration in milliseconds
        sr: Sample rate

    Returns:
        Filtered list of slices meeting minimum duration
    """
    min_samples = int((min_duration_ms / 1000) * sr)

    print(f"\n⏱️  Filtering by minimum duration...")
    print(f"   Minimum: {min_duration_ms}ms ({min_samples:,} samples)")
    print(f"   Checking {len(slices)} slices...")

    filtered_slices = []
    rejected_count = 0

    for s in slices:
        if s['length'] >= min_samples:
            filtered_slices.append(s)
        else:
            rejected_count += 1
            # Debug: show first few rejected slices
            if rejected_count <= 3:
                print(f"   Rejecting slice {s['index']}: {s['duration_ms']:.1f}ms (too short)")

    print(f"✓ Removed {rejected_count} slices below minimum duration")
    print(f"✓ Kept {len(filtered_slices)} slices")

    return filtered_slices

def force_target_slices(slices, target_slices, audio_length, sr=48000, min_duration_ms=None):
    """Force exact slice count by subdividing longest slices (respects minimum duration)"""
    current_count = len(slices)

    if current_count >= target_slices:
        # Already have enough, just trim to target
        print(f"\n✂️  Trimming from {current_count} to {target_slices} slices...")
        return slices[:target_slices]

    print(f"\n✂️  Subdividing to reach target of {target_slices} slices...")
    print(f"   Current: {current_count} slices")
    print(f"   Need to add: {target_slices - current_count} more slices")

    if min_duration_ms:
        min_samples = int((min_duration_ms / 1000) * sr)
        print(f"   Respecting minimum duration: {min_duration_ms}ms ({min_samples:,} samples)")
    else:
        min_samples = 0

    needed = target_slices - current_count

    # Work with a copy
    working_slices = [dict(s) for s in slices]

    # Keep subdividing longest slices until we reach target
    while len(working_slices) < target_slices:
        # Find longest slice that can still be subdivided
        subdividable = [i for i, s in enumerate(working_slices)
                       if s['length'] >= min_samples * 2]

        if not subdividable:
            print(f"\n⚠️  Cannot subdivide further without violating minimum duration!")
            print(f"   Reached {len(working_slices)} slices (target was {target_slices})")
            print(f"   All remaining slices are at or below 2x minimum ({min_duration_ms * 2}ms)")
            break

        # Find longest subdividable slice
        longest_idx = max(subdividable, key=lambda i: working_slices[i]['length'])
        longest = working_slices[longest_idx]

        # Split it in half
        mid_point = (longest['start'] + longest['end']) // 2

        # Create two new slices
        first_half = {
            'index': len(working_slices),  # Will re-index later
            'start': longest['start'],
            'end': mid_point,
            'length': mid_point - longest['start'],
            'duration_ms': ((mid_point - longest['start']) / sr) * 1000
        }

        second_half = {
            'index': len(working_slices) + 1,
            'start': mid_point,
            'end': longest['end'],
            'length': longest['end'] - mid_point,
            'duration_ms': ((longest['end'] - mid_point) / sr) * 1000
        }

        # Remove original and add two halves
        working_slices.pop(longest_idx)
        working_slices.append(first_half)
        working_slices.append(second_half)

    # Sort by start position
    working_slices.sort(key=lambda x: x['start'])

    # Re-index
    for i, s in enumerate(working_slices):
        s['index'] = i

    # Trim to exact target if we overshot
    if len(working_slices) > target_slices:
        working_slices = working_slices[:target_slices]

    print(f"✓ Final slice count: {len(working_slices)}")

    # Statistics
    lengths = [s['length'] for s in working_slices]
    durations = [s['duration_ms'] for s in working_slices]
    print(f"\n   New slice statistics:")
    print(f"   Shortest: {min(lengths):,} samples ({min(durations):.2f}ms)")
    print(f"   Longest:  {max(lengths):,} samples ({max(durations):.2f}ms)")
    print(f"   Average:  {sum(lengths)//len(lengths):,} samples ({sum(durations)/len(durations):.2f}ms)")

    return working_slices

def reorganize_slices_by_similarity(audio, slices, sr, direction='low_to_high'):
    """
    Reorganize slices by spectral similarity

    Args:
        direction: 'low_to_high' or 'high_to_low'
    """
    print(f"\n🔀 Reorganizing slices by spectral similarity...")
    print(f"   Analyzing audio features...")

    # Extract features for each slice
    features = []
    for s in slices:
        audio_segment = audio[s['start']:s['end']]

        if len(audio_segment) < 2048:
            # For very short segments, use simpler features
            rms = np.sqrt(np.mean(audio_segment ** 2))
            zcr = np.mean(librosa.feature.zero_crossing_rate(audio_segment))
            features.append([rms * 1000, zcr * 100, len(audio_segment)])
        else:
            # Full spectral analysis
            spectral_centroid = np.mean(librosa.feature.spectral_centroid(y=audio_segment, sr=sr))
            rms = np.sqrt(np.mean(audio_segment ** 2))
            zcr = np.mean(librosa.feature.zero_crossing_rate(audio_segment))
            features.append([spectral_centroid, rms * 1000, zcr * 100])

    features = np.array(features)

    # Sort by spectral centroid (frequency characteristic)
    centroid_order = np.argsort(features[:, 0])

    # Reverse if high to low
    if direction == 'high_to_low':
        centroid_order = centroid_order[::-1]

    reorganized_slices = [slices[i] for i in centroid_order]

    if direction == 'low_to_high':
        print(f"✓ Slices reorganized by frequency characteristics")
        print(f"   Order is now: LOW frequency → HIGH frequency")
    else:
        print(f"✓ Slices reorganized by frequency characteristics")
        print(f"   Order is now: HIGH frequency → LOW frequency")

    return reorganized_slices

def organize_slices_by_banks(audio_files_data, bank_sort='chronological'):
    """
    Organize slices into 8 banks of 16 slices each (for 128 total)
    Perfect for MIDI controllers with 8 banks × 16 pads

    Args:
        audio_files_data: List of dicts with 'audio', 'slices', 'sr', 'filename'
        bank_sort: 'chronological', 'pitch_ascending', or 'pitch_descending'

    Returns:
        Flat list of 128 slices organized in banks
    """
    print(f"\n🏦 Organizing into 8 banks of 16 slices...")
    print(f"   Bank sorting: {bank_sort.upper()}")

    if len(audio_files_data) != 8:
        raise ValueError(f"Bank mode requires exactly 8 files, got {len(audio_files_data)}")

    organized_slices = []

    for bank_num, file_data in enumerate(audio_files_data):
        audio = file_data['audio']
        slices = file_data['slices']
        sr = file_data['sr']
        filename = file_data['filename']

        print(f"\n   Bank {bank_num + 1}: {filename}")
        print(f"   Raw slices: {len(slices)}")

        # Get exactly 16 slices from this file
        if len(slices) > 16:
            # Sample evenly across available slices
            step = len(slices) / 16
            indices = [int(i * step) for i in range(16)]
            bank_slices = [slices[i] for i in indices]
        elif len(slices) < 16:
            # Duplicate to reach 16
            while len(slices) < 16:
                slices.append(slices[-1])
            bank_slices = slices[:16]
        else:
            bank_slices = slices[:16]

        # Sort this bank if requested
        if bank_sort in ['pitch_ascending', 'pitch_descending']:
            print(f"      Analyzing pitch for sorting...")

            # Extract pitch for each slice
            pitches = []
            for s in bank_slices:
                audio_segment = audio[s['start']:s['end']]

                # Use librosa's pitch detection
                try:
                    # Get fundamental frequency estimate
                    f0 = librosa.yin(audio_segment, fmin=librosa.note_to_hz('C1'),
                                    fmax=librosa.note_to_hz('C8'), sr=sr)
                    # Use median pitch (ignore zeros from unvoiced frames)
                    voiced_f0 = f0[f0 > 0]
                    if len(voiced_f0) > 0:
                        median_pitch = np.median(voiced_f0)
                    else:
                        # Fallback to spectral centroid if no pitch detected
                        median_pitch = np.mean(librosa.feature.spectral_centroid(y=audio_segment, sr=sr))
                except:
                    # Fallback to spectral centroid on error
                    median_pitch = np.mean(librosa.feature.spectral_centroid(y=audio_segment, sr=sr))

                pitches.append(median_pitch)

            # Sort by pitch
            pitch_order = np.argsort(pitches)

            if bank_sort == 'pitch_descending':
                pitch_order = pitch_order[::-1]

            bank_slices = [bank_slices[i] for i in pitch_order]

            pitch_range_text = f"{min(pitches):.0f}Hz - {max(pitches):.0f}Hz"
            direction_text = "Low→High" if bank_sort == 'pitch_ascending' else "High→Low"
            print(f"      Sorted by pitch: {direction_text} ({pitch_range_text})")

        else:
            print(f"      Keeping chronological order")

        # Add to organized list
        organized_slices.extend(bank_slices)

    # Reindex
    for i, s in enumerate(organized_slices):
        s['index'] = i

    print(f"\n✓ Organized into 8 banks × 16 slices = {len(organized_slices)} total")
    print(f"   Bank 1: Slices 0-15   | Bank 5: Slices 64-79")
    print(f"   Bank 2: Slices 16-31  | Bank 6: Slices 80-95")
    print(f"   Bank 3: Slices 32-47  | Bank 7: Slices 96-111")
    print(f"   Bank 4: Slices 48-63  | Bank 8: Slices 112-127")

    return organized_slices

def export_slices_custom(audio, slices, output_path, sr, generate_slc=True, reorganize=True, spectral_direction='low_to_high', processing_config=None):
    """
    Export slices as a sample chain with built-in .slc generation.
    Audio processing (compress/normalize) is applied to the assembled chain,
    NOT the full source audio, to avoid out-of-memory kills on large inputs.
    """
    print(f"\n💾 Exporting sample chain...")
    print(f"   Path: {output_path}")
    print(f"   Slices: {len(slices)}")
    print(f"   Sample rate: {sr}Hz")

    # Reorganize if requested
    if reorganize:
        slices = reorganize_slices_by_similarity(audio, slices, sr, direction=spectral_direction)

    # Build the chain
    chain_audio = []
    chain_slices = []
    cumulative_position = 0

    for s in slices:
        audio_segment = audio[s['start']:s['end']]
        chain_audio.append(audio_segment)

        chain_slices.append({
            'index': s['index'],
            'start': cumulative_position,
            'end': cumulative_position + len(audio_segment),
            'length': len(audio_segment),
            'duration_ms': (len(audio_segment) / sr) * 1000
        })
        cumulative_position += len(audio_segment)

    # Concatenate
    chain_audio = np.concatenate(chain_audio)

    # Apply audio processing to the chain (much smaller than the full source file)
    if processing_config and processing_config.get('mode', 'none') != 'none':
        print(f"\n🎛️  Processing audio chain ({len(chain_audio)/sr:.2f}s)...")
        chain_audio = process_audio_chain(chain_audio, processing_config)

    # Write WAV
    sf.write(output_path, chain_audio, sr)

    duration = len(chain_audio) / sr
    print(f"✓ Exported sample chain")
    print(f"   Duration: {duration:.2f}s")
    print(f"   Samples: {len(chain_audio):,}")

    # Generate .slc file
    if generate_slc:
        generate_slc_file(output_path, chain_slices, len(chain_audio))

    return output_path

# ============================================================================
# UI Helper Functions
# ============================================================================

def scan_audio_files(directory):
    """Scan directory for audio files"""
    audio_extensions = ['.wav', '.mp3', '.flac', '.ogg', '.aif', '.aiff', '.m4a']
    audio_files = []

    if not os.path.exists(directory):
        return []

    for filename in os.listdir(directory):
        if any(filename.lower().endswith(ext) for ext in audio_extensions):
            audio_files.append(os.path.join(directory, filename))

    return sorted(audio_files)

def get_user_choice(prompt, options, default=None):
    """Get user selection"""
    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        default_marker = " (default)" if default == i else ""
        print(f"  {i}. {option}{default_marker}")

    while True:
        if default:
            choice = input(f"\nEnter choice [1-{len(options)}] (default: {default}): ").strip()
            if choice == "":
                return default
        else:
            choice = input(f"\nEnter choice [1-{len(options)}]: ").strip()

        try:
            choice = int(choice)
            if 1 <= choice <= len(options):
                return choice
            print(f"Please enter a number between 1 and {len(options)}")
        except ValueError:
            print("Please enter a valid number")

def get_multiple_choices(prompt, options):
    """Get multiple selections"""
    print(f"\n{prompt}")
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")

    while True:
        choices_input = input(f"\nEnter choices [1-{len(options)}] (comma-separated, or 'all'): ").strip().lower()

        if choices_input == 'all':
            return list(range(1, len(options) + 1))

        try:
            choices = [int(c.strip()) for c in choices_input.split(',')]
            if all(1 <= c <= len(options) for c in choices):
                return sorted(list(set(choices)))
            print(f"Please enter numbers between 1 and {len(options)}")
        except ValueError:
            print("Please enter valid numbers separated by commas, or 'all'")

def get_user_input(prompt, default=None, input_type=str):
    """Get user input with default"""
    if default:
        user_input = input(f"{prompt} (default: {default}): ").strip()
        if user_input == "":
            return default
    else:
        user_input = input(f"{prompt}: ").strip()

    try:
        return input_type(user_input)
    except ValueError:
        print(f"Invalid input. Please enter a {input_type.__name__}")
        return get_user_input(prompt, default, input_type)

def combine_audio_files(input_files, sample_rate):
    """Combine multiple audio files"""
    print(f"\n🔗 Combining {len(input_files)} audio files...")

    combined_audio = []
    for filepath in input_files:
        print(f"  Loading: {os.path.basename(filepath)}")
        audio, _ = librosa.load(filepath, sr=sample_rate, mono=True)
        combined_audio.append(audio)

    combined = np.concatenate(combined_audio)
    print(f"✓ Combined into {len(combined)} samples ({len(combined)/sample_rate:.2f}s)")

    return combined

# ============================================================================
# Main Function
# ============================================================================

def main():
    print("=" * 70)
    print("🎵  ER-301 SLICE GENERATOR - WITH CDP INTEGRATION")
    print("=" * 70)
    print("Features: Forced slice count + Built-in .slc + CDP processing")
    if CDP_AVAILABLE:
        print("✓ CDP SoundThread processing available")
    else:
        print("⚠️  CDP processing unavailable")
    print("=" * 70)

    # Step 1: Select files
    print("\n📁 Step 1: Select Audio File(s)")
    print("-" * 70)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == 'src':
        project_root = os.path.dirname(script_dir)
    else:
        project_root = script_dir

    default_input_dir = os.path.join(project_root, 'input')
    use_default = input(f"\nUse default input directory? ({default_input_dir}) [Y/n]: ").strip().lower()

    if use_default in ['', 'y', 'yes']:
        input_dir = default_input_dir
    else:
        input_dir = input("Enter input directory path: ").strip()

    audio_files = scan_audio_files(input_dir)

    if not audio_files:
        print(f"\n❌ No audio files found in: {input_dir}")
        return

    print(f"\n✓ Found {len(audio_files)} audio file(s):")
    for i, filepath in enumerate(audio_files, 1):
        filename = os.path.basename(filepath)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  {i}. {filename} ({size_mb:.2f} MB)")

    file_choices = get_multiple_choices("Select audio file(s):", [os.path.basename(f) for f in audio_files])
    selected_files = [audio_files[i - 1] for i in file_choices]

    print(f"\n✓ Selected {len(selected_files)} file(s)")

    # Processing mode and output name
    processing_mode = 'single'
    if len(selected_files) > 1:
        print("\n🔀 Step 1b: Choose Processing Mode")
        print("-" * 70)
        modes = [
            "batch - Process each file separately",
            "combine - Merge all files into one chain"
        ]
        mode_choice = get_user_choice("Select mode:", modes, default=2)
        processing_mode = 'batch' if mode_choice == 1 else 'combine'

    # Get output name
    if processing_mode == 'combine' or len(selected_files) == 1:
        # Ask for name for combine mode or single file
        default_name = 'combined' if len(selected_files) > 1 else os.path.splitext(os.path.basename(selected_files[0]))[0]
        default_name = default_name.replace(' ', '_').lower()
        output_name = input(f"\nEnter output name (default: '{default_name}'): ").strip() or default_name
        output_name = output_name.replace(' ', '_').lower()
    else:
        # Batch mode uses individual filenames
        output_name = None

    # Step 2: Parameters
    print("\n⚙️  Step 2: Configure Parameters")
    print("-" * 70)

    target_slices = get_user_input("\nSlices (will be forced exactly)", default=128, input_type=int)
    sample_rate = get_user_input("Sample rate (Hz)", default=48000, input_type=int)

    # Step 3: Detection
    print("\n🔍 Step 3: Detection Method")
    print("-" * 70)
    detection_choice = get_user_choice("Method:", ["energy", "percussive"], default=1)
    detection_method = 'energy' if detection_choice == 1 else 'percussive'

    # Step 3a: Slice Length Mode (NEW!)
    print("\n⏱️  Step 3a: Slice Length Mode")
    print("-" * 70)
    print("Choose target slice length based on your content type:")
    print("")
    mode_options = []
    for i, (key, config) in enumerate(SLICE_MODES.items(), 1):
        mode_options.append(f"{key} - {config['description']}")
        print(f"  {i}. {key.upper()}")
        print(f"     {config['description']}")
        print(f"     Min: {config['min_duration_ms']}ms | Target: {config['target_duration_ms']}ms")
        print("")

    slice_mode_choice = get_user_choice("Select slice length mode:", mode_options, default=1)
    slice_mode_keys = list(SLICE_MODES.keys())
    slice_mode = slice_mode_keys[slice_mode_choice - 1]
    slice_config = SLICE_MODES[slice_mode]

    print(f"\n✓ Selected: {slice_mode.upper()}")
    print(f"   Minimum duration: {slice_config['min_duration_ms']}ms")
    print(f"   Target duration: {slice_config['target_duration_ms']}ms")
    print(f"   Onset sensitivity: {slice_config['hop_length']} hop length")

    # Step 3b: CDP Pre-Processing (NEW!)
    use_cdp_pre = False
    pre_thread_path = None

    # Step 3c: CDP Post-Processing (NEW!)
    use_cdp_post = False
    post_thread_path = None

    if CDP_AVAILABLE:
        # Scan for .thd files once
        src_dir = os.path.dirname(os.path.abspath(__file__))
        thread_files = scan_thread_files(src_dir)

        if not thread_files:
            print("\n⚠️  No .thd files found in src directory")
            print("   Place your SoundThread .thd files in the src/ folder")
        else:
            # PRE-PROCESSING OPTION
            print("\n🎨 Step 3b: CDP Pre-Processing (OPTIONAL)")
            print("-" * 70)
            print("Apply CDP effects BEFORE slicing?")
            print("• Processes entire audio file once")
            print("• Works with complex effects (granular, spectral)")
            print("• Faster than per-slice processing")
            print("• Example: stepped_resynthesis.thd")
            print("")

            pre_choice = input("Use pre-processing? [y/N]: ").strip().lower()
            use_cdp_pre = (pre_choice in ['y', 'yes'])

            if use_cdp_pre:
                print(f"\n✓ Found {len(thread_files)} thread file(s):")
                for i, filepath in enumerate(thread_files, 1):
                    filename = os.path.basename(filepath)
                    print(f"  {i}. {filename}")

                thread_choice = get_user_choice("Select pre-processing thread:", [os.path.basename(f) for f in thread_files])
                pre_thread_path = thread_files[thread_choice - 1]

                print(f"\n✓ Selected: {os.path.basename(pre_thread_path)}")
                print(f"   Will process full audio before slicing")

            # POST-PROCESSING OPTION
            print("\n🎨 Step 3c: CDP Post-Processing (OPTIONAL)")
            print("-" * 70)
            print("Apply CDP effects AFTER slicing?")
            print("• Processes each individual slice")
            print("• Maximum variety and texture")
            print("• Best with simple effects (ring mod, distortion)")
            print("• Example: ring_mod_only.thd")
            print("")

            post_choice = input("Use post-processing? [y/N]: ").strip().lower()
            use_cdp_post = (post_choice in ['y', 'yes'])

            if use_cdp_post:
                print(f"\n✓ Found {len(thread_files)} thread file(s):")
                for i, filepath in enumerate(thread_files, 1):
                    filename = os.path.basename(filepath)
                    print(f"  {i}. {filename}")

                thread_choice = get_user_choice("Select post-processing thread:", [os.path.basename(f) for f in thread_files])
                post_thread_path = thread_files[thread_choice - 1]

                print(f"\n✓ Selected: {os.path.basename(post_thread_path)}")
                print(f"   Will process each slice individually")

            if use_cdp_pre and use_cdp_post:
                print(f"\n✨ DUAL PROCESSING ENABLED!")
                print(f"   Pre: {os.path.basename(pre_thread_path)}")
                print(f"   Post: {os.path.basename(post_thread_path)}")
                print(f"   Get ready for wild textures!")

    # Step 4: Slice Organization
    print("\n🔀 Step 4: Slice Organization")
    print("-" * 70)

    # Check if bank mode is possible
    bank_mode_available = (len(selected_files) == 8 and processing_mode == 'combine')

    if bank_mode_available:
        print("Choose how to organize slices in the final chain:")
        org_options = [
            "sequential - Keep slices in original order (chronological)",
            "similarity - Reorganize by frequency characteristics",
            "bank - 8 banks × 16 slices (perfect for MIDI controllers!) ✨"
        ]
        reorg_choice = get_user_choice("Organization:", org_options, default=3)

        if reorg_choice == 3:
            # Bank mode selected
            reorganize = False  # Will use custom bank organization instead
            use_bank_mode = True

            print("\n🏦 Bank Mode Configuration")
            print("-" * 70)
            print("Perfect for controllers with 8 banks of 16 pads!")
            print("")
            print("Choose how to order slices WITHIN each bank:")
            bank_sort_options = [
                "chronological - Keep original time order (drums/percussion)",
                "pitch_ascending - Low → High pitch (melodic content)",
                "pitch_descending - High → Low pitch (melodic content)"
            ]
            bank_sort_choice = get_user_choice("Within-bank sorting:", bank_sort_options, default=1)
            bank_sort_mode = ['chronological', 'pitch_ascending', 'pitch_descending'][bank_sort_choice - 1]

        else:
            use_bank_mode = False
            reorganize = (reorg_choice == 2)
            bank_sort_mode = None

    else:
        use_bank_mode = False
        bank_sort_mode = None
        print("Choose how to organize slices in the final chain:")
        reorg_choice = get_user_choice("Organization:", [
            "sequential - Keep slices in original order (chronological)",
            "similarity - Reorganize by frequency characteristics (recommended)"
        ], default=2)
        reorganize = (reorg_choice == 2)

    # If using similarity, choose direction
    spectral_direction = 'low_to_high'
    if reorganize:
        print("\n   Spectral organization direction:")
        print("   (This determines which sounds play first)")
        dir_choice = get_user_choice("   Direction:", [
            "low_to_high - KICKS/BASS first → snares/hats last (deep to bright)",
            "high_to_low - SNARES/HATS first → kicks/bass last (bright to deep)"
        ], default=2)
        spectral_direction = 'low_to_high' if dir_choice == 1 else 'high_to_low'

        # Step 4b: Silence removal
    print("\n🔇 Step 4b: Silence Removal")
    print("-" * 70)
    print("Remove silent/quiet slices from the chain?")
    print("(HIGHLY RECOMMENDED for drum breaks to remove dead air)")
    remove_silence = input("\nRemove silent slices? [Y/n]: ").strip().lower() in ['', 'y', 'yes']

    silence_threshold_db = -40
    if remove_silence:
        print("\n   🎯 Threshold guide for drums:")
        print("   -60dB: Permissive (only complete silence)")
        print("   -50dB: Moderate (quiet room tone)")
        print("   -40dB: Recommended (removes tails/decay) ✓")
        print("   -30dB: Aggressive (only loud transients)")
        print("")
        print("   💡 Tip: Silence is checked AFTER slicing, so even -40dB")
        print("       will catch silent portions created by subdivision.")
        custom_threshold = input("   Silence threshold in dB (default: -40): ").strip()
        if custom_threshold:
            try:
                silence_threshold_db = float(custom_threshold)
            except ValueError:
                print("   Invalid input, using default -40dB")
                silence_threshold_db = -40

    # Step 5: Processing
    print("\n🎛️  Step 5: Audio Processing")
    print("-" * 70)
    processing_choice = get_user_choice("Processing:", ["none", "normalize", "compress", "both"], default=4)
    processing_map = {1: 'none', 2: 'normalize', 3: 'compress', 4: 'both'}
    processing_mode_selected = processing_map[processing_choice]

    processing_config = {
        'mode': processing_mode_selected,
        'compress': processing_mode_selected in ['compress', 'both'],
        'normalize': processing_mode_selected in ['normalize', 'both'],
        'sr': sample_rate,
        'threshold_db': -20,
        'ratio': 4.0,
        'attack_ms': 5,
        'release_ms': 50,
        'normalize_method': 'peak',
        'normalize_target_db': -3
    }

    # Confirm
    print("\n" + "=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    print(f"Files: {len(selected_files)}")
    print(f"Mode: {processing_mode}")
    print(f"Target slices: {target_slices} (FORCED)")
    print(f"Slice mode: {slice_mode.upper()}")
    print(f"  Min duration: {slice_config['min_duration_ms']}ms")
    print(f"  Target duration: {slice_config['target_duration_ms']}ms")
    print(f"  Hop length: {slice_config['hop_length']}")
    if use_cdp_pre and use_cdp_post:
        print(f"CDP Pre-Process: {os.path.basename(pre_thread_path)} ✨")
        print(f"CDP Post-Process: {os.path.basename(post_thread_path)} ✨")
    elif use_cdp_pre:
        print(f"CDP Pre-Process: {os.path.basename(pre_thread_path)} ✨")
    elif use_cdp_post:
        print(f"CDP Post-Process: {os.path.basename(post_thread_path)} ✨")
    else:
        print(f"CDP Processing: No")

    if use_bank_mode:
        print(f"Organization: Bank Mode (8×16)")
        print(f"  Bank sorting: {bank_sort_mode}")
    elif reorganize:
        direction_text = "Low→High" if spectral_direction == 'low_to_high' else "High→Low"
        print(f"Organization: Similarity ({direction_text})")
    else:
        print(f"Organization: Sequential (original order)")

    print(f"Silence removal: {'Yes' if remove_silence else 'No'}" + (f" (threshold: {silence_threshold_db}dB)" if remove_silence else ""))
    print(f"Processing: {processing_mode_selected}")
    print("=" * 70)

    confirm = input("\nProceed? [Y/n]: ").strip().lower()
    if confirm not in ['', 'y', 'yes']:
        print("❌ Cancelled")
        return

    # Create temp directory for CDP processing
    import tempfile
    temp_dir = tempfile.mkdtemp(prefix='slice_machine_')

    try:
        # Process
        print("\n" + "=" * 70)
        print("🎵 PROCESSING")
        print("=" * 70)

        output_dir = os.path.join(project_root, 'output')
        os.makedirs(output_dir, exist_ok=True)

        if processing_mode == 'combine':
            if use_bank_mode:
                # Process each file individually to get slices
                audio_files_data = []

                for i, input_file in enumerate(selected_files):
                    print(f"\n{'='*70}")
                    print(f"Processing file {i+1}/8 for Bank {i+1}")
                    print(f"{'='*70}")

                    # Load audio
                    print(f"\n📂 Loading: {os.path.basename(input_file)}")
                    file_audio, _ = librosa.load(input_file, sr=sample_rate, mono=True)
                    print(f"✓ Loaded {len(file_audio)} samples ({len(file_audio)/sample_rate:.2f}s)")

                    # CDP Pre-Processing if enabled
                    if use_cdp_pre and pre_thread_path:
                        file_audio = process_full_audio_with_cdp(
                            file_audio, sample_rate, pre_thread_path, temp_dir
                        )

                    # Detect onsets for this file
                    print(f"\n🔍 Detecting onsets using {slice_mode.upper()} mode...")
                    if detection_method == 'percussive':
                        onset_frames = librosa.onset.onset_detect(
                            y=file_audio, sr=sample_rate, hop_length=slice_config['hop_length'],
                            units='samples', backtrack=True
                        )
                    else:
                        onset_frames = librosa.onset.onset_detect(
                            y=file_audio, sr=sample_rate, hop_length=slice_config['hop_length'],
                            units='samples', backtrack=True
                        )

                    onset_frames = np.append(onset_frames, len(file_audio))

                    # Convert to slices
                    file_slices = []
                    for j in range(len(onset_frames) - 1):
                        start = onset_frames[j]
                        end = onset_frames[j + 1]
                        file_slices.append({
                            'index': j,
                            'start': start,
                            'end': end,
                            'length': end - start,
                            'duration_ms': ((end - start) / sample_rate) * 1000
                        })

                    print(f"Found {len(file_slices)} slices from onset detection")

                    # Filter by minimum duration
                    file_slices = filter_slices_by_duration(
                        file_slices, slice_config['min_duration_ms'], sample_rate
                    )

                    # Remove silence if enabled
                    if remove_silence:
                        file_slices = remove_silent_slices(file_audio, file_slices, sample_rate, silence_threshold_db)

                    # Store this file's data
                    audio_files_data.append({
                        'audio': file_audio,
                        'slices': file_slices,
                        'sr': sample_rate,
                        'filename': os.path.basename(input_file)
                    })

                    print(f"✓ Bank {i+1}: {len(file_slices)} slices ready")

                # Organize into banks
                slices = organize_slices_by_banks(audio_files_data, bank_sort=bank_sort_mode)

                # Build combined audio from organized slices
                print(f"\n🔗 Building combined audio from {len(slices)} organized slices...")
                combined_audio = []
                cumulative_pos = 0

                for s in slices:
                    # Find which file this slice came from (each bank has 16 slices)
                    file_idx = s['index'] // 16
                    file_audio = audio_files_data[file_idx]['audio']
                    audio_segment = file_audio[s['start']:s['end']]
                    combined_audio.append(audio_segment)

                    # Update slice position for final chain
                    s['start'] = cumulative_pos
                    s['end'] = cumulative_pos + len(audio_segment)
                    s['length'] = len(audio_segment)
                    cumulative_pos = s['end']

                combined_audio = np.concatenate(combined_audio)
                print(f"✓ Combined audio: {len(combined_audio)} samples ({len(combined_audio)/sample_rate:.2f}s)")

                # CDP Post-Processing if enabled
                if use_cdp_post and post_thread_path:
                    combined_audio, slices = process_slices_with_cdp(
                        combined_audio, slices, sample_rate, post_thread_path, temp_dir
                    )

                # Export (without reorganization since we already organized by banks)
                output_path = os.path.join(output_dir, f'{output_name}_chain.wav')
                export_slices_custom(combined_audio, slices, output_path, sample_rate,
                                    generate_slc=True, reorganize=False, spectral_direction=None,
                                    processing_config=processing_config)

                # Stats
                lengths = [s['length'] for s in slices]
                durations = [s['duration_ms'] for s in slices]

                print("\n" + "=" * 70)
                print("📊 RESULTS - BANK MODE")
                print("=" * 70)
                print(f"Slice mode: {slice_mode.upper()} ({slice_config['min_duration_ms']}-{slice_config['target_duration_ms']}ms)")
                print(f"Bank organization: {bank_sort_mode}")
                print(f"Total slices: {len(slices)} (8 banks × 16 slices)")
                print(f"Shortest: {min(lengths):,} samples ({min(durations):.2f}ms)")
                print(f"Longest: {max(lengths):,} samples ({max(durations):.2f}ms)")
                print(f"Average: {sum(lengths)//len(lengths):,} samples ({sum(durations)/len(durations):.2f}ms)")
                print(f"\n✨ Output: {output_path}")
                print(f"✨ .slc file: {output_path.replace('.wav', '.slc')}")
                if use_cdp_pre and use_cdp_post:
                    print(f"✨ CDP pre-processed: {os.path.basename(pre_thread_path)}")
                    print(f"✨ CDP post-processed: {os.path.basename(post_thread_path)}")
                elif use_cdp_pre:
                    print(f"✨ CDP pre-processed: {os.path.basename(pre_thread_path)}")
                elif use_cdp_post:
                    print(f"✨ CDP post-processed: {os.path.basename(post_thread_path)}")
            else:
                # Combine multiple files
                combined_audio = combine_audio_files(selected_files, sample_rate)

                # CDP Pre-Processing (NEW!)
                if use_cdp_pre and pre_thread_path:
                    combined_audio = process_full_audio_with_cdp(
                        combined_audio, sample_rate, pre_thread_path, temp_dir
                    )

            # Detect onsets
            print(f"\n🔍 Detecting onsets using {slice_mode.upper()} mode...")
            print(f"   Hop length: {slice_config['hop_length']} (sensitivity)")

            if detection_method == 'percussive':
                onset_frames = librosa.onset.onset_detect(
                    y=combined_audio,
                    sr=sample_rate,
                    hop_length=slice_config['hop_length'],
                    units='samples',
                    backtrack=True
                )
            else:
                onset_frames = librosa.onset.onset_detect(
                    y=combined_audio,
                    sr=sample_rate,
                    hop_length=slice_config['hop_length'],
                    units='samples',
                    backtrack=True
                )

            onset_frames = np.append(onset_frames, len(combined_audio))

            # Convert to slices
            all_slices = []
            for i in range(len(onset_frames) - 1):
                start = onset_frames[i]
                end = onset_frames[i + 1]
                all_slices.append({
                    'index': i,
                    'start': start,
                    'end': end,
                    'length': end - start,
                    'duration_ms': ((end - start) / sample_rate) * 1000
                })

            print(f"Found {len(all_slices)} slices from onset detection")

            # Filter by minimum duration
            all_slices = filter_slices_by_duration(
                all_slices,
                slice_config['min_duration_ms'],
                sample_rate
            )

            # Reduce to target if we have too many
            if len(all_slices) > target_slices:
                print(f"\n✂️  Reducing {len(all_slices)} slices to {target_slices}...")
                step = len(all_slices) / target_slices
                indices = [int(i * step) for i in range(target_slices)]
                slices = [all_slices[i] for i in indices]
                for i, s in enumerate(slices):
                    s['index'] = i
                print(f"✓ Selected {len(slices)} slices")
            else:
                slices = all_slices

            # Force exact target count
            print(f"\n🎯 Forcing exactly {target_slices} slices...")
            slices = force_target_slices(
                slices,
                target_slices,
                len(combined_audio),
                sample_rate,
                min_duration_ms=slice_config['min_duration_ms']
            )

            # Remove silence AFTER subdivision
            if remove_silence:
                print(f"\n🔇 Final silence check after subdivision...")
                slices = remove_silent_slices(combined_audio, slices, sample_rate, silence_threshold_db)

                if len(slices) < target_slices:
                    print(f"\n🎯 Re-subdividing to reach {target_slices} after silence removal...")
                    slices = force_target_slices(
                        slices,
                        target_slices,
                        len(combined_audio),
                        sample_rate,
                        min_duration_ms=slice_config['min_duration_ms']
                    )

                    print(f"\n🔇 Final cleanup pass...")
                    pre_cleanup_count = len(slices)
                    slices = remove_silent_slices(combined_audio, slices, sample_rate, silence_threshold_db)

                    if len(slices) < target_slices:
                        print(f"\n🎯 Final subdivision to reach {target_slices}...")
                        slices = force_target_slices(
                            slices,
                            target_slices,
                            len(combined_audio),
                            sample_rate,
                            min_duration_ms=slice_config['min_duration_ms']
                        )
                    elif len(slices) == pre_cleanup_count:
                        print(f"✓ No additional silent slices found - we're done!")

            # CDP Processing (NEW!)
            if use_cdp_post and post_thread_path:
                combined_audio, slices = process_slices_with_cdp(
                    combined_audio, slices, sample_rate, post_thread_path, temp_dir
                )

            # Export
            output_path = os.path.join(output_dir, f'{output_name}_chain.wav')
            export_slices_custom(combined_audio, slices, output_path, sample_rate, generate_slc=True, reorganize=reorganize, spectral_direction=spectral_direction, processing_config=processing_config)

            # Stats
            lengths = [s['length'] for s in slices]
            durations = [s['duration_ms'] for s in slices]

            print("\n" + "=" * 70)
            print("📊 RESULTS")
            print("=" * 70)
            print(f"Slice mode: {slice_mode.upper()} ({slice_config['min_duration_ms']}-{slice_config['target_duration_ms']}ms)")
            print(f"Total slices: {len(slices)}")
            print(f"Shortest: {min(lengths):,} samples ({min(durations):.2f}ms)")
            print(f"Longest: {max(lengths):,} samples ({max(durations):.2f}ms)")
            print(f"Average: {sum(lengths)//len(lengths):,} samples ({sum(durations)/len(durations):.2f}ms)")
            print(f"\n✨ Output: {output_path}")
            print(f"✨ .slc file: {output_path.replace('.wav', '.slc')}")
            if use_cdp_pre and use_cdp_post:
                print(f"✨ CDP pre-processed: {os.path.basename(pre_thread_path)}")
                print(f"✨ CDP post-processed: {os.path.basename(post_thread_path)}")
            elif use_cdp_pre:
                print(f"✨ CDP pre-processed: {os.path.basename(pre_thread_path)}")
            elif use_cdp_post:
                print(f"✨ CDP post-processed: {os.path.basename(post_thread_path)}")

        else:
            # Single file or batch mode
            for i, input_file in enumerate(selected_files):
                if len(selected_files) > 1:
                    print(f"\n{'='*70}")
                    print(f"Processing file {i+1}/{len(selected_files)}")
                    print(f"{'='*70}")

                # Load audio
                print(f"\n📂 Loading: {os.path.basename(input_file)}")
                audio, _ = librosa.load(input_file, sr=sample_rate, mono=True)
                print(f"✓ Loaded {len(audio)} samples ({len(audio)/sample_rate:.2f}s)")

                # CDP Pre-Processing (NEW!)
                if use_cdp_pre and pre_thread_path:
                    audio = process_full_audio_with_cdp(
                        audio, sample_rate, pre_thread_path, temp_dir
                    )

                # Detect onsets
                print(f"\n🔍 Detecting onsets using {slice_mode.upper()} mode...")
                print(f"   Hop length: {slice_config['hop_length']} (sensitivity)")

                if detection_method == 'percussive':
                    onset_frames = librosa.onset.onset_detect(
                        y=audio,
                        sr=sample_rate,
                        hop_length=slice_config['hop_length'],
                        units='samples',
                        backtrack=True
                    )
                else:
                    onset_frames = librosa.onset.onset_detect(
                        y=audio,
                        sr=sample_rate,
                        hop_length=slice_config['hop_length'],
                        units='samples',
                        backtrack=True
                    )

                onset_frames = np.append(onset_frames, len(audio))

                # Convert to slices
                all_slices = []
                for j in range(len(onset_frames) - 1):
                    start = onset_frames[j]
                    end = onset_frames[j + 1]
                    all_slices.append({
                        'index': j,
                        'start': start,
                        'end': end,
                        'length': end - start,
                        'duration_ms': ((end - start) / sample_rate) * 1000
                    })

                print(f"Found {len(all_slices)} slices from onset detection")

                # Filter by minimum duration
                all_slices = filter_slices_by_duration(
                    all_slices,
                    slice_config['min_duration_ms'],
                    sample_rate
                )

                # Reduce to target if we have too many
                if len(all_slices) > target_slices:
                    print(f"\n✂️  Reducing {len(all_slices)} slices to {target_slices}...")
                    step = len(all_slices) / target_slices
                    indices = [int(j * step) for j in range(target_slices)]
                    slices = [all_slices[idx] for idx in indices]
                    for j, s in enumerate(slices):
                        s['index'] = j
                    print(f"✓ Selected {len(slices)} slices")
                else:
                    slices = all_slices

                # Force exact target count
                print(f"\n🎯 Forcing exactly {target_slices} slices...")
                slices = force_target_slices(
                    slices,
                    target_slices,
                    len(audio),
                    sample_rate,
                    min_duration_ms=slice_config['min_duration_ms']
                )

                # Remove silence AFTER subdivision
                if remove_silence:
                    print(f"\n🔇 Final silence check after subdivision...")
                    slices = remove_silent_slices(audio, slices, sample_rate, silence_threshold_db)

                    if len(slices) < target_slices:
                        print(f"\n🎯 Re-subdividing to reach {target_slices} after silence removal...")
                        slices = force_target_slices(
                            slices,
                            target_slices,
                            len(audio),
                            sample_rate,
                            min_duration_ms=slice_config['min_duration_ms']
                        )

                        print(f"\n🔇 Final cleanup pass...")
                        pre_cleanup_count = len(slices)
                        slices = remove_silent_slices(audio, slices, sample_rate, silence_threshold_db)

                        if len(slices) < target_slices:
                            print(f"\n🎯 Final subdivision to reach {target_slices}...")
                            slices = force_target_slices(
                                slices,
                                target_slices,
                                len(audio),
                                sample_rate,
                                min_duration_ms=slice_config['min_duration_ms']
                            )
                        elif len(slices) == pre_cleanup_count:
                            print(f"✓ No additional silent slices found - we're done!")

                # CDP Processing (NEW!)
                if use_cdp_post and post_thread_path:
                    audio, slices = process_slices_with_cdp(
                        audio, slices, sample_rate, post_thread_path, temp_dir
                    )

                # Generate output name for this file
                if len(selected_files) == 1:
                    file_output_name = output_name
                else:
                    file_output_name = os.path.splitext(os.path.basename(input_file))[0].replace(' ', '_').lower()

                # Export
                output_path = os.path.join(output_dir, f'{file_output_name}_chain.wav')
                export_slices_custom(audio, slices, output_path, sample_rate, generate_slc=True, reorganize=reorganize, spectral_direction=spectral_direction, processing_config=processing_config)

                # Stats
                lengths = [s['length'] for s in slices]
                durations = [s['duration_ms'] for s in slices]

                print("\n" + "=" * 70)
                print("📊 RESULTS")
                print("=" * 70)
                print(f"File: {os.path.basename(input_file)}")
                print(f"Slice mode: {slice_mode.upper()} ({slice_config['min_duration_ms']}-{slice_config['target_duration_ms']}ms)")
                print(f"Total slices: {len(slices)}")
                print(f"Shortest: {min(lengths):,} samples ({min(durations):.2f}ms)")
                print(f"Longest: {max(lengths):,} samples ({max(durations):.2f}ms)")
                print(f"Average: {sum(lengths)//len(lengths):,} samples ({sum(durations)/len(durations):.2f}ms)")
                print(f"\n✨ Output: {output_path}")
                print(f"✨ .slc file: {output_path.replace('.wav', '.slc')}")
                if use_cdp_pre and use_cdp_post:
                    print(f"✨ CDP pre-processed: {os.path.basename(pre_thread_path)}")
                    print(f"✨ CDP post-processed: {os.path.basename(post_thread_path)}")
                elif use_cdp_pre:
                    print(f"✨ CDP pre-processed: {os.path.basename(pre_thread_path)}")
                elif use_cdp_post:
                    print(f"✨ CDP post-processed: {os.path.basename(post_thread_path)}")

    finally:
        # Cleanup temp directory
        import shutil
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    print("\n🎉 Complete!\n")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
