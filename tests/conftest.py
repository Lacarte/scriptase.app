"""Shared pytest configuration.

``live`` tests hit a real provider or network service and are skipped unless
``STS_LIVE=1``. Several live providers are known-unavailable (the WaveSpeed key
returns 401, the hosted n8n webhook is retired, OpenRouter's balance is
negative, one video provider needs a human driving a browser), so the marker is
the default-off gate rather than an opt-out.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Step 9.2: create_app starts schedule/watch/cadence threads by default for
# real servers. Keep unit tests free of those daemons unless a test opts in.
os.environ.setdefault("SCRIPTASE_DISABLE_TRIGGERS", "1")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("STS_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live provider test; set STS_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
