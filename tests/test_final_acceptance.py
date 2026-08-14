"""Step 10.4 — Final end-to-end acceptance gate.

Covers the offline form of proposition-final.md § End-to-end acceptance:
Channel from niche preset → Automatic Job → Production projection →
image gate before video → re-segmentation rebinding → export logo across
aspect profiles → zero credential leakage in persisted records.

Live providers stay behind ``@pytest.mark.live``; this suite uses deterministic
executors and managed fixture media so a fresh clone can prove the path without
credits.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.channels.presets import get_presets, preset_to_channel_draft
from scriptase.channels.store import create_channel, get_channel
from scriptase.engine.adapters import AdapterContext, AdapterError
from scriptase.engine.adapters import export as export_adapter
from scriptase.engine.adapters import video as video_adapter
from scriptase.engine.adapters.export import PROFILES
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import load_execution
from scriptase.engine.registry import get_node_type
from scriptase.engine.templates import full_video_template
from scriptase.jobs import store as job_store
from scriptase.jobs.orchestration import start_job
from scriptase.jobs.stage_projection import project_stages
from scriptase.jobs.store import create_job, default_draft
from scriptase.review import open_issues as issue_store
from scriptase.review.gates import QUALITY_GATE_FAILED
from scriptase.review.open_issues import create_open_issue, list_issues
from scriptase.scenes import store as scene_store
from scriptase.scenes.resegment import apply_resegmentation
from scriptase.scenes.store import scene_resolves


# Secret-ish tokens that must never appear in persisted records after a run.
_CREDENTIAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*['\"]?[^'\"\s,]{6,}", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I),
    re.compile(r"client_secret\s*[:=]", re.I),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    channels = tmp_path / "channels"
    jobs = tmp_path / "jobs"
    artifacts = tmp_path / "artifacts"
    scenes = tmp_path / "scene_records"
    issues = tmp_path / "issue_bindings"
    output = tmp_path / "output"
    for path in (channels, jobs, artifacts, scenes, issues, output):
        path.mkdir()
    monkeypatch.setattr(channel_store, "_channels_dir", str(channels))
    monkeypatch.setattr(channel_store, "_trash_dir", str(channels / "trash"))
    monkeypatch.setattr(job_store, "_jobs_dir", str(jobs))
    monkeypatch.setattr(job_store, "_trash_dir", str(jobs / "trash"))
    monkeypatch.setattr(artifact_store, "_artifacts_dir", str(artifacts))
    monkeypatch.setattr(artifact_store, "_output_dir", str(output))
    monkeypatch.setattr(scene_store, "_scenes_dir", str(scenes))
    monkeypatch.setattr(issue_store, "_issues_dir", str(issues))
    return {
        "channels": channels,
        "jobs": jobs,
        "artifacts": artifacts,
        "output": output,
        "tmp": tmp_path,
    }


def _deterministic_full_resolver(output_dir: str):
    """Stable full-video outputs with no live providers."""

    port_defaults = {
        "control": {"ok": True},
        "settings": {
            "channel_name": "acceptance",
            "tone": "calm",
            "style": "cinematic",
            "logo_enabled": True,
            "logo": {"ref": "branding/logo.png"},
            "aspect_ratio": "9:16",
        },
        "script": "Acceptance narration from Channel idea to export.",
        "audio": {"filename": "voice.wav", "artifact_refs": []},
        "metadata": {"duration": 1.0},
        "alignment": {"words": []},
        "segments": {"segments": [{"id": "seg_1", "text": "one"}]},
        "scenes": {
            "scenes": [{
                "id": "scn_ACC001",
                "scene_id": "scn_ACC001",
                "image_prompt": "a quiet harbor at dusk",
            }]
        },
        "images": {
            "ready": 1,
            "total": 1,
            "artifact_refs": ["storyboard/pm_ACCEPT/0/still.png"],
        },
        "assets": {
            "ready": 1,
            "total": 1,
            "artifact_refs": ["animator/pm_ACCEPT/0/clip.mp4"],
        },
        "captions": {"cues": []},
        "track": {"title": "ambient"},
        "project": {
            "assembled_data": {
                "scenes": [{"id": 1, "duration": 1}],
                "total_duration": 1,
            }
        },
        "video": {"filename": "final.mp4"},
        "value": {"filename": "final.mp4"},
    }

    def _write(relative: str, content: bytes) -> str:
        abs_path = os.path.join(output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(content)
        return relative.replace("\\", "/")

    def resolve(node):
        node_type = node.get("type")
        node_id = node.get("id")

        def execute(inputs, config, context):
            definition = get_node_type(node_type) or {}
            result = {}
            project_id = getattr(context, "project_id", None) or "pm_ACCEPT"
            for port in definition.get("outputs", []):
                port_id = port["id"]
                if port_id in port_defaults:
                    result[port_id] = port_defaults[port_id]
                else:
                    result[port_id] = {"ok": True, "from": node_id}
            if node_type == "export.video":
                rel = _write(f"exports/{project_id}_final.mp4", b"fake-mp4-bytes")
                result["video"] = {
                    "filename": os.path.basename(rel),
                    "artifact_refs": [rel],
                }
                result["value"] = result["video"]
            if node_type == "script.input":
                text = (config or {}).get("text") or port_defaults["script"]
                result["script"] = text
            if node_type == "project.setup":
                result["settings"] = {
                    **port_defaults["settings"],
                    **{
                        k: v
                        for k, v in (config or {}).items()
                        if k not in {"api_key", "client_secret", "token"}
                    },
                }
            return result

        return execute

    return resolve


def _scan_for_credentials(blob: str) -> list[str]:
    hits = []
    for pattern in _CREDENTIAL_PATTERNS:
        for match in pattern.finditer(blob):
            hits.append(match.group(0)[:40])
    return hits


def _walk_json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*.json") if p.is_file()]


def _pick_preset_id() -> str:
    presets = get_presets()
    assert presets, "niche preset catalog must ship with the clone"
    if "stoicism_cinematic" in presets:
        return "stoicism_cinematic"
    return next(iter(presets))


# ---------------------------------------------------------------------------
# Acceptance scenarios
# ---------------------------------------------------------------------------


def test_acceptance_channel_from_niche_preset_with_logo_and_pattern(isolated_stores):
    """1. Create a Channel from a seeded niche preset; enable logo; set pattern."""
    presets = get_presets()
    preset_id = _pick_preset_id()
    draft = preset_to_channel_draft(preset_id, presets[preset_id])

    pattern = draft["visual_direction"]["pattern"]
    assert isinstance(pattern, list) and len(pattern) >= 1
    assert "narrative_role" in pattern[0]
    assert "shot" in pattern[0]

    draft["branding"] = {
        **(draft.get("branding") or {}),
        "enabled": True,
        "logo_asset_id": "branding/logo_accept.png",
        "position": "bottom-right",
    }
    draft["export_defaults"] = {
        **(draft.get("export_defaults") or {}),
        "aspect_ratio": "9:16",
    }

    channel = create_channel(draft)
    loaded = get_channel(channel.id)
    assert loaded.name == draft["name"]
    assert loaded.branding.enabled is True
    assert loaded.branding.logo_asset_id == "branding/logo_accept.png"
    dumped = json.dumps(loaded.model_dump(mode="json"), default=str)
    assert _scan_for_credentials(dumped) == []
    assert ":\\" not in (loaded.branding.logo_asset_id or "")


def test_acceptance_automatic_job_channel_to_export(isolated_stores):
    """2–4. Job from Channel, Automatic mode, Run once, Production projection."""
    presets = get_presets()
    preset_id = _pick_preset_id()
    draft = preset_to_channel_draft(preset_id, presets[preset_id])
    draft["branding"] = {
        **(draft.get("branding") or {}),
        "enabled": True,
        "logo_asset_id": "branding/logo_accept.png",
    }
    channel = create_channel(draft)

    workflow = full_video_template()
    workflow["workflow_id"] = "wf_ACCEPT"
    projection = project_stages(workflow)
    keys = [s["key"] for s in projection["stages"]]
    assert keys[0] == "script"
    assert keys[-1] == "export"
    # Production stages are projected from the graph, not a hardcoded list.
    assert "script" in keys and "export" in keys

    job = create_job(default_draft(
        channel_id=channel.id,
        execution_mode="automatic",
        workflow_id="wf_ACCEPT",
        source={
            "mode": "paste",
            "pasted_script": "A quiet stoic reflection on morning light.",
        },
    ))
    assert job.execution_mode == "automatic"
    assert job.channel_id == channel.id
    snapshot = job.channel_snapshot
    snap_text = json.dumps(
        snapshot if isinstance(snapshot, dict) else snapshot.model_dump(mode="json"),
        default=str,
    )
    assert _scan_for_credentials(snap_text) == []

    engine_dir = str(isolated_stores["tmp"] / "engine")
    manager = ExecutionManager(
        output_dir=engine_dir,
        executor_resolver=_deterministic_full_resolver(engine_dir),
    )
    finished = start_job(
        job.id,
        manager=manager,
        workflow=workflow,
        project_id="pm_ACCEPT",
        force=True,
        wait=True,
        timeout=30.0,
    )
    assert finished.status == "completed", (
        f"Automatic Job should complete unattended; got "
        f"status={finished.status} reason={finished.status_reason}"
    )
    record = load_execution(finished.execution_id, root=manager.execution_root)
    assert record["status"] in {"succeeded", "partial"}
    assert record["status"] != "awaiting_approval"

    # Same execution record feeds Production stage projection and Workflow view.
    live_projection = project_stages(workflow, execution=record)
    assert live_projection["stages"]
    export_stage = next(s for s in live_projection["stages"] if s["key"] == "export")
    assert export_stage is not None

    # Credential scan over every persisted execution / job / channel record.
    all_hits: list[str] = []
    for root in (
        Path(engine_dir),
        isolated_stores["jobs"],
        isolated_stores["channels"],
    ):
        for path in _walk_json_files(root):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            hits = _scan_for_credentials(text)
            if hits:
                all_hits.extend(f"{path.name}:{h}" for h in hits)
    assert all_hits == [], f"credentials leaked into persisted records: {all_hits}"


def test_acceptance_image_gate_blocks_video_before_provider(isolated_stores):
    """6. Bad scene image is caught before any video generation call."""
    from config import OUTPUT_DIR

    ref = "storyboard/pm_ACCEPT/0/bad.png"
    abs_path = os.path.join(OUTPUT_DIR, *ref.split("/"))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as handle:
        handle.write(b"not-a-real-image-payload")

    video_calls: list[dict] = []

    def fake_run(**kwargs):
        video_calls.append(kwargs)
        return {"total": 1, "ready": 1, "errors": 0}

    original = video_adapter.run_manifest_job
    video_adapter.run_manifest_job = fake_run
    try:
        with pytest.raises(AdapterError) as ctx:
            video_adapter.generate(
                {
                    "scenes": {
                        "scenes": [{
                            "index": 0,
                            "id": "scn_ACC02",
                            "scene_id": "scn_ACC02",
                            "image_prompt": "harbor",
                            "motion_prompt": "slow pan",
                        }]
                    },
                    "storyboard": {
                        "ready": 1,
                        "total": 1,
                        "artifact_refs": [ref],
                    },
                },
                {"provider_id": "grok_automa", "aspect_ratio": "9:16"},
                AdapterContext(project_id="pm_ACCEPT", node_id="n_animator"),
            )
        assert ctx.value.code == QUALITY_GATE_FAILED
        assert video_calls == [], "video provider must not be invoked on a bad still"
    finally:
        video_adapter.run_manifest_job = original
        try:
            os.remove(abs_path)
        except OSError:
            pass


def test_acceptance_resegmentation_unbinds_stale_issues(isolated_stores):
    """7. Re-run segmenter; no open issue stays bound to a gone scene."""
    job_id = "job_ACCEPT"

    first = apply_resegmentation(
        job_id,
        [
            {"start": 0.0, "end": 2.0, "words": "keep", "is_filler": False},
            {"start": 2.0, "end": 4.0, "words": "drop", "is_filler": False},
            {"start": 4.0, "end": 6.0, "words": "keep2", "is_filler": False},
        ],
    )
    keep_a, drop, keep_b = first.scenes
    create_open_issue(job_id=job_id, scene_id=keep_a.id, reason="niggle")
    create_open_issue(job_id=job_id, scene_id=drop.id, reason="bad cut")

    # Drop the middle scene entirely.
    second = apply_resegmentation(
        job_id,
        [
            {"start": 0.0, "end": 2.0, "words": "keep", "is_filler": False},
            {"start": 4.0, "end": 6.0, "words": "keep2", "is_filler": False},
        ],
    )
    active_ids = {s.id for s in second.scenes}
    assert keep_a.id in active_ids
    assert keep_b.id in active_ids
    assert drop.id not in active_ids
    assert drop.id in second.invalidated_ids
    assert not scene_resolves(drop.id)

    open_on_drop = list_issues(job_id=job_id, scene_id=drop.id, open_only=True)
    assert open_on_drop == [], "open issue left bound to a scene that no longer exists"
    open_on_keep = list_issues(job_id=job_id, scene_id=keep_a.id, open_only=True)
    assert len(open_on_keep) == 1


def test_acceptance_export_logo_survives_aspect_profiles(tmp_path, monkeypatch):
    """8. Export with logo overlay works for 9:16, 16:9, and 1:1 profiles."""
    captured: list[dict] = []

    class Processor:
        def __init__(self, payload, progress_callback=None):
            captured.append(dict(payload))

        def process(self, path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"video")

    monkeypatch.setattr(export_adapter, "VideoProcessor", Processor)
    monkeypatch.setattr(export_adapter, "EXPORT_DIR", str(tmp_path))
    monkeypatch.setattr(
        export_adapter,
        "with_artifacts",
        lambda payload, *paths: {**payload, "artifact_refs": [Path(paths[0]).name]},
    )

    project_payload = {
        "assembled_data": {
            "scenes": [{"id": 1, "duration": 1, "mediaUrl": "image/p/a.png"}],
            "total_duration": 1,
        }
    }
    settings = {
        "logo_enabled": True,
        "logo": {"ref": "branding/logo.png"},
        "logo_position": "bottom_right",
        "logo_size": 10,
    }

    # One profile per aspect family: 9:16, 16:9, 1:1.
    profile_by_ratio = {}
    for name, (_w, _h, ratio) in PROFILES.items():
        profile_by_ratio.setdefault(ratio, name)
    assert set(profile_by_ratio) >= {"9:16", "16:9", "1:1"}

    ctx = AdapterContext(project_id="pm_ACCEPT", node_id="n_export")
    for ratio, profile in profile_by_ratio.items():
        if ratio not in {"9:16", "16:9", "1:1"}:
            continue
        captured.clear()
        result = export_adapter.video(
            {"project": project_payload, "settings": settings},
            {"profile": profile},
            ctx,
        )
        assert "video" in result
        assert captured, f"VideoProcessor not invoked for {profile} ({ratio})"
        overlay = captured[0].get("logo_overlay")
        assert overlay and overlay.get("enabled"), (
            f"logo overlay missing for {profile}: {captured[0].keys()}"
        )
        assert captured[0].get("aspect_ratio") == ratio
        pathish = str(overlay.get("path") or "")
        assert pathish.startswith("/output/branding/") or pathish.startswith("branding/")
        assert ":\\" not in pathish
