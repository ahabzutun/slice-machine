"""
Audio Slicer for ER-301 Sample Chains
Detects and extracts slices from audio files
"""

import librosa
import numpy as np
import soundfile as sf

class AudioSlicer:
    """Slice audio files intelligently for sample chains"""

    def __init__(self, target_slices=128, sr=48000):
        """
        Args:
            target_slices: Number of slices to generate (default 128)
            sr: Sample rate (ER-301 typically uses 48kHz)
        """
        self.target_slices = target_slices
        self.sr = sr
        self.audio = None
        self.slice_points = []

    def load_audio(self, filepath):
        """Load an audio file"""
        print(f"Loading: {filepath}")
        self.audio, _ = librosa.load(filepath, sr=self.sr, mono=True)
        print(f"Loaded {len(self.audio)} samples ({len(self.audio)/self.sr:.2f}s)")
        return self

    def detect_onsets(self, method='energy'):
        """
        Detect slice points using onset detection

        Args:
            method: 'energy' or 'percussive'
        """
        if self.audio is None:
            raise ValueError("No audio loaded! Call load_audio() first")

        print(f"Detecting onsets using {method} method...")

        # Detect onsets (transients)
        onset_frames = librosa.onset.onset_detect(
            y=self.audio,
            sr=self.sr,
            units='samples',
            backtrack=True
        )

        print(f"Found {len(onset_frames)} onsets")
        self.slice_points = sorted(onset_frames.tolist())
        return self

    def get_slice_info(self):
        """Return information about detected slices"""
        if not self.slice_points:
            return None

        # Add start and end points
        points = [0] + self.slice_points + [len(self.audio)]

        slices = []
        for i in range(len(points) - 1):
            start = points[i]
            end = points[i + 1]
            length = end - start
            slices.append({
                'index': i,
                'start': start,
                'end': end,
                'length': length,
                'duration_ms': (length / self.sr) * 1000
            })

        return slices

    def adjust_to_target_slices(self, method='even'):
            """
            Adjust the number of slices to exactly match target_slices

            Args:
                method: 'even' (sample evenly), 'energy' (keep loudest), or 'duration' (keep longest)
            """
            slices = self.get_slice_info()

            if len(slices) == self.target_slices:
                print(f"✓ Already have exactly {self.target_slices} slices!")
                return slices

            if len(slices) < self.target_slices:
                print(f"⚠ Warning: Only {len(slices)} slices detected, need {self.target_slices}")
                print(f"  Consider using subdivide method or different detection settings")
                return slices

            print(f"Reducing {len(slices)} slices to {self.target_slices} using '{method}' method...")

            if method == 'even':
                # Sample evenly across all slices
                step = len(slices) / self.target_slices
                selected_indices = [int(i * step) for i in range(self.target_slices)]
                selected_slices = [slices[i] for i in selected_indices]

            elif method == 'energy':
                # Keep the slices with highest energy
                # Calculate energy for each slice
                slice_energies = []
                for s in slices:
                    audio_segment = self.audio[s['start']:s['end']]
                    energy = np.sum(audio_segment ** 2)
                    slice_energies.append((energy, s))

                # Sort by energy and take top target_slices
                slice_energies.sort(reverse=True, key=lambda x: x[0])
                selected_slices = [s for _, s in slice_energies[:self.target_slices]]
                # Re-sort by position
                selected_slices.sort(key=lambda x: x['start'])

            elif method == 'duration':
                # Keep the longest slices
                sorted_by_length = sorted(slices, key=lambda x: x['length'], reverse=True)
                selected_slices = sorted_by_length[:self.target_slices]
                # Re-sort by position
                selected_slices.sort(key=lambda x: x['start'])

            else:
                raise ValueError(f"Unknown method: {method}")

            # Re-index the selected slices
            for i, slice_info in enumerate(selected_slices):
                slice_info['index'] = i

            print(f"✓ Selected {len(selected_slices)} slices")
            return selected_slices

    def organize_into_groups(self, slices, method='similarity'):
        """
        Organize slices into groups of 8

        Args:
            slices: List of slice info dictionaries
            method: 'similarity' (by audio features), 'duration' (by length), or 'sequential' (as-is)

        Returns:
            List of 16 groups, each containing 8 slices
        """
        if len(slices) != self.target_slices:
            raise ValueError(f"Expected {self.target_slices} slices, got {len(slices)}")

        print(f"\nOrganizing {len(slices)} slices into groups of 8 using '{method}' method...")

        if method == 'sequential':
            # Just split into sequential groups of 8
            groups = []
            for i in range(0, len(slices), 8):
                groups.append(slices[i:i+8])

        elif method == 'duration':
            # Sort by duration and distribute
            sorted_slices = sorted(slices, key=lambda x: x['length'])
            groups = [[] for _ in range(16)]

            # Distribute slices round-robin style
            for i, slice_info in enumerate(sorted_slices):
                group_idx = i % 16
                groups[group_idx].append(slice_info)

            # Sort each group by position to maintain timeline flow
            for group in groups:
                group.sort(key=lambda x: x['start'])

        elif method == 'similarity':
            # Group by audio similarity (spectral features)
            print("  Analyzing spectral features...")

            # Extract features for each slice
            features = []
            for s in slices:
                audio_segment = self.audio[s['start']:s['end']]

                # Calculate spectral features
                spectral_centroid = np.mean(librosa.feature.spectral_centroid(y=audio_segment, sr=self.sr))
                rms = np.mean(librosa.feature.rms(y=audio_segment))
                zcr = np.mean(librosa.feature.zero_crossing_rate(audio_segment))

                features.append([spectral_centroid, rms * 1000, zcr * 100])  # Scale for better clustering

            features = np.array(features)

            # Simple clustering: sort by spectral centroid and group
            centroid_order = np.argsort(features[:, 0])
            sorted_slices = [slices[i] for i in centroid_order]

            # Create groups
            groups = []
            for i in range(0, len(sorted_slices), 8):
                group = sorted_slices[i:i+8]
                # Sort each group by original position
                group.sort(key=lambda x: x['start'])
                groups.append(group)

        else:
            raise ValueError(f"Unknown grouping method: {method}")

        # Print group summary
        print(f"✓ Created {len(groups)} groups of 8 slices")
        for i, group in enumerate(groups):
            avg_duration = sum(s['duration_ms'] for s in group) / len(group)
            print(f"  Group {i+1:2d}: avg duration = {avg_duration:6.2f}ms")

        return groups

    def export_slices(self, slices, output_dir, prefix='slice', export_mode='chain', generate_slc=True):
            """
            Export slices as audio files

            Args:
                slices: List of slice info dictionaries
                output_dir: Directory to save files
                prefix: Filename prefix
                export_mode: 'chain' (single file) or 'individual' (separate files)
                generate_slc: If True, also generate .slc file (default: True)

            Returns:
                Path to exported file(s)
            """
            import os

            # Make sure output directory exists
            try:
                os.makedirs(output_dir, exist_ok=True)
                print(f"\n📁 Output directory: {output_dir}")
                print(f"   Directory exists: {os.path.exists(output_dir)}")
                print(f"   Directory is writable: {os.access(output_dir, os.W_OK)}")
            except Exception as e:
                print(f"❌ Error creating output directory: {e}")
                raise

            print(f"\nExporting {len(slices)} slices in '{export_mode}' mode...")

            if export_mode == 'chain':
                # Concatenate all slices into one file
                # Build new slice info with positions in the chain
                chain_slices = []
                chain_audio = []
                cumulative_position = 0

                for s in slices:
                    audio_segment = self.audio[s['start']:s['end']]
                    chain_audio.append(audio_segment)

                    # Create slice info for the chain
                    chain_slices.append({
                        'index': s['index'],
                        'start': cumulative_position,
                        'length': len(audio_segment)
                    })
                    cumulative_position += len(audio_segment)

                chain_audio = np.concatenate(chain_audio)

                output_path = os.path.join(output_dir, f'{prefix}_chain.wav')

                print(f"\n🎵 Writing audio file...")
                print(f"   Path: {output_path}")
                print(f"   Samples: {len(chain_audio)}")
                print(f"   Sample rate: {self.sr}")

                try:
                    sf.write(output_path, chain_audio, self.sr)

                    # Verify the file was created
                    if os.path.exists(output_path):
                        file_size = os.path.getsize(output_path)
                        print(f"✓ File created successfully!")
                        print(f"   Size: {file_size:,} bytes")
                    else:
                        print(f"❌ File was not created!")
                        return None

                except Exception as e:
                    print(f"❌ Error writing audio file: {e}")
                    raise

                duration = len(chain_audio) / self.sr
                print(f"✓ Exported sample chain: {output_path}")
                print(f"  Duration: {duration:.2f}s")
                print(f"  Sample rate: {self.sr}Hz")
                print(f"  Samples: {len(chain_audio):,}")

                # Generate .slc file for ER-301
                if generate_slc:
                    try:
                        from slc_generator import SLCGenerator
                        slc_gen = SLCGenerator()
                        slc_path = slc_gen.generate_from_audio_file(
                            output_path,
                            chain_slices,
                            len(chain_audio)
                        )
                        print(f"✓ Generated .slc file: {slc_path}")
                    except Exception as e:
                        print(f"⚠️  Warning: Could not generate .slc file: {e}")

                        # Verify .slc file exists
                        if os.path.exists(slc_path):
                            slc_size = os.path.getsize(slc_path)
                            print(f"✓ .slc file verified: {slc_size} bytes")
                        else:
                            print(f"❌ .slc file was not created!")

                    except Exception as e:
                        print(f"❌ Error generating .slc file: {e}")
                        import traceback
                        traceback.print_exc()

                return output_path

            elif export_mode == 'individual':
                # Export each slice as a separate file
                output_paths = []

                for s in slices:
                    audio_segment = self.audio[s['start']:s['end']]
                    filename = f'{prefix}_{s["index"]:03d}.wav'
                    output_path = os.path.join(output_dir, filename)

                    try:
                        sf.write(output_path, audio_segment, self.sr)
                        output_paths.append(output_path)
                    except Exception as e:
                        print(f"❌ Error writing {filename}: {e}")

                print(f"✓ Exported {len(output_paths)} individual slice files to: {output_dir}")
                return output_paths

            else:
                raise ValueError(f"Unknown export_mode: {export_mode}")
                """
                Export slices as audio files

                Args:
                    slices: List of slice info dictionaries
                    output_dir: Directory to save files
                    prefix: Filename prefix
                    export_mode: 'chain' (single file) or 'individual' (separate files)
                    generate_slc: If True, also generate .slc file (default: True)

                Returns:
                    Path to exported file(s)
                """
                import os
                os.makedirs(output_dir, exist_ok=True)

                print(f"\nExporting {len(slices)} slices in '{export_mode}' mode...")

                if export_mode == 'chain':
                    # Concatenate all slices into one file
                    # Build new slice info with positions in the chain
                    chain_slices = []
                    chain_audio = []
                    cumulative_position = 0

                    for s in slices:
                        audio_segment = self.audio[s['start']:s['end']]
                        chain_audio.append(audio_segment)

                        # Create slice info for the chain
                        chain_slices.append({
                            'index': s['index'],
                            'start': cumulative_position,
                            'length': len(audio_segment)
                        })
                        cumulative_position += len(audio_segment)

                    chain_audio = np.concatenate(chain_audio)

                    output_path = os.path.join(output_dir, f'{prefix}_chain.wav')
                    sf.write(output_path, chain_audio, self.sr)

                    duration = len(chain_audio) / self.sr
                    print(f"✓ Exported sample chain: {output_path}")
                    print(f"  Duration: {duration:.2f}s")
                    print(f"  Sample rate: {self.sr}Hz")
                    print(f"  Samples: {len(chain_audio):,}")

                    # Generate .slc file if requested
                    if generate_slc:
                        from slc_generator import SLCGenerator
                        slc_gen = SLCGenerator()
                        slc_path = slc_gen.generate_from_audio_file(output_path, chain_slices, len(chain_audio))

                    return output_path

                elif export_mode == 'individual':
                    # Export each slice as a separate file
                    output_paths = []

                    for s in slices:
                        audio_segment = self.audio[s['start']:s['end']]
                        filename = f'{prefix}_{s["index"]:03d}.wav'
                        output_path = os.path.join(output_dir, filename)
                        sf.write(output_path, audio_segment, self.sr)
                        output_paths.append(output_path)

                    print(f"✓ Exported {len(output_paths)} individual slice files to: {output_dir}")
                    return output_paths

                else:
                    raise ValueError(f"Unknown export_mode: {export_mode}")

# Quick test
if __name__ == '__main__':
    slicer = AudioSlicer()
    # We'll test this once you have an audio file!
    print("AudioSlicer module ready!")
