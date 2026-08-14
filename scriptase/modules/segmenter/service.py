"""Segmentation service — the in-process step implementation.

`_step_segment` moves here verbatim from V2's `studio/pipeline/services.py` so
adapters and the pipeline can run segmentation without importing a `routes.py`.
"""

import os
from datetime import datetime

from loguru import logger

from config import SEGMENTER_DIR


def _step_segment(timing_result, config, project_id):
    """Run segmentation on alignment data."""
    from scriptase.modules.segmenter.algorithm import run_segmenter, save_output

    metadata = {
        "project_id": project_id,
        "source_folder": timing_result.get("folder", ""),
        "style": config.get("style", ""),
        "transcript": timing_result.get("transcript", ""),
    }

    seg_config = config.get("segment_config")

    result = run_segmenter(
        timing_result["alignment"],
        seg_config,
        metadata,
    )

    folder = project_id or f"{timing_result.get('folder', 'pipeline')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_path = os.path.join(SEGMENTER_DIR, folder, "segmented.json")
    save_output(result, out_path)
    result["output_folder"] = folder
    result["output_path"] = out_path

    logger.success("Pipeline Segment: {} scenes",
                   result["stats"]["segment_count"])
    return result
