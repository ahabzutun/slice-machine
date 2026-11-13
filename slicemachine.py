#!/usr/bin/env python3
"""Slice Machine — the desktop app for the slicer, merger, splitter, NerdSEQ preparer and GRID kit
writer in src/. Same look as Kontrolleur. Runs on macOS and Linux (Python + Qt / PySide6)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from slicemachine.app import main  # noqa: E402

if __name__ == "__main__":
    main()
