"""LaMa inpainting client — bridges main env to the isolated worker.

The LaMa model has incompatible dependencies (numpy<2, torch 2.11) so it
runs in `_dev/venvs/lama/` as a long-lived subprocess. This client lazily
spawns the worker on first use, keeps it warm across calls, and exposes a
simple ``inpaint(image_path, mask_path, output_path)`` API.

If the worker venv is missing or fails to start, ``inpaint()`` returns False
and callers should fall back to OpenCV inpainting.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
import time

from loguru import logger

from config import ROOT_DIR

# Repository-relative path to the isolated venv created by:
#   python -m venv _dev/venvs/lama
#   _dev/venvs/lama/Scripts/pip install simple-lama-inpainting
# V2 walked up from `__file__`; this package sits a level deeper, and `config`
# already owns the repository root, so it is read rather than recomputed.
_VENV_PYTHON_WIN = os.path.join(ROOT_DIR, "_dev", "venvs", "lama", "Scripts", "python.exe")
_VENV_PYTHON_NIX = os.path.join(ROOT_DIR, "_dev", "venvs", "lama", "bin", "python")
_WORKER_SCRIPT = os.path.join(os.path.dirname(__file__), "lama_worker.py")

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_disabled = False  # Set True after a permanent failure to skip retries


def _venv_python() -> str | None:
    if os.path.isfile(_VENV_PYTHON_WIN):
        return _VENV_PYTHON_WIN
    if os.path.isfile(_VENV_PYTHON_NIX):
        return _VENV_PYTHON_NIX
    return None


def _spawn_worker() -> subprocess.Popen | None:
    """Start the LaMa worker subprocess and wait for the ready signal."""
    py = _venv_python()
    if py is None:
        logger.warning(
            "[lama] Isolated venv not found at _dev/venvs/lama/. "
            "Run: python -m venv _dev/venvs/lama && _dev/venvs/lama/Scripts/pip install simple-lama-inpainting"
        )
        return None

    if not os.path.isfile(_WORKER_SCRIPT):
        logger.warning("[lama] Worker script missing: {}", _WORKER_SCRIPT)
        return None

    logger.info("[lama] Spawning worker subprocess (loading model — first call ~3-5s)")
    try:
        proc = subprocess.Popen(
            [py, _WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
            cwd=_REPO_ROOT,
        )
    except Exception as exc:
        logger.warning("[lama] Failed to spawn worker: {}", exc)
        return None

    # Wait for ready message. Cached model loads in ~20s on CPU; first-run
    # download adds another 30-90s. We allow generous headroom because
    # PyTorch's download progress goes to stderr (not captured here).
    deadline = time.time() + 180.0
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr = (proc.stderr.read() or "").strip()
            logger.warning("[lama] Worker exited during startup: {}", stderr or "<no stderr>")
            return None
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        try:
            payload = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if payload.get("ready"):
            logger.success("[lama] Worker ready")
            return proc
        if payload.get("error"):
            logger.warning("[lama] Worker init error: {}", payload["error"])
            try:
                proc.kill()
            except Exception:
                pass
            return None

    logger.warning("[lama] Worker startup timed out")
    try:
        proc.kill()
    except Exception:
        pass
    return None


def _ensure_worker() -> subprocess.Popen | None:
    """Return a live worker, spawning one if needed. None if unavailable."""
    global _proc, _disabled
    if _disabled:
        return None
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return _proc
        # Worker died — try to respawn once
        if _proc is not None:
            logger.warning("[lama] Worker exited unexpectedly, respawning")
            _proc = None
        _proc = _spawn_worker()
        if _proc is None:
            _disabled = True  # Don't retry forever
        return _proc


def is_available() -> bool:
    """Cheap check — does the venv exist?"""
    return _venv_python() is not None


def inpaint(image_path: str, mask_path: str, output_path: str, timeout: float = 60.0) -> bool:
    """Inpaint *image_path* using *mask_path*, writing to *output_path*.

    Returns True on success, False if LaMa is unavailable or the call failed.
    Callers should fall back to a different inpainting method on False.
    """
    proc = _ensure_worker()
    if proc is None:
        return False

    job = {"in": image_path, "mask": mask_path, "out": output_path}
    with _lock:
        try:
            proc.stdin.write(json.dumps(job) + "\n")
            proc.stdin.flush()
        except Exception as exc:
            logger.warning("[lama] Failed to write job: {}", exc)
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                logger.warning("[lama] Worker died mid-job")
                return False
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.02)
                continue
            try:
                resp = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if resp.get("ok"):
                return True
            logger.warning("[lama] Inpaint failed: {}", resp.get("error", "<unknown>"))
            return False

    logger.warning("[lama] Inpaint timed out after {}s", timeout)
    return False


def shutdown() -> None:
    """Cleanly stop the worker subprocess."""
    global _proc
    with _lock:
        if _proc is None:
            return
        try:
            _proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
            _proc.stdin.flush()
            _proc.wait(timeout=5)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass
        _proc = None


atexit.register(shutdown)
