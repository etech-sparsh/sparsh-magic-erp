"""Locate the ffmpeg binary without depending on the process PATH.

A freshly winget/choco-installed ffmpeg only lands on PATH for *new* shells, so a
long-running backend (or one restarted in a stale terminal) won't find it via a
bare ``ffmpeg`` command. This resolver checks an explicit setting first, then
PATH, then the well-known install locations on Windows/macOS/Linux, and caches
the result. Both the assistant extractor and the transcription service use it.
"""
from __future__ import annotations

import glob
import os
import shutil
from typing import Optional

from app.config.settings import settings

_cached: Optional[str] = None


def _candidates() -> list[str]:
    paths: list[str] = []
    # 1) Explicit override (settings.FFMPEG_BINARY or FFMPEG_DIR).
    if getattr(settings, "FFMPEG_BINARY", None):
        paths.append(settings.FFMPEG_BINARY)
    if getattr(settings, "FFMPEG_DIR", None):
        paths.append(os.path.join(settings.FFMPEG_DIR, "ffmpeg"))
        paths.append(os.path.join(settings.FFMPEG_DIR, "ffmpeg.exe"))

    # 2) Common Windows install locations (winget / choco / manual).
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        paths += glob.glob(os.path.join(
            local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe",
        ), recursive=True)
        paths += glob.glob(os.path.join(
            local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "bin", "ffmpeg.exe",
        ), recursive=True)
    for base in (r"C:\ProgramData\chocolatey\bin", r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
        paths.append(os.path.join(base, "ffmpeg.exe"))

    # 3) Common POSIX locations.
    paths += ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"]
    return paths


def resolve_ffmpeg() -> Optional[str]:
    """Return an absolute path to a working ffmpeg, or None if unavailable."""
    global _cached
    if _cached and os.path.exists(_cached):
        return _cached

    # PATH lookup first (cheapest, honours a properly-refreshed environment).
    found = shutil.which("ffmpeg")
    if found:
        _cached = found
        return found

    for cand in _candidates():
        if cand and os.path.exists(cand):
            _cached = cand
            return cand
    return None


def ffmpeg_available() -> bool:
    return resolve_ffmpeg() is not None
