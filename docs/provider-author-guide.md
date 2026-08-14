<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Regenerate with: python -m scriptase.engine.docs
     (or: python -m scriptase.providers.docs)
     Source of truth: scriptase.providers domains + hub -->

# Provider Author Guide

This is the complete path for adding a domain provider: **scaffold → manifest → settings → implementation → results/errors → artifacts → tests → health → ship**. Run commands from the repository root with the project venv (`venv/Scripts/python.exe` on this machine). Generated packages are source-controlled; a normal application restart discovers them, while development hot reload discovers saved changes when `STS_WORKFLOW_DEV_RELOAD=1`.

The tables under [Live domain contracts](#live-domain-contracts) and [Current catalog](#current-catalog) come from the same domain catalog and hub that power `GET /api/providers`. Companion files:

- [Provider Reference](providers.md) — full catalog generated from the hub.
- [Provider template notes](provider-template/README.md) — short scaffold layout notes.
- Normative machine contracts: [`contracts.md`](../_dev/loop-engineering/phases-plans/contracts.md) §19–§36.

Regenerate this guide after any domain or provider change:

```powershell
python -m scriptase.engine.docs
python -m scriptase.engine.docs --check
```

## Extensibility rule

**A provider may not modify workflow node definitions, adapters, routes, or generic UI components.** Adding a conforming provider means creating only its package under the domain's `providers/` folder plus tests. Discovery, catalog UI, settings forms, health, and the generic domain node all consume the package through the hub. If your change requires editing `scriptase/engine/`, a shared Vue provider component, or a route dispatcher, it is not a provider plugin — stop and rework the design.

## 1. Scaffold

Choose a stable lowercase id matching `^[a-z][a-z0-9_]{0,31}$`. It is the folder name, the manifest `id`, and the settings key — do not rename it after shipping. Pick one of the five catalog domains and a kind (`cloud`, `extension`, `local`, `webhook`).

The step 16.2 offline demo is reproducible with:

```powershell
python -m scriptase.providers.scaffold script scaffold_check
```

Other shapes:

```powershell
python -m scriptase.providers.scaffold tts my_provider --kind cloud
python -m scriptase.providers.scaffold image my_renderer --kind extension
python -m scriptase.providers.scaffold scene_director my_planner --kind webhook
```

This creates:

- `scriptase/<domain-package>/providers/<provider_id>/manifest.py` — `ProviderManifest` with `contract_version=2`.
- `…/settings_schema.py` — JSON-schema object for the generic settings UI.
- `…/provider.py` — `create()` factory plus domain methods / hooks.
- `…/runtime.py` — only when `--kind extension`.
- `tests/test_provider_<domain>_<provider_id>.py` — generated contract tests.

The command refuses unknown domains, invalid ids, existing packages, and colliding test files. Failure is atomic — no partial provider folder is left behind. Use `python -m scriptase.providers.scaffold --help` for options.

## 2. Manifest

Edit `manifest.py`. Keep `id` equal to the folder name and `domain` equal to the parent domain. Required fields:

| Field | Rule |
|---|---|
| `id` | Folder name; `^[a-z][a-z0-9_]{0,31}$` |
| `label` | Browser-safe display name |
| `domain` | One of the five catalog domains |
| `kind` | One of `cloud`, `extension`, `local`, `webhook` |
| `version` | Semver string |
| `contract_version` | `2` for the invocation/result envelope |
| `capabilities` | Subset of the domain vocabulary; unknown keys warned |
| `requires` | Settings **key names** that must be non-empty |
| `aliases` | Optional legacy wire ids (input aliases only) |
| `environment` | Setting key → env var name; **never serialized** |
| `description` / `docs_url` / `open_url` | Optional browser-safe metadata |

Capabilities outside the domain vocabulary are dropped with a warning at discovery. Shared keys every domain understands: `async_job`, `batch`, `cancel`, `exclusive_execution`, `progress`, `push_callbacks`, `single_scene`, `test_connection`.

## 3. Settings

`settings_schema()` returns a JSON-schema object rendered by the generic provider settings UI. Do not hardcode fields in Vue.

Widget types (`ui.type`): `dropdown`, `number`, `password`, `select`, `slider`, `text`, `textarea`, `toggle`. `text` / `number` are the defaults when `ui.type` is omitted.

### Secret rules

- A field is a secret if `ui.type == "password"` **or** its key matches `(api_key|token|secret|password|auth|bearer|credential)`.
- Reads leave the process as the `***` sentinel; a write of that sentinel means "leave the stored secret alone".
- Secrets must never appear in workflow JSON, execution records, SSE events, logs, errors, archives, notifications, or exported templates.
- Environment variables are a **read-time fallback only** — they are never seeded into settings and never returned to the browser. Map them with the manifest `environment` dict.

Use `validate_settings(settings)` on the provider for cross-field checks the schema cannot express. Unknown saved keys are preserved and warned; required-but-empty is an error.

## 4. Implementation

Every package exports `create()` — a zero-arg factory returning the provider instance. Domain bases live in `scriptase/<package>/providers/base.py`. Prefer Contract v2 `invoke()` (or the media-job service for image/video); the concrete domain seams remain for legacy adapters.

| Domain | Shape | Concrete seam |
|---|---|---|
| `script` | sync document | `generate(configuration, project_id=…)` → `invoke(request, invocation)` |
| `scene_director` | sync document | `generate(segments, configuration, project_id=…)` → `invoke(…)` |
| `tts` | sync artifact | `synthesize(text, settings, …)` → `invoke(…)` |
| `image` | async multi-asset | `submit` / `poll` (media-job service) |
| `video` | async multi-asset | `submit` / `poll` (media-job service) |

### Sync document example (script / scene_director)

Implement `generate(...)` and/or `invoke(request, invocation) -> ProviderResult`. Build the domain request model from configuration, produce the typed result payload, write any managed files under the project output root, and return a `ProviderResult` with relative `artifact_refs` only.

The committed `script/scaffold_check` demo turns idea + optional `label_prefix` into a short script, writes `story.json`, and returns a clean envelope. Its generated contract tests continue to pass without modification.

### Sync artifact example (tts)

Implement `synthesize(...)` / `invoke(...)` that writes audio under the managed output directory, returns `TTSResultPayload.audio_ref` as a **relative** ref (via `normalize_ref`), and never embeds absolute paths or credentials in the envelope.

### Async multi-asset example (image / video)

Implement `submit` + `poll` against the shared media-job service. Declare `async_job` (and `progress` / `cancel` when true). Per-unit detail belongs in `units[]`; absolute paths never leave the job status or result.

### Extension providers

Kind `extension` must export `register_runtime(app, sock)` (emitted as `runtime.py`). The hub binds that hook once per process after discovery. Claiming `push_callbacks` without kind `extension` is warned, not given a WebSocket route.

## 5. Results and errors

One envelope serves all five domains: `ProviderResult` (`scriptase.providers.results`). Only `payload` varies by domain. Status is `succeeded`, `partial`, or `failed`.

- Raise `ProviderError(code, message, details=…)` for expected failures. Codes come from the frozen catalog (see the [Provider Reference](providers.md#stable-provider-error-codes)).
- Never copy `str(exc)` from an unknown exception into a result — the boundary wraps it with a generic per-domain message.
- Retryability is fixed per code. Providers do not retry generation POSTs blindly; the platform owns invocation retry.
- Cancellation: providers that declare `cancel` must observe the invocation token. A cancelled remote job may still consume quota — document that for operators; the platform records node status `cancelled`, never `failed`.

## 6. Artifacts

Absolute filesystem paths never leave a `ProviderResult`, job status, error message, execution record, SSE frame, or API response.

- Convert managed paths with `normalize_ref(absolute_path)`.
- Resolve inbound refs with `resolve_ref(relative_ref)`.
- `validate_egress(result)` rejects absolute paths, sensitive keys, `bytes`, non-JSON types, and oversized fields at the boundary.

Write under the domain/project output roots already used by the pipeline. Use `safe_json_write` / `safe_join` for filesystem work.

## 7. Tests

Run the generated contract tests first, then add domain-specific cases. Reusable suites and offline fakes live in `scriptase.providers.contract_tests`.

```powershell
venv/Scripts/python.exe -m pytest tests/test_provider_script_scaffold_check.py -q
venv/Scripts/python.exe -m pytest tests/test_provider_scaffold.py tests/test_provider_contract_kit.py -q
venv/Scripts/python.exe -m scriptase.engine.docs --check
```

Generated tests cover discovery, catalog visibility, settings schema, health shape, and — for the working `script` skeleton — execution on the `story.generate` seam plus egress cleanliness. Those cases must keep passing without hand-edits. Deterministic suites must not require live providers (`@pytest.mark.live` stays gated by `STS_LIVE=1`).

## 8. Health

Implement `health_check(settings) -> HealthResult | dict` as a cheap probe. Return `{status, message, latency_ms?}` where `status` is one of `ok` / `warn` / `fail` (or the registry's accepted synonyms). Provider-authored `details` are redacted before they leave the health API. Availability (`available` / `needs_configuration` / `degraded`) is computed from settings and `requires` without network I/O; health may perform I/O and is orthogonal.

One provider's import, health, execution, or shutdown failure must not hide healthy providers or take down Flask. Discovery exclusions appear in `excluded[]` with a reason code.

## 9. Ship

1. Keep `create()`, manifest `id`, and folder name aligned.
2. Run generated + domain tests; regenerate docs (`python -m scriptase.engine.docs`).
3. Restart the app (or rely on dev reload).
4. Confirm the provider appears in the catalog, accepts settings, reports health, and runs on the generic domain node — without editing that node.
5. Commit the provider package, tests, and generated docs together.
6. Removing the package folder and its test must leave no central registration entry behind.

Compatibility aliases for retired wire ids belong only in the documented compatibility module / manifest `aliases` — never as new branches in generic dispatch.

## Live domain contracts

Field tables are loaded from each domain's request/result models at generation time.

### Script / Story (`script`)

- **Default provider:** `gemini`
- **Package:** `scriptase.modules.script.providers`
- **Providers folder:** `scriptase/modules/script/providers`
- **Execution shape:** sync document
- **Concrete seam:** `generate(configuration, project_id=…)` → `invoke(request, invocation)`

#### Capability vocabulary

`async_job`, `batch`, `cancel`, `exclusive_execution`, `language_select`, `offline`, `progress`, `push_callbacks`, `single_scene`, `structured_sections`, `test_connection`

#### Request model (`scriptase.modules.script.providers.contract:ScriptRequest`)

| Field | Type | Required | Default |
|---|---|---|---|
| `idea` | `str` | no | `""` |
| `category` | `str` | no | `""` |
| `style` | `str` | no | `""` |
| `tone` | `str` | no | `""` |
| `language` | `str` | no | `"english"` |
| `language_level` | `str` | no | `""` |
| `target_duration_s` | `int` | no | `45` |
| `niche_preset` | `str` | no | `""` |
| `seed` | `int | None` | no | `null` |

#### Result payload (`scriptase.modules.script.providers.contract:ScriptResultPayload`)

| Field | Type | Required | Default |
|---|---|---|---|
| `script_text` | `str` | yes | — |
| `sections` | `dict[str, str]` | no | factory |
| `word_count` | `int` | yes | — |
| `estimated_duration_s` | `int` | yes | — |
| `language` | `str` | yes | — |

### Scene Director (`scene_director`)

- **Default provider:** `n8n`
- **Package:** `scriptase.modules.scene_director.providers`
- **Providers folder:** `scriptase/modules/scene_director/providers`
- **Execution shape:** sync document
- **Concrete seam:** `generate(segments, configuration, project_id=…)` → `invoke(…)`

#### Capability vocabulary

`async_job`, `batch`, `cancel`, `chaptering`, `coherence_scoring`, `exclusive_execution`, `progress`, `push_callbacks`, `sfx_report`, `single_scene`, `test_connection`

#### Request model (`scriptase.modules.scene_director.providers.contract:SceneBlueprintRequest`)

| Field | Type | Required | Default |
|---|---|---|---|
| `script` | `str` | no | `""` |
| `segments` | `list[SegmentInput]` | no | factory |
| `style` | `str` | no | `"cinematic"` |
| `style_notes` | `str` | no | `""` |
| `tone` | `str` | no | `""` |
| `aspect_ratio` | `str` | no | `"9:16"` |
| `visual_direction` | `VisualDirectionInput` | no | factory |

#### Result payload (`scriptase.modules.scene_director.providers.contract:SceneBlueprintResultPayload`)

| Field | Type | Required | Default |
|---|---|---|---|
| `scenes` | `list[SceneSpec]` | no | factory |
| `style_spec` | `dict[str, Any]` | no | factory |
| `style_prompt` | `str` | no | `""` |
| `analysis` | `dict[str, Any]` | no | factory |
| `coherence` | `CoherenceBlock` | no | factory |
| `sfx_report` | `dict[str, Any] | None` | no | `null` |
| `total_duration_s` | `float` | no | `0.0` |

### Text to Speech (`tts`)

- **Default provider:** `kokoro`
- **Package:** `scriptase.modules.tts.providers`
- **Providers folder:** `scriptase/modules/tts/providers`
- **Execution shape:** sync artifact
- **Concrete seam:** `synthesize(text, settings, …)` → `invoke(…)`

#### Capability vocabulary

`async_job`, `batch`, `cancel`, `exclusive_execution`, `model_download`, `progress`, `push_callbacks`, `single_scene`, `speed_control`, `streaming`, `test_connection`, `voice_blend`, `voice_list`

#### Request model (`scriptase.modules.tts.providers.contract:TTSRequest`)

| Field | Type | Required | Default |
|---|---|---|---|
| `text` | `str` | yes | — |
| `voice` | `str` | no | `""` |
| `speed` | `float` | no | `1.0` |
| `language` | `str` | no | `""` |
| `output_basename` | `str` | no | `"voice"` |
| `output_sidecar` | `str` | no | `"tts.json"` |

#### Result payload (`scriptase.modules.tts.providers.contract:TTSResultPayload`)

| Field | Type | Required | Default |
|---|---|---|---|
| `audio_ref` | `str` | yes | — |
| `duration_seconds` | `float` | yes | — |
| `sample_rate` | `int` | yes | — |
| `format` | `str` | no | `"wav"` |
| `voice` | `str` | no | `""` |
| `characters_billed` | `int | None` | no | `null` |

### Image (`image`)

- **Default provider:** `gemini_ws`
- **Package:** `scriptase.modules.image.providers`
- **Providers folder:** `scriptase/modules/image/providers`
- **Execution shape:** async multi-asset
- **Concrete seam:** `submit` / `poll` (media-job service)

#### Capability vocabulary

`async_job`, `auto_animate`, `batch`, `cancel`, `exclusive_execution`, `image_edit`, `progress`, `prompt_prefix`, `push_callbacks`, `single_scene`, `test_connection`, `watermark_removal`

#### Request model (`scriptase.modules.image.providers.contract:StoryboardRequest`)

| Field | Type | Required | Default |
|---|---|---|---|
| `scenes` | `list[StoryboardScene]` | yes | — |
| `aspect_ratio` | `str` | no | `"9:16"` |
| `style` | `str` | no | `""` |

#### Result payload (`scriptase.modules.image.providers.contract:StoryboardResultPayload`)

| Field | Type | Required | Default |
|---|---|---|---|
| `total` | `int` | yes | — |
| `ready` | `int` | yes | — |
| `errors` | `int` | yes | — |
| `manifest_ref` | `str` | no | `""` |

### Video (`video`)

- **Default provider:** `grok_automa`
- **Package:** `scriptase.modules.video.providers`
- **Providers folder:** `scriptase/modules/video/providers`
- **Execution shape:** async multi-asset
- **Concrete seam:** `submit` / `poll` (media-job service)

#### Capability vocabulary

`async_job`, `batch`, `cancel`, `duration_control`, `exclusive_execution`, `image_to_video`, `progress`, `push_callbacks`, `resolution_select`, `single_scene`, `test_connection`

#### Request model (`scriptase.modules.video.providers.contract:AnimatorRequest`)

| Field | Type | Required | Default |
|---|---|---|---|
| `scenes` | `list[AnimatorScene]` | yes | — |
| `aspect_ratio` | `str` | no | `"9:16"` |
| `mode` | `str` | no | `"video"` |

#### Result payload (`scriptase.modules.video.providers.contract:AnimatorResultPayload`)

| Field | Type | Required | Default |
|---|---|---|---|
| `total` | `int` | yes | — |
| `ready` | `int` | yes | — |
| `errors` | `int` | yes | — |
| `manifest_ref` | `str` | no | `""` |

## Current catalog

Snapshot of providers discovered when this guide was generated.

| Domain | Providers |
|---|---|
| `script` | `gemini`, `random_template`, `scaffold_check` |
| `scene_director` | `n8n` |
| `tts` | `inworld`, `kokoro` |
| `image` | `gemini_ws`, `wavespeed_direct`, `wavespeed_webhook` |
| `video` | `grok_automa`, `kie_ai` |

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Provider missing from catalog | Folder/id mismatch, invalid manifest, or discovery exclusion | Check app logs for `[EXCLUDED]`; fix `manifest.py` so `id` equals the folder name and `domain` matches the parent |
| `needs_configuration` forever | `requires` key empty or secret never saved | Fill required settings; confirm password fields send a real value once (not only `***`) |
| Health `fail` | Credentials, network, or probe bug | Run `GET /api/providers/<domain>/<id>/health` on loopback; fix `health_check` so details never echo secrets |
| Settings UI blank | Missing `settings_schema.py` or empty `properties` | Ship at least one field; scaffold always includes `label_prefix` for this reason |
| `PROVIDER_ARTIFACT_UNMANAGED` | Absolute path in result | Use `normalize_ref` and managed output roots only |
| Contract test fails on capabilities | Declared key outside domain vocabulary | Remove the key or add it to `DomainSpec.capability_vocabulary` (platform change, not a plugin) |
| Docs check fails | Manifest/domain change without regen | `python -m scriptase.engine.docs` then commit `docs/providers.md` and `docs/provider-author-guide.md` |
| Wanted a sixth domain | Out of scope for a provider package | Add a `DomainSpec` entry and providers folder as a platform change; Music/Captions stay non-provider by design |

Provider API routes are **loopback-only**. Errors use `{"error": {"code", "message", "details?"}}`.
