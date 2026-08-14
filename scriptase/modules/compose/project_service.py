"""Project directories, asset resolution, audio/caption resolution, discovery.

Moved verbatim out of V2 ``studio/editor/routes.py`` in step 0.3.
Service layer: no Flask import belongs in this module.
"""

import json
import os
import time

from loguru import logger

from config import (
    ALIGN_DIR,
    ANIMATOR_DIR,
    CAPTIONS_DIR,
    OUTPUT_DIR,
    PROJECTS_DIR,
    SCENES_DIR,
    TTS_DIR,
)
from scriptase.shared.io_utils import safe_json_read, safe_json_write

# V2 read the story tone from ``config.PIPELINE_DIR``. Scriptase leaves the
# step-wizard pipeline behind, so that constant does not exist here; the
# on-disk location is unchanged (``output/pipeline``) because the V2 output
# layout has to stay importable.
PIPELINE_DIR = os.path.join(OUTPUT_DIR, "pipeline")

logger.info("Projects directory: {}", PROJECTS_DIR)

WIP_FILENAME = "work@in@progress.json"
INITIAL_FILENAME = "initial.json"


def _project_dir(project_id: str) -> str:
    """Return the per-project directory inside PROJECTS_DIR."""
    return os.path.join(PROJECTS_DIR, project_id)


def _wip_path(project_id: str) -> str:
    """Return the path to the work-in-progress save file for a project."""
    return os.path.join(_project_dir(project_id), WIP_FILENAME)


def _initial_path(project_id: str) -> str:
    """Return the path to the initial (pristine) project file."""
    return os.path.join(_project_dir(project_id), INITIAL_FILENAME)


def _load_asset_metadata(project_id: str) -> dict:
    """Read per-scene asset metadata for a project if it exists."""
    meta_path = os.path.join(ANIMATOR_DIR, project_id, "metadata.json")
    try:
        data = safe_json_read(meta_path)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data.get("scenes", {}) if isinstance(data, dict) else {}


def _pick_scene_asset(project_id: str, *scene_keys: str,
                      used_urls: set | None = None) -> tuple[str, str]:
    """Return the best asset URL and resolved type for the given scene keys.

    If *used_urls* is provided, any URL already in the set is skipped and the
    chosen URL is added to the set — preventing the same asset from being
    assigned to multiple scenes.
    """
    video_exts = (".mp4", ".webm", ".mov")
    media_exts = video_exts + (".jpg", ".jpeg", ".png", ".webp")
    metadata = _load_asset_metadata(project_id)
    deduped_keys = tuple(dict.fromkeys(str(key) for key in scene_keys if key is not None))

    for scene_key in deduped_keys:
        meta_scene = metadata.get(scene_key, {}) or {}
        local_files = [
            path for path in meta_scene.get("local_files", [])
            if isinstance(path, str) and path.lower().endswith(media_exts)
        ]
        if local_files:
            # Prefer video files over images (thumbnails)
            video_local = [p for p in local_files if p.lower().endswith(video_exts)]
            media_url = video_local[-1] if video_local else local_files[-1]
            if used_urls is not None and media_url in used_urls:
                continue
            media_type = "video" if media_url.lower().endswith(video_exts) else "image"
            if used_urls is not None:
                used_urls.add(media_url)
            return media_url, media_type

    for scene_key in deduped_keys:
        asset_dir = os.path.join(ANIMATOR_DIR, project_id, scene_key)
        if not os.path.isdir(asset_dir):
            continue

        files = []
        for fname in os.listdir(asset_dir):
            fpath = os.path.join(asset_dir, fname)
            if os.path.isfile(fpath) and fname.lower().endswith(media_exts):
                files.append((os.path.getmtime(fpath), fname))

        if not files:
            continue

        # Prefer video files over images (thumbnails) when both exist
        video_files = [(t, f) for t, f in files if f.lower().endswith(video_exts)]
        pick = max(video_files) if video_files else max(files)
        _, fname = pick
        media_url = f"/output/animator/{project_id}/{scene_key}/{fname}"
        if used_urls is not None and media_url in used_urls:
            continue
        media_type = "video" if fname.lower().endswith(video_exts) else "image"
        if used_urls is not None:
            used_urls.add(media_url)
        return media_url, media_type

    # Fallback: check animator videos (output/animator/{project_id}/{scene_key}/*.mp4)
    for scene_key in deduped_keys:
        animator_scene_dir = os.path.join(ANIMATOR_DIR, project_id, str(scene_key))
        if not os.path.isdir(animator_scene_dir):
            continue
        vid_files = []
        for fname in os.listdir(animator_scene_dir):
            fpath = os.path.join(animator_scene_dir, fname)
            if os.path.isfile(fpath) and fname.lower().endswith(video_exts):
                vid_files.append((os.path.getmtime(fpath), fname))
        if not vid_files:
            continue
        _, fname = max(vid_files)
        media_url = f"/output/animator/{project_id}/{scene_key}/{fname}"
        if used_urls is not None and media_url in used_urls:
            continue
        if used_urls is not None:
            used_urls.add(media_url)
        return media_url, "video"

    return "", ""

def _get_source_folder(project_id: str) -> str | None:
    """Look up source_folder from scenes.json for a given project."""
    scenes_path = os.path.join(SCENES_DIR, project_id, "scenes.json")
    try:
        with open(scenes_path, "r", encoding="utf-8") as f:
            return json.load(f).get("source_folder")
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        logger.debug("Could not read source_folder from {}: {}", scenes_path, error)
        return None


def _get_story_tone(project_id: str) -> str | None:
    """Look up story_tone from pipeline.json for a given project."""
    pipeline_path = os.path.join(PIPELINE_DIR, project_id, "pipeline.json")
    try:
        with open(pipeline_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("story_tone") or (data.get("config") or {}).get("story_tone") or None
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        logger.debug("Could not read story_tone from {}: {}", pipeline_path, error)
        return None


def _resolve_audio_url(source_folder: str) -> dict | None:
    """Resolve audio file URL from the alignment or TTS folder."""
    # Try alignment folder first (post-timing audio)
    align_path = os.path.join(ALIGN_DIR, source_folder)
    if os.path.isdir(align_path):
        try:
            for f in os.listdir(align_path):
                if f.endswith((".wav", ".mp3")):
                    return {
                        "url": f"/output/alignments/{source_folder}/{f}",
                        "source_file": f,
                    }
        except OSError:
            pass
    # Fall back to TTS folder (pre-timing audio)
    tts_path = os.path.join(TTS_DIR, source_folder)
    if os.path.isdir(tts_path):
        try:
            for f in os.listdir(tts_path):
                if f.endswith((".wav", ".mp3")):
                    return {
                        "url": f"/output/tts/{source_folder}/{f}",
                        "source_file": f,
                    }
        except OSError:
            pass
    return None


def _resolve_project_audio(data: dict, project_id: str):
    """Replace saved voice track with the correct audio for this project."""
    source_folder = _get_source_folder(project_id)
    if not source_folder:
        return
    resolved = _resolve_audio_url(source_folder)
    if not resolved:
        return
    correct_url = resolved["url"]
    # Keep the persisted voice track aligned with the actual resolved source.
    for track in data.get("audio_tracks", []):
        if track.get("type") != "voice":
            continue
        prev_path = track.get("path")
        prev_file = track.get("file")
        if prev_path != correct_url or prev_file != resolved["source_file"]:
            logger.info(
                "Normalizing voice track for {}: path {} -> {}, file {} -> {}",
                project_id,
                prev_path,
                correct_url,
                prev_file,
                resolved["source_file"],
            )
        track["path"] = correct_url
        track["file"] = resolved["source_file"]
        break


def _resolve_project_captions(data: dict, project_id: str):
    """Replace stale captions with the latest matching source_folder captions."""
    captions = data.get("captions")
    source_folder = _get_source_folder(project_id)
    if not source_folder:
        data["captions"] = None
        return

    cap_source = captions.get("source_folder", "") if captions else ""
    if captions and cap_source == source_folder:
        return

    if captions:
        logger.info(
            "Clearing stale captions for {}: cap source={} != project source={}",
            project_id,
            cap_source,
            source_folder,
        )

    latest_match = None
    latest_ts = ""
    if os.path.isdir(CAPTIONS_DIR):
        # Sort entries in reverse so newest (alphabetically highest) is checked first.
        # Since timestamps are ISO-formatted, the first match with the right
        # source_folder is very likely the latest — but we still keep the best.
        entries = sorted(os.listdir(CAPTIONS_DIR), reverse=True)
        for entry in entries:
            cap_json = os.path.join(CAPTIONS_DIR, entry, "captions.json")
            if not os.path.isfile(cap_json):
                continue
            try:
                payload = safe_json_read(cap_json)
            except Exception as error:
                logger.debug("Skipping captions payload {}: {}", cap_json, error)
                continue
            if payload.get("source_folder") != source_folder:
                continue
            ts = payload.get("timestamp", "")
            if ts >= latest_ts:
                latest_ts = ts
                latest_match = payload
                # First matching entry in reverse-sorted order is almost
                # certainly the newest; stop scanning the rest.
                break

    data["captions"] = latest_match
    if latest_match:
        logger.info(
            "Resolved captions for {} from source_folder={} -> {}",
            project_id,
            source_folder,
            latest_match.get("project_id", ""),
        )
        return

    # Fallback: build captions from alignment data (grouped with style)
    align_path = os.path.join(ALIGN_DIR, source_folder, "alignment.json")
    if os.path.isfile(align_path):
        try:
            from scriptase.modules.captions.presets import (
                _get_default_caption_preset_id,
                CAPTION_PRESETS,
            )
            from scriptase.modules.captions.service import _group_words_into_captions
            align_data = safe_json_read(align_path)
            alignment = align_data.get("alignment", [])
            if alignment:
                captions_list = _group_words_into_captions(alignment, words_per_group=3)
                if captions_list:
                    preset_id = _get_default_caption_preset_id()
                    cap_style = dict(CAPTION_PRESETS.get(preset_id, CAPTION_PRESETS.get("bold_popup", {})))
                    cap_style["preset"] = preset_id
                    data["captions"] = {
                        "project_id": project_id,
                        "source_folder": source_folder,
                        "captions": captions_list,
                        "style": cap_style,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    }
                    logger.info("Built {} captions from alignment for {}", len(captions_list), project_id)
        except Exception as e:
            logger.debug("Failed to build captions from alignment: {}", e)


_AUDIO_HISTORY_LIMIT = 10


def _normalize_audio_history(history) -> list[str]:
    """Keep a bounded list of valid persisted audio history paths."""
    if not isinstance(history, list):
        return []
    return [path for path in history if isinstance(path, str) and path.strip()][-_AUDIO_HISTORY_LIMIT:]


def _append_audio_history(history: list[str], path: str | None) -> list[str]:
    """Append a path to bounded recent history, de-duping earlier occurrences."""
    if not isinstance(path, str) or not path.strip():
        return _normalize_audio_history(history)
    normalized = [item for item in _normalize_audio_history(history) if item != path]
    normalized.append(path)
    return normalized[-_AUDIO_HISTORY_LIMIT:]

def _discover_projects() -> list[dict]:
    """Scan output directories to discover all projects and their status."""
    projects = {}  # project_id → info dict

    # 1. Scan scenes dir (source of truth for generated projects)
    if os.path.isdir(SCENES_DIR):
        for entry in os.listdir(SCENES_DIR):
            scenes_path = os.path.join(SCENES_DIR, entry, "scenes.json")
            if not os.path.isfile(scenes_path):
                continue
            try:
                mtime = os.path.getmtime(scenes_path)
                with open(scenes_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                projects[entry] = {
                    "project_id": entry,
                    "project_name": data.get("project_name", entry),
                    "source_folder": data.get("source_folder", entry),
                    "scene_count": data.get("scene_count", len(data.get("scenes", []))),
                    "total_duration": data.get("total_duration", 0),
                    "style": data.get("style", ""),
                    "created_at": data.get("timestamp", ""),
                    "has_scenes": True,
                    "has_assets": False,
                    "has_audio": False,
                    "has_editor": False,
                    "asset_count": 0,
                }
            except Exception as error:
                logger.debug("Skipping scenes manifest {}: {}", scenes_path, error)
                continue

    # 2. Check assets
    if os.path.isdir(ANIMATOR_DIR):
        for entry in os.listdir(ANIMATOR_DIR):
            asset_dir = os.path.join(ANIMATOR_DIR, entry)
            if not os.path.isdir(asset_dir):
                continue
            if entry not in projects:
                projects[entry] = {
                    "project_id": entry,
                    "project_name": entry,
                    "source_folder": entry,
                    "scene_count": 0,
                    "total_duration": 0,
                    "style": "",
                    "created_at": "",
                    "has_scenes": False,
                    "has_assets": False,
                    "has_audio": False,
                    "has_editor": False,
                    "asset_count": 0,
                }
            # Count asset subdirs (scene folders with media)
            asset_count = sum(
                1 for d in os.listdir(asset_dir)
                if os.path.isdir(os.path.join(asset_dir, d)) and d.isdigit()
            )
            projects[entry]["has_assets"] = asset_count > 0
            projects[entry]["asset_count"] = asset_count

    # 3. Check audio (alignments)
    if os.path.isdir(ALIGN_DIR):
        for entry in os.listdir(ALIGN_DIR):
            align_path = os.path.join(ALIGN_DIR, entry)
            if not os.path.isdir(align_path):
                continue
            has_wav = any(f.endswith((".wav", ".mp3")) for f in os.listdir(align_path))
            if has_wav:
                # Find the project this audio belongs to (source_folder match)
                for pid, info in projects.items():
                    if info.get("source_folder") == entry:
                        info["has_audio"] = True
                        break

    # 4. Check editor saves in output/projects/{id}/
    for pid in list(projects.keys()):
        proj_dir = os.path.join(PROJECTS_DIR, pid)
        if os.path.isdir(proj_dir):
            has_save = os.path.isfile(os.path.join(proj_dir, WIP_FILENAME)) or \
                       os.path.isfile(os.path.join(proj_dir, INITIAL_FILENAME))
            if has_save:
                projects[pid]["has_editor"] = True

    # 5. Enrich with TTS metadata (text, voice, speed)
    if os.path.isdir(TTS_DIR):
        for pid, info in projects.items():
            sf = info.get("source_folder", pid)
            tts_meta = os.path.join(TTS_DIR, sf, "tts.json")
            if os.path.isfile(tts_meta):
                try:
                    with open(tts_meta, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    info["text_preview"] = (meta.get("prompt", "") or "")[:120]
                    info["voice"] = meta.get("voice", "")
                    info["audio_duration"] = meta.get("duration_seconds", 0)
                except Exception as error:
                    logger.debug("Skipping TTS metadata {}: {}", tts_meta, error)

    # 6. Write/update manifests to PROJECTS_DIR (skip if initial.json already exists)
    for pid, info in projects.items():
        manifest_dir = os.path.join(PROJECTS_DIR, pid)
        project_file = os.path.join(manifest_dir, "project.json")
        initial_file = os.path.join(manifest_dir, INITIAL_FILENAME)
        os.makedirs(manifest_dir, exist_ok=True)
        # Don't overwrite if initial.json or a full project.json already exists
        if os.path.isfile(initial_file):
            continue
        if os.path.isfile(project_file):
            try:
                existing = safe_json_read(project_file)
                if existing.get("scenes"):
                    continue  # Already has full project data
            except Exception as error:
                logger.debug("Could not read existing project manifest {}: {}", project_file, error)
        safe_json_write(project_file, info, indent=2)

    result = sorted(projects.values(), key=lambda p: p.get("created_at", ""), reverse=True)
    return result
