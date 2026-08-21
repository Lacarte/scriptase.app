"""On-demand deterministic virality scoring for Script Studio documents."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any

from scriptase.modules.viral.models import SCORER_ID, SCORER_VERSION, ViralScore
from scriptase.modules.viral.providers.contract import ViralRequest
from scriptase.modules.viral.service import score_script
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join
from scriptase.scripts.models import SCRIPT_ID_RE
from scriptase.scripts import store as script_store


_CACHE_SCHEMA_VERSION = 1
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _thread_lock(script_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(script_id, threading.Lock())


def _cache_path(script_id: str) -> str:
    if not isinstance(script_id, str) or not SCRIPT_ID_RE.fullmatch(script_id):
        raise ValueError("script_id must match scr_[A-Z0-9]{6}")
    return safe_join(script_store._scripts_dir, f"{script_id}.virality.json")


def _request(script_id: str, text: str) -> ViralRequest:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    # A Script Studio body carries its labels (Hook:/Build:/Climax:/CTA:).
    # Parse them into `sections` so the scorer sees the structure — without
    # this, hook/CTA/balance all read as missing and the score craters.
    from scriptase.modules.script.engine import parse_story_sections

    parsed = parse_story_sections(text)
    sections = {k: v for k, v in (parsed.get("sections") or {}).items() if v}
    request = ViralRequest(
        job_id=script_id,
        sections=sections,
        story_text=parsed.get("story_text") or text,
    )
    if not request.has_content:
        raise ValueError("Write a script before checking virality")
    return request


def _input_hash(request: ViralRequest) -> str:
    canonical = json.dumps(
        {
            "scorer": SCORER_ID,
            "scorer_version": SCORER_VERSION,
            "sections": request.sections,
            "story_text": request.story_text,
            "target_duration": request.target_duration,
            "narrative_roles": request.narrative_roles,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_matching(script_id: str, input_hash: str) -> ViralScore | None:
    try:
        cached = safe_json_read(_cache_path(script_id))
        if (
            cached.get("schema_version") != _CACHE_SCHEMA_VERSION
            or cached.get("input_hash") != input_hash
            or cached.get("scorer") != SCORER_ID
            or cached.get("scorer_version") != SCORER_VERSION
        ):
            return None
        return ViralScore.model_validate(cached.get("result"))
    except (AttributeError, FileNotFoundError, OSError, TypeError, ValueError):
        return None


def score_script_text(script_id: str, text: str) -> tuple[ViralScore, bool]:
    """Return the cached score for identical text, otherwise score and cache it."""
    request = _request(script_id, text)
    input_hash = _input_hash(request)
    with _thread_lock(script_id):
        cached = _read_matching(script_id, input_hash)
        if cached is not None:
            return cached, True

        result = score_script(
            sections=request.sections,
            story_text=request.story_text,
            target_duration=request.target_duration,
            narrative_roles=request.narrative_roles,
        )
        os.makedirs(script_store._scripts_dir, exist_ok=True)
        safe_json_write(
            _cache_path(script_id),
            {
                "schema_version": _CACHE_SCHEMA_VERSION,
                "script_id": script_id,
                "input_hash": input_hash,
                "scorer": SCORER_ID,
                "scorer_version": SCORER_VERSION,
                "scored_at": now_iso(),
                "result": result.model_dump(mode="json"),
            },
            indent=2,
        )
        return result, False


def llm_score_script_text(script_id: str, text: str) -> tuple[ViralScore | None, str]:
    """A second, semantic virality opinion from the LLM-judge viral provider.

    Best-effort and never fatal: the deterministic score is the guarantee, this
    is a bonus that needs a reachable, funded webhook. Returns (score, "") on
    success or (None, reason) so the caller can show why it is missing. Not
    cached — an LLM opinion is non-deterministic, so a stored one would mislead.
    """
    try:
        request = _request(script_id, text)
        from scriptase.modules.viral.providers.llm_judge.provider import create as _make_judge

        return _make_judge().score(request), ""
    except Exception as exc:  # noqa: BLE001 — never fail the request over the bonus
        # `str(exc)` here is our own ProviderError safe message, not raw webhook text.
        return None, str(exc)[:300]


def cached_script_score(script_id: str, text: str) -> dict[str, Any] | None:
    """Read a valid score without running the scorer (used when opening a script)."""
    request = _request(script_id, text) if text.strip() else None
    if request is None:
        return None
    cached = _read_matching(script_id, _input_hash(request))
    return cached.model_dump(mode="json") if cached is not None else None


__all__ = ["cached_script_score", "llm_score_script_text", "score_script_text"]
