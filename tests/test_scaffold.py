"""Step 0.1 — the scaffold matches the layout Phases 0-10 are written against.

These are structural assertions, not placeholders. Later steps fill the packages
in; if one is renamed or dropped without updating the plan, this fails loudly
instead of surfacing as an import error three phases later.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PACKAGES = [
    "scriptase",
    "scriptase.artifacts",
    "scriptase.channels",
    "scriptase.engine",
    "scriptase.engine.adapters",
    "scriptase.jobs",
    "scriptase.modules",
    "scriptase.modules.captions",
    "scriptase.modules.compose",
    "scriptase.modules.image",
    "scriptase.modules.music",
    "scriptase.modules.scene_director",
    "scriptase.modules.script",
    "scriptase.modules.segmenter",
    "scriptase.modules.timing",
    "scriptase.modules.tts",
    "scriptase.modules.video",
    "scriptase.providers",
    "scriptase.review",
    "scriptase.shared",
]

# Ignoring these is load-bearing, not cosmetic. ``n8n-data`` alone carries
# several thousand copied build assets, and ``venv``/``node_modules`` would
# swamp every diff the review stage reads.
MUST_BE_IGNORED = [
    "venv/lib/site-packages/pytest/__init__.py",
    "output/projects/demo/scene_01.png",
    "node_modules/vite/index.js",
    "frontend/node_modules/vite/index.js",
    "static/dist/index.js",
    "logs/run.log",
    "scriptase/__pycache__/__init__.cpython-310.pyc",
    "develop/loop-engineering/live-verification/n8n-data/nodes.json",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    assert importlib.import_module(name) is not None


def test_config_paths_are_under_the_repo_root():
    import config

    assert config.ROOT == ROOT
    for managed in config.MANAGED_ROOTS:
        assert managed.is_absolute()


def test_plan_documents_are_present():
    plans = ROOT / "plans"
    for name in ("proposition-final.md", "implementation-plan.md", "contracts.md"):
        document = plans / name
        assert document.is_file(), f"missing plans/{name}"
        assert document.stat().st_size > 0, f"empty plans/{name}"


def test_gitignore_covers_every_generated_tree():
    import subprocess

    # Paths go as arguments, not through --stdin. In text mode Python rewrites
    # every \n to \r\n on Windows, git keeps the CR as part of the pathname and
    # then C-quotes the result because it holds a control character -- so each
    # echoed path comes back as "venv/...\r" and matches nothing.
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *MUST_BE_IGNORED],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode in (0, 1), f"git check-ignore failed: {result.stderr}"
    ignored = set(result.stdout.split())
    missing = [path for path in MUST_BE_IGNORED if path not in ignored]
    assert not missing, f"not covered by .gitignore: {missing}"


def test_pytest_live_marker_is_registered():
    import configparser

    parser = configparser.ConfigParser()
    parser.read(ROOT / "pytest.ini", encoding="utf-8")
    markers = parser["pytest"]["markers"]
    assert "live:" in markers
    assert "--strict-markers" in parser["pytest"]["addopts"]


@pytest.mark.live
def test_live_marker_is_skipped_by_default():
    raise AssertionError("live tests must not run without STS_LIVE=1")
