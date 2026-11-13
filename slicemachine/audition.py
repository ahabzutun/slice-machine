"""Listen to a slice: writes it to a temporary .wav and plays it with the system's player
(afplay on macOS; pw-play, paplay, aplay or ffplay on Linux). No extra Python packages needed."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional

_proc: Optional[subprocess.Popen] = None
_tmp = os.path.join(tempfile.gettempdir(), f"slicemachine-audition-{os.getpid()}.wav")


def player() -> Optional[List[str]]:
    if sys.platform == "darwin":
        return ["afplay"]
    for cmd in (["pw-play"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def available() -> bool:
    return player() is not None


def stop():
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
    _proc = None


def play(path: str, start: int = 0, end: Optional[int] = None) -> str:
    """Plays frames start…end of `path` (frames of the file itself). Returns "" or what went wrong."""
    global _proc
    cmd = player()
    if cmd is None:
        return "No audio player found (install pipewire-utils, pulseaudio-utils or alsa-utils)."
    stop()
    try:
        import soundfile as sf
        with sf.SoundFile(path) as f:
            sr = f.samplerate
            end = f.frames if end is None else min(end, f.frames)
            f.seek(max(0, start))
            data = f.read(max(0, end - start), dtype="float32", always_2d=True)
        if len(data) == 0:
            return "That slice is empty."
        sf.write(_tmp, data, sr, subtype="PCM_16")
        _proc = subprocess.Popen(cmd + [_tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return f"Could not play it: {e}"
    return ""


def cleanup():
    stop()
    try:
        os.remove(_tmp)
    except OSError:
        pass
