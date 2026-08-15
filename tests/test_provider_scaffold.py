"""Step 16.2: provider scaffolder behaviour and atomic failure."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from scriptase.providers.domains import DOMAIN_IDS
from scriptase.providers import scaffold as scaffold_module
from scriptase.providers.scaffold import (
    ScaffoldError,
    build_parser,
    generated_test_path,
    scaffold_provider,
)
from scriptase.providers.validation import ID_RE, KINDS

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_scaffolder_emits_v2_package_and_contract_tests_for_every_domain(tmp_path):
    for domain in sorted(DOMAIN_IDS):
        provider_id = f"demo_{domain[:6]}"
        # id must match ID_RE (max 32); keep short.
        provider_id = provider_id[:32]
        paths = scaffold_provider(
            domain,
            provider_id,
            kind="local",
            project_root=tmp_path,
            check_live_collision=False,
        )
        assert all(path.exists() for path in paths)
        manifest_path = next(p for p in paths if p.name == "manifest.py")
        mod = _load(manifest_path, f"m_{domain}")
        manifest = mod.manifest()
        assert manifest.contract_version == 2
        assert manifest.domain == domain
        assert manifest.id == provider_id
        assert (manifest_path.parent / "provider.py").is_file()
        assert (manifest_path.parent / "settings_schema.py").is_file()
        test_path = next(p for p in paths if p.name.startswith("test_provider_"))
        text = test_path.read_text(encoding="utf-8")
        assert "assert_manifest_v2" in text
        assert provider_id in text


def test_scaffolder_script_skeleton_executes_offline(tmp_path, monkeypatch):
    paths = scaffold_provider(
        "script",
        "demo_echo",
        kind="local",
        project_root=tmp_path,
        check_live_collision=False,
    )
    provider_path = next(p for p in paths if p.name == "provider.py")
    mod = _load(provider_path, "scaffold_demo_echo")
    stories = tmp_path / "stories"
    stories.mkdir()
    monkeypatch.setattr(mod, "STORIES_DIR", str(stories))
    result = mod.create().generate(
        {"idea": "hello world", "label_prefix": "Hi"},
        project_id="pm_DEMO01",
    )
    assert result["story_text"].startswith("Hi:")
    assert (stories / "pm_DEMO01" / "story.json").is_file()


def test_scaffolder_refuses_unknown_domain_invalid_id_and_kind():
    with pytest.raises(ScaffoldError, match="unknown domain"):
        scaffold_provider("music", "x", check_live_collision=False)
    with pytest.raises(ScaffoldError, match="provider_id"):
        scaffold_provider("script", "Bad-Id", check_live_collision=False)
    with pytest.raises(ScaffoldError, match="unknown kind"):
        scaffold_provider("script", "ok_id", kind="plugin", check_live_collision=False)


def test_scaffolder_refuses_collision_without_partial_files(tmp_path):
    scaffold_provider(
        "tts",
        "once_only",
        project_root=tmp_path,
        check_live_collision=False,
    )
    provider_dir = (
        tmp_path / "scriptase" / "modules" / "tts" / "providers" / "once_only"
    )
    assert provider_dir.is_dir()

    with pytest.raises(ScaffoldError, match="already exists"):
        scaffold_provider(
            "tts",
            "once_only",
            project_root=tmp_path,
            check_live_collision=False,
        )

    # Existing package untouched; no sibling partial folders.
    siblings = {p.name for p in provider_dir.parent.iterdir()}
    assert siblings == {"once_only"}


def test_scaffolder_atomic_failure_cleans_partial_writes(tmp_path, monkeypatch):
    """If a later write fails, earlier files and the provider dir are removed."""
    from scriptase.providers import scaffold as scaffold_mod

    real_write = Path.write_text
    calls = {"n": 0}

    def flaky(self, data, *args, **kwargs):
        calls["n"] += 1
        # Fail after the first two successful writes so a partial tree exists.
        if calls["n"] == 3:
            raise OSError("disk full (simulated)")
        return real_write(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky)
    with pytest.raises(OSError, match="disk full"):
        scaffold_provider(
            "script",
            "partial_fail",
            project_root=tmp_path,
            check_live_collision=False,
        )

    provider_dir = tmp_path / "scriptase" / "modules" / "script" / "providers" / "partial_fail"
    assert not provider_dir.exists()
    test_path = tmp_path / "tests" / "test_provider_script_partial_fail.py"
    assert not test_path.exists()


def test_scaffolder_extension_emits_runtime_hook(tmp_path):
    paths = scaffold_provider(
        "image",
        "ext_demo",
        kind="extension",
        project_root=tmp_path,
        check_live_collision=False,
    )
    names = {p.name for p in paths}
    assert "runtime.py" in names
    runtime = next(p for p in paths if p.name == "runtime.py")
    assert "register_runtime" in runtime.read_text(encoding="utf-8")


def test_scaffolder_cli_help_lists_catalog_domains():
    parser = build_parser()
    help_text = parser.format_help()
    for domain in DOMAIN_IDS:
        assert domain in help_text
    for kind in KINDS:
        assert kind in help_text


def test_scaffolder_cli_rejects_bad_port_style_args():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["not_a_domain", "ok_id", "--kind", "nope"])


def test_id_regex_matches_scaffold_rules():
    assert ID_RE.fullmatch("scaffold_check")
    assert not ID_RE.fullmatch("Scaffold_Check")
    assert not ID_RE.fullmatch("a" * 33)


def test_committed_scaffold_check_runs_on_generic_story_node(tmp_path, monkeypatch):
    """Removing the package would break this — there is no central registration."""
    import config
    from scriptase.providers.hub import hub
    from scriptase.engine.adapters import common as adapter_common
    from scriptase.engine.adapters.common import AdapterContext
    from scriptase.engine.adapters.script import generate as story_generate

    instance = hub.get("script", "scaffold_check")
    assert instance is not None
    # Stories must sit under the managed output root the adapter validates against.
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(adapter_common, "OUTPUT_DIR", str(tmp_path), raising=False)
    stories = tmp_path / "stories"
    stories.mkdir()
    monkeypatch.setattr(instance.provider_module, "STORIES_DIR", str(stories))
    # Memoized create() must see the patched module binding.
    instance._instance = None
    outputs = story_generate(
        inputs={},
        config={
            "provider_id": "scaffold_check",
            "idea": "generic node path",
            "label_prefix": "Node",
        },
        context=AdapterContext(project_id="pm_SCFF01"),
    )
    assert outputs["script"].startswith("Node:")
    assert (stories / "pm_SCFF01" / "story.json").is_file()


# ---------------------------------------------------------------------------
# Step 12.5 — the one-command add-a-provider path
# ---------------------------------------------------------------------------


@pytest.fixture
def recorded_runs(monkeypatch):
    """Capture the follow-up steps `main` delegates to, without running them."""
    calls: list[list[str]] = []

    def fake_run(argv, *, cwd):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(scaffold_module, "_run", fake_run)
    return calls


def test_one_command_scaffolds_then_tests_then_documents(tmp_path, recorded_runs):
    """The three steps that always belong together, in that order."""
    code = scaffold_module.main(
        ["tts", "one_cmd", "--kind", "cloud", "--project-root", str(tmp_path)]
    )
    assert code == 0
    package = tmp_path / "scriptase" / "modules" / "tts" / "providers" / "one_cmd"
    assert (package / "manifest.py").is_file()

    assert len(recorded_runs) == 2, recorded_runs
    pytest_call, docs_call = recorded_runs
    assert pytest_call[:2] == ["-m", "pytest"]
    assert pytest_call[2].endswith("test_provider_tts_one_cmd.py")
    assert docs_call == ["-m", "scriptase.engine.docs"]


def test_one_command_steps_can_be_skipped_individually(tmp_path, recorded_runs):
    scaffold_module.main(
        ["tts", "skip_both", "--no-tests", "--no-docs", "--project-root", str(tmp_path)]
    )
    assert recorded_runs == []

    scaffold_module.main(["tts", "skip_docs", "--no-docs", "--project-root", str(tmp_path)])
    assert len(recorded_runs) == 1
    assert recorded_runs[0][:2] == ["-m", "pytest"]


def test_failing_contract_tests_fail_the_command_and_stop_before_docs(tmp_path, monkeypatch):
    """A scaffold whose own generated tests fail must not be reported as success."""
    calls: list[list[str]] = []

    def fake_run(argv, *, cwd):
        calls.append(list(argv))
        return 1

    monkeypatch.setattr(scaffold_module, "_run", fake_run)
    code = scaffold_module.main(["tts", "bad_tests", "--project-root", str(tmp_path)])
    assert code == 1
    assert len(calls) == 1, "docs regeneration ran despite failing contract tests"


def test_failing_docs_regeneration_fails_the_command(tmp_path, monkeypatch):
    def fake_run(argv, *, cwd):
        return 0 if argv[1] == "pytest" else 1

    monkeypatch.setattr(scaffold_module, "_run", fake_run)
    code = scaffold_module.main(["tts", "bad_docs", "--project-root", str(tmp_path)])
    assert code == 1


def test_generated_test_path_picks_the_generated_test(tmp_path):
    paths = scaffold_provider("tts", "find_test", project_root=tmp_path)
    found = generated_test_path(paths)
    assert found is not None
    assert found.name == "test_provider_tts_find_test.py"
    assert generated_test_path([p for p in paths if not p.name.startswith("test_")]) is None


def test_the_one_command_entry_point_is_committed_and_only_transports():
    """`bin/` is gitignored, so the entry point lives beside `start.bat`.

    It must also stay transport: the logic belongs in `scaffold.py`, where the
    headless loop — which can run pytest but not PowerShell — can verify it.
    """
    entry = REPO_ROOT / "new-provider.bat"
    driver = REPO_ROOT / "tools" / "new-provider.ps1"
    assert entry.is_file(), "the documented one-command entry point is missing"
    assert driver.is_file()

    entry_text = entry.read_text(encoding="utf-8")
    assert "tools\\new-provider.ps1" in entry_text
    assert "%*" in entry_text, "arguments must be forwarded verbatim"

    driver_text = driver.read_text(encoding="utf-8")
    assert "scriptase.providers.scaffold" in driver_text
    assert "venv\\Scripts\\python.exe" in driver_text, "python is not on PATH here"
    # No second copy of the scaffolder's vocabulary to rot.
    for domain in DOMAIN_IDS:
        assert f"'{domain}'" not in driver_text


def test_the_author_guide_documents_the_one_command_path():
    """The guide is generated; this is what keeps the prose pointing at reality."""
    guide = (REPO_ROOT / "docs" / "provider-author-guide.md").read_text(encoding="utf-8")
    assert "new-provider.bat" in guide
    assert "--no-tests" in guide and "--no-docs" in guide
    # The counted claim must track the live catalog, not a frozen number.
    assert f"{len(DOMAIN_IDS)} catalog domains" in guide
    assert "five catalog domains" not in guide
