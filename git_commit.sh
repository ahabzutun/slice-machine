#!/bin/bash
# Git commit script for slice-machine

echo "🚀 SLICE-MACHINE GIT COMMIT"
echo "============================"
echo ""

cd ~/projects/slice-machine || exit 1

# Check if git repo exists
if [ ! -d ".git" ]; then
    echo "⚠️  Not a git repository yet!"
    read -p "Initialize git repository? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git init
        echo "✓ Initialized git repository"
    else
        echo "❌ Aborted"
        exit 1
    fi
fi

# Check git status
echo "📋 Current git status:"
echo ""
git status --short
echo ""

# Add all files
echo "➕ Adding files to git..."
git add .

# Show what will be committed
echo ""
echo "📝 Files to be committed:"
echo ""
git status --short
echo ""

# Ask for confirmation
read -p "Proceed with commit? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Aborted"
    exit 1
fi

# Commit with a nice message
echo ""
echo "💾 Committing..."
git commit -m "🎉 Initial release: Complete ER-301 sample chain generator

Features:
- Intelligent onset detection and slicing
- 128-slice organization with smart grouping
- Native .slc file generation (reverse-engineered format!)
- Batch processing and file combining
- Full documentation and examples

This represents the successful reverse engineering of the ER-301's
binary .slc format through hardware testing and analysis."

echo ""
echo "✓ Committed!"
echo ""

# Check if remote exists
if git remote | grep -q origin; then
    echo "🌐 Remote 'origin' exists:"
    git remote -v
    echo ""
    read -p "Push to origin? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git push -u origin main 2>/dev/null || git push -u origin master
        echo "✓ Pushed to remote!"
    fi
else
    echo "📡 No remote repository configured"
    echo ""
    echo "To add GitHub remote:"
    echo "  git remote add origin https://github.com/YOUR_USERNAME/slice-machine.git"
    echo "  git branch -M main"
    echo "  git push -u origin main"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ Done! Your project is committed and ready to share!"
echo ""
echo "Recent commits:"
git log --oneline -3
