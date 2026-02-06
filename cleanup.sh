#!/bin/bash
# Cleanup script for slice-machine project

echo "🧹 SLICE-MACHINE CLEANUP"
echo "========================"
echo ""

cd ~/projects/slice-machine || exit 1

echo "📂 Current directory structure:"
echo ""
find . -maxdepth 3 -not -path '*/venv/*' -not -path '*/__pycache__/*' -not -path '*/.git/*' | sort
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create docs directory if it doesn't exist
echo "📁 Creating docs directory..."
mkdir -p docs

# Remove old/redundant files
echo "🗑️  Removing old files..."

# Remove cue marker writer (doesn't work)
if [ -f "src/cue_marker_writer.py" ]; then
    echo "  Removing src/cue_marker_writer.py (obsolete)"
    rm src/cue_marker_writer.py
fi

# Remove any backup files
if [ -f "src/slc_generator_OLD.py" ]; then
    echo "  Removing src/slc_generator_OLD.py (backup)"
    rm src/slc_generator_OLD.py
fi

# Remove __pycache__ directories
echo "  Removing __pycache__ directories..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Remove .pyc files
echo "  Removing .pyc files..."
find . -name "*.pyc" -delete 2>/dev/null

# Clean up output directory test files (optional)
echo ""
echo "⚠️  Output directory contains test files:"
ls -lh output/ 2>/dev/null | head -10
echo ""
read -p "Do you want to clean output directory? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "  Cleaning output directory..."
    rm -f output/TEST_*.wav output/TEST_*.slc
    rm -f output/bubbles_with_cues*.wav output/bubbles_with_cues*.slc
    rm -f output/*_test_*.wav output/*_test_*.slc
    echo "  ✓ Cleaned test files from output/"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✓ Cleanup complete!"
echo ""
echo "📂 Final structure:"
echo ""
tree -L 2 -I 'venv|__pycache__|*.pyc' . 2>/dev/null || find . -maxdepth 2 -not -path '*/venv/*' -not -path '*/__pycache__/*' | sort
echo ""
echo "Next steps:"
echo "  1. Review the structure above"
echo "  2. Run: python3 /path/to/create_documentation.py"
echo "  3. Review README.md and docs/"
echo "  4. Commit to GitHub"
