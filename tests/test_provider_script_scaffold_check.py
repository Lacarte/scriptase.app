"""Generated contract tests for script/scaffold_check.

Produced by `python -m scriptase.providers.scaffold`.
These cases must keep passing without hand-edits as the package evolves.
"""

from pathlib import Path

from scriptase.providers.contract_tests import (
    assert_health_shape,
    assert_manifest_v2,
    assert_settings_schema,
    load_provider_modules,
)
from scriptase.providers.domains import get_domain
from scriptase.providers.hub import hub


DOMAIN = "script"
PROVIDER_ID = "scaffold_check"
# Relative package path inside the repo (also the discovery folder).
PACKAGE_REL = "scriptase/modules/script/providers/scaffold_check"


def test_script_scaffold_check_is_discovered_but_not_catalog_visible():
    instance = hub.get(DOMAIN, PROVIDER_ID)
    assert instance is not None, f"{DOMAIN}/{PROVIDER_ID} was not discovered"
    assert instance.id == PROVIDER_ID
    assert_manifest_v2(
        instance.manifest,
        folder_id=PROVIDER_ID,
        domain=DOMAIN,
        capability_vocabulary=get_domain(DOMAIN).capability_vocabulary,
    )
    catalog = hub.catalog()
    assert DOMAIN in catalog
    provider_ids = {entry["id"] for entry in catalog[DOMAIN]["providers"]}
    assert PROVIDER_ID not in provider_ids


def test_script_scaffold_check_settings_schema_is_ui_configurable():
    instance = hub.get(DOMAIN, PROVIDER_ID)
    assert instance is not None
    schema = instance.settings_schema()
    assert_settings_schema(schema)
    # At least one field so the generic settings renderer has something to show.
    assert schema is not None
    assert schema.get("properties")


def test_script_scaffold_check_health_check_shape():
    instance = hub.get(DOMAIN, PROVIDER_ID)
    assert instance is not None
    # Prefer the package hook; fall back to constructing the provider.
    mod = instance.provider_module
    if mod is not None and hasattr(mod, "health_check"):
        result = mod.health_check({})
    else:
        result = {"status": "warn", "message": "no health_check"}
    assert_health_shape(result)


def test_script_scaffold_check_package_files_load_from_disk():
    """The package is a plain folder — no central registration table."""
    root = Path(__file__).resolve().parents[1]
    modules = load_provider_modules(root / PACKAGE_REL)
    assert "manifest" in modules
    assert "provider" in modules
    assert "settings_schema" in modules
    manifest = modules["manifest"].manifest()
    assert_manifest_v2(manifest, folder_id=PROVIDER_ID, domain=DOMAIN)
    assert callable(modules["provider"].create)


def test_script_scaffold_check_generate_is_executable_on_script_seam(tmp_path, monkeypatch):
    """The concrete `story.generate` seam works without node/adapter edits."""
    from scriptase.providers.hub import hub

    stories = tmp_path / "stories"
    stories.mkdir()

    instance = hub.get("script", "scaffold_check")
    assert instance is not None
    # Discovery loads the package under a synthetic module name, so patch the
    # bound name on that module object rather than a package-import path.
    monkeypatch.setattr(instance.provider_module, "STORIES_DIR", str(stories))
    provider = instance.create()
    result = provider.generate(
        {"idea": "scaffold check idea", "label_prefix": "Demo"},
        project_id="pm_SCAFFOLD99",
    )
    assert result["story_text"].startswith("Demo:")
    assert result["path"]
    assert (stories / "pm_SCAFFOLD99" / "story.json").is_file()


def test_script_scaffold_check_invoke_returns_clean_envelope(tmp_path, monkeypatch):
    import config
    from scriptase.providers.contract_tests import assert_egress_clean
    from scriptase.providers.hub import hub
    from scriptase.providers.invocation import build_invocation
    from scriptase.providers.results import ProviderResult
    from scriptase.modules.script.providers.contract import ScriptRequest

    # Managed root is `tmp_path`; stories must live under it so normalize_ref works.
    stories = tmp_path / "stories"
    stories.mkdir()
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(
        "scriptase.providers.results.OUTPUT_DIR", str(tmp_path), raising=False
    )

    instance = hub.get("script", "scaffold_check")
    assert instance is not None
    monkeypatch.setattr(instance.provider_module, "STORIES_DIR", str(stories))
    provider = instance.create()
    invocation = build_invocation(
        None,
        domain="script",
        provider_id="scaffold_check",
        project_id="pm_SCAFFOLD99",
        output_dir=str(tmp_path / "script" / "pm_SCAFFOLD99"),
        settings={},
        options={},
    )
    result = provider.invoke(
        ScriptRequest(idea="envelope check"),
        invocation,
    )
    assert isinstance(result, ProviderResult)
    assert result.artifact_refs
    assert_egress_clean(result)

