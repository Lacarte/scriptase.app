"""Shared ffmpeg/ffprobe path resolution helpers."""

from __future__ import annotations

import os
import shutil

from config import BIN_DIR


def _resolve_binary(binary_name: str) -> str | None:
    executable = f"{binary_name}.exe" if os.name == "nt" else binary_name
    local_path = os.path.join(BIN_DIR, executable)
    if os.path.isfile(local_path):
        return local_path
    return shutil.which(binary_name)


def find_ffmpeg() -> str | None:
    """Locate the ffmpeg binary in bin/ first, then on PATH."""
    return _resolve_binary("ffmpeg")


def find_ffprobe() -> str | None:
    """Locate the ffprobe binary in bin/ first, then on PATH."""
    return _resolve_binary("ffprobe")
