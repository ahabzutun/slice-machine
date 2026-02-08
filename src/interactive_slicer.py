#!/usr/bin/env python3
"""
Interactive Audio Slicer for ER-301 - COMPLETE VERSION
Self-contained with built-in .slc generator (no external dependencies)
Forces target slice count and generates valid .slc files
"""

import sys
import os
import numpy as np
import struct
import warnings

# Suppress librosa warnings
warnings.filterwarnings('ignore', category=UserWarning, module='librosa')

# Determine the correct path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(script_dir) == 'src':
    sys.path.insert(0, script_dir)
else:
    sys.path.insert(0, os.path.join(script_dir, 'src'))

from audio_slicer import AudioSlicer
import librosa
import soundfile as sf

# ============================================================================
# BUILT-IN SLC GENERATOR (no external dependencies)
# ============================================================================

def generate_slc_file(wav_path, slices, total_samples):
    """
    Generate .slc file for ER-301 sample chains

    Format:
    - 2 bytes: number of slices (uint16, little-endian)
    - For each slice:
      - 4 bytes: start position in samples (uint32, little-endian)
      - 2 bytes: length in samples (uint16, little-endian)
    """
    slc_path = wav_path.replace('.wav', '.slc')

    print(f"\n📄 Generating .slc file: {slc_path}")
    print(f"   Slices: {len(slices)}")

    with open(slc_path, 'wb') as f:
        # Write number of slices (2 bytes, little-endian)
        f.write(struct.pack('<H', len(slices)))

        # Write each slice
        for s in slices:
            start = s['start']
            length = s['length']

            # Validate
            if start < 0 or start >= total_samples:
                print(f"⚠️  Warning: Slice {s['index']} has invalid start: {start}")
                start = 0

            if length <= 0 or length > 65535:
                print(f"⚠️  Warning: Slice {s['index']} has invalid length: {length}")
                length = min(65535, total_samples - start)

            # Write start position (4 bytes, little-endian)
            f.write(struct.pack('<I', start))

            # Write length (2 bytes, little-endian)
            f.write(struct.pack('<H', length))

    # Verify file was created
    if os.path.exists(slc_path):
        file_size = os.path.getsize(slc_path)
        expected_size = 2 + (len(slices) * 6)
        print(f"✓ Generated {slc_path}")
        print(f"   File size: {file_size} bytes")
        print(f"   Expected: {expected_size} bytes")

        if file_size != expected_size:
            print(f"   ⚠️  Size mismatch! File may be corrupted.")

        return slc_path
    else:
        print(f"❌ Failed to create .slc file")
        return None

# ============================================================================
# Audio Processing Functions
# ============================================================================

def compress_audio(audio, threshold_db=-20, ratio=4.0, attack_ms=5, release_ms=50, sr=48000):
    """Apply dynamic range compression"""
    threshold = 10 ** (threshold_db / 20)
    hop_length = int(sr * 0.001)
    rms = librosa.feature.rms(y=audio, hop_length=hop_length)[0]
    times = librosa.frames_to_samples(np.arange(len(rms)), hop_length=hop_length)
    envelope = np.interp(np.arange(len(audio)), times, rms)

    gain = np.ones_like(envelope)
    above_threshold = envelope > threshold
    gain[above_threshold] = threshold / envelope[above_threshold]
    gain[above_threshold] = gain[above_threshold] ** (1 - 1/ratio)

    attack_samples = int(sr * attack_ms / 1000)
    release_samples = int(sr * release_ms / 1000)

    smoothed_gain = np.copy(gain)
    for i in range(1, len(gain)):
        if gain[i] < smoothed_gain[i-1]:
            alpha = 1 - np.exp(-1 / attack_samples)
        else:
            alpha = 1 - np.exp(-1 / release_samples)
        smoothed_gain[i] = alpha * gain[i] + (1 - alpha) * smoothed_gain[i-1]

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

def force_target_slices(slices, target_slices, audio_length, sr=48000):
    """Force exact slice count by subdividing longest slices"""
    current_count = len(slices)

    if current_count >= target_slices:
        # Already have enough, just trim to target
        print(f"\n✂️  Trimming from {current_count} to {target_slices} slices...")
        return slices[:target_slices]

    print(f"\n✂️  Subdividing to reach target of {target_slices} slices...")
    print(f"   Current: {current_count} slices")
    print(f"   Need to add: {target_slices - current_count} more slices")

    needed = target_slices - current_count

    # Work with a copy
    working_slices = [dict(s) for s in slices]

    # Keep subdividing longest slices until we reach target
    while len(working_slices) < target_slices:
        # Find longest slice
        longest_idx = max(range(len(working_slices)), key=lambda i: working_slices[i]['length'])
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

def export_slices_custom(audio, slices, output_path, sr, generate_slc=True, reorganize=True, spectral_direction='low_to_high'):
    """
    Export slices as a sample chain with built-in .slc generation
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
    print("🎵  ER-301 SLICE GENERATOR - COMPLETE VERSION")
    print("=" * 70)
    print("Features: Forced slice count + Built-in .slc generator")
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

    # Step 4: Slice Organization
    print("\n🔀 Step 4: Slice Organization")
    print("-" * 70)
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
        ], default=2)  # Changed default to high_to_low for drums
        spectral_direction = 'low_to_high' if dir_choice == 1 else 'high_to_low'

    # Step 4b: Silence removal
    print("\n🔇 Step 4b: Silence Removal")
    print("-" * 70)
    print("Remove silent/quiet slices from the chain?")
    print("(HIGHLY RECOMMENDED for drum breaks to remove dead air)")
    remove_silence = input("\nRemove silent slices? [Y/n]: ").strip().lower() in ['', 'y', 'yes']

    silence_threshold_db = -40  # Default to -40dB for aggressive removal
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
    if reorganize:
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

    # Process
    print("\n" + "=" * 70)
    print("🎵 PROCESSING")
    print("=" * 70)

    output_dir = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)

    if processing_mode == 'combine':
        # Combine multiple files
        combined_audio = combine_audio_files(selected_files, sample_rate)

        # Detect onsets
        print(f"\n🔍 Detecting onsets...")

        # Detect onsets directly with librosa
        if detection_method == 'percussive':
            onset_frames = librosa.onset.onset_detect(y=combined_audio, sr=sample_rate, units='samples', backtrack=True)
        else:
            onset_frames = librosa.onset.onset_detect(y=combined_audio, sr=sample_rate, units='samples', backtrack=True)

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

        # DON'T remove silence yet - do it after subdivision

        # NOW reduce to target if we have too many
        if len(all_slices) > target_slices:
            print(f"\n✂️  Reducing {len(all_slices)} slices to {target_slices}...")
            step = len(all_slices) / target_slices
            indices = [int(i * step) for i in range(target_slices)]
            slices = [all_slices[i] for i in indices]
            # Re-index
            for i, s in enumerate(slices):
                s['index'] = i
            print(f"✓ Selected {len(slices)} slices")
        else:
            slices = all_slices

        # FORCE exact target count (subdivide if below)
        print(f"\n🎯 Forcing exactly {target_slices} slices...")
        slices = force_target_slices(slices, target_slices, len(combined_audio), sample_rate)

        # NOW remove silence AFTER subdivision (so we catch newly created silent slices)
        if remove_silence:
            print(f"\n🔇 Final silence check after subdivision...")
            slices = remove_silent_slices(combined_audio, slices, sample_rate, silence_threshold_db)

            # If we removed some, we need to subdivide again to reach target
            if len(slices) < target_slices:
                print(f"\n🎯 Re-subdividing to reach {target_slices} after silence removal...")
                slices = force_target_slices(slices, target_slices, len(combined_audio), sample_rate)

                # FINAL silence check after re-subdivision
                print(f"\n🔇 Final cleanup pass...")
                pre_cleanup_count = len(slices)
                slices = remove_silent_slices(combined_audio, slices, sample_rate, silence_threshold_db)

                # If we removed more, subdivide ONE more time
                if len(slices) < target_slices:
                    print(f"\n🎯 Final subdivision to reach {target_slices}...")
                    slices = force_target_slices(slices, target_slices, len(combined_audio), sample_rate)
                elif len(slices) == pre_cleanup_count:
                    print(f"✓ No additional silent slices found - we're done!")

        # Process audio
        if processing_config['mode'] != 'none':
            print(f"\n🎛️  Processing audio...")
            combined_audio = process_audio_chain(combined_audio, processing_config)

        # Export
        output_path = os.path.join(output_dir, f'{output_name}_chain.wav')
        export_slices_custom(combined_audio, slices, output_path, sample_rate, generate_slc=True, reorganize=reorganize, spectral_direction=spectral_direction)

        # Stats
        lengths = [s['length'] for s in slices]
        durations = [s['duration_ms'] for s in slices]

        print("\n" + "=" * 70)
        print("📊 RESULTS")
        print("=" * 70)
        print(f"Total slices: {len(slices)}")
        print(f"Shortest: {min(lengths):,} samples ({min(durations):.2f}ms)")
        print(f"Longest: {max(lengths):,} samples ({max(durations):.2f}ms)")
        print(f"Average: {sum(lengths)//len(lengths):,} samples ({sum(durations)/len(durations):.2f}ms)")
        print(f"\n✨ Output: {output_path}")
        print(f"✨ .slc file: {output_path.replace('.wav', '.slc')}")

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

            # Detect onsets
            print(f"\n🔍 Detecting onsets...")

            # Detect onsets directly with librosa
            if detection_method == 'percussive':
                onset_frames = librosa.onset.onset_detect(y=audio, sr=sample_rate, units='samples', backtrack=True)
            else:
                onset_frames = librosa.onset.onset_detect(y=audio, sr=sample_rate, units='samples', backtrack=True)

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

            # DON'T remove silence yet - do it after subdivision

            # NOW reduce to target if we have too many
            if len(all_slices) > target_slices:
                print(f"\n✂️  Reducing {len(all_slices)} slices to {target_slices}...")
                step = len(all_slices) / target_slices
                indices = [int(j * step) for j in range(target_slices)]
                slices = [all_slices[idx] for idx in indices]
                # Re-index
                for j, s in enumerate(slices):
                    s['index'] = j
                print(f"✓ Selected {len(slices)} slices")
            else:
                slices = all_slices

            # FORCE exact target count (subdivide if below)
            print(f"\n🎯 Forcing exactly {target_slices} slices...")
            slices = force_target_slices(slices, target_slices, len(audio), sample_rate)

            # NOW remove silence AFTER subdivision (so we catch newly created silent slices)
            if remove_silence:
                print(f"\n🔇 Final silence check after subdivision...")
                slices = remove_silent_slices(audio, slices, sample_rate, silence_threshold_db)

                # If we removed some, we need to subdivide again to reach target
                if len(slices) < target_slices:
                    print(f"\n🎯 Re-subdividing to reach {target_slices} after silence removal...")
                    slices = force_target_slices(slices, target_slices, len(audio), sample_rate)

                    # FINAL silence check after re-subdivision
                    print(f"\n🔇 Final cleanup pass...")
                    pre_cleanup_count = len(slices)
                    slices = remove_silent_slices(audio, slices, sample_rate, silence_threshold_db)

                    # If we removed more, subdivide ONE more time
                    if len(slices) < target_slices:
                        print(f"\n🎯 Final subdivision to reach {target_slices}...")
                        slices = force_target_slices(slices, target_slices, len(audio), sample_rate)
                    elif len(slices) == pre_cleanup_count:
                        print(f"✓ No additional silent slices found - we're done!")

            # Process audio
            if processing_config['mode'] != 'none':
                print(f"\n🎛️  Processing audio...")
                audio = process_audio_chain(audio, processing_config)

            # Generate output name for this file
            if len(selected_files) == 1:
                # Single file - use the name we already derived
                file_output_name = output_name
            else:
                # Batch mode - derive from each filename
                file_output_name = os.path.splitext(os.path.basename(input_file))[0].replace(' ', '_').lower()

            # Export
            output_path = os.path.join(output_dir, f'{file_output_name}_chain.wav')
            export_slices_custom(audio, slices, output_path, sample_rate, generate_slc=True, reorganize=reorganize, spectral_direction=spectral_direction)

            # Stats
            lengths = [s['length'] for s in slices]
            durations = [s['duration_ms'] for s in slices]

            print("\n" + "=" * 70)
            print("📊 RESULTS")
            print("=" * 70)
            print(f"File: {os.path.basename(input_file)}")
            print(f"Total slices: {len(slices)}")
            print(f"Shortest: {min(lengths):,} samples ({min(durations):.2f}ms)")
            print(f"Longest: {max(lengths):,} samples ({max(durations):.2f}ms)")
            print(f"Average: {sum(lengths)//len(lengths):,} samples ({sum(durations)/len(durations):.2f}ms)")
            print(f"\n✨ Output: {output_path}")
            print(f"✨ .slc file: {output_path.replace('.wav', '.slc')}")

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
