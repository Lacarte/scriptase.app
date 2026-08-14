"""Assemble a project into editor-ready form.

The body of ``assemble_project_for_editor`` comes verbatim from V2
``studio/editor/routes.py`` (lines 1254-1572) and ``_step_assemble`` from
V2 ``studio/pipeline/services.py`` (lines 459-473). The two are siblings
here, so the cross-module import ``_step_assemble`` used is gone.

Service layer: no Flask import belongs in this module. Where V2 returned
``jsonify(payload)`` this returns ``payload``; where V2 returned
``jsonify({"error": ...}), <status>`` this returns ``({"error": ...},
<status>)``. ``compose/assemble_routes.py`` does the jsonify. Direct
(``_direct=True``) callers are unaffected — they never reached those
branches.
"""

import json
import os
import time

from loguru import logger

from config import ALIGN_DIR, CAPTIONS_DIR, SCENES_DIR
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.modules.compose.audio_service import _build_per_scene_sfx_tracks
from scriptase.modules.compose.project_service import (
    INITIAL_FILENAME,
    _get_story_tone,
    _initial_path,
    _project_dir,
    _resolve_audio_url,
    _resolve_project_audio,
    _resolve_project_captions,
    _pick_scene_asset,
    _wip_path,
)


def assemble_project_for_editor(project_id, *, _direct=False, force=None):
    """Assemble a project from scenes + assets into editor-ready format.

    Creates initial.json in the editor directory if it doesn't exist,
    then returns the assembled data ready for the editor to load.
    """
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("_", "-"))

    # V2 read `force` off the query string here. The blueprint reads it now and
    # passes it in; direct callers already passed it explicitly.
    force = bool(force)

    # Check if editor save already exists → return it directly (unless force rebuild)

    wip = _wip_path(safe_id)
    initial = _initial_path(safe_id)

    if not force and (os.path.isfile(wip) or os.path.isfile(initial)):
        try:
            data = safe_json_read(wip if os.path.isfile(wip) else initial)
            _resolve_project_audio(data, safe_id)
            _resolve_project_captions(data, safe_id)
            data["_source"] = "wip" if os.path.isfile(wip) else "initial"
            return data
        except Exception as e:
            logger.warning("Existing editor data corrupt for {}, rebuilding: {}", safe_id, e)

    # Build from scenes.json
    scenes_path = os.path.join(SCENES_DIR, safe_id, "scenes.json")
    if not os.path.isfile(scenes_path):
        if _direct:
            raise FileNotFoundError("No scenes found for this project")
        return {"error": "No scenes found for this project"}, 404

    try:
        with open(scenes_path, "r", encoding="utf-8") as f:
            scenes_data = json.load(f)
    except Exception as e:
        if _direct:
            raise RuntimeError(f"Failed to read scenes: {e}") from e
        return {"error": f"Failed to read scenes: {e}"}, 500

    source_folder = scenes_data.get("source_folder", safe_id)
    raw_scenes = scenes_data.get("scenes", [])

    # Build editor-format scenes
    editor_scenes = []
    used_asset_urls = set()  # prevent the same asset from being assigned to multiple scenes
    for i, s in enumerate(raw_scenes):
        scene_index = s.get("index", i)
        scene_type = s.get("type_of_scene", s.get("type", "image"))
        duration = s.get("duration", 3)

        # Cap bloated scene durations — if the scene has way more time than its
        # speech segment (e.g., TTS inserted a long paragraph pause), trim it
        seg_dur = s.get("segment_duration")
        if seg_dur and seg_dur > 0 and duration > seg_dur + 2.0:
            duration = round(seg_dur + 1.5, 2)
        media_url, media_type = _pick_scene_asset(safe_id, i, scene_index,
                                                   used_urls=used_asset_urls)
        if scene_type != "text" and media_type:
            scene_type = media_type

        # Find media asset — asset dirs use sequential position (i), not scene_index
        # because the grabber saves files by array position, not by scene.index
        is_video = scene_type == "video" or media_url.endswith((".mp4", ".webm", ".mov"))

        editor_scenes.append({
            "id": i,
            "scene_id": i,
            "type": scene_type,
            "scene_type": s.get("narrative_role", s.get("type_of_scene", scene_type)),
            "duration": duration,
            "visual_fx": s.get("visual_fx", "static"),
            "effect": {"type": "none"},
            "transition": {"type": "none", "duration": 0},
            "image_url": media_url,
            "mediaUrl": media_url,
            "image": "",
            "image_prompt": s.get("image_prompt", ""),
            "prompt": s.get("image_prompt", ""),
            "description": s.get("description", ""),
            "style": s.get("style", ""),
            "text_content": s.get("text_content"),
            "text_x": None,
            "text_y": None,
            "text_timeline_offset": 0,
            "text_overlay_duration": duration,
            "text_background_enabled": s.get("text_content") is not None and scene_type == "text",
            "text_background_color": "#000000",
            "timestamp": 0,
            "status": "done" if media_url else "pending",
            "isVideo": is_video,
            "script": s.get("segment_words", ""),
            "narrative_role": s.get("narrative_role", ""),
            "text_hook_animation": s.get("text_hook_animation"),
            "filler_shift": 0,
            "segment_start": s.get("segment_start"),
            "segment_end": s.get("segment_end"),
            "segment_duration": s.get("segment_duration"),
            "asset_files": [media_url] if media_url else [],
            # SFX hint chosen by the scene planner LLM and validated by sfx_validator.
            # The renderer turns this into an actual per-scene audio track in the
            # _build_per_scene_sfx_tracks step below; we also keep the raw value
            # on the editor scene for debugging and for future editor-UI surfacing.
            "sfx_hint": s.get("sfx_hint"),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        })

    # Compute cumulative timeline positions
    cumulative = 0
    for es in editor_scenes:
        es["timestamp"] = cumulative
        cumulative += es["duration"]

    # Build audio tracks
    audio_tracks = []
    audio_url = _resolve_audio_url(source_folder)
    if audio_url:
        audio_tracks.append({
            "id": "at_1",
            "label": "Voice",
            "type": "voice",
            "file": audio_url["source_file"],
            "path": audio_url["url"],
            "duration": 0,
            "timelineOffset": 0,
            "startOffset": 0,
            "trimmedDuration": None,
            "volume": 1,
            "loop": False,
            "muted": False,
            "duckingEnabled": False,
            "duckingLevel": 0.2,
            "fadeIn": 0,
            "fadeOut": 0,
        })

    music_history = []
    sfx_history = []
    initial_path = _initial_path(safe_id)
    if os.path.isfile(initial_path):
        try:
            existing_initial = safe_json_read(initial_path)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
            logger.debug("Could not read existing initial.json for {}: {}", safe_id, e)
            existing_initial = {}
        if isinstance(existing_initial, dict):
            music_history = list(existing_initial.get("music_history") or [])
            sfx_history = list(existing_initial.get("sfx_history") or [])

    # Auto-select background music + ambient SFX based on story tone.
    # Track order is preserved by insertion order: voice → music → sfx.
    story_tone = _get_story_tone(safe_id)
    if story_tone:
        try:
            from scriptase.modules.music.selector import select_music, select_sfx
            bg_music = select_music(story_tone, history=music_history)
            if bg_music:
                music_history = list(bg_music.get("history") or music_history)
                # Music files live under APP_ASSETS_DIR/sounds/music/<folder>/<file>.
                # Build a Flask-servable /assets/... URL the same way
                # /api/music/auto-select does so the editor + renderer both
                # resolve it. The folder is the immediate parent of the file.
                music_abs = bg_music["path"]
                music_file = os.path.basename(music_abs)
                music_folder = os.path.basename(os.path.dirname(music_abs))
                music_url = f"/assets/sounds/music/{music_folder}/{music_file}" if music_folder else f"/assets/sounds/music/{music_file}"
                audio_tracks.append({
                    "id": "at_music_1",
                    "label": "Music",
                    "type": "music",
                    "file": music_file,
                    "path": music_url,
                    "duration": 0,
                    "timelineOffset": 0,
                    "startOffset": 0,
                    "trimmedDuration": None,
                    "volume": bg_music.get("volume", 0.15),
                    "loop": bg_music.get("loop", True),
                    "muted": False,
                    "duckingEnabled": bg_music.get("ducking_enabled", True),
                    "duckingLevel": bg_music.get("ducking_level", 0.2),
                    "fadeIn": bg_music.get("fade_in", 2.0),
                    "fadeOut": bg_music.get("fade_out", 3.0),
                })
                logger.info("Auto-selected bgMusic for tone '{}' → '{}'",
                            story_tone, music_file)

            sfx = select_sfx(story_tone, history=sfx_history)
            if sfx:
                sfx_history = list(sfx.get("history") or sfx_history)
                # Build a /assets/sounds/sfx/<folder>/<file> URL — keep the
                # folder so the editor can resolve it the same way the SFX
                # library endpoint does.
                sfx_file = os.path.basename(sfx["path"])
                sfx_folder = sfx.get("folder") or os.path.basename(os.path.dirname(sfx["path"]))
                sfx_url = f"/assets/sounds/sfx/{sfx_folder}/{sfx_file}" if sfx_folder else f"/assets/sounds/sfx/{sfx_file}"
                audio_tracks.append({
                    "id": "at_sfx_1",
                    "label": "SFX",
                    "type": "sfx",
                    "file": sfx_file,
                    "path": sfx_url,
                    "duration": 0,
                    "timelineOffset": 0,
                    "startOffset": 0,
                    "trimmedDuration": None,
                    "volume": sfx.get("volume", 0.10),
                    "loop": sfx.get("loop", True),
                    "muted": False,
                    "duckingEnabled": sfx.get("ducking_enabled", True),
                    "duckingLevel": sfx.get("ducking_level", 0.20),
                    "fadeIn": sfx.get("fade_in", 1.5),
                    "fadeOut": sfx.get("fade_out", 2.0),
                })
                logger.info("Auto-selected SFX for tone '{}' → '{}'",
                            story_tone, sfx_file)
        except Exception as e:
            logger.debug("Could not auto-select bgMusic/SFX for {}: {}", safe_id, e)

    # Per-scene SFX placement based on validated sfx_hint fields from the
    # scene planner. Runs AFTER the tone-driven music + SFX bed so the per-scene
    # accents layer ON TOP of the ambient bed without competing with the bed's
    # tone-matching. The bed is the atmosphere layer; these are the punctuation
    # layer. Both can coexist with ducking handling the voice mix.
    try:
        scene_sfx_tracks, sfx_history = _build_per_scene_sfx_tracks(
            editor_scenes, raw_scenes, sfx_history,
        )
        if scene_sfx_tracks:
            audio_tracks.extend(scene_sfx_tracks)
            logger.info("Built {} per-scene SFX track(s) for {}", len(scene_sfx_tracks), safe_id)
    except Exception as e:
        logger.warning("Could not build per-scene SFX tracks for {}: {}", safe_id, e)

    total_duration = sum(s["duration"] for s in editor_scenes)
    editor_data = {
        "project_id": safe_id,
        "project_name": scenes_data.get("project_name", safe_id),
        "source_folder": source_folder,
        "style": scenes_data.get("style", ""),
        "total_duration": total_duration,
        "scene_count": len(editor_scenes),
        "scenes": editor_scenes,
        "audio_tracks": audio_tracks,
        "music_history": music_history,
        "sfx_history": sfx_history,
        "grain_overlay": {
            "enabled": False,
            "opacity": 0.16,
            "start": 0,
            "fade_in": 0,
            "hold": 0,
            "fade_out": 0,
            "noise_strength": 88,
            "threshold": 246,
        },
        "captionsEnabled": False,
        "edit_history": [],
        "history_index": -1,
        "disabled_tracks": [],
    }

    # Resolve captions — auto-generate from alignment if none exist
    _resolve_project_captions(editor_data, safe_id)
    _cap = editor_data.get("captions") or {}
    _has_entries = bool(_cap.get("entries") or _cap.get("captions"))
    if _has_entries:
        editor_data["captionsEnabled"] = True
    if not _has_entries and source_folder:
        try:
            from scriptase.modules.captions.presets import (
                _get_default_caption_preset_id,
                CAPTION_PRESETS,
            )
            from scriptase.modules.captions.service import _group_words_into_captions
            align_path = os.path.join(ALIGN_DIR, source_folder, "alignment.json")
            if os.path.isfile(align_path):
                alignment_raw = safe_json_read(align_path)
                # alignment.json may be a dict with word_alignment key or a plain list
                if isinstance(alignment_raw, dict):
                    alignment = alignment_raw.get("word_alignment") or alignment_raw.get("alignment") or []
                elif isinstance(alignment_raw, list):
                    alignment = alignment_raw
                else:
                    alignment = []
                if alignment:
                    captions = _group_words_into_captions(alignment, words_per_group=3)
                    if captions:
                        preset_id = _get_default_caption_preset_id()
                        style = dict(CAPTION_PRESETS.get(preset_id, CAPTION_PRESETS.get("bold_popup", {})))
                        style["preset"] = preset_id
                        captions_result = {
                            "project_id": safe_id,
                            "source_folder": source_folder,
                            "captions": captions,
                            "style": style,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                        }
                        # Save for future use
                        cap_dir = os.path.join(CAPTIONS_DIR, safe_id)
                        os.makedirs(cap_dir, exist_ok=True)
                        safe_json_write(os.path.join(cap_dir, "captions.json"), captions_result, indent=2)
                        editor_data["captions"] = captions_result
                        editor_data["captionsEnabled"] = True
                        logger.info("Auto-generated {} captions for {}", len(captions), safe_id)
        except Exception as e:
            logger.debug("Could not auto-generate captions for {}: {}", safe_id, e)

    # Save as initial.json in output/projects/{id}/
    editor_data["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    proj_dir = _project_dir(safe_id)
    os.makedirs(proj_dir, exist_ok=True)
    safe_json_write(os.path.join(proj_dir, INITIAL_FILENAME), editor_data, indent=2)

    logger.info("Assembled editor project for {}", safe_id)

    editor_data["_source"] = "initial"
    return editor_data


def _step_assemble(project_id):
    """Step 6: Assemble project for the editor."""
    # Direct service invocation: never loop back through Flask over HTTP.
    data = assemble_project_for_editor(project_id, _direct=True, force=True)
    logger.success("Pipeline Assemble: {} scenes, {}s duration",
                   data.get("scene_count", 0),
                   data.get("total_duration", 0))
    return {
        "scene_count": data.get("scene_count", 0),
        "total_duration": data.get("total_duration", 0),
        "has_audio": bool(data.get("audio_tracks")),
        "has_captions": bool((data.get("captions") or {}).get("captions")),
        "assembled_data": data,
    }
