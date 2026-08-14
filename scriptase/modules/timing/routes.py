"""Timing Module — Force Alignment Routes"""

import json
import os
import re
import subprocess
import time
from datetime import datetime

from flask import Blueprint, jsonify, request, send_from_directory
from loguru import logger
from werkzeug.utils import secure_filename

from config import ALIGN_DIR, TRASH_DIR, BIN_DIR, generate_project_id
from scriptase.shared.ffmpeg_utils import find_ffmpeg
from scriptase.shared.io_utils import move_to_unique_path, safe_json_write

from .service import _check_alignment_available, _run_alignment

timing_bp = Blueprint("timing", __name__)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@timing_bp.route("/api/alignment/history")
def list_force_alignments():
    items = []
    if not os.path.exists(ALIGN_DIR):
        return jsonify(items)
    for entry in os.listdir(ALIGN_DIR):
        entry_path = os.path.join(ALIGN_DIR, entry)
        if not os.path.isdir(entry_path) or entry == "TRASH":
            continue
        json_path = os.path.join(entry_path, "alignment.json")
        if not os.path.isfile(json_path):
            continue
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            words = meta.get("alignment", [])
            duration = round(words[-1]["end"], 2) if words else 0
            items.append({
                "type": "force-alignment",
                "project_id": meta.get("project_id", ""),
                "folder": meta.get("folder", entry),
                "source_file": meta.get("source_file", ""),
                "transcript": meta.get("transcript", ""),
                "word_count": meta.get("word_count", len(words)),
                "word_alignment": words,
                "duration_seconds": duration,
                "inference_time": meta.get("inference_time", 0),
                "timestamp": meta.get("timestamp", ""),
            })
        except (json.JSONDecodeError, OSError, IndexError, KeyError):
            pass
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(items)


@timing_bp.route("/api/alignment/align", methods=["POST"])
@timing_bp.route("/api/timing/align", methods=["POST"])
def force_align():
    if not _check_alignment_available():
        return jsonify({"error": "Force alignment not available (stable-ts not installed)"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "No transcript text provided"}), 400

    audio_file = request.files["audio"]
    original_name = secure_filename(audio_file.filename or "")
    if not original_name:
        return jsonify({"error": "Invalid filename"}), 400
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in (".wav", ".mp3", ".flac", ".ogg"):
        return jsonify({"error": f"Unsupported format: {ext}"}), 400

    project_id = generate_project_id("pm")
    folder_name = project_id
    job_dir = os.path.join(ALIGN_DIR, folder_name)
    os.makedirs(job_dir, exist_ok=True)

    audio_path = os.path.join(job_dir, original_name)
    audio_file.save(audio_path)

    wav_path = audio_path
    conv_path = None
    try:
        if ext != ".wav":
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                return jsonify({"error": "ffmpeg required for non-WAV files"}), 400
            conv_path = os.path.join(job_dir, os.path.splitext(original_name)[0] + "_conv.wav")
            result = subprocess.run(
                [ffmpeg, "-nostdin", "-y", "-i", audio_path, "-ar", "24000", "-ac", "1", conv_path],
                capture_output=True, timeout=60,
            )
            if result.returncode != 0:
                return jsonify({"error": "Audio conversion failed"}), 500
            wav_path = conv_path

        start = time.perf_counter()
        alignment = _run_alignment(wav_path, text)
        elapsed = time.perf_counter() - start

        if not alignment:
            return jsonify({"error": "Alignment produced no results"}), 500

        result_data = {
            "project_id": project_id,
            "source_file": original_name,
            "folder": folder_name,
            "transcript": text,
            "alignment": alignment,
            "word_count": len(alignment),
            "inference_time": round(elapsed, 3),
            "timestamp": datetime.now().isoformat(),
        }
        safe_json_write(os.path.join(job_dir, "alignment.json"), result_data, indent=2)

        logger.success("Force-aligned  {} | {} words in {:.2f}s -> {}", original_name, len(alignment), elapsed, folder_name)
        return jsonify(result_data)

    finally:
        if conv_path:
            try:
                os.unlink(conv_path)
            except OSError:
                pass


@timing_bp.route("/api/alignment/align-and-segment", methods=["POST"])
def align_and_segment():
    """Combined alignment + segmentation in one request.

    Same inputs as /api/alignment/align, plus optional segment_config JSON field.
    Returns both alignment and segmentation results.
    """
    from scriptase.modules.segmenter.algorithm import run_segmenter, save_output
    from config import SEGMENTER_DIR

    if not _check_alignment_available():
        return jsonify({"error": "Force alignment not available"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "No transcript text provided"}), 400

    audio_file = request.files["audio"]
    original_name = secure_filename(audio_file.filename or "")
    if not original_name:
        return jsonify({"error": "Invalid filename"}), 400
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in (".wav", ".mp3", ".flac", ".ogg"):
        return jsonify({"error": f"Unsupported format: {ext}"}), 400

    seg_config_str = request.form.get("segment_config", "")
    if seg_config_str:
        try:
            seg_config = json.loads(seg_config_str)
        except json.JSONDecodeError:
            return jsonify({"error": "segment_config must be valid JSON"}), 400
        if seg_config is not None and not isinstance(seg_config, dict):
            return jsonify({"error": "segment_config must be a JSON object"}), 400
    else:
        seg_config = None

    project_id = generate_project_id("pm")
    folder_name = project_id
    job_dir = os.path.join(ALIGN_DIR, folder_name)
    os.makedirs(job_dir, exist_ok=True)

    audio_path = os.path.join(job_dir, original_name)
    audio_file.save(audio_path)

    wav_path = audio_path
    conv_path = None
    try:
        if ext != ".wav":
            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                return jsonify({"error": "ffmpeg required for non-WAV files"}), 400
            conv_path = os.path.join(job_dir, os.path.splitext(original_name)[0] + "_conv.wav")
            result = subprocess.run(
                [ffmpeg, "-nostdin", "-y", "-i", audio_path, "-ar", "24000", "-ac", "1", conv_path],
                capture_output=True, timeout=60,
            )
            if result.returncode != 0:
                return jsonify({"error": "Audio conversion failed"}), 500
            wav_path = conv_path

        # ── Alignment ──
        start = time.perf_counter()
        alignment = _run_alignment(wav_path, text)
        align_elapsed = time.perf_counter() - start

        if not alignment:
            return jsonify({"error": "Alignment produced no results"}), 500

        align_data = {
            "project_id": project_id,
            "source_file": original_name,
            "folder": folder_name,
            "transcript": text,
            "alignment": alignment,
            "word_count": len(alignment),
            "inference_time": round(align_elapsed, 3),
            "timestamp": datetime.now().isoformat(),
        }
        safe_json_write(os.path.join(job_dir, "alignment.json"), align_data, indent=2)

        # ── Segmentation ──
        seg_metadata = {
            "project_id": project_id,
            "source_folder": folder_name,
            "transcript": text,
        }

        seg_result = run_segmenter(alignment, seg_config, seg_metadata)

        seg_folder = project_id
        out_path = os.path.join(SEGMENTER_DIR, seg_folder, "segmented.json")
        save_output(seg_result, out_path)
        seg_result["output_folder"] = seg_folder
        seg_result["output_path"] = out_path

        logger.success("Align+Segment  {} | {} words in {:.2f}s | {} segments",
                       original_name, len(alignment), align_elapsed,
                       seg_result["stats"]["segment_count"])

        return jsonify({
            "alignment": align_data,
            "segmentation": seg_result,
        })

    finally:
        if conv_path:
            try:
                os.unlink(conv_path)
            except OSError:
                pass


@timing_bp.route("/api/alignment/<folder>", methods=["DELETE"])
@timing_bp.route("/api/timing/<folder>", methods=["DELETE"])
def delete_alignment(folder):
    folder = os.path.basename(folder)
    job_dir = os.path.join(ALIGN_DIR, folder)
    if os.path.isdir(job_dir):
        align_trash = os.path.join(TRASH_DIR, "alignments")
        move_to_unique_path(job_dir, align_trash, folder)
        return jsonify({"status": "deleted", "folder": folder})
    return jsonify({"error": "Folder not found"}), 404


@timing_bp.route("/output/alignments/<path:filename>")
def serve_alignment_audio(filename):
    return send_from_directory(ALIGN_DIR, filename)
