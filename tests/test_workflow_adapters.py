import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from studio.workflows.adapters import AdapterContext, AdapterError
from studio.workflows.adapters import animator, captions, editor, export, music, project, scenes, segmenter, storyboard, timing, tts


CTX = AdapterContext(project_id="pm_ABC123")


def test_project_setup_emits_validated_managed_logo(monkeypatch, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    monkeypatch.setattr(project, "BRANDING_DIR", str(tmp_path))
    result = project.setup({}, {"logo_enabled": True, "logo": {"ref": "branding/logo.png"}}, CTX)
    assert result["settings"]["logo"]["path"] == "branding/logo.png"
    assert result["settings"]["artifact_refs"] == ["branding/logo.png"]


def test_tts_adapter_translates_ports_and_inherited_defaults(monkeypatch, tmp_path):
    # Absolute paths must live under OUTPUT_DIR so artifact_ref accepts them.
    import studio.workflows.adapters.common as adapter_common

    managed = tmp_path / "tts" / "pm_ABC123"
    managed.mkdir(parents=True)
    wav = managed / "voice.wav"
    (managed / "tts.json").write_text("{}")
    wav.write_bytes(b"wav")
    monkeypatch.setattr(adapter_common, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(tts, "_step_tts", lambda cfg, pid, ctx=None: {
        "wav_path": str(wav), "filename": "voice.wav", "folder": pid,
        "duration_seconds": 1.2, "sample_rate": 24000, "voice": cfg["voice"],
    })
    result = tts.generate(
        {"script": "hello", "settings": {"tone": "dramatic"}},
        {"engine": "kokoro", "voice": "af_heart"},
        CTX,
    )
    assert result["metadata"]["voice"] == "af_heart"
    assert result["audio"]["duration_seconds"] == 1.2
    # §36 L7 (15.3): absolute paths never leave the TTS ports.
    assert not os.path.isabs(result["audio"]["wav_path"])
    assert not os.path.isabs(result["metadata"]["wav_path"])
    assert "path" not in result["audio"]
    assert result["audio"]["artifact_refs"]
    assert result["audio"]["wav_path"] == result["audio"]["artifact_refs"][0]


def test_timing_maps_empty_alignment_to_stable_error(monkeypatch):
    monkeypatch.setattr(timing, "_step_timing", Mock(side_effect=RuntimeError("empty")))
    monkeypatch.setattr(
        timing, "resolve_ref",
        lambda ref, **kwargs: f"/managed/{ref}",
    )
    with pytest.raises(AdapterError, match="empty") as raised:
        timing.align({
            "audio": {"artifact_refs": ["tts/pm_ABC123/voice.wav"], "wav_path": "tts/pm_ABC123/voice.wav"},
            "script": "hello",
        }, {}, CTX)
    assert raised.value.code == "ALIGNMENT_EMPTY"


def test_timing_resolves_audio_through_artifact_refs(monkeypatch):
    seen = {}

    def capture(metadata, config, pid):
        seen.update(metadata)
        return {"folder": pid, "alignment": [{"word": "hi", "begin": 0, "end": 0.2}]}

    monkeypatch.setattr(timing, "_step_timing", capture)
    monkeypatch.setattr(timing, "ALIGN_DIR", "/tmp/align")
    monkeypatch.setattr(
        timing, "with_artifacts",
        lambda payload, *paths: {**payload, "artifact_refs": list(paths)},
    )
    monkeypatch.setattr(
        timing, "resolve_ref",
        lambda ref, **kwargs: f"D:/managed/{ref.replace('/', os.sep)}",
    )
    result = timing.align({
        "audio": {
            "artifact_refs": ["tts/pm_ABC123/voice.wav", "tts/pm_ABC123/tts.json"],
            "filename": "voice.wav",
            "folder": "pm_ABC123",
        },
        "script": "hello",
    }, {}, CTX)
    assert seen["wav_path"].endswith(os.path.join("tts", "pm_ABC123", "voice.wav"))
    assert seen["filename"] == "voice.wav"
    assert result["alignment"]["folder"] == CTX.project_id


def test_segmenter_adapter_uses_service_result(monkeypatch):
    monkeypatch.setattr(segmenter, "_step_segment", lambda value, cfg, pid: {"output_path": "x", "segments": [], "project_id": pid})
    monkeypatch.setattr(segmenter, "with_artifacts", lambda payload, *paths: payload)
    assert segmenter.run({"alignment": {"alignment": []}}, {}, CTX)["segments"]["project_id"] == CTX.project_id


def test_scenes_explicit_config_beats_project_settings(monkeypatch):
    seen = {}

    class FakeProvider:
        def generate(self, segments, configuration, *, project_id):
            seen.update(configuration)
            return {
                "scenes": [{"image_prompt": "p"}],
                "path": "scenes/pm_x/scenes.json",
            }

    monkeypatch.setattr(scenes, "resolve_provider", lambda domain, selected: FakeProvider())
    monkeypatch.setattr(scenes, "provider_run_options", lambda *a, **k: {})
    monkeypatch.setattr(scenes, "with_artifacts", lambda payload, *paths: payload)
    scenes.blueprint(
        {"segments": {}, "script": "x", "settings": {"style": "inherited", "tone": "dark"}},
        {"style": "explicit"},
        CTX,
    )
    assert seen["style"] == "explicit"
    assert seen["story_tone"] == "dark"


@pytest.mark.parametrize("module,method,input_port,output_port", [
    (storyboard, "_step_storyboard", "scenes", "images"),
    (animator, "_step_assets", "scenes", "assets"),
])
def test_provider_adapters_expose_typed_outputs(monkeypatch, module, method, input_port, output_port):
    monkeypatch.setattr(module, method, lambda *args: {"total": 1, "ready": 1, "errors": 0})
    monkeypatch.setattr(module, "with_artifacts", lambda payload, *paths: payload)
    result = module.generate({input_port: {"scenes": [{"image_prompt": "p"}]}}, {}, CTX)
    assert result[output_port]["ready"] == 1


@pytest.mark.parametrize("module,method,input_port,code", [
    (storyboard, "_step_storyboard", "scenes", "STORYBOARD_FAILED"),
    (animator, "_step_assets", "scenes", "ANIMATOR_FAILED"),
])
def test_provider_adapters_fail_when_no_assets_produced(monkeypatch, module, method, input_port, code):
    # Live finding (step 6.1): a rejected provider key errors every scene but
    # still completes the manifest; the node must fail, not report success.
    monkeypatch.setattr(module, method, lambda *args: {"total": 2, "ready": 0, "errors": 2})
    with pytest.raises(AdapterError) as raised:
        module.generate({input_port: {"scenes": [{"image_prompt": "p"}]}}, {}, CTX)
    assert raised.value.code == code


def test_empty_node_config_does_not_mask_inherited_settings(monkeypatch):
    # Live finding (step 6.1): music.select carries story_tone="" as its schema
    # default, which silently discarded the tone configured in Project Setup.
    seen = {}

    class FakeProvider:
        def generate(self, segments, configuration, *, project_id):
            seen.update(configuration)
            return {
                "scenes": [{"image_prompt": "p"}],
                "path": "scenes/pm_x/scenes.json",
            }

    monkeypatch.setattr(scenes, "resolve_provider", lambda domain, selected: FakeProvider())
    monkeypatch.setattr(scenes, "provider_run_options", lambda *a, **k: {})
    monkeypatch.setattr(scenes, "with_artifacts", lambda payload, *paths: payload)
    scenes.blueprint(
        {"segments": {}, "script": "x", "settings": {"tone": "educational"}},
        {"story_tone": "", "style_prompt": ""},
        CTX,
    )
    assert seen["story_tone"] == "educational"
    assert seen["style_prompt"] == ""  # nothing inherited: the empty value stays


def test_caption_adapter_writes_fixture_project(monkeypatch, tmp_path):
    monkeypatch.setattr(captions, "CAPTIONS_DIR", str(tmp_path))
    monkeypatch.setattr(captions, "with_artifacts", lambda payload, *paths: {**payload, "artifact_refs": list(paths)})
    result = captions.generate({"alignment": {"folder": "sample", "alignment": [
        {"word": "hello", "begin": 0.0, "end": 0.4},
        {"word": "world", "begin": 0.4, "end": 0.8},
    ]}}, {"preset_id": "bold_popup", "words_per_group": 2}, CTX)
    assert result["captions"]["captions"][0]["text"] == "hello world"
    assert (tmp_path / "sample" / "captions.json").is_file()


def test_music_specific_rejects_unmanaged_file(tmp_path):
    track = tmp_path / "track.mp3"
    track.write_bytes(b"audio")
    with pytest.raises(AdapterError) as raised:
        music.select({}, {"mode": "specific", "track_ref": str(track)}, CTX)
    assert raised.value.code == "ARTIFACT_UNMANAGED"


def test_assemble_adapter_calls_service_with_project_only(monkeypatch):
    service = Mock(return_value={"assembled_data": {}, "scene_count": 0})
    monkeypatch.setattr(editor, "_step_assemble", service)
    monkeypatch.setattr(editor, "with_artifacts", lambda payload, *paths: payload)
    monkeypatch.setattr(editor, "safe_json_write", lambda *args, **kwargs: None)
    editor.assemble({"assets": {}, "metadata": {}, "scenes": {}}, {}, CTX)
    service.assert_called_once_with("pm_ABC123")


def test_export_adapter_builds_logo_payload_without_http(monkeypatch, tmp_path):
    captured = {}
    class Processor:
        def __init__(self, payload, progress_callback=None):
            captured.update(payload)
        def process(self, path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"video")
    monkeypatch.setattr(export, "VideoProcessor", Processor)
    monkeypatch.setattr(export, "EXPORT_DIR", str(tmp_path))
    monkeypatch.setattr(export, "with_artifacts", lambda payload, *paths: payload)
    project_payload = {"assembled_data": {"scenes": [{"id": 1, "duration": 1, "mediaUrl": "/output/a.png"}], "total_duration": 1}}
    settings = {"logo_enabled": True, "logo": {"ref": "branding/logo.png"}, "logo_position": "bottom_left", "logo_size": 12}
    result = export.video({"project": project_payload, "settings": settings}, {"profile": "square"}, CTX)
    assert result["video"]["resolution"] == "1080x1080"
    assert captured["logo_overlay"]["position"] == "bottom_left"
