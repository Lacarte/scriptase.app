"""Paths and environment for Scriptase.

Single source of truth for filesystem locations. Nothing else in the codebase
constructs a repo-relative absolute path by hand.

The ``output/`` layout deliberately stays V2-compatible so the Phase 10 import
works without rewriting paths. That is also why the per-module directory
constants below keep their V2 names and their V2 ``str`` type: the engine and
provider platform ported in step 0.2 do ``os.path.join`` on them, and the
managed-path helpers in ``scriptase.shared.security`` compare them as strings.
``ROOT`` and ``STATIC_DIST_DIR`` stay ``Path`` for new code.
"""

from __future__ import annotations

import os
import random
import string
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The ported platform reads `ROOT_DIR` (V2 spelling, str).
ROOT_DIR = str(ROOT)

# Managed roots. Everything the app writes lives under one of these.
OUTPUT_DIR = str(Path(os.environ.get("SCRIPTASE_OUTPUT_DIR") or ROOT / "output"))
SETTINGS_DIR = str(Path(os.environ.get("SCRIPTASE_SETTINGS_DIR") or ROOT / "settings"))
RESOURCES_DIR = str(ROOT / "resources")
MODELS_DIR = str(Path(os.environ.get("SCRIPTASE_MODELS_DIR") or ROOT / "models"))
BIN_DIR = str(Path(os.environ.get("SCRIPTASE_BIN_DIR") or ROOT / "bin"))
LOG_DIR = str(ROOT / "logs")
TMP_DIR = str(ROOT / "tmp")
TTS_CACHE_DIR = os.path.join(TMP_DIR, "tts")

STATIC_DIST_DIR = ROOT / "static" / "dist"
FRONTEND_DIR = ROOT / "frontend"

# ---------------------------------------------------------------------------
# Managed output layout — V2-compatible on purpose (Phase 10 import).
#
# Directory *names* keep their V2 spellings even where the owning package was
# renamed (`storyboard`, `animator`), because these are on-disk locations of
# existing artifacts rather than import paths. Renaming them would break the
# import this layout exists to serve.
# ---------------------------------------------------------------------------
TRASH_DIR = os.path.join(OUTPUT_DIR, "TRASH")
WORKFLOWS_DIR = os.path.join(OUTPUT_DIR, "workflows")
WORKFLOW_EXECUTIONS_DIR = os.path.join(WORKFLOWS_DIR, "executions")
BRANDING_DIR = os.path.join(OUTPUT_DIR, "branding")
ALIGN_DIR = os.path.join(OUTPUT_DIR, "alignments")
SCENES_DIR = os.path.join(OUTPUT_DIR, "scenes")
STORIES_DIR = os.path.join(OUTPUT_DIR, "stories")
ANIMATOR_DIR = os.path.join(OUTPUT_DIR, "animator")
STORYBOARD_DIR = os.path.join(OUTPUT_DIR, "storyboard")
SEGMENTER_DIR = os.path.join(OUTPUT_DIR, "segmenters")
CAPTIONS_DIR = os.path.join(OUTPUT_DIR, "captions")
TTS_DIR = os.path.join(OUTPUT_DIR, "tts")
EXPORT_DIR = os.path.join(OUTPUT_DIR, "exports")
PROJECTS_DIR = os.path.join(OUTPUT_DIR, "projects")
MUSIC_DIR = os.path.join(OUTPUT_DIR, "musics")
THUMBNAILS_DIR = os.path.join(OUTPUT_DIR, "thumbnails")
# Channel profiles (step 1.1). One JSON document per channel id.
CHANNELS_DIR = os.path.join(OUTPUT_DIR, "channels")
# Artifact index (step 1.2). Metadata only — blob files stay under the
# per-module trees (tts/, scenes/, …) for V2 import compatibility.
ARTIFACTS_DIR = os.path.join(OUTPUT_DIR, "artifacts")
# Job documents (step 1.4). One JSON document per job id; channel snapshots
# live inside each document (provider instance references only — never secrets).
JOBS_DIR = os.path.join(OUTPUT_DIR, "jobs")
# Scene identity records (step 1.6). One JSON document per stable scene id
# (scn_XXXXXX). Distinct from SCENES_DIR, which holds Scene Director
# blueprint payloads under the V2 layout.
SCENE_RECORDS_DIR = os.path.join(OUTPUT_DIR, "scene_records")

# Read-only built-in asset library.
APP_ASSETS_DIR = RESOURCES_DIR
MUSIC_LIBRARY_DIR = os.path.join(APP_ASSETS_DIR, "sounds", "music")
FONTS_DIR = os.path.join(APP_ASSETS_DIR, "fonts")

# The retired V2 selection store. Read once by the v2 settings migration and
# never written; `settings/settings.json` is the selection authority.
APP_CONFIG_PATH = os.path.join(ROOT_DIR, "app-config.json")

# ---------------------------------------------------------------------------
# Provider environment fallbacks.
#
# These are *defaults a provider may read*, never values an API returns. A
# provider's `manifest.environment` maps its settings key to the variable it
# falls back to, and `ProviderInstance.resolve_settings()` is the only place a
# fallback is consumed. Step 3.4 replaces the stored half of this with secret
# references; the env fallback stays.
# ---------------------------------------------------------------------------
N8N_WEBHOOK_URL = os.environ.get(
    "N8N_WEBHOOK_URL", "http://localhost:5678/webhook/scene-blueprint-generator"
)
N8N_ASSET_WEBHOOK_URL = os.environ.get(
    "N8N_ASSET_WEBHOOK_URL", "http://localhost:5678/webhook/image-generator"
)
N8N_STORY_WEBHOOK_URL = os.environ.get(
    "N8N_STORY_WEBHOOK_URL", "http://localhost:5678/webhook/story-generator"
)
N8N_STORYBOARD_WEBHOOK_URL = os.environ.get(
    "N8N_STORYBOARD_WEBHOOK_URL", "http://localhost:5678/webhook/storyboard-generator"
)
N8N_CLASSIFY_WEBHOOK_URL = os.environ.get(
    "N8N_CLASSIFY_WEBHOOK_URL", "http://localhost:5678/webhook/classify-style"
)

KIE_AI_API_KEY = os.environ.get("KIE_AI_API_KEY", "")
KIE_AI_BASE_URL = os.environ.get("KIE_AI_BASE_URL", "https://api.kie.ai/api/v1")
KIE_AI_MODEL = os.environ.get("KIE_AI_MODEL", "google/nano-banana")

INWORLD_API_KEY = os.environ.get("INWORLD_API_KEY", "")
INWORLD_TTS_MODEL = os.environ.get("INWORLD_TTS_MODEL", "inworld-tts-1.5-max")
INWORLD_TTS_BASE_URL = os.environ.get(
    "INWORLD_TTS_BASE_URL", "https://api.inworld.ai/tts/v1"
)

WAVESPEED_API_KEY = os.environ.get("WAVESPEED_API_KEY", "")

# Workflow and provider API routes stay loopback-only: they describe and mutate
# the credential store.
HOST = os.environ.get("SCRIPTASE_HOST", "127.0.0.1")
PORT = int(os.environ.get("SCRIPTASE_PORT", "5000"))
DEBUG = os.environ.get("SCRIPTASE_DEBUG", "0") == "1"

# Tests that call a real provider are gated behind this flag and the
# ``live`` pytest marker.
LIVE_TESTS = os.environ.get("STS_LIVE") == "1"

MANAGED_ROOTS = (OUTPUT_DIR, SETTINGS_DIR, RESOURCES_DIR, MODELS_DIR, BIN_DIR)

RUNTIME_DIRS = (
    OUTPUT_DIR, SETTINGS_DIR, LOG_DIR, TMP_DIR, TRASH_DIR, WORKFLOWS_DIR,
    WORKFLOW_EXECUTIONS_DIR, BRANDING_DIR, ALIGN_DIR, SCENES_DIR, STORIES_DIR,
    ANIMATOR_DIR, STORYBOARD_DIR, SEGMENTER_DIR, CAPTIONS_DIR, TTS_DIR,
    EXPORT_DIR, PROJECTS_DIR, MUSIC_DIR, THUMBNAILS_DIR, CHANNELS_DIR,
    ARTIFACTS_DIR, JOBS_DIR, SCENE_RECORDS_DIR, MODELS_DIR, TTS_CACHE_DIR,
)


def ensure_runtime_dirs() -> None:
    """Create the writable roots the app expects. Safe to call repeatedly."""
    for directory in RUNTIME_DIRS:
        os.makedirs(directory, exist_ok=True)


# The ported persistence, scheduler, and media-job layers assume their roots
# exist at import time, exactly as they did in V2.
ensure_runtime_dirs()


# ---------------------------------------------------------------------------
# Project id generator — V2-compatible ids, so imported projects keep their
# names and a freshly generated id can never collide with one.
# ---------------------------------------------------------------------------

_PROJECT_ID_ROOTS = (
    ALIGN_DIR, SCENES_DIR, ANIMATOR_DIR, STORYBOARD_DIR, SEGMENTER_DIR,
    CAPTIONS_DIR, TTS_DIR, PROJECTS_DIR,
)


def _collect_existing_project_ids() -> set[str]:
    """Scan project-bearing output locations for identifiers already in use."""
    existing: set[str] = set()
    for search_dir in _PROJECT_ID_ROOTS:
        if not os.path.isdir(search_dir):
            continue
        for entry in os.listdir(search_dir):
            if os.path.isdir(os.path.join(search_dir, entry)):
                existing.add(entry)
    return existing


def generate_project_id(prefix: str = "pm") -> str:
    """Generate a unique project id like ``pm_SLLGTM``.

    Prefixes: ``pm`` for a manually created project, ``pp`` for one created by
    an automated run.
    """
    existing = _collect_existing_project_ids()
    charset = string.ascii_uppercase + string.digits
    for _ in range(100):
        candidate = f"{prefix}_" + "".join(random.choices(charset, k=6))
        if candidate not in existing:
            return candidate
    return (
        f"{prefix}_"
        + datetime.now().strftime("%H%M%S")
        + "".join(random.choices(charset, k=3))
    )
