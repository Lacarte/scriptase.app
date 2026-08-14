"""Paths and environment for Scriptase.

Single source of truth for filesystem locations. Nothing else in the codebase
constructs a repo-relative absolute path by hand.

The ``output/`` layout deliberately stays V2-compatible so the Phase 10 import
works without rewriting paths.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Managed roots. Everything the app writes lives under one of these.
OUTPUT_DIR = Path(os.environ.get("SCRIPTASE_OUTPUT_DIR") or ROOT / "output")
SETTINGS_DIR = Path(os.environ.get("SCRIPTASE_SETTINGS_DIR") or ROOT / "settings")
RESOURCES_DIR = ROOT / "resources"
MODELS_DIR = Path(os.environ.get("SCRIPTASE_MODELS_DIR") or ROOT / "models")
BIN_DIR = Path(os.environ.get("SCRIPTASE_BIN_DIR") or ROOT / "bin")
STATIC_DIST_DIR = ROOT / "static" / "dist"

# Frontend build output, served by Flask in production.
FRONTEND_DIR = ROOT / "frontend"

# Workflow and provider API routes stay loopback-only: they describe and mutate
# the credential store.
HOST = os.environ.get("SCRIPTASE_HOST", "127.0.0.1")
PORT = int(os.environ.get("SCRIPTASE_PORT", "5000"))
DEBUG = os.environ.get("SCRIPTASE_DEBUG", "0") == "1"

# Tests that call a real provider are gated behind this flag and the
# ``live`` pytest marker.
LIVE_TESTS = os.environ.get("STS_LIVE") == "1"

MANAGED_ROOTS = (OUTPUT_DIR, SETTINGS_DIR, RESOURCES_DIR, MODELS_DIR, BIN_DIR)


def ensure_runtime_dirs() -> None:
    """Create the writable roots the app expects. Safe to call repeatedly."""
    for directory in (OUTPUT_DIR, SETTINGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
