<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Regenerate with: python -m scriptase.engine.docs
     (or: python -m scriptase.providers.docs)
     Source of truth: scriptase.providers domains + hub -->

# Provider Reference

Live catalog: **7 domains**, **9 registered providers**.

This document is generated from the domain catalog (`scriptase.providers.domains`) and the process-wide hub (`scriptase.providers.hub`). It is the same discovery surface served by `GET /api/providers`. Music and Captions are deliberately **not** provider domains — they remain local services without a provider dimension.

Regenerate after any domain, manifest, or provider package change:

```powershell
python -m scriptase.engine.docs
python -m scriptase.engine.docs --check
```

## Domains

| Domain | Label | Default provider | Package | Shape |
|---|---|---|---|---|
| `script` | Script / Story | `script_n8n` | `scriptase.modules.script.providers` | sync document |
| `scene_director` | Scene Director | `n8n` | `scriptase.modules.scene_director.providers` | sync document |
| `tts` | Text to Speech | `inworld` | `scriptase.modules.tts.providers` | sync artifact |
| `image` | Image | `gemini_ws` | `scriptase.modules.image.providers` | async multi-asset |
| `video` | Video | `grok_automa` | `scriptase.modules.video.providers` | async multi-asset |
| `review` | Review | `None` | `scriptase.review.providers` | sync document |
| `viral` | Virality | `deterministic` | `scriptase.modules.viral.providers` | sync document |

## Shared capabilities

Every domain understands these capability keys. Domain-specific keys are listed under each domain below. Unknown capability keys declared on a manifest are dropped with a discovery warning.

`async_job`, `batch`, `cancel`, `exclusive_execution`, `progress`, `push_callbacks`, `single_scene`, `test_connection`

## Provider kinds

| Kind | Meaning |
|---|---|
| `local` | In-process; no network required for the happy path |
| `cloud` | External API; typically requires credentials |
| `extension` | Browser extension over WebSocket; needs `register_runtime` |
| `webhook` | Outbound HTTPS webhook; typically requires a URL + key |

Allowed kinds: `cloud`, `extension`, `local`, `webhook`.

## Domain contracts

### Script / Story (`script`)

- **Default provider:** `script_n8n`
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

- **Default provider:** `inworld`
- **Package:** `scriptase.modules.tts.providers`
- **Providers folder:** `scriptase/modules/tts/providers`
- **Execution shape:** sync artifact
- **Concrete seam:** `synthesize(text, settings, …)` → `invoke(…)`

#### Capability vocabulary

`async_job`, `batch`, `cancel`, `exclusive_execution`, `model_download`, `native_word_timing`, `progress`, `push_callbacks`, `single_scene`, `speed_control`, `streaming`, `test_connection`, `voice_blend`, `voice_list`

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

`async_job`, `auto_animate`, `batch`, `cancel`, `exclusive_execution`, `image_edit`, `inpainting`, `progress`, `prompt_prefix`, `push_callbacks`, `reference_image`, `single_scene`, `test_connection`, `text_to_image`, `watermark_removal`

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

`async_job`, `batch`, `cancel`, `duration_control`, `exclusive_execution`, `image_to_video`, `progress`, `push_callbacks`, `reference_image`, `resolution_select`, `single_scene`, `test_connection`, `text_to_video`

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

### Review (`review`)

- **Default provider:** `None`
- **Package:** `scriptase.review.providers`
- **Providers folder:** `scriptase/review/providers`
- **Execution shape:** sync document
- **Concrete seam:** `review(request)` → `invoke(request, invocation)`

#### Capability vocabulary

`async_job`, `batch`, `cancel`, `exclusive_execution`, `image_review`, `progress`, `push_callbacks`, `single_scene`, `structured_output`, `test_connection`, `text_review`, `video_review`

#### Request model (`scriptase.review.providers.contract:ReviewRequest`)

| Field | Type | Required | Default |
|---|---|---|---|
| `job_id` | `str` | yes | — |
| `subject_kind` | `Literal` | no | `"text"` |
| `scene_id` | `str | None` | no | `null` |
| `target_node_id` | `str | None` | no | `null` |
| `target_artifact_id` | `str | None` | no | `null` |
| `text` | `str` | no | `""` |
| `artifact_ref` | `str` | no | `""` |
| `caption` | `str` | no | `""` |
| `image_prompt` | `str` | no | `""` |
| `expected_subject` | `str` | no | `""` |
| `expected_style` | `str` | no | `""` |
| `expected_text` | `str` | no | `""` |
| `expected_duration_s` | `float | None` | no | `null` |
| `duration_s` | `float | None` | no | `null` |
| `structured` | `dict[str, Any]` | no | factory |
| `required_keys` | `list[str]` | no | factory |

#### Result payload (`scriptase.review.providers.contract:ReviewResultPayload`)

| Field | Type | Required | Default |
|---|---|---|---|
| `issues` | `list[dict[str, Any]]` | no | factory |
| `subject_kind` | `Literal` | no | `"text"` |
| `capability` | `str` | no | `"text_review"` |
| `issue_count` | `int` | no | `0` |
| `clean` | `bool` | no | `true` |

### Virality (`viral`)

- **Default provider:** `deterministic`
- **Package:** `scriptase.modules.viral.providers`
- **Providers folder:** `scriptase/modules/viral/providers`
- **Execution shape:** sync document
- **Concrete seam:** —

#### Capability vocabulary

`async_job`, `batch`, `cancel`, `dimension_breakdown`, `exclusive_execution`, `offline`, `progress`, `push_callbacks`, `script_scoring`, `single_scene`, `test_connection`

#### Request model (`scriptase.modules.viral.providers.contract:ViralRequest`)

| Field | Type | Required | Default |
|---|---|---|---|
| `job_id` | `str` | yes | — |
| `sections` | `dict[str, str]` | no | factory |
| `story_text` | `str` | no | `""` |
| `target_duration` | `int` | no | `45` |
| `narrative_roles` | `list[str]` | no | factory |

#### Result payload (`scriptase.modules.viral.providers.contract:ViralResultPayload`)

| Field | Type | Required | Default |
|---|---|---|---|
| `scorer` | `str` | no | `"deterministic"` |
| `scorer_version` | `int` | no | `1` |
| `score` | `int` | yes | — |
| `band` | `Literal` | yes | — |
| `dimensions` | `list[DimensionScore]` | no | factory |
| `metrics` | `dict[str, Any]` | no | factory |

## Registered providers

Providers are discovered by scanning each domain's `providers/` folder. There is no central registration table.

### `script` providers

| Id | Label | Kind | Version | Contract | Capabilities |
|---|---|---|---|---|---|
| `n8n` | Script Generator | `webhook` | `1.0.0` | v1 | `language_select`, `structured_sections`, `test_connection`; off: `batch`, `offline`, `single_scene` |
| `random_template` | Random template | `local` | `1.0.0` | v1 | `language_select`, `offline`, `single_scene`, `test_connection`; off: `batch`, `structured_sections` |
| `script_n8n` | Story Generator | `webhook` | `1.0.0` | v1 | `language_select`, `structured_sections`, `test_connection`; off: `batch`, `offline`, `single_scene` |

#### `n8n` — Script Generator

Script generation via a configurable n8n webhook. Sends the Channel's niche, style, tone, duration, and template outline, and writes stories/{id}/story.json from the returned script.

- **Kind:** `webhook`
- **Version:** `1.0.0` (contract v1)
- **Capabilities:** `language_select`, `structured_sections`, `test_connection`; off: `batch`, `offline`, `single_scene`

#### `random_template` — Random template

Picks a curated sample narration from a local catalog. Offline, deterministic when seeded, and free of network or credentials.

- **Kind:** `local`
- **Version:** `1.0.0` (contract v1)
- **Capabilities:** `language_select`, `offline`, `single_scene`, `test_connection`; off: `batch`, `structured_sections`

#### `script_n8n` — Story Generator

AI story generation via the configured n8n/Gemini webhook. Returns hook/build/climax/CTA sections and writes stories/{id}/story.json.

- **Kind:** `webhook`
- **Version:** `1.0.0` (contract v1)
- **Aliases:** `gemini`, `builtin`
- **Capabilities:** `language_select`, `structured_sections`, `test_connection`; off: `batch`, `offline`, `single_scene`

### `scene_director` providers

| Id | Label | Kind | Version | Contract | Capabilities |
|---|---|---|---|---|---|
| `n8n` | Scene Director | `webhook` | `1.0.0` | v1 | `batch`, `chaptering`, `coherence_scoring`, `sfx_report`, `test_connection`; off: `single_scene` |

#### `n8n` — Scene Director

AI scene planning via the configured n8n/OpenRouter webhook. Returns scenes, image prompts, coherence scoring, and sfx validation, and writes scenes/{id}/scenes.json.

- **Kind:** `webhook`
- **Version:** `1.0.0` (contract v1)
- **Aliases:** `builtin`
- **Capabilities:** `batch`, `chaptering`, `coherence_scoring`, `sfx_report`, `test_connection`; off: `single_scene`

### `tts` providers

| Id | Label | Kind | Version | Contract | Capabilities |
|---|---|---|---|---|---|
| `inworld` | Inworld | `cloud` | `1.0.0` | v2 | `batch`, `single_scene`, `speed_control`, `test_connection`, `voice_list`; off: `model_download`, `streaming` |

#### `inworld` — Inworld

Cloud text-to-speech with named voices and selectable models.

- **Kind:** `cloud`
- **Version:** `1.0.0` (contract v2)
- **Requires settings:** `api_key`
- **Capabilities:** `batch`, `single_scene`, `speed_control`, `test_connection`, `voice_list`; off: `model_download`, `streaming`

### `image` providers

| Id | Label | Kind | Version | Contract | Capabilities |
|---|---|---|---|---|---|
| `gemini_ws` | Gemini (extension) | `extension` | `2.0.0` | v2 | `async_job`, `auto_animate`, `batch`, `progress`, `prompt_prefix`, `push_callbacks`, `single_scene`, `test_connection`, `text_to_image`, `watermark_removal` |

#### `gemini_ws` — Gemini (extension)

Storyboard frames driven by the browser extension over a WebSocket.

- **Kind:** `extension`
- **Version:** `2.0.0` (contract v2)
- **Aliases:** `gemini`
- **Open URL:** human-driven UI available
- **Capabilities:** `async_job`, `auto_animate`, `batch`, `progress`, `prompt_prefix`, `push_callbacks`, `single_scene`, `test_connection`, `text_to_image`, `watermark_removal`

### `video` providers

| Id | Label | Kind | Version | Contract | Capabilities |
|---|---|---|---|---|---|
| `grok_automa` | Grok (extension) | `extension` | `2.0.0` | v2 | `async_job`, `batch`, `duration_control`, `image_to_video`, `progress`, `push_callbacks`, `resolution_select`, `single_scene`, `test_connection` |

#### `grok_automa` — Grok (extension)

Animator takes driven by the browser extension over a WebSocket.

- **Kind:** `extension`
- **Version:** `2.0.0` (contract v2)
- **Aliases:** `grok`, `midjourney`
- **Open URL:** human-driven UI available
- **Capabilities:** `async_job`, `batch`, `duration_control`, `image_to_video`, `progress`, `push_callbacks`, `resolution_select`, `single_scene`, `test_connection`

### `review` providers

_No providers currently registered._

### `viral` providers

| Id | Label | Kind | Version | Contract | Capabilities |
|---|---|---|---|---|---|
| `deterministic` | Deterministic scorer | `local` | `1.0.0` | v2 | `batch`, `dimension_breakdown`, `offline`, `script_scoring`, `single_scene`, `test_connection` |
| `llm_judge` | LLM Judge | `webhook` | `1.0.0` | v2 | `batch`, `dimension_breakdown`, `script_scoring`, `single_scene`, `test_connection`; off: `offline` |

#### `deterministic` — Deterministic scorer

Offline, deterministic virality scorer. Measures hook presence and position, opening-line strength against fifteen archetypes, pacing against the target duration, open loops, CTA presence, and section balance. Identical input always scores identically, and it costs nothing to run. LLM judges ship as sibling packages.

- **Kind:** `local`
- **Version:** `1.0.0` (contract v2)
- **Capabilities:** `batch`, `dimension_breakdown`, `offline`, `script_scoring`, `single_scene`, `test_connection`

#### `llm_judge` — LLM Judge

LLM virality judge. Sends the script to an n8n/OpenRouter webhook and asks a model to score the same six dimensions the deterministic scorer measures, returning a 0-100 total and a per-dimension breakdown. A semantic second opinion — non-deterministic and paid — meant to sit beside the offline scorer, not replace it.

- **Kind:** `webhook`
- **Version:** `1.0.0` (contract v2)
- **Capabilities:** `batch`, `dimension_breakdown`, `script_scoring`, `single_scene`, `test_connection`; off: `offline`

## Stable provider error codes

Retryability is a property of the code, not of the provider. A provider must not mark non-retryable codes as retryable.

| Code | Retryable |
|---|---|
| `CANCELLED` | no |
| `PROVIDER_ARTIFACT_MISSING` | no |
| `PROVIDER_ARTIFACT_UNMANAGED` | no |
| `PROVIDER_AUTH_FAILED` | no |
| `PROVIDER_FAILED` | no |
| `PROVIDER_NOT_CONFIGURED` | no |
| `PROVIDER_NOT_FOUND` | no |
| `PROVIDER_QUOTA_EXHAUSTED` | no |
| `PROVIDER_RATE_LIMITED` | yes |
| `PROVIDER_REQUEST_INVALID` | no |
| `PROVIDER_RESPONSE_MALFORMED` | yes |
| `PROVIDER_RESULT_INVALID` | no |
| `PROVIDER_TIMEOUT` | yes |
| `PROVIDER_TRANSPORT_FAILED` | yes |
| `PROVIDER_UNAVAILABLE` | yes |
| `PROVIDER_UNIT_FAILED` | per-case |
| `SECRET_REF_UNRESOLVED` | no |
