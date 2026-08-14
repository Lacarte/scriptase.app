"""Segmenter Module — Scene Segmentation Routes"""

import json
import os
import time
from datetime import datetime

from flask import Blueprint, jsonify, request
from loguru import logger

from config import SEGMENTER_DIR, generate_project_id
from scriptase.shared.validation import validate_json
from scriptase.modules.segmenter.schemas import SegmenterRunRequest

segmenter_bp = Blueprint("segmenter", __name__)


@segmenter_bp.route("/api/segmenter/run", methods=["POST"])
@validate_json(SegmenterRunRequest)
def segment_alignment(data: SegmenterRunRequest):
    """Run the segmenter on alignment data.

    Accepts JSON body:
      - alignment: array of {word, begin, end}
      - transcript, source_folder, style, aspect_ratio: optional metadata
      - config: optional {target_min, target_max, hard_max, hard_min, gap_filler}
      - save: boolean (default true) — persist result to disk
    """
    from scriptase.modules.segmenter.algorithm import run_segmenter, save_output

    alignment = [w.model_dump() for w in data.alignment]

    metadata = {
        "project_id": data.project_id,
        "source_folder": data.source_folder,
        "style": data.style,
        "aspect_ratio": data.aspect_ratio,
        "transcript": data.transcript,
    }
    config = data.config

    started = time.perf_counter()
    result = run_segmenter(alignment, config, metadata)
    result.setdefault("metadata", {})["generation_time"] = round(
        time.perf_counter() - started, 3
    )

    # Save to disk
    should_save = data.save
    if should_save:
        folder = data.project_id or generate_project_id("pm")
        out_path = os.path.join(SEGMENTER_DIR, folder, "segmented.json")
        save_output(result, out_path)
        result["output_folder"] = folder
        result["output_path"] = out_path
        logger.success("Segmented {} | {} segments -> {}", folder, result["stats"]["segment_count"], out_path)

    return jsonify(result)


@segmenter_bp.route("/api/segmenter/history")
def segment_history():
    """List saved segmenter results."""
    items = []
    if not os.path.exists(SEGMENTER_DIR):
        return jsonify(items)
    for entry in os.listdir(SEGMENTER_DIR):
        entry_path = os.path.join(SEGMENTER_DIR, entry)
        if not os.path.isdir(entry_path):
            continue
        json_path = os.path.join(entry_path, "segmented.json")
        if not os.path.isfile(json_path):
            continue
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("metadata", {})
            stats = data.get("stats", {})
            items.append({
                "folder": entry,
                "project_id": meta.get("project_id", ""),
                "source_folder": meta.get("source_folder", ""),
                "total_duration": meta.get("total_duration", 0),
                "generation_time": meta.get("generation_time", 0),
                "segmented_at": meta.get("segmented_at", ""),
                "segment_count": stats.get("segment_count", 0),
                "filler_count": stats.get("filler_count", 0),
                "avg_duration": stats.get("avg_duration", 0),
            })
        except (json.JSONDecodeError, OSError):
            pass
    items.sort(key=lambda x: x.get("segmented_at", ""), reverse=True)
    return jsonify(items)


@segmenter_bp.route("/api/segmenter/<folder>")
def get_segmenter_result(folder):
    """Get full segmenter result for a saved run."""
    folder = os.path.basename(folder)
    json_path = os.path.join(SEGMENTER_DIR, folder, "segmented.json")
    if not os.path.isfile(json_path):
        return jsonify({"error": "Not found"}), 404
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except (json.JSONDecodeError, OSError) as e:
        return jsonify({"error": f"Failed to read segmenter data: {e}"}), 500
