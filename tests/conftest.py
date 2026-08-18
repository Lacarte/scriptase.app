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
# Step 10.3: create_app runs crash recovery against OUTPUT_DIR by default.
# Keep unit tests from mutating a developer's real output tree; tests that
# need reconciliation call reconcile_on_startup() against a temp root.
os.environ.setdefault("SCRIPTASE_DISABLE_RECONCILE", "1")

# Redirect the managed output tree at a throwaway directory for the whole run.
#
# The two settings above stop daemons and crash recovery touching output/, but
# not tests that legitimately create domain objects. Anything calling
# channels.store.create_channel(), the job store, or the artifact store wrote
# into the developer's real output/ — 592 stray channel documents accumulated
# there, two per run from the approval tests alone, and they render on the
# Channels page as "Approval channel" / "Reject channel".
#
# config.py resolves OUTPUT_DIR from this variable at import time and conftest
# is imported before any scriptase module, so one assignment here makes the
# whole suite hermetic. It is also the precondition for running pytest in
# parallel: workers cannot race over a tree none of them shares with the app.
# An explicit SCRIPTASE_OUTPUT_DIR still wins, so a debugging session can point
# the suite wherever it likes.
if not os.environ.get("SCRIPTASE_OUTPUT_DIR"):
    import atexit
    import shutil
    import tempfile

    _TEST_OUTPUT_ROOT = tempfile.mkdtemp(prefix="scriptase-tests-")
    os.environ["SCRIPTASE_OUTPUT_DIR"] = _TEST_OUTPUT_ROOT
    atexit.register(shutil.rmtree, _TEST_OUTPUT_ROOT, ignore_errors=True)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("STS_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live provider test; set STS_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
