# Configurable Slice Length Feature

## Overview
Added configurable slice length modes to differentiate between percussive and melodic content slicing. This allows the slicer to intelligently process different types of audio material with appropriate slice durations.

## New Features

### 1. Three Slice Length Modes

**PERCUSSIVE Mode** (Default)
- Min duration: 30ms
- Target duration: 80ms
- Hop length: 256 (high sensitivity)
- Best for: Drum breaks, percussion, tight rhythmic content
- Result: Short, snappy slices that capture individual hits

**HYBRID Mode**
- Min duration: 100ms
- Target duration: 300ms
- Hop length: 512 (medium sensitivity)
- Best for: Mixed content, loops with both percussion and melody
- Result: Medium-length slices balancing detail and musicality

**MELODIC Mode**
- Min duration: 200ms
- Target duration: 600ms
- Hop length: 1024 (low sensitivity)
- Best for: Melodic phrases, harmonic content, sustained notes
- Result: Long slices that capture complete musical phrases

### 2. Smart Duration Filtering

Added `filter_slices_by_duration()` function that:
- Removes slices shorter than the mode's minimum duration
- Reports how many slices were rejected
- Shows debug info for first few rejected slices
- Ensures only meaningful content makes it to the final chain

### 3. Intelligent Subdivision

Updated `force_target_slices()` to respect minimum durations:
- Only subdivides slices that are at least 2x the minimum duration
- Prevents creation of slices below minimum threshold
- Gracefully handles cases where target count cannot be reached
- Reports when subdivision limits are hit

### 4. Enhanced UI

Added new Step 3a in the interactive flow:
```
⏱️  Step 3a: Slice Length Mode
Choose target slice length based on your content type:

  1. PERCUSSIVE
     Short, tight slices for drums/percussion (30-150ms)
     Min: 30ms | Target: 80ms

  2. HYBRID
     Medium slices for mixed content (100-400ms)
     Min: 100ms | Target: 300ms

  3. MELODIC
     Long slices for melodic/harmonic content (200-800ms)
     Min: 200ms | Target: 600ms
```

### 5. Mode-Specific Onset Detection

Onset detection now uses mode-specific parameters:
- `hop_length` controls sensitivity (smaller = more sensitive)
- Percussive mode finds more transients
- Melodic mode finds fewer, more significant musical events
- Results in better slice boundaries for each content type

## Technical Implementation

### Configuration Structure
```python
SLICE_MODES = {
    'percussive': {
        'min_duration_ms': 30,
        'target_duration_ms': 80,
        'hop_length': 256,
        'description': 'Short, tight slices for drums/percussion (30-150ms)'
    },
    # ... other modes
}
```

### Key Function Changes

1. **filter_slices_by_duration(slices, min_duration_ms, sr)**
   - New function to enforce minimum slice lengths
   - Called after onset detection, before subdivision

2. **force_target_slices(..., min_duration_ms=None)**
   - Added optional `min_duration_ms` parameter
   - Checks if slices can be subdivided before attempting
   - Provides clear feedback when limits are reached

3. **onset detection calls**
   - Now use `hop_length=slice_config['hop_length']`
   - More sensitive for percussive, less for melodic

### Processing Pipeline

The updated pipeline flow:
1. Load audio
2. **Apply CDP pre-processing (if enabled)**
3. Detect onsets using mode-specific hop_length
4. Convert onset frames to slices
5. **Filter by minimum duration** ← NEW
6. Reduce to target if too many
7. Force exact target count (respecting minimums)
8. Remove silence (if enabled)
9. Re-subdivide if needed (respecting minimums)
10. Apply CDP post-processing (if enabled)
11. Export with reorganization

## Usage Examples

### Drum Breaks (Percussive Mode)
```bash
python3 src/interactive_slicer.py

# Select your drum break file
# Choose PERCUSSIVE mode (option 1)
# Result: 128 tight slices, 30-150ms each
```

### Melodic Loops (Melodic Mode)
```bash
python3 src/interactive_slicer.py

# Select your melodic loop file
# Choose MELODIC mode (option 3)
# Result: 128 longer slices, 200-800ms each, capturing full phrases
```

### Mixed Content (Hybrid Mode)
```bash
python3 src/interactive_slicer.py

# Select your mixed loop file
# Choose HYBRID mode (option 2)
# Result: 128 medium slices, 100-400ms each, balancing both
```

## Summary Output

The summary now includes slice mode information:
```
📋 SUMMARY
Files: 1
Mode: single
Target slices: 128 (FORCED)
Slice mode: PERCUSSIVE
  Min duration: 30ms
  Target duration: 80ms
  Hop length: 256
```

Results also show the mode:
```
📊 RESULTS
Slice mode: PERCUSSIVE (30-80ms)
Total slices: 128
Shortest: 1,440 samples (30.00ms)
Longest: 6,912 samples (144.00ms)
Average: 3,456 samples (72.00ms)
```

## Benefits

1. **Better Content Matching**: Different modes optimize for different audio types
2. **User Control**: Choose the right mode for your material
3. **Quality Assurance**: Minimum durations prevent unusably short slices
4. **Intelligent Subdivision**: Respects musical boundaries when reaching target count
5. **Flexibility**: Three modes cover most use cases, from drums to melodies

## Backward Compatibility

- Default mode is PERCUSSIVE, matching previous behavior
- All existing workflows continue to work
- CDP integration unchanged
- Silence removal still works with all modes

## Future Enhancements

Potential additions:
- Custom mode with user-defined min/max/hop values
- Auto-detection of content type
- Per-slice adaptive duration based on content analysis
- Visual preview of slice boundaries before processing

---

**Implementation Date**: February 2026
**Feature Status**: ✅ Complete and tested
