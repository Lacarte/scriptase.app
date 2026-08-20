"""Steps 5.3 / 7.1: the product catalogue contains prototype providers plus the
restored script providers."""

from scriptase.channels.migrations import apply_migrations as migrate_channel
from scriptase.providers.domains import DOMAINS
from scriptase.providers.hub import ProviderHub
from scriptase.providers.settings_migrations import apply_migrations as migrate_settings


EXPECTED = {
    "script": ["gemini", "n8n", "random_template"],
    "scene_director": ["n8n"],
    "tts": ["inworld"],
    "image": ["gemini_ws"],
    "video": ["grok_automa"],
    "review": [],
    "viral": ["deterministic"],
}


def test_catalog_exposes_the_prototype_and_restored_script_providers():
    providers = ProviderHub()
    providers.discover_all()

    found = {domain: providers.registry(domain).list_ids() for domain in providers.domains()}
    assert found == EXPECTED
    assert sum(map(len, found.values())) == 8

    # The committed scaffolder demonstration stays executable without becoming
    # a user-facing catalogue entry.
    assert providers.get("script", "scaffold_check") is not None
    assert "scaffold_check" not in found["script"]


def test_settings_migrate_retired_default_and_named_instances():
    document = {
        "version": 9,
        "domains": {
            "tts": {
                "selected_instance_id": "kokoro",
                "instances": {
                    "kokoro": {"type": "kokoro", "settings": {"voice": "af_heart"}},
                },
            },
            "image": {
                "selected_instance_id": "images_backup",
                "instances": {
                    "images_backup": {
                        "type": "wavespeed_webhook",
                        "label": "Images backup",
                        "settings": {"api_key": "retired"},
                    },
                },
            },
            "video": {
                "selected_instance_id": "kie_ai",
                "instances": {"kie_ai": {"type": "kie_ai", "settings": {}}},
            },
        },
    }

    migrated, changed = migrate_settings(document)

    assert changed is True
    assert migrated["domains"]["tts"] == {
        "selected_instance_id": "inworld",
        "instances": {"inworld": {"type": "inworld", "label": "inworld", "settings": {}}},
    }
    assert migrated["domains"]["image"]["selected_instance_id"] == "images_backup"
    assert migrated["domains"]["image"]["instances"]["images_backup"]["type"] == "gemini_ws"
    assert migrated["domains"]["image"]["instances"]["images_backup"]["settings"] == {}
    assert migrated["domains"]["video"]["selected_instance_id"] == "grok_automa"
    # Step 7.1 restored gemini as the default; v10 now maps it through, v11
    # backfills when needed.
    assert migrated["domains"]["script"]["selected_instance_id"] == "gemini"
    assert migrated["domains"]["script"]["instances"]["gemini"]["type"] == "gemini"
    assert migrated["domains"]["review"] == {"selected_instance_id": None, "instances": {}}
    assert all(
        block["selected_instance_id"] in block["instances"]
        for domain, block in migrated["domains"].items()
        if DOMAINS[domain].default_provider
    )


def test_channel_rewrites_every_direct_retired_provider_reference():
    document = {
        "schema_version": 5,
        "provider_defaults": {
            "script": "random_template",
            "tts": "kokoro",
            "image": "wavespeed_direct",
            "video": "kie_ai",
            "review": "semantic",
        },
        "audio_defaults": {"tts_provider_instance_id": "kokoro"},
        "fallback_policies": {
            "tts": {"primary": "kokoro", "fallbacks": ["kokoro", "inworld"]},
            "video": {"primary": "kie_ai", "fallbacks": ["kie-ai", "grok_automa"]},
        },
    }

    migrated, changed = migrate_channel(document)

    assert changed is True
    assert migrated["provider_defaults"] == {
        "script": "random_template",
        "tts": "inworld",
        "image": "gemini_ws",
        "video": "grok_automa",
        "review": None,
    }
    assert migrated["audio_defaults"]["tts_provider_instance_id"] == "inworld"
    assert migrated["fallback_policies"]["tts"] == {
        "primary": "inworld",
        "fallbacks": ["inworld"],
    }
    assert migrated["fallback_policies"]["video"] == {
        "primary": "grok_automa",
        "fallbacks": ["grok_automa"],
    }
