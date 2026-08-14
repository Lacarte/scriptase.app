# Provider Templates

Scaffold a Provider Contract v2 package for any of the five supported domains.
The CLI is the single source of the skeleton — this document describes what it
emits and how to finish the package.

**Primary guide:** the complete scaffold → manifest → settings → implementation
→ results → artifacts → tests → health → ship path, plus troubleshooting, is the
generated [Provider Author Guide](../provider-author-guide.md). The live catalog
is the generated [Provider Reference](../providers.md). Prefer those over this
short layout note when authoring a new provider.

## Quick start

```bash
# Offline script demo (the step-16.2 reference package)
python -m scriptase.providers.scaffold script scaffold_check

# Cloud TTS provider
python -m scriptase.providers.scaffold tts my_provider --kind cloud

# Extension storyboard provider
python -m scriptase.providers.scaffold storyboard my_renderer --kind extension

# Webhook scene-blueprint provider
python -m scriptase.providers.scaffold scene_blueprint my_planner --kind webhook
```

Domains come from the live catalog (`scriptase.providers.domains`):
`script`, `scene_blueprint`, `tts`, `storyboard`, `animator`.

Kinds: `local` | `cloud` | `extension` | `webhook`.

The command refuses unknown domains, invalid ids, existing packages, and
colliding test files. Failure is atomic — no partial provider folder is left
behind.

## Generated layout

```
scriptase/<domain-package>/providers/<provider_id>/
  manifest.py          # ProviderManifest, contract_version=2
  settings_schema.py   # JSON-schema object for the generic settings UI
  provider.py          # create() + domain methods + health/validate hooks
  runtime.py           # only when --kind extension
tests/test_provider_<domain>_<provider_id>.py
```

No central registration table and no node or Vue edit. Discovery scans the
domain's `providers/` folder on startup (and on reload when
`STS_WORKFLOW_DEV_RELOAD=1`).

## Manifest (Contract v2)

```python
from scriptase.providers import ProviderManifest

def manifest() -> ProviderManifest:
    return ProviderManifest(
        id="my_provider",            # must equal the folder name
        label="My Provider",
        domain="tts",                # one of the five catalog domains
        kind="cloud",                # local | cloud | extension | webhook
        version="1.0.0",             # semver
        contract_version=2,          # 2 = invocation/result envelope
        requires=["api_key"],        # settings keys that must be present
        aliases=[],                  # optional input aliases (legacy ids)
        capabilities={
            "test_connection": True,
            "single_scene": True,
            "batch": True,
            # plus domain vocabulary (voice_list, async_job, offline, …)
        },
        description="Short browser-safe summary.",
        docs_url=None,               # https URL only
        environment={"api_key": "STS_MY_PROVIDER_API_KEY"},  # never serialized
        open_url=None,               # optional human-driven UI URL
    )
```

Capabilities outside the domain vocabulary are dropped with a warning at
discovery. See `DomainSpec.capability_vocabulary` in
`scriptase/providers/domains.py`.

## Settings schema

```python
def settings_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "label": "API Key",
                "ui": {"type": "password"},
            },
            "label_prefix": {
                "type": "string",
                "label": "Label prefix",
                "default": "",
                "ui": {"type": "text"},
            },
        },
        "required": ["api_key"],
    }
```

Widget types: `text`, `password`, `dropdown`, `slider`, `toggle`, `file_picker`,
`path_picker`, `multi_select`. Password fields and keys matching
`*_key` / `*_token` / `*_secret` are redacted everywhere they leave the process.

## Provider body

Every package exports:

| Hook | Required | Purpose |
|---|---|---|
| `create()` | yes | Zero-arg factory returning the provider instance |
| domain method | yes | `generate` / `synthesize` / `submit`+`poll` by domain |
| `validate_settings(settings)` | recommended | Cross-field checks a schema cannot express |
| `health_check(settings)` | recommended | Cheap `{status, message, latency_ms?}` probe |
| `register_runtime(app, sock)` | extension only | WebSocket route registration |

### Domain seams

| Domain | Concrete seam | v2 entry | Shape |
|---|---|---|---|
| `script` | `generate(configuration, project_id=…)` | `invoke(request, invocation)` | sync document |
| `scene_blueprint` | `generate(segments, configuration, project_id=…)` | `invoke(…)` | sync document |
| `tts` | `synthesize(text, settings, …)` | `invoke(…)` | sync artifact |
| `storyboard` | `submit` / `poll` | media-job service | async multi-asset |
| `animator` | `submit` / `poll` | media-job service | async multi-asset |

Bases live in `scriptase/<package>/providers/base.py`. Default `invoke()` on the
sync bases bridges through the concrete seam into a `ProviderResult` envelope
(contracts.md §30 / §31). Absolute filesystem paths never leave the envelope —
use relative managed refs via `normalize_ref`.

## Contract-test kit

Reusable suites and offline fakes ship in
`scriptase.providers.contract_tests`:

```python
from scriptase.providers.contract_tests import (
    SyncDocumentContractSuite,
    SyncArtifactContractSuite,
    AsyncMultiAssetContractSuite,
    FakeSyncDocumentProvider,
    FakeSyncArtifactProvider,
    FakeAsyncMultiAssetProvider,
    assert_manifest_v2,
    assert_egress_clean,
    run_suite_methods,
)

# Drive the shared suite against a fake (or your own make_provider):
run_suite_methods(SyncDocumentContractSuite)
```

The scaffolder emits a generated test file that already covers discovery,
catalog visibility, settings schema, health shape, and — for the working
`script` skeleton — execution on the `story.generate` seam plus egress
cleanliness. Those cases must keep passing without hand-edits.

```bash
venv/Scripts/python.exe -m pytest tests/test_provider_script_scaffold_check.py -q
venv/Scripts/python.exe -m pytest tests/test_provider_scaffold.py tests/test_provider_contract_kit.py -q
```

## Kinds

| Kind | Meaning |
|---|---|
| `local` | In-process, no network required for the happy path |
| `cloud` | External API; typically requires an API key |
| `extension` | Browser extension over WebSocket; needs `register_runtime` |
| `webhook` | Outbound HTTPS webhook; typically requires a URL + key |

## Ship checklist

1. `python -m scriptase.providers.scaffold <domain> <id> …`
2. Replace the skeleton body; keep `create()`, manifest id, and folder name aligned.
3. Run the generated contract tests plus any domain-specific cases.
4. Restart the app (or rely on dev reload). Confirm the provider appears in the
   catalog, accepts settings, reports health, and runs on the generic node.
5. Do **not** edit workflow nodes, adapters, or shared Vue components to add a
   provider — that is the extensibility proof (contracts.md §26).

The committed demo package is `script/scaffold_check`. Removing its folder and
its generated test leaves no central registration entry behind.
