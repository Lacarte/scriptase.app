"""Segmentation service — the in-process step implementation.

`_step_segment` moves here verbatim from V2's `studio/pipeline/services.py` so
adapters and the pipeline can run segmentation without importing a `routes.py`.

Step 1.6 layers stable scene identity on top of the algorithm output: speech
segments receive ``scn_`` ids that survive re-segmentation under the
contracts.md §4 rebind rule. Pass ``job_id`` (via config or the project_id
argument when it is a Job id) so a re-run rebinds / supersedes prior scenes
instead of minting a fresh index array.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from loguru import logger

from config import SEGMENTER_DIR
from scriptase.scenes.resegment import (
    REBIND_IOU_THRESHOLD,
    REBIND_MAX_SPAN_RATIO,
    ResegmentConfig,
    apply_resegmentation,
    stamp_segments_with_scene_ids,
)


def _rebind_config_from(seg_config: dict[str, Any] | None) -> ResegmentConfig:
    """Read rebind thresholds from segmenter config (defaults from contracts §4)."""
    cfg = dict(seg_config or {})
    return ResegmentConfig(
        iou_threshold=float(cfg.get("rebind_iou_threshold", REBIND_IOU_THRESHOLD)),
        max_span_ratio=float(cfg.get("rebind_max_span_ratio", REBIND_MAX_SPAN_RATIO)),
    )


def _looks_like_job_id(value: str | None) -> bool:
    if not value or not isinstance(value, str):
        return False
    text = value.strip()
    return len(text) == 10 and text.startswith("job_")


def apply_stable_scene_identity(
    result: dict[str, Any],
    *,
    job_id: str | None,
    seg_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stamp stable scene ids onto a segmenter result for a Job.

    When ``job_id`` is missing, speech segments still get fresh ``scn_`` ids
    (no rebind history). When present, re-segmentation rebinds / supersedes
    against prior active scenes for that Job and cleans artifact/issue bindings.
    """
    segments = list(result.get("segments") or [])
    if not job_id:
        return result

    reseg = apply_resegmentation(
        job_id,
        segments,
        config=_rebind_config_from(seg_config),
        persist=True,
        apply_bindings=True,
    )
    stamped = stamp_segments_with_scene_ids(segments, reseg.scenes)
    result = dict(result)
    result["segments"] = stamped
    result["scenes"] = [scene.to_document() for scene in reseg.scenes]
    result["scene_ids"] = [scene.id for scene in reseg.scenes]
    result["resegmentation"] = {
        "rebound": sum(1 for d in reseg.decisions if d.action == "rebind"),
        "superseded": sum(1 for d in reseg.decisions if d.action == "supersede"),
        "new": sum(1 for d in reseg.decisions if d.action == "new"),
        "invalidated": list(reseg.invalidated_ids),
        "id_map": dict(reseg.id_map),
        "iou_threshold": reseg.config.iou_threshold,
        "max_span_ratio": reseg.config.max_span_ratio,
    }

    # Keep Job.scenes in sync when the Job store knows this id.
    try:
        from scriptase.jobs.store import get_job, update_job

        job = get_job(job_id)
        update_job(
            job.id,
            scenes=[scene.id for scene in reseg.scenes],
            allow_terminal=True,
        )
    except Exception:
        # Segmenter works without a Job document (CLI / standalone runs).
        pass

    return result


def _step_segment(timing_result, config, project_id):
    """Run segmentation on alignment data."""
    from scriptase.modules.segmenter.algorithm import run_segmenter, save_output

    cfg = dict(config or {})
    metadata = {
        "project_id": project_id,
        "source_folder": timing_result.get("folder", ""),
        "style": cfg.get("style", ""),
        "transcript": timing_result.get("transcript", ""),
    }

    seg_config = cfg.get("segment_config")
    if seg_config is None:
        # Allow rebind thresholds and algorithm knobs at the top level too.
        seg_config = {
            key: cfg[key]
            for key in (
                "target_min",
                "target_max",
                "hard_max",
                "hard_min",
                "gap_filler",
                "max_silence",
                "break_weights",
                "rebind_iou_threshold",
                "rebind_max_span_ratio",
            )
            if key in cfg
        } or None

    result = run_segmenter(
        timing_result["alignment"],
        seg_config,
        metadata,
    )

    job_id = cfg.get("job_id") or (
        project_id if _looks_like_job_id(project_id) else None
    )
    result = apply_stable_scene_identity(
        result,
        job_id=job_id,
        seg_config=seg_config if isinstance(seg_config, dict) else cfg,
    )

    folder = project_id or f"{timing_result.get('folder', 'pipeline')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_path = os.path.join(SEGMENTER_DIR, folder, "segmented.json")
    save_output(result, out_path)
    result["output_folder"] = folder
    result["output_path"] = out_path

    scene_count = result.get("stats", {}).get("segment_count", 0)
    logger.success(
        "Pipeline Segment: {} scenes (stable ids: {})",
        scene_count,
        len(result.get("scene_ids") or []),
    )
    return result
