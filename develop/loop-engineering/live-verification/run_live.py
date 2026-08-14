"""Run the step 6.1 live verification suite with STS_LIVE=1 (dev-only helper)."""
import os
import sys

os.environ["STS_LIVE"] = "1"
sys.path.insert(0, os.getcwd())  # match `python -m pytest` run from the repo root

import pytest

sys.exit(pytest.main(["tests/test_live_providers.py", "-v", "--tb=long", *sys.argv[1:]]))
