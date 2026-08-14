"""Step 8.2: guarded workflow node developer hot reload."""

import json
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from scriptase.providers.domains import DOMAINS
from scriptase.providers.hub import ReloadReport, hub as provider_hub
from scriptase.engine import workflows_bp
from scriptase.engine.dev_reload import WorkflowDevReloader, dev_reload_enabled
from scriptase.engine.registry import load_generated_node_types, reload_generated_node_types

DOMAINS_TTS_BASE = DOMAINS["tts"].providers_base


def _definition(display_name="Hot Node"):
    return {
        "key": "dev.hot_node",
        "definition": {
            "type_version": 1,
            "display_name": display_name,
            "description": "Reload test node.",
            "category": "utility",
            "icon": "box",
            "inputs": [],
            "outputs": [{"id": "control", "type": "control"}],
            "config_schema": [],
            "capabilities": {"retry": False, "cancel": False},
            "executor": "scriptase.engine.adapters.generated.dev_hot_node:execute",
        },
    }


def test_flag_is_strictly_opt_in():
    assert not dev_reload_enabled({})
    assert not dev_reload_enabled({"STS_WORKFLOW_DEV_RELOAD": "0"})
    assert dev_reload_enabled({"STS_WORKFLOW_DEV_RELOAD": "yes"})


def test_disabled_reloader_never_starts_or_scans(tmp_path):
    reloader = WorkflowDevReloader(tmp_path, enabled=False)
    assert reloader.start() is False
    assert reloader.scan_once() is False
    assert reloader.running is False


def test_enabled_reloader_detects_changes_and_publishes(tmp_path):
    workflows = tmp_path / "workflows"
    definitions = workflows / "node_definitions"
    definitions.mkdir(parents=True)
    path = definitions / "dev.hot_node.json"
    path.write_text(json.dumps(_definition()), encoding="utf-8")
    reloader = WorkflowDevReloader(workflows, enabled=True)
    reloader._snapshot = reloader.snapshot()
    channel = reloader.subscribe()

    called = []
    reloader._reload = lambda changed: called.extend(changed)
    path.write_text(json.dumps(_definition("Changed Hot Node")), encoding="utf-8")

    assert reloader.scan_once() is True
    assert path.resolve() in called
    assert channel.get_nowait()["generation"] == 1


def test_definition_change_reaches_live_registry_without_process_restart(tmp_path):
    workflows = tmp_path / "workflows"
    definitions = workflows / "node_definitions"
    definitions.mkdir(parents=True)
    path = definitions / "dev.hot_node.json"
    path.write_text(json.dumps(_definition()), encoding="utf-8")
    reloader = WorkflowDevReloader(workflows, enabled=True)
    reloader._snapshot = reloader.snapshot()

    path.write_text(json.dumps(_definition("Palette Updated")), encoding="utf-8")
    try:
        assert reloader.scan_once() is True
        from scriptase.engine.registry import serialize_registry
        assert serialize_registry()["node_types"]["dev.hot_node"]["display_name"] == "Palette Updated"
    finally:
        # Do not leak the temporary developer catalog into other tests.
        reload_generated_node_types()


def test_generated_registry_refresh_is_atomic_on_invalid_edit(tmp_path):
    path = tmp_path / "dev.hot_node.json"
    path.write_text(json.dumps(_definition()), encoding="utf-8")
    loaded = load_generated_node_types(tmp_path)
    assert loaded["dev.hot_node"]["display_name"] == "Hot Node"

    path.write_text("{invalid", encoding="utf-8")
    try:
        reload_generated_node_types(tmp_path)
    except RuntimeError:
        pass
    else:
        raise AssertionError("invalid definition should fail")
    # Restore the process catalog for the rest of the suite. The failed load
    # itself made no mutation because validation precedes the atomic swap.
    reload_generated_node_types()


def test_provider_sources_are_watched_from_the_domain_catalog():
    """Step 11.2: a provider edit must be observable without a central file list."""
    from scriptase.providers.domains import DOMAINS

    reloader = WorkflowDevReloader(enabled=True)
    watched = {path.resolve() for path in reloader.watched_provider_files()}

    tts_manifest = Path(DOMAINS["tts"].providers_base) / "kokoro" / "manifest.py"
    assert tts_manifest.resolve() in watched
    assert all(
        path.name in {"manifest.py", "provider.py", "settings_schema.py"} for path in watched
    )


def test_a_provider_edit_triggers_a_guarded_catalog_reload():
    reloader = WorkflowDevReloader(enabled=True)
    manifest = Path(DOMAINS_TTS_BASE) / "kokoro" / "manifest.py"

    with patch.object(provider_hub, "reload") as reload_mock:
        reload_mock.return_value = ReloadReport(swapped=["tts"])
        reloader._reload_providers([manifest])

    reload_mock.assert_called_once_with(["tts"])


def test_a_workflow_only_edit_never_touches_the_provider_catalog():
    reloader = WorkflowDevReloader(enabled=True)

    with patch.object(provider_hub, "reload") as reload_mock:
        reloader._reload_providers([Path(__file__)])

    reload_mock.assert_not_called()


def test_dev_event_endpoint_is_hidden_when_flag_is_off():
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    with patch.dict("os.environ", {"STS_WORKFLOW_DEV_RELOAD": ""}):
        response = app.test_client().get("/api/workflow/dev-reload/events")
    assert response.status_code == 404


def test_node_types_advertises_dev_reload_only_when_enabled():
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    client = app.test_client()
    with patch.dict("os.environ", {"STS_WORKFLOW_DEV_RELOAD": ""}):
        assert client.get("/api/workflow/node-types").get_json()["dev_reload_enabled"] is False
    with patch.dict("os.environ", {"STS_WORKFLOW_DEV_RELOAD": "1"}):
        assert client.get("/api/workflow/node-types").get_json()["dev_reload_enabled"] is True
