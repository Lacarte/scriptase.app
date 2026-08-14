"""Built-in, versioned workflow templates."""

from __future__ import annotations

from .models import workflow_draft
from .registry import get_node_type
from .validation import validate_workflow, validation_errors


def _node(node_id: str, type_key: str, x: int, y: int, *, name: str | None = None, config: dict | None = None) -> dict:
    definition = get_node_type(type_key)
    configuration = {
        field["name"]: field.get("default") for field in definition["config_schema"]
    }
    if config:
        configuration.update(config)
    return {
        "id": node_id,
        "type": type_key,
        "type_version": definition["type_version"],
        "name": name or definition["display_name"],
        "position": {"x": x, "y": y},
        "configuration": configuration,
        "disabled": False,
    }


def _edge(edge_id: str, source: str, source_port: str, target: str, target_port: str, edge_type: str = "data") -> dict:
    return {
        "id": edge_id,
        "source_node": source,
        "source_port": source_port,
        "target_node": target,
        "target_port": target_port,
        "edge_type": edge_type,
    }


def full_video_template() -> dict:
    doc = workflow_draft(name="Full Video", description="Complete ScriptToScene production workflow")
    doc["template_id"] = "full_video"  # removed before validation/persistence
    doc["nodes"] = [
        _node("n_trigger", "trigger.manual", 0, 220),
        _node("n_setup", "project.setup", 220, 80),
        _node("n_script", "script.input", 220, 340),
        _node("n_tts", "tts.generate", 500, 340),
        _node("n_align", "timing.align", 760, 340),
        _node("n_segment", "segment.run", 1020, 340),
        _node("n_scenes", "scenes.blueprint", 1280, 340),
        _node("n_storyboard", "storyboard.generate", 1540, 190),
        _node("n_animator", "animator.generate", 1800, 340),
        _node("n_captions", "captions.generate", 1280, 570),
        _node("n_music", "music.select", 760, 80),
        _node("n_assemble", "assemble.project", 2060, 340),
        _node("n_timeline", "timeline.project", 2320, 340),
        _node("n_export", "export.video", 2580, 340),
        _node("n_output", "workflow.output", 2840, 340, config={"port_type": "video_file", "label": "Final video"}),
    ]
    doc["edges"] = [
        _edge("e_trigger_setup", "n_trigger", "control", "n_setup", "trigger", "control"),
        _edge("e_trigger_script", "n_trigger", "control", "n_script", "trigger", "control"),
        _edge("e_script_tts", "n_script", "script", "n_tts", "script"),
        _edge("e_setup_tts", "n_setup", "settings", "n_tts", "settings"),
        _edge("e_tts_align_audio", "n_tts", "audio", "n_align", "audio"),
        _edge("e_script_align", "n_script", "script", "n_align", "script"),
        _edge("e_align_segment", "n_align", "alignment", "n_segment", "alignment"),
        _edge("e_segment_scenes", "n_segment", "segments", "n_scenes", "segments"),
        _edge("e_script_scenes", "n_script", "script", "n_scenes", "script"),
        _edge("e_setup_scenes", "n_setup", "settings", "n_scenes", "settings"),
        _edge("e_scenes_storyboard", "n_scenes", "scenes", "n_storyboard", "scenes"),
        _edge("e_setup_storyboard", "n_setup", "settings", "n_storyboard", "settings"),
        _edge("e_scenes_animator", "n_scenes", "scenes", "n_animator", "scenes"),
        _edge("e_storyboard_animator", "n_storyboard", "images", "n_animator", "storyboard"),
        _edge("e_setup_animator", "n_setup", "settings", "n_animator", "settings"),
        _edge("e_align_captions", "n_align", "alignment", "n_captions", "alignment"),
        _edge("e_setup_music", "n_setup", "settings", "n_music", "settings"),
        _edge("e_animator_assemble", "n_animator", "assets", "n_assemble", "assets"),
        _edge("e_tts_assemble", "n_tts", "metadata", "n_assemble", "metadata"),
        _edge("e_scenes_assemble", "n_scenes", "scenes", "n_assemble", "scenes"),
        _edge("e_captions_assemble", "n_captions", "captions", "n_assemble", "captions"),
        _edge("e_music_assemble", "n_music", "track", "n_assemble", "music"),
        _edge("e_setup_assemble", "n_setup", "settings", "n_assemble", "settings"),
        _edge("e_assemble_timeline", "n_assemble", "project", "n_timeline", "project"),
        _edge("e_timeline_export", "n_timeline", "project", "n_export", "project"),
        _edge("e_setup_export", "n_setup", "settings", "n_export", "settings"),
        _edge("e_export_output", "n_export", "video", "n_output", "value"),
    ]
    return doc


def narration_only_template() -> dict:
    doc = workflow_draft(name="Narration Only", description="Turn a script into narration audio")
    doc["template_id"] = "narration_only"
    doc["nodes"] = [
        _node("n_trigger", "trigger.manual", 0, 160),
        _node("n_script", "script.input", 240, 160),
        _node("n_tts", "tts.generate", 500, 160),
        _node(
            "n_output", "workflow.output", 760, 160,
            config={"port_type": "audio_file", "label": "Narration audio"},
        ),
    ]
    doc["edges"] = [
        _edge("e_trigger_script", "n_trigger", "control", "n_script", "trigger", "control"),
        _edge("e_script_tts", "n_script", "script", "n_tts", "script"),
        _edge("e_tts_output", "n_tts", "audio", "n_output", "value"),
    ]
    return doc


def storyboard_only_template() -> dict:
    doc = workflow_draft(name="Storyboard Only", description="Generate storyboard images from a script")
    doc["template_id"] = "storyboard_only"
    doc["nodes"] = [
        _node("n_trigger", "trigger.manual", 0, 220),
        _node("n_script", "script.input", 240, 220),
        _node("n_tts", "tts.generate", 500, 100),
        _node("n_align", "timing.align", 760, 220),
        _node("n_segment", "segment.run", 1020, 220),
        _node("n_scenes", "scenes.blueprint", 1280, 220),
        _node("n_storyboard", "storyboard.generate", 1540, 220),
        _node(
            "n_output", "workflow.output", 1800, 220,
            config={"port_type": "storyboard_images", "label": "Storyboard images"},
        ),
    ]
    doc["edges"] = [
        _edge("e_trigger_script", "n_trigger", "control", "n_script", "trigger", "control"),
        _edge("e_script_tts", "n_script", "script", "n_tts", "script"),
        _edge("e_tts_align_audio", "n_tts", "audio", "n_align", "audio"),
        _edge("e_script_align", "n_script", "script", "n_align", "script"),
        _edge("e_align_segment", "n_align", "alignment", "n_segment", "alignment"),
        _edge("e_segment_scenes", "n_segment", "segments", "n_scenes", "segments"),
        _edge("e_script_scenes", "n_script", "script", "n_scenes", "script"),
        _edge("e_scenes_storyboard", "n_scenes", "scenes", "n_storyboard", "scenes"),
        _edge("e_storyboard_output", "n_storyboard", "images", "n_output", "value"),
    ]
    return doc


def reexport_existing_project_template() -> dict:
    doc = workflow_draft(
        name="Re-export Existing Project",
        description="Render a new export from an existing timeline project",
    )
    doc["template_id"] = "reexport_existing_project"
    doc["nodes"] = [
        _node("n_trigger", "trigger.manual", 0, 160),
        _node("n_project", "project.existing", 260, 160),
        _node("n_export", "export.video", 540, 160),
        _node(
            "n_output", "workflow.output", 820, 160,
            config={"port_type": "video_file", "label": "Exported video"},
        ),
    ]
    doc["edges"] = [
        _edge("e_trigger_project", "n_trigger", "control", "n_project", "trigger", "control"),
        _edge("e_project_export", "n_project", "project", "n_export", "project"),
        _edge("e_export_output", "n_export", "video", "n_output", "value"),
    ]
    return doc


def text_to_video_template() -> dict:
    """Full production without a Storyboard node (step 6.2).

    Scene Director output feeds the Animator directly. The video provider is
    ``kie_ai`` (``text_to_video``). The default ``full_video`` template still
    routes through image-to-video for visual consistency.
    """
    doc = workflow_draft(
        name="Text to Video",
        description=(
            "Complete production without storyboard images — "
            "Scene Director prompts drive a text_to_video provider"
        ),
    )
    doc["template_id"] = "text_to_video"
    doc["nodes"] = [
        _node("n_trigger", "trigger.manual", 0, 220),
        _node("n_setup", "project.setup", 220, 80),
        _node("n_script", "script.input", 220, 340),
        _node("n_tts", "tts.generate", 500, 340),
        _node("n_align", "timing.align", 760, 340),
        _node("n_segment", "segment.run", 1020, 340),
        _node("n_scenes", "scenes.blueprint", 1280, 340),
        # No storyboard.generate — optional image dependency (step 6.2).
        _node(
            "n_animator",
            "animator.generate",
            1540,
            340,
            config={"provider_id": "kie_ai"},
        ),
        _node("n_captions", "captions.generate", 1280, 570),
        _node("n_music", "music.select", 760, 80),
        _node("n_assemble", "assemble.project", 1800, 340),
        _node("n_timeline", "timeline.project", 2060, 340),
        _node("n_export", "export.video", 2320, 340),
        _node(
            "n_output",
            "workflow.output",
            2580,
            340,
            config={"port_type": "video_file", "label": "Final video"},
        ),
    ]
    doc["edges"] = [
        _edge("e_trigger_setup", "n_trigger", "control", "n_setup", "trigger", "control"),
        _edge("e_trigger_script", "n_trigger", "control", "n_script", "trigger", "control"),
        _edge("e_script_tts", "n_script", "script", "n_tts", "script"),
        _edge("e_setup_tts", "n_setup", "settings", "n_tts", "settings"),
        _edge("e_tts_align_audio", "n_tts", "audio", "n_align", "audio"),
        _edge("e_script_align", "n_script", "script", "n_align", "script"),
        _edge("e_align_segment", "n_align", "alignment", "n_segment", "alignment"),
        _edge("e_segment_scenes", "n_segment", "segments", "n_scenes", "segments"),
        _edge("e_script_scenes", "n_script", "script", "n_scenes", "script"),
        _edge("e_setup_scenes", "n_setup", "settings", "n_scenes", "settings"),
        _edge("e_scenes_animator", "n_scenes", "scenes", "n_animator", "scenes"),
        _edge("e_setup_animator", "n_setup", "settings", "n_animator", "settings"),
        _edge("e_align_captions", "n_align", "alignment", "n_captions", "alignment"),
        _edge("e_setup_music", "n_setup", "settings", "n_music", "settings"),
        _edge("e_animator_assemble", "n_animator", "assets", "n_assemble", "assets"),
        _edge("e_tts_assemble", "n_tts", "metadata", "n_assemble", "metadata"),
        _edge("e_scenes_assemble", "n_scenes", "scenes", "n_assemble", "scenes"),
        _edge("e_captions_assemble", "n_captions", "captions", "n_assemble", "captions"),
        _edge("e_music_assemble", "n_music", "track", "n_assemble", "music"),
        _edge("e_setup_assemble", "n_setup", "settings", "n_assemble", "settings"),
        _edge("e_assemble_timeline", "n_assemble", "project", "n_timeline", "project"),
        _edge("e_timeline_export", "n_timeline", "project", "n_export", "project"),
        _edge("e_setup_export", "n_setup", "settings", "n_export", "settings"),
        _edge("e_export_output", "n_export", "video", "n_output", "value"),
    ]
    return doc


def serialize_templates() -> list[dict]:
    result = []
    for template in (
        full_video_template(),
        text_to_video_template(),
        narration_only_template(),
        storyboard_only_template(),
        reexport_existing_project_template(),
    ):
        template_id = template.pop("template_id")
        # Templates may intentionally leave required user-authored configuration
        # (notably Script Input text) blank, but the graph itself must be valid.
        problems = validate_workflow(template, require_identity=False, require_complete=False)
        errors = validation_errors(problems)
        if errors:
            raise RuntimeError(f"Built-in template {template_id} is invalid: {errors}")
        result.append({"template_id": template_id, "workflow": template})
    return result
