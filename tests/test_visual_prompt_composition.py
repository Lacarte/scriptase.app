"""Step 2.2 acceptance tests for Channel visual prompt composition."""

from __future__ import annotations

from scriptase.channels.migrations import apply_migrations
from scriptase.modules.image.providers.contract import StoryboardRequest
from scriptase.modules.scene_director.providers.contract import SceneSpec
from scriptase.prompts.visual import compose_visual_prompt


def test_two_channel_styles_diverge_for_the_same_scene_subject():
    subject = "A glass observatory above a stormy ocean"
    channel_a = compose_visual_prompt(
        subject,
        "Soft watercolor washes with handmade paper texture",
        "hopeful",
        "9:16",
    )
    channel_b = compose_visual_prompt(
        subject,
        "High-contrast monochrome film noir with hard grain",
        "hopeful",
        "9:16",
    )

    assert channel_a != channel_b
    assert channel_a.startswith(subject)
    assert "watercolor" in channel_a
    assert "film noir" in channel_b
    assert channel_a.endswith("Aspect ratio: 9:16.")


def test_image_request_uses_the_canonical_composer_on_director_components():
    scene = SceneSpec(
        index=4,
        scene_subject="A glass observatory above a stormy ocean",
        visual_style_prompt="Soft watercolor washes",
        mood="hopeful",
        prompt_aspect_ratio="1:1",
        # Deliberately stale: the image boundary must rebuild from components.
        image_prompt="stale prompt",
    )

    request = StoryboardRequest.from_scene_specs([scene], aspect_ratio="9:16")

    assert request.scenes[0].index == 4
    assert request.scenes[0].prompt == compose_visual_prompt(
        scene.scene_subject,
        scene.visual_style_prompt,
        scene.mood,
        scene.prompt_aspect_ratio,
    )


def test_v2_channel_migrates_visual_style_prompt_from_existing_style():
    legacy = {
        "id": "ch_AAAAAA",
        "name": "Noir Channel",
        "version": 7,
        "schema_version": 2,
        "visual_direction": {"style": "noir"},
    }

    migrated, changed = apply_migrations(legacy)

    assert changed is True
    # Later Channel fields continue the same hop-by-hop migration chain.
    assert migrated["schema_version"] == 4
    assert migrated["visual_direction"]["style_prompt"] == "noir"
    assert migrated["audio_defaults"]["remove_silence"] is True
    assert migrated["version"] == 7
