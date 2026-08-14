# Workflow Builder — Machine Contracts (Phase 0 frozen)

> Produced by the Phase 0 audit (steps 0.1 + 0.2 of [implementation-plan.md](implementation-plan.md)).
> Grounded in code as of commit `4aca8cb` (2026-08-04). Line numbers refer to that state.
> Rule inherited from the spec: discrepancies between the spec and the code are resolved
> **in favor of preserving working behavior** — every such resolution is recorded here.

> **Status:** Phase 0.4 review passed on 2026-08-04. Named ports/control semantics, strict
> ID rules, HTTP envelopes, SSE replay, security limits, and the test baseline are frozen.
> Deterministic fixture files are scheduled as the first prerequisite of step 2.5, before
> stubs consume them.

---

## 1. Spec-vs-code discrepancies (resolved)

| # | Spec said | Code reality | Resolution |
|---|---|---|---|
| D1 | `studio/scenes` module | Does not exist. Scene generation is `studio/build_scene_blueprints/` (blueprint name `scenes`, routes `/api/scenes/*`) | Adapters import from `studio.build_scene_blueprints.*` |
| D2 | `studio/assets` module | Does not exist. The "assets" step is `studio/animator/` (`animation_routes.py` grabber + `organizer.py`) | Animator node wraps `studio.animator`; "assets" is UI vocabulary only |
| D3 | Assemble consumes audio+scenes+assets via data edges | `_step_assemble(project_id)` takes **only** `project_id` and reads everything from disk (`routes.py:1919`) | Assemble node keeps typed input ports for **ordering/readiness**, but the adapter contract is: inputs assert artifact presence; payload = `project_id` |
| D4 | Storyboard and/or Animator feed Assemble | **Mutually exclusive.** `_pick_scene_asset` (`editor/routes.py:72`) reads ONLY `output/animator/`. Storyboard images are reference inputs to the animator (base64 side channel, `animation_routes.py:243-256`); no code path puts them on the timeline | Assemble's asset input port type is `animation_assets` only. Storyboard output port connects to Animator (reference) or Workflow Output — never Assemble. Storyboard→timeline is a possible future adapter feature, out of scope v1 |
| D5 | Resume can reload any step | `_load_prior_results` has **no `assets` branch** (`routes.py:793`) — assets are never reloadable in the legacy pipeline | Workflow engine's own `run_data` + fingerprint cache supersedes `_load_prior_results`; adapters must not depend on it |
| D6 | — | `storyboard_provider`, `image_model`, `arguments` are declared in `PipelineRunRequest` but never copied into the job config (`routes.py:283-318`) — silently dead in the legacy pipeline | Workflow node configs bypass the legacy config dict entirely; adapters receive node configuration directly |
| D7 | Project identity can be inferred from every edge payload | Legacy artifacts sometimes use a `source_folder` different from the editor `project_id`; several steps reconstruct paths from one or the other | Every execution has one immutable project context. New runs allocate `pm_XXXXXX`; `project.existing` selects an existing ID before side-effecting nodes start. Artifact outputs carry safe relative refs plus `project_id` and `source_folder` where relevant. Adapters consume those fields instead of guessing paths. Conflicting existing-project inputs or request/project-node mismatches fail validation. |

## 2. Node contract table (core production nodes)

Legend: **cfg** = node configuration keys; **in/out** = typed ports; **artifacts** = files under `output/`;
**service** = the function(s) the adapter calls (✅ = already clean/importable, 🔶 = requires extraction in step 3.1).

### `project.setup` (Project Setup)
- in: — · out: `project_settings`
- cfg: `project_name, channel_name, logo_enabled, logo, logo_position, logo_size, logo_opacity, logo_margin, tone, style, aspect_ratio`
- service: trivial validate+emit (new code). Logo is a managed reference under `output/branding/`.
- artifacts: none. Instant, cacheable, no side effects.

### `script.input` (Script Input)
- in: — · out: `script` (str, 1–10,000 chars)
- cfg: `text` (textarea). Later: Story Generator node (`studio/story`) can feed the same port type.

### `trigger.manual`, `project.existing` (entry nodes)
- `trigger.manual`: no config or artifacts; emits one `control` token when included in the selected execution scope. It is optional because the toolbar/API already initiates runs.
- `project.existing`: cfg `project_id`; validates strict project ID syntax and existence, then resolves WIP before `initial.json` using the same preference as `editor_load_project` (`editor/routes.py:1211`). It emits `project_id` and an `editor_project` artifact reference without copying or rewriting the project.
- Execution validation permits at most one enabled `project.existing` node in a selected side-effecting subgraph. Its ID must agree with any `project_id` supplied to `/api/workflow/run`.

### `tts.generate` (Text to Speech)
- in: `script` (required) · optional `project_settings` · out: `audio_file`, `tts_metadata`
- cfg: `engine` (kokoro|inworld), `voice`, `speed` (0.5–2.0), `provider_options` (dict)
- service: 🔶 extract from `_step_tts` + `_step_tts_kokoro_pipeline` / `_step_tts_inworld_pipeline` (`pipeline/routes.py:1242-1467`). Underlying clean pieces: `studio.tts.normalize.clean_for_tts` ✅, `studio.tts.audio.{pad_audio,run_loudnorm}` ✅, `studio.tts.inworld.synthesize_to_wav` ✅. Kokoro path uses module singletons `kokoro_instance`/`generation_inference_lock` (`tts/routes.py:199-204`) — adapter must reuse the SAME singletons (do not duplicate; see K1 below).
- artifacts: `output/tts/{pid}/voice.wav`, `output/tts/{pid}/tts.json` (+ cache `TMP_DIR/tts/{sha16}.wav`)
- `tts_metadata` payload = the metadata dict of §4.3 of the step audit; minimum downstream needs: `{wav_path, folder, filename, duration_seconds, words}`.
- Known quirks preserved: local voice fallback `af_bella` (schema default is `af_heart`); Inworld ignores `speed`; cache key sha256(text|voice|speed) ignores provider; cache hits get loudnorm twice.

### `timing.align` (Force Alignment)
- in: `audio_file` + `script` (both required) · out: `alignment`
- cfg: — (model fixed: stable-whisper tiny.en)
- service: `studio.timing.routes._run_alignment(wav_path, prompt_text)` ✅ logic (module import pulls blueprint — acceptable; singleton `alignment_model`/`alignment_lock`). Text cleaning: strip `[]*_#`~` + whitespace-collapse (`routes.py:1474-1477`).
- artifacts: `output/alignments/{folder}/alignment.json` (+ wav copy if absent)
- Failure mode: `_run_alignment` returns `None` on ANY exception → adapter raises `NODE_EXECUTION_FAILED` with code `ALIGNMENT_EMPTY`.
- `alignment` payload: `{project_id, source_file, folder, transcript, alignment:[{word,begin,end}], word_count, inference_time, timestamp}`

### `segment.run` (Segmenter)
- in: `alignment` (required) · out: `segments`
- cfg: `segment_config` overrides of `DEFAULT_CONFIG = {target_min:1.5, target_max:4.0, hard_max:5.0, hard_min:0.8, gap_filler:0.3}` (+ `break_weights`, `max_silence`)
- service: `studio.timing.segmenter.run_segmenter(alignment, config, metadata)` ✅ (purest module in repo) + `save_output` ✅
- artifacts: `output/segmenters/{pid}/segmented.json`
- `segments` payload: file content + injected `output_folder`, `output_path`. `stats.segment_count` counts non-filler only.

### `scenes.blueprint` (Scene Blueprint)
- in: `segments` + `script` (required) · optional `project_settings` (tone/style defaults) · out: `scenes`, `image_prompts`
- cfg: `webhook_url` (fallback `N8N_WEBHOOK_URL`), `style` (template id), `style_prompt` (custom notes), `story_tone`
- service: 🔶 extract orchestration from `_step_scenes` (`pipeline/routes.py:1586-1704`). Clean pieces ✅: `resolve_template_bundle`, `build_visual_bible`, `build_scene_blueprints`, `summarize_blueprints`, `build_scene_system_prompt`, `should_use_chapters`, `studio.webhooks.call_webhook`, `_normalize_webhook_response`, `_apply_segmenter_timing`, `ensure_analysis_payload`, `finalize_scene_result`, `resolve_niche`. Chunked path: `generate_with_chapters_chunked` (lives in bsb/routes.py — move in 3.1).
- artifacts: `output/scenes/{pid}/scenes.json`
- Side effects: outbound HTTP to n8n webhook; unseeded `random.shuffle` in `_assign_hook_animations` (non-deterministic `text_hook_animation`) — excluded from fingerprint.
- Progress: accepts `progress_cb(str)` → engine forwards as node progress events.
- No stop check inside (v1: interruptible only at boundaries).

### `storyboard.generate` (Storyboard)
- in: `scenes` (required, uses `scenes[].{index,image_prompt}`) · optional `project_settings` · out: `storyboard_images`
- cfg: `provider` (webhook|direct|gemini; registry ids `wavespeed_webhook|wavespeed_direct|gemini_ws`), `aspect_ratio`, `style`, `image_model`, `prompt_prefix` (gemini only), `auto_type`
- service: 🔶 `_generate_storyboard(project_id, scenes, aspect_ratio, webhook_url, style, image_model)` ✅ (already thread-callable, `storyboard/routes.py:144`) or `gemini_ws.add_job/queue_image_job` ✅ (WebSocket to extension). Status: re-read `output/storyboard/{pid}/storyboard.json` — NOT the HTTP status route.
- artifacts: `output/storyboard/{pid}/storyboard.json`, `{scene}/image.{ext}` (versioned rotation), thumbnails, `scene_prompts.json` (gemini)
- Poll contract: 10s interval, 30min timeout; **errors count toward completion** (`pending = total-ready-errors`).
- `storyboard_images` payload: `{total, ready, errors, scene_statuses}` + artifact refs.

### `animator.generate` (Animator — the "assets" step)
- in: `scenes` (required) · optional `storyboard_images` (reference-image edge; see D4) · optional `project_settings` · out: `animation_assets`
- cfg: `provider` (grok|kie-ai; registry ids `grok_automa|kie_ai`), `aspect_ratio`, `mode` (video|image), `quality`, `duration`, `arguments`, `auto_type`
- service: 🔶 biggest extraction: `grabber_start` logic (`animation_routes.py:188-`) is `@validate_json`-route-coupled. Clean pieces ✅: `organizer.organize_grabber_assets`, `save_base64_assets`, `reconcile_project`, `kie_ai.generate_image`, `routes.add_job/queue_grabber_start`.
- artifacts: `output/animator/{pid}/{scene}/*` (media + `*_thumb.jpg`), `metadata.json`, `grabber_job.json`
- Poll contract: 10s interval, **120min** timeout. In-memory `grabber_jobs` JobStore — status lost on process restart (adapter must tolerate + fall back to disk reconcile).
- `animation_assets` payload: `{total, ready, errors, provider}` + artifact refs.
- `mode=video` filters non-video URLs to `status="error"` at ingest — the only lever forcing video assets.

### `assemble.project` (Assemble Project)
- in: `animation_assets` + `tts_metadata` + `scenes` (readiness edges; see D3) · optional `captions`, `music_track`, `project_settings` · out: `editor_project`
- cfg: — (v1; force-rebuild is implicit)
- service: 🔶 **extract `assemble(project_id, *, force=True) -> dict` from `assemble_project_for_editor` (`editor/routes.py:1451`, ~300 lines)** — the single biggest extraction. Uses clean helpers `_pick_scene_asset`, `_load_asset_metadata`, `_resolve_audio_url`, `select_music/select_sfx` ✅, `_group_words_into_captions` ✅.
- artifacts: `output/projects/{pid}/initial.json` (overwritten on force; WIP untouched), `output/captions/{pid}/captions.json` (auto-gen branch)
- Asset resolution (frozen contract): per scene, tier 1 = animator `metadata.json` `local_files` (any video beats any image; last list entry wins); tier 2 = dir scan of `output/animator/{pid}/{scene_key}` (videos preferred; newest mtime wins); global de-dup via `used_asset_urls` (one file backs one scene); losers get `mediaUrl:""` + `status:"pending"`.
- **Not interruptible; no stop check. Music/SFX selection is random (bounded by 10-entry history) → non-deterministic; excluded from fingerprint, and pinning the output is the determinism lever.**
- `editor_project` payload: `{scene_count, total_duration, has_audio, has_captions, assembled_data}`.

### `captions.generate` (Caption Generator)
- in: `alignment` (required) · out: `captions`
- cfg: `preset_id` (approved preset id), `words_per_group` (1–10, default 3), `enabled` (default true)
- service: `studio.captions.routes._group_words_into_captions(alignment, words_per_group)` ✅ and preset lookup via `CAPTION_PRESETS` / `_get_default_caption_preset_id` ✅. Extraction to a service module in 3.1 avoids importing a route module from the adapter.
- artifacts: `output/captions/{source_folder}/captions.json`, written atomically. Payload matches existing editor support: `{project_id, source_folder, preset, captions:[{text,start,end,words}]}`.
- deterministic and synchronously cancellable at the node boundary; no retry needed. Invalid word timings fail validation instead of being silently reordered.

### `music.select` (Background Music)
- in: optional `project_settings`, optional `project_id` · out: `music_track`
- cfg: `mode` (`tone|random|specific`), `story_tone`, managed `track_ref`, `volume` (0–1), `fade_in`, `fade_out`, `loop`, `ducking_enabled`, `ducking_level`
- service: `studio.music.selector.{select_music,select_random_music,recall_last_music}` ✅ plus existing history helpers. The adapter converts approved absolute library selections into managed `/assets/sounds/music/...` references before emitting output; arbitrary browser paths are rejected.
- artifacts: no standalone node artifact in v1; selection/history is persisted in the execution record and later editor project. If a project ID is present, history mutation is deferred until Assemble succeeds so a failed exploratory run does not consume a random pick.
- selection is non-deterministic unless `specific` or pinned. Its fingerprint includes the resolved managed track reference; cache lookup happens before a fresh random choice.

### `timeline.project`, `workflow.output` (output helpers)
- `timeline.project`: takes `editor_project`, verifies its managed artifact, and atomically writes/updates the editor project through the extracted editor save service. It emits the same `editor_project` reference plus `project_id`. It must not overwrite `work@in@progress.json` unless the workflow explicitly targets the existing project and the run request authorizes replacement.
- `workflow.output`: cfg `port_type`, `label`; accepts one dynamically typed value, records a redacted summary and safe artifact refs in the execution result, and has no filesystem side effect of its own.
- `stub.input` and `stub.output` remain testing nodes described below; they never allocate a project or convert sample-derived artifacts into a normal project without an explicit non-sample rebuild.

### `export.video` (Video Export)
- in: `editor_project` (required) · optional `project_settings` (logo block, aspect ratio) · out: `video_file`
- cfg: `profile` (yt_shorts|tiktok|reels|yt_landscape|square), `captions` (bool), `grain` (bool) — v1 sourced from node config, NOT app-config (deliberate divergence: node config beats `app-config.json`; recorded as workflow behavior)
- service: 🔶 extract job creation from `start_export` (`editor/routes.py:2192`); `VideoProcessor` ✅ (`video_processor.py:201`, clean class) + `_process_video` ✅ (already thread-run). Logo overlay pass added here (Phase 3.2).
- artifacts: `output/exports/{pid}_{job8}.mp4` + sidecar json; mutates `initial.json`/WIP via audio-persist helpers
- Known defects preserved-but-documented (fix candidates AFTER parity, tracked in §8): export status route omits `output_filename` (⇒ legacy auto-sync dead); only the FIRST sfx track reaches the renderer (per-scene SFX dropped); `_persist_auto_selected_export_audio` strips per-scene SFX from saved projects; audio fallback can promote music to narration channel when no voice track exists.
- Cancellation: cooperative via export job cancel — the ONLY step with true cancel support.

### Utility/testing nodes
- `stub.input`: out = dynamic `port_type`; cfg `{port_type, payload}`; executes instantly; file-backed types reference `studio/workflows/fixtures/` only.
- `stub.output`: in = dynamic; captures + displays; Phase 4 pinning = winning cache entry.
- `workflow.output`, `trigger.manual`, `project.existing`: declarative, no side effects.

### Phase 5.4 utility nodes (frozen v1 semantics)

- `story.generate` (Story Generator): in `trigger:control?`, `settings:project_settings?`; out
  `control:control`, `script:script`. Configuration is `preset_style`, `story_category`,
  `duration` (15-180 seconds), `language`, optional `language_level`, optional `story_tone`,
  optional `idea`, and optional `webhook_url`. Explicit node configuration wins over incoming
  `settings.style`/`settings.tone`. It calls the importable `studio.story` prompt, webhook,
  parser, persistence, and history services directly (never its Flask route), writes
  `output/stories/{execution_project_id}/story.json`, and emits the parsed `story_text` on the
  existing `script` port. It is provider-dependent, retryable, and non-deterministic.
- `utility.set_value` (Set Value): in `trigger:control?`, `value:generic_json?`; out
  `control:control`, `value:generic_json`. Configuration `value` is any bounded JSON value.
  The configured value always replaces the optional input; the input exists only to sequence
  and branch the node. The node is instant, deterministic, and side-effect free.
- `utility.condition` (Condition): in `trigger:control?`, `value:generic_json`; out
  `true:generic_json?`, `false:generic_json?`. Configuration `operator` is one of
  `truthy|falsy|equals|not_equals|contains`; `compare_to` is used by the last three operators.
  Exactly one output port is present at runtime and carries the input value unchanged. The
  other output is deliberately inactive, not `null`, not an error, and not a success token.
  `contains` means membership for arrays/object keys and substring containment for strings;
  other input types evaluate false. Equality uses normal JSON structural equality. The node
  is instant, deterministic, and side-effect free.
- `utility.wait` (Wait): in `trigger:control?`, `value:generic_json?`; out `control:control`,
  `value:generic_json`. Configuration `delay_ms` is an integer from 0 through 300000. It emits
  its input unchanged (or JSON `null` when absent) after the delay, checks cancellation in
  intervals no longer than 50 ms, and creates no artifacts. It is deterministic but is never
  cache-reused because the delay itself is its intended side effect.
- `utility.merge` (Merge): in `values:generic_json` with `multiple:true`; out
  `control:control`, `value:generic_json`. It is the only skip-tolerant join in v1. The
  scheduler waits until every connected predecessor is terminal, then discards inactive
  edges caused by Condition/skip propagation and runs Merge when at least one value edge is
  active. Zero active inputs skips Merge. Active values retain saved edge order. Configuration
  `mode=array` emits the ordered list, `mode=first` emits its first item, and `mode=object`
  shallow-merges objects from left to right (later keys win) and fails if an active value is
  not an object. Merge is instant, deterministic, and side-effect free.

Scheduler rule for conditional branches: a succeeded node activates only output ports actually
present in its output mapping. A node with any inactive normal predecessor is skipped, and that
skip propagates through ordinary descendants. This is a normal successful-run state. Merge is
the explicit convergence boundary: inactive/skipped predecessors count as resolved rather than
as required active inputs. Failures and cancellations are not converted to inactive branches;
the existing error policy remains authoritative.

## 3. Port types & compatibility matrix

Types (v1): `control, text, script, project_id, project_settings, audio_file, tts_metadata, alignment, segments, scenes, image_prompts, storyboard_images, animation_assets, captions, music_track, editor_project, export_profile, video_file, generic_json`.

Compatibility rule: **exact type match only.** No wildcard: `generic_json` connects only to `generic_json`. `stub.input`/`stub.output` resolve their dynamic type from configuration at validation time and then obey exact-match. Additional rules: no in→in / out→out; single-value inputs reject a second edge; DAG only (cycle rejection); control edges distinct from data edges. Every payload that references files carries `{artifact_refs: [relpaths]}` alongside inline JSON; integrity check = existence + nonzero size.

### 3.1 Stable port IDs and control readiness

Type names alone are not port IDs. Registry entries and persisted edges use the following
stable IDs; renaming a display label never changes them.

| node type | inputs (`id:type`, `?` optional) | outputs (`id:type`) |
|---|---|---|
| `trigger.manual` | — | `control:control` |
| `project.setup` | `trigger:control?` | `control:control`, `settings:project_settings` |
| `script.input` | `trigger:control?` | `control:control`, `script:script` |
| `project.existing` | `trigger:control?` | `control:control`, `project_id:project_id`, `project:editor_project` |
| `tts.generate` | `trigger:control?`, `script:script`, `settings:project_settings?` | `control:control`, `audio:audio_file`, `metadata:tts_metadata` |
| `timing.align` | `trigger:control?`, `audio:audio_file`, `script:script` | `control:control`, `alignment:alignment` |
| `segment.run` | `trigger:control?`, `alignment:alignment` | `control:control`, `segments:segments` |
| `scenes.blueprint` | `trigger:control?`, `segments:segments`, `script:script`, `settings:project_settings?` | `control:control`, `scenes:scenes`, `image_prompts:image_prompts` |
| `storyboard.generate` | `trigger:control?`, `scenes:scenes`, `settings:project_settings?` | `control:control`, `images:storyboard_images` |
| `animator.generate` | `trigger:control?`, `scenes:scenes`, `storyboard:storyboard_images?`, `settings:project_settings?` | `control:control`, `assets:animation_assets` |
| `captions.generate` | `trigger:control?`, `alignment:alignment` | `control:control`, `captions:captions` |
| `music.select` | `trigger:control?`, `settings:project_settings?`, `project_id:project_id?` | `control:control`, `track:music_track` |
| `assemble.project` | `trigger:control?`, `assets:animation_assets`, `metadata:tts_metadata`, `scenes:scenes`, `captions:captions?`, `music:music_track?`, `settings:project_settings?` | `control:control`, `project:editor_project` |
| `timeline.project` | `trigger:control?`, `project:editor_project` | `control:control`, `project:editor_project`, `project_id:project_id` |
| `export.video` | `trigger:control?`, `project:editor_project`, `settings:project_settings?` | `control:control`, `video:video_file` |
| `workflow.output` | `trigger:control?`, `value:<dynamic>` | — |
| `stub.input` | — | `value:<dynamic>` |
| `stub.output` | `value:<dynamic>` | `value:<dynamic>` |

Required data inputs are shown without `?`; registry fields still encode this as
`required` and `multiple`. All inputs above are single-value in v1. Outputs may fan out.
`workflow.output` and both stubs resolve `<dynamic>` from validated `configuration.port_type`.

Data edges establish both a dependency and a typed value. Control edges establish only a
dependency and never satisfy a required data input. A node with a connected `trigger` waits
for that control predecessor as well as all required data. An unconnected optional `trigger`
does not block a node. A node emits `control` only after successful completion; skipped,
failed, and cancelled propagation is handled explicitly by scheduler policy rather than by
fabricating a success token. These rules make Manual Trigger useful without making it
mandatory for partial or isolated execution.

## 4. Workflow JSON schema (frozen)

As specified in [proposition-final.md](proposition-final.md) §Persistence — `schema_version: 1`, nodes `{id, type, type_version, name, position, configuration, disabled}`, edges `{id, source_node, source_port, target_node, target_port, edge_type}`, `variables`, `viewport`, `settings: {on_error}`, ISO timestamps. Persisted under `output/workflows/{workflow_id}.json` via `safe_json_write`; soft-delete to `output/TRASH/workflows/`. `output/workflows/` and `output/branding/` must be added to clear-all handling.

`sanitize_project_id` is a normalizer, not sufficient request validation: it silently removes
invalid characters and can alias two user inputs. API IDs must first match the entire strict
pattern `^wf_[A-Z0-9]{6}$` or `^ex_[A-Z0-9]{6}$` as applicable, then be resolved with
`safe_join`. Imported node/edge IDs use a documented bounded safe pattern and must also be
unique within the document. Reject altered, empty, overlong, wrong-prefix, and duplicate IDs;
never normalize them into acceptance.

### 4.1 Field-level validation policy

The implementation may use Pydantic or equivalent explicit validators, but these constraints
are transport-independent:

| field | rule |
|---|---|
| document | JSON object, UTF-8, maximum 2 MiB after encoding, maximum nesting depth 20 |
| `schema_version` | required integer, exactly `1` |
| `workflow_id` | server-generated on create; otherwise required `^wf_[A-Z0-9]{6}$` |
| `name` | required trimmed string, 1–120 characters |
| `description` | string, 0–2,000 characters |
| `nodes` | required array, 0–200 unique nodes |
| `edges` | required array, 0–500 unique edges |
| node `id` | `^[A-Za-z][A-Za-z0-9_-]{0,63}$`, unique |
| node `type` | required registry key, maximum 80 characters |
| node `type_version` | required positive integer supported by the registry |
| node `name` | trimmed string, 1–120 characters |
| node `position.x/y` | finite number in `[-1000000, 1000000]` |
| node `configuration` | JSON object, maximum 256 KiB per node, schema-validated |
| node `disabled` | required boolean |
| edge `id` | `^[A-Za-z][A-Za-z0-9_-]{0,63}$`, unique |
| edge endpoints/ports | existing node IDs and registry port IDs; maximum 64 characters each |
| edge `edge_type` | `data` or `control`, and must match the source/target port types |
| `variables` | finite JSON object, maximum 64 KiB; expression path segments match `[A-Za-z_][A-Za-z0-9_]{0,63}` |
| `viewport` | finite `x/y`; `zoom` in `[0.1, 1.5]` |
| `settings.on_error` | `stop` in v1; later values enabled only with Phase 4 capability support |
| timestamps | RFC 3339 strings written by the server; clients cannot override them on update |

V1 rejects unknown fields at the document, node, and edge levels. Forward-compatible metadata
must live under a bounded `extensions` object (reserved now, optional, ignored by execution,
round-tripped). This avoids silently trusting misspelled contract fields while leaving an
explicit extension path. JSON numbers must be finite; `NaN` and infinities are rejected.

### Expressions and data mapping (Phase 5.5)

An expression is a string containing exactly one whole-value reference (surrounding whitespace
is ignored): `{{ nodes.<node_id>.outputs.<port_id> }}`, `{{ workflow.project_id }}`, or
`{{ variables.<name>[.<nested_name>...] }}`. Interpolation, operators, calls, indexing, and
all other roots are invalid. Whole-value replacement preserves the referenced JSON type.
Expressions may appear recursively in configuration JSON, but structural configuration such as
dynamic `port_type` must still resolve to a valid registry value.

Node-output references must name an existing non-control output on a strict graph ancestor and
that ancestor must be included in the selected execution scope. Static expression validation is
part of workflow validation and scheduler construction. Immediately before a node is fingerprinted
and invoked, expressions resolve from already-produced outputs, immutable execution `project_id`,
and the workflow snapshot's finite JSON `variables`; the resolved configuration is schema-validated.
A skipped, absent, or stale output fails with `EXPRESSION_VALUE_UNAVAILABLE`. The parser does not
evaluate code and exposes no environment, secret store, object attributes, or filesystem API.

## 5. Execution record schema (frozen)

```jsonc
{
  "schema_version": 1,
  "execution_id": "ex_XXXXXX",           // generate_project_id-style, sanitized
  "workflow_id": "wf_XXXXXX",
  "workflow_snapshot": { /* full workflow JSON at run time */ },
  "project_id": "pm_XXXXXX",
  "run_mode": "full|node_with_deps|node_isolated|selected|from_node|retry_failed|retry_failed_desc",
  "scope_node_ids": ["n_tts"],
  "status": "running|succeeded|failed|cancelled|partial",
  "started_at": "ISO", "finished_at": "ISO|null",
  "nodes": {
    "n_tts": {
      "status": "idle|invalid|queued|running|waiting|succeeded|failed|cancelled|skipped|stale",
      "attempts": 1, "duration_ms": 5230,
      "fingerprint": "sha256…", "cache": {"hit": false, "reason": "config_changed"},
      "from_sample_data": false,
      "resolved_inputs_summary": {"script": {"chars": 812}},
      "outputs_summary": {"audio_file": {"artifact": "tts/pm_X/voice.wav", "duration_s": 28.5}},
      "artifact_refs": ["tts/pm_X/voice.wav", "tts/pm_X/tts.json"],
      "logs": [{"ts": "ISO", "level": "info", "message": "…"}],
      "error": null   // or structured error, §7
    }
  }
}
```
Persisted per run at `output/workflows/executions/{execution_id}.json` (atomic, redacted). Large payloads stay as artifact refs — never inlined.

Execution records are server-owned and never accepted back as workflow definitions. Node map
keys must equal node IDs in the stored snapshot. `attempts` is a non-negative integer;
`duration_ms` is null until terminal and otherwise non-negative; `artifact_refs` are normalized
relative paths beneath approved output roots; logs are capped by count and bytes; and all
free-text/log/error fields pass through redaction before persistence and SSE emission. Overall
and node status transitions are monotonic according to the scheduler state machine; terminal
states cannot transition back to running.

## 6. API surface & SSE event shape (frozen)

Routes exactly as the spec lists (`/api/workflows` CRUD+import/export; `/api/workflow/node-types|validate|run|executions/*`). New blueprint `workflows_bp`, name `"workflows"`, **no url_prefix** (matches all 14 existing blueprints), imported and registered with the other blueprints in `app.py`. Provider-backed option resolution occurs at request time after startup initialization; blueprint registration itself must not assume populated provider registries.

All endpoints are local-app endpoints and enforce `is_loopback_remote`; mutation endpoints also
require JSON content types where applicable. Success payloads are JSON objects rather than bare
arrays. Errors use one envelope everywhere:

```json
{
  "error": {
    "code": "WORKFLOW_INVALID",
    "message": "Workflow has validation errors",
    "details": { "problems": [] }
  }
}
```

`details` is optional and redacted. Expected endpoint contracts:

| endpoint | request | success |
|---|---|---|
| `GET /api/workflows` | optional `limit` 1–200 (default 100) | `200 {workflows:[summary], total:n}` sorted by `updated_at` descending then ID; no pagination until the 200-item cap is insufficient |
| `POST /api/workflows` | `{workflow:<definition without server id/timestamps>}` | `201 {workflow}` + `Location`; server allocates ID/timestamps |
| `GET /api/workflows/<id>` | — | `200 {workflow}`; `404` if absent |
| `PUT /api/workflows/<id>` | `{workflow, expected_updated_at}` | `200 {workflow}`; `409 WORKFLOW_CONFLICT` on stale update |
| `DELETE /api/workflows/<id>` | `{expected_updated_at?}` | `200 {deleted:true, workflow_id}` after atomic move to trash; `409` on stale update |
| `POST /api/workflows/import` | `{workflow, on_conflict:"reject"|"new_id"}` | `201 {workflow, imported_from_id?}`; default `new_id` |
| `GET /api/workflows/<id>/export` | — | `200 application/json` definition with attachment filename; no execution data/secrets |
| `GET /api/workflow/node-types` | — | `200 {registry_version, node_types, port_types}` with no executor/callable internals |
| `GET /api/workflow/templates` | — | `200 {templates:[{template_id, workflow}]}`; every bundled graph passes server validation |
| `POST /api/workflow/validate` | `{workflow}` | `200 {valid, problems, warnings}` for a well-formed request, even when graph-invalid; malformed transport is `400` |
| `POST /api/workflow/run` | `{workflow_id xor workflow, run_mode, target_node_ids:[], force:false, project_id?}` | `202 {execution_id, project_id, status:"queued"}` |
| `POST /api/workflow/executions/<id>/stop` | `{}` | `202 {execution_id, status:"cancelling"}`; `409` if already terminal |
| `GET /api/workflow/executions/<id>` | — | `200 {execution}`; `404` if absent |
| `GET /api/workflow/executions/<id>/events` | standard `Last-Event-ID` on reconnect | `200 text/event-stream`; `404` if absent |
| `GET /api/workflow/executions` | required `workflow_id`, optional `limit` 1–200 | `200 {executions:[summary], total:n}` sorted newest first |
| `GET /api/workflows/<id>/webhook` | — | `200 {webhook, token, path}` with `Cache-Control: no-store`; creates the separately persisted token when absent |
| `POST /api/workflows/<id>/webhook/regenerate` | `{}` | `200 {token, path}` with `Cache-Control: no-store`; immediately invalidates the prior URL |
| `POST /api/workflow/hooks/<id>/<token>` | mapped JSON object, max 64 KiB | `202 {execution_id, project_id, status:"queued"}` with queue source `webhook`; available only to loopback clients while the server itself is loopback-bound |

Create/import/save return `422 WORKFLOW_INVALID` when the JSON transport is valid but violates
workflow rules. Use `400` for malformed JSON/request shape, `403` for non-loopback access,
`404` for missing resources, `409` for conflicts/locks/terminal stop, `413` for size limits,
and `500` only for unexpected redacted server failures. Add `WORKFLOW_CONFLICT` to the stable
error-code set.

SSE (own emitter in `studio/workflows/events.py` — do NOT reuse pipeline `_emit`, which is private and closes over `_jobs`; see blocker B6):

```jsonc
{ "sequence": 12, "execution_id": "ex_123", "node_id": "n_tts",
  "status": "running", "attempt": 1, "timestamp": "ISO",
  "duration_ms": 0, "summary": "Generating narration",
  "progress": {"ready": 3, "total": 10},      // optional, poll-driven nodes
  "from_sample_data": false }                  // present when stub-fed
```
Monotonic `sequence` per execution; each SSE frame includes `id: <sequence>` and a JSON `data:` payload. The stream ends on terminal event `{node_id: null, status: "succeeded|failed|cancelled"}`. On automatic reconnect, browser `EventSource` sends the standard `Last-Event-ID` header; the server replays events with greater sequence values from a bounded ring (1000 events). If the requested ID predates the retained buffer, emit a snapshot/reset event before live events. The client also deduplicates by `sequence`.

## 7. Error codes (stable)

`WORKFLOW_INVALID, WORKFLOW_CONFLICT, UNKNOWN_NODE_TYPE, UNSUPPORTED_NODE_VERSION, PORT_TYPE_MISMATCH, MISSING_REQUIRED_INPUT, CYCLE_DETECTED, PROJECT_LOCKED, NODE_EXECUTION_FAILED, ALIGNMENT_EMPTY, WEBHOOK_FAILED, WEBHOOK_NOT_FOUND, WEBHOOK_PAYLOAD_INVALID, PROVIDER_UNAVAILABLE, EXTENSION_NOT_CONNECTED, POLL_TIMEOUT, EXPORT_FAILED, CANCELLED, ARTIFACT_MISSING, CACHE_INTEGRITY, STUB_PAYLOAD_INVALID, SAMPLE_FIXTURE_MISSING, OPTION_CONTEXT_INVALID`.
`OPTION_CONTEXT_INVALID` was added by step 12.2, exactly as §23.3 requires: it is
additive and changes the meaning of no existing code.
Failure payload: `{code, node_id, node_name, message, details_redacted, attempt, timestamp, recovery_suggestion}`.

## 8. Extraction blockers & known defects (input to step 3.1)

Blockers (must fix in 3.1):
- **B1** HTTP-to-self calls in storyboard/assets/assemble/auto-sync steps (`127.0.0.1:{STS_PORT}`) — replace with direct service calls.
- **B2** `STS_PORT` env var set inside a request handler (`pipeline/routes.py:280`) — never rely on it in workflow code.
- **B3** `grabber_start` `@validate_json` route-coupling — extract `start_grabber(request_model) -> job` service.
- **B4** `assemble_project_for_editor` — extract `assemble(project_id, *, force=False) -> dict`.
- **B5** Duplicate Kokoro/misaki singletons in `tts/routes.py` AND `tts/providers/kokoro/provider.py` (two model caches possible) — collapse to one owner (K1).
- **B6** No shared SSE emitter — build `studio/workflows/events.py`; later optionally lift pipeline `_emit` onto it.
- **B7** `ProviderRegistry.VALID_DOMAINS` is closed `{tts,storyboard,animator}` — workflow engine goes through existing domains only; no new domain in v1.
- **B8** Provider modules load under synthetic names — always `registry.get(id)`, never `import`.
- Dual provider vocabulary: **registry ids are canonical** in node configs (`kokoro, inworld, wavespeed_webhook, wavespeed_direct, gemini_ws, grok_automa, kie_ai`); legacy strings accepted on import with mapping.

Known defects (preserve during extraction; fix only as explicit follow-ups): export status omits `output_filename`; per-scene SFX dropped at export & stripped by persist helper; audio fallback promotes non-voice track to narration; double loudnorm on TTS cache hit; TTS cache key ignores provider; `_step_scenes`/kokoro paths have no stop checks; storyboard poll counts errors as done; `midjourney`/`meta_ai` are URL strings, not providers.

## 9. Mandatory shared helpers

- `studio.io_utils`: `safe_json_write` / `safe_json_read` for every JSON touch; `JobStore` instead of new dict+Lock pairs; `now_iso`.
- `studio.security`: `sanitize_project_id` (workflow/execution ids), `safe_join` (all path building), `is_safe_webhook_url`, `is_loopback_remote`. Do not copy the hand-rolled sanitizers in editor/story.
- `config.py`: all dir constants; `generate_project_id(prefix)` — workflow projects use existing prefixes (`pm_`) plus `wf_`/`ex_` for workflow/execution ids.
- Frontend: setup-style `defineStore` (both existing stores are composition style); `@` alias inherited by Vitest through `vite.config.js`.

## 10. Sample fixtures map (step 0.2 → consumed by 2.5/3.5)

`studio/workflows/fixtures/` — one per port type, frozen from a real tiny-script pipeline run:

| port type | fixture | notes |
|---|---|---|
| `script` | `script.json` | ~40-word script text |
| `audio_file` + `tts_metadata` | `voice.wav` + `tts.json` | few seconds, kokoro |
| `alignment` | `alignment.json` | matching the fixture audio |
| `segments` | `segmented.json` | 3 segments |
| `scenes` / `image_prompts` | `scenes.json` | 3 scenes with prompts |
| `storyboard_images` | `storyboard.json` + 1 small image | |
| `animation_assets` | `metadata.json` + 1 tiny mp4 + 1 jpg | |
| `editor_project` | `initial.json` | references fixture assets |
| `project_settings` | `project_settings.json` | defaults + sample logo png |
| `captions` / `music_track` | `captions.json` / ref to a resources track | |

Fixture validation is type-specific, not just "JSON parses": script is non-empty and bounded;
audio is a decodable WAV with positive duration; alignment words have finite ordered times;
segments are ordered, non-overlapping, and reference the canonical script; scenes have stable
indices and prompts; all media references are relative and contained beneath the fixture root;
storyboard/animator counts match their listed statuses; editor-project URLs resolve only to
fixture assets; and caption/music timings fit the canonical audio duration. A manifest records
SHA-256, byte size, media metadata, port types, and fixture schema version for every file.

Generation procedure: use a tiny canonical script; derive JSON shapes from audited real
artifacts; strip timestamps, secrets, provider payloads, and absolute paths; generate tiny
WAV/image/video media deterministically with local tools; validate all cross-references; and
commit the result. Live n8n/provider access must not be required to reproduce the fixture set.

**Current status: captured and frozen (step 2.5, 2026-08-04).** The fixture set lives in
`studio/workflows/fixtures/` (~188 KiB total) with `manifest.json` recording SHA-256, byte
size, media metadata, port types, and `fixture_schema_version: 1` for every file. Media is
generated locally (stdlib `wave`, Pillow, ffmpeg in bitexact mode) by
`studio/workflows/fixtures/generate.py`, which is byte-for-byte reproducible and requires no
provider access. `studio/workflows/sample_data.py` enforces the type-specific validation rules
above (`validate_fixtures()`, exercised by `tests/test_workflow_fixtures.py`) and serves the
per-port-type sample payloads consumed by stub nodes. One deliberate divergence from the
inventory table: the `music_track` fixture references a bundled `media/music.wav` instead of a
resources-library track so the set stays self-contained under the fixture root.

## 11. Security / threat notes

Redaction points: node configuration echoes (provider options may hold keys), execution records, SSE payloads, logs, clipboard fragments, exported workflow JSON — all through `studio/workflows/redaction.py`. Import validation limits: max 2 MB workflow JSON, ≤ 200 nodes, ≤ 500 edges, ids sanitized, unknown types/versions block execution. Async option sources: allowlist identifiers only (`tts_voices, story_tones, style_templates, storyboard_providers, animator_providers, export_profiles, caption_presets`). Media uploads (`media_asset`): extension+MIME+size (≤ 5 MB) validation into `output/branding/`, never raw paths. All new endpoints respect `MAX_CONTENT_LENGTH`, CORS config, and loopback guards for destructive ops.

Request hardening (step 6.3): JSON body limits are enforced by a bounded stream read (≤ 2 MiB + 1 byte), so chunked transfer encoding with no `Content-Length` cannot bypass them; non-empty bodies still require a JSON content type (forces a CORS preflight for cross-origin callers). Submitted values for `options_source` config fields are validated server-side against the allowlisted resolver's current values (`allowed_option_values`, process-lifetime cached); an unavailable resolver fails open — bad values are rejected, missing providers never block saving. Branding uploads cap the whole multipart request at 6 MiB via per-request `max_content_length` (Werkzeug enforces it while reading, chunked included; `413 REQUEST_TOO_LARGE` envelope via blueprint error handler) and cap the library at 50 stored logos (`409 LIMIT_EXCEEDED`).

## 12. Phase 0 verification record (2026-08-04)

- Backend: `venv` was broken (base interpreter from another project, missing). Rebuilt on Python 3.10.0; requirements + pytest installed. Initial run exposed a real false positive in the watermark confidence gate: the clean radial-glow regression had brightness difference 8.82, while the weakest real watermark fixture was about 17. Raising `_BRIGHTNESS_DIFF_MIN` from 8 to 10 preserves the real fixtures and fixes the false positive. Current `pytest tests/ -q`: **14 passed, 2 subtests passed**.
- Frontend: Vitest + @vue/test-utils + jsdom added (`npm run test`): **1 passed**. `test` block lives in `vite.config.js` (alias inherited).
- No `conftest.py`/pytest config exists; tests are `unittest`-style and run from repo root. Development dependencies are declared in `requirements-dev.txt` so pytest installation is reproducible without adding it to runtime requirements.
- Verified toolchain: Python 3.10.0; Node 24.14.0; npm 11.11.0. Vite 8 requires Node `^20.19.0 || >=22.12.0`, which is the frontend minimum. The Python source uses 3.10 union syntax, so Python 3.10+ is the backend minimum.
- Leftover empty `tests/test_*_<hash>/` dirs from an old run: ignorable noise.

### Tracked follow-through after the Phase 0 gate

1. Capture/generate and validate the fixture inventory before step 2.5.
2. Convert the field-level contracts into executable validators/tests as their owning modules
   land in Phases 1–3; until then, this document is the normative source.

---

# Provider Platform — Migration Audit (Phase 10.1)

> Produced by step 10.1 of [implementation-plan.md](implementation-plan.md).
> Grounded in code at commit `36734f6` (2026-08-08). Every line number below was read
> directly at that commit, not inferred.
> Vocabulary reconciled with `_dev/docs/plans/modular-providers-plan-v4.md` (the design doc
> the existing `studio/shared/providers_common/` was built from). Where v4 and this plan
> disagree, this document wins and the divergence is recorded in §17.6.
>
> **Scope.** Five domains migrate: `script`, `scene_blueprint`, `tts`, `storyboard`,
> `animator`. Music and Captions are excluded by owner decision; they are audited in §17.7
> only to confirm they keep working untouched.

## 13. Domain migration matrix

Legend — **State**: `platform` = has a provider package + registry today; `ad-hoc` = no
provider abstraction at all.

### 13.1 `script` (Story Generator) — state: **ad-hoc**

| aspect | evidence |
|---|---|
| entry points | `POST /api/story/generate` (`studio/story/routes.py:197`); workflow node `story.generate` → `studio.workflows.adapters.story:generate` (`registry.py:159`, adapter `adapters/story.py:10`) |
| shared service | `studio.story.service.generate_story(config, project_id=…)` — called by the adapter (`adapters/story.py:18`). The legacy route does **not** call it; it re-implements the same flow inline (`routes.py:197-351`) |
| other routes | `GET /api/story/webhook-url` (`routes.py:185`), `GET /api/story/categories` (`routes.py:191`), `GET /api/story/history` (`routes.py:353`), `GET /api/story/<project_id>` (`routes.py:382`), `POST /api/story/classify-style` (`routes.py:404`) |
| inputs | `preset_style, story_category, duration (15–180), language (english\|french\|spanish), language_level, story_tone, idea, webhook_url, project_name_id, niche_preset` (`studio/story/schemas.py:21-53`) |
| outputs | `{success, project_id, story_text, sections{hook,build,climax,cta}, metadata{…}}` |
| artifacts | `output/stories/{project_id}/story.json`; history `output/story_history/{preset}__{category}__{language}.json` (cap 10 entries) |
| side effects | outbound HTTP to n8n (120 s timeout); anti-repeat history mutation; non-deterministic concept-family pick |
| provider IDs | **none.** `"provider": "gemini"` is a hardcoded literal in the response metadata (`studio/story/service.py:102`, and again at `routes.py:287`) — a label, not a selector |
| aliases | none |
| settings/env | `N8N_STORY_WEBHOOK_URL` (`config.py:74-76`), `N8N_CLASSIFY_WEBHOOK_URL` (`config.py:80-82`), `STS_ALLOW_PRIVATE_WEBHOOKS`. **No `settings.json` participation** |
| hardcoded branches | none (single path) |
| callers | frontend `features/pipeline/composables/useStory.js`; `PipelinePage.vue` (classify); workflow scheduler through the adapter |
| owner | 13.1 (random_template provider), 13.2 (AI provider wrap), 13.3 (generic dispatch + defect fix) |

**Frontend random-story templates are not a provider and never were.**
`frontend/src/shared/data/stories.js:6` exports a static `RANDOM_STORIES` array of
`{text, type, styles}` objects; `useRandomStory.js:14` picks one at random while avoiding an
immediate repeat (`lastIdx`, lines 4 and 19). Consumers: `usePipeline.js:5`, `useTts.js:13`,
`PipelinePage.vue:17`, `TtsPage.vue:5`. It never calls an API and has no backend counterpart —
it is a "fill the textarea with sample text" affordance. 13.1 moves this catalog and its
anti-repeat rule behind a backend `random_template` script provider; until then it is
**public compatibility surface** (users rely on the button) with **zero** migration coupling.

### 13.2 `scene_blueprint` (Scene Blueprint) — state: **ad-hoc**

| aspect | evidence |
|---|---|
| entry points | `POST /api/scenes/generate` (`studio/build_scene_blueprints/routes.py:263`); workflow node `scenes.blueprint` → `adapters/scenes.py:7`; legacy pipeline `_step_scenes` (`studio/pipeline/services.py:403`, wrapper `pipeline/routes.py:1265`) |
| other routes | `GET /api/scenes/templates` (`routes.py:251`), `/api/scenes/webhook-url` (`:257`), `/api/scenes/history` (`:533`), `/api/scenes/<project_id>` (`:565`), `/api/scenes/audio/<source_folder>` (`:579`) |
| inputs | `segments[] (required), script, style, style_prompt, custom_style_notes, full_segments, webhook_url, project_id, parent_id, source_folder, aspect_ratio` (`schemas.py`, `extra="allow"`) |
| outputs | `{scenes[], analysis, style_spec, style_prompt, scene_blueprints, coherence_score, coherence_warnings, coherence_metrics, sfx_report, total_duration, …}` |
| artifacts | `output/scenes/{project_id}/scenes.json` (`routes.py:360`, `services.py:517`) |
| side effects | outbound HTTP to n8n; chapter mode splits into chunks with per-chunk retry; unseeded `random.shuffle` in `_assign_hook_animations` (`pipeline/services.py:384-396`, invoked at `:508`) |
| provider IDs | **none.** A grep for `provider` across `studio/build_scene_blueprints/` returns nothing |
| aliases | none |
| settings/env | `N8N_WEBHOOK_URL` (`config.py:68-70`), `STS_ALLOW_PRIVATE_WEBHOOKS`. **No `settings.json` participation** |
| dispatch branch | the only branch is `should_use_chapters(segments)` → `speech_count > 20` (`chapters.py:31-34`) — a payload-size decision, not a provider decision |
| transport | `studio.webhooks.call_webhook(url, payload, timeout=180, label=…)`; 3 attempts, 2/4/8 s backoff; chapter mode raises the timeout to 300 s |
| owner | 13.4 |

### 13.3 `tts` — state: **platform** (registry present, dispatch still by string)

| aspect | evidence |
|---|---|
| entry points | `POST /api/tts/generate` (`studio/tts/routes.py:625`), `/api/tts/stream` (`:896`), `/api/tts/voices` (`:515`), model download/status, `/api/tts/cache/*`; workflow node `tts.generate` → `adapters/tts.py:7`; legacy `_step_tts` (`services.py:59`) |
| provider IDs | `kokoro`, `inworld` |
| aliases | **none** for TTS; the legacy and canonical IDs are both `kokoro` / `inworld` |
| dispatch | `services.py:77-82` resolves `tts_provider_override → tts_provider → settings.json domains.tts.selected_provider → "kokoro"`, then **branches on the string** at `services.py:103` (`if provider_id == "inworld"`). `tts_registry.get()` at `:84` is only an existence gate plus `.version`/`.kind` reads (`:106`, `:112`) |
| route dispatch | `tts/routes.py:629`, `:517`, `:902` each branch `if provider == "inworld"` |
| registry bypass | **`studio/tts/routes.py` never imports or touches the registry** — a grep for `registry` and `providers import` in that file returns **no matches** |
| settings | `settings.json domains.tts.{selected_provider, per_provider.{kokoro,inworld}}`; legacy `app-config.json` key `sts-tts-provider`; kokoro schema = `voice, speed, lang, blend, blendA, blendB, blendRatio, blendMethod`; inworld = `api_key, voice, model, speed` |
| env | `INWORLD_API_KEY` (side effect — §14.3), `INWORLD_TTS_MODEL`, `INWORLD_TTS_BASE_URL` |
| artifacts | `output/tts/{basename}/{basename}.wav` + `.json`; pipeline `…/voice.wav` + `tts.json`; cache `TMP_DIR/tts/{sha16}.wav` |
| cache key | `sha256(f"{text}|{voice}|{speed:.2f}")[:16]` (`tts/routes.py:854-862`) — **provider is not in the key** (known defect, §8) |
| node config | `engine` is a **static hardcoded list** `["kokoro","inworld"]` (`registry.py:186`); there is no `tts_providers` option source (§15.1) |
| callers | frontend `useTts.js` and `TtsPage.vue`; pipeline `usePipelineForm.js`, `usePipeline.js`, `PipelinePage.vue`, and `VoicePicker.vue`; workflow scheduler through `adapters/tts.py` |
| owner | 15.1, 15.2, 15.3 |

### 13.4 `storyboard` — state: **platform** (registry present, dispatch still by string)

| aspect | evidence |
|---|---|
| entry points | `POST /api/storyboard/generate` (`studio/storyboard/routes.py:283`), `/api/storyboard/grab` (`:490`), status/images/image-models/webhook-url/remove-watermarks; workflow node `storyboard.generate` → `adapters/storyboard.py:54`; legacy `_step_storyboard` (`services.py:530-627`) |
| provider IDs | `gemini_ws`, `wavespeed_webhook`, `wavespeed_direct` |
| aliases | canonical→legacy: `gemini_ws→gemini`, `wavespeed_webhook→webhook`, `wavespeed_direct→direct` (`services.py:550`). The legacy page and single-image route use `gemini` / `webhook`; there is no general reverse-normalization layer |
| dispatch | bulk `routes.py:311-324` uses `provider_override → settings.json selection → gemini_ws`, then branches on `gemini_ws`; single-image `routes.py:603-605` branches on legacy `provider == "gemini"`. **The bulk route ignores its legacy extra field `provider`**, so the pipeline's canonical→legacy value at `services.py:563` does not select the provider; without `provider_override`, the settings selection wins. Adapter branches at `adapters/storyboard.py:21` |
| async transport | WebSocket `/ws/storyboard-gemini-image-grabber`, registered by `gemini_ws.register_runtime(app, sock)` through `call_provider_runtime` when `manifest.kind == "extension"` (`storyboard/providers/__init__.py:36-52`) |
| artifacts | `output/storyboard/{pid}/storyboard.json`, `{scene}/image.{ext}` (versioned), `scene_prompts.json`, thumbnails |
| poll contract | 10 s interval / 30 min timeout; errors count toward completion (`pending = total-ready-errors`) |
| settings | `per_provider.wavespeed_webhook.{webhook_url,image_model}`, `wavespeed_direct.{api_key,image_model}`, `gemini_ws.{auto_type}`; legacy frontend key `sts-storyboard-provider` (default `gemini`) |
| env | `WAVESPEED_API_KEY` seeds `wavespeed_direct.api_key` (`settings_manager.py:94-96`) |
| callers | frontend `StoryboardPage.vue`; pipeline `usePipeline.js`, `useProviderTabs.js`, and `PipelinePage.vue`; workflow scheduler through `adapters/storyboard.py` |
| owner | 14.1, 14.2, 14.4, 14.5 |

### 13.5 `animator` — state: **platform** (registry present, dispatch still by string)

| aspect | evidence |
|---|---|
| entry points | `POST /api/animator/grabber/start` (`animation_routes.py:186`) plus pending/results/upload/status/redownload/history/reconcile/project/thumbnails; WS `/ws/animator-grok-video-grabber` (`animator/routes.py:199`); workflow node `animator.generate` → `adapters/animator.py:64`; legacy `_step_assets` (`services.py:630`) |
| provider IDs | `grok_automa`, `kie_ai` |
| aliases | canonical→legacy in the pipeline: `grok_automa→grok`, `kie_ai→kie-ai` (`services.py:644`). Reverse normalization is local to `GrabberStartRequest.provider_id`: `midjourney→grok_automa`, `grok→grok_automa`, `kie-ai→kie_ai`, and every unknown legacy value→`grok_automa` (`schemas.py:30-36`) |
| dispatch | `animation_routes.py:194` uses `GrabberStartRequest.provider_id` (override or legacy-map result), falls back to `grok_automa` only if that ID is absent from the registry, then branches at `:266`, `:297`, `:314`, `:333`. Despite the comment at `:190`, it **does not read `domains.animator.selected_provider` for selection**. Adapter branches at `adapters/animator.py:28` and `:37` |
| registry bypass | **`animation_routes.py:21`**: `from .providers.kie_ai import generate_image as kie_ai_generate` — direct module import; the registry is never consulted for this call |
| artifacts | `output/animator/{pid}/{scene}/*` (+ `*_thumb.jpg`), `metadata.json`, `grabber_job.json`, legacy `animator.json` |
| poll contract | 10 s interval / **120 min** timeout; `grabber_jobs` JobStore is in-memory, rehydrated from disk on import |
| settings | `per_provider.kie_ai.{api_key,model,resolution}`, `grok_automa.{mode,quality,duration}`; legacy frontend key `sts-asset-provider` (default `grok`). The backend selected value is currently catalog/display state, not route or adapter dispatch input |
| env | `KIE_AI_API_KEY`, `KIE_AI_MODEL` seed `kie_ai` settings (`settings_manager.py:98-104`) |
| dead config | `arguments if provider == "midjourney"` (`animation_routes.py:260`) — `midjourney` is not a registered provider; the branch is unreachable |
| callers | frontend `AssetsPage.vue`, `useAssets.js`, `GrabberControls.vue`, and `AssetCard.vue`; pipeline `usePipeline.js`, `useProviderTabs.js`, and `PipelinePage.vue`; workflow scheduler through `adapters/animator.py` |
| owner | 14.1, 14.3, 14.4, 14.5 |

## 14. The seven mandated items, answered

### 14.1 Dead-interface inventory

Method: exhaustive repo-wide grep for `.synthesize(`, `.submit(`, `.poll(`, and `get_provider`.

| symbol | call sites found | verdict |
|---|---|---|
| `TTSProvider.synthesize` (+ both implementations) | **0** | never executed |
| `StoryboardProvider.submit` / `.poll` (3 implementations) | **0** — the only `.submit(` in the repo is `pool.submit(` (`scheduler.py:535`); the only `.poll(` calls are `subprocess.poll()` (`storyboard/lama_client.py:77,114,152`) | never executed |
| `AnimatorProvider.submit` / `.poll` (2 implementations) | **0** (same evidence) | never executed |
| `get_provider()` — domain factories (`tts/providers/__init__.py:26`, `storyboard/…:26`, `animator/…:26`) | **0 call sites**; only the `def` plus an `__all__` entry at `:57` of each | never executed |
| `get_provider()` — provider factories (`storyboard/providers/gemini_ws/provider.py:89`, `wavespeed_webhook/provider.py:108`, `wavespeed_direct/provider.py:98`, `animator/providers/grok_automa/provider.py:106`, `kie_ai/provider.py:246`) | **0**; `kie_ai/__init__.py:11` merely re-exports it | never executed |

Beware the false positive: `settings_manager.get_provider_settings()` is a **different, live**
function with many call sites. It is not a factory.

What *is* live on provider objects: `.version` / `.kind` metadata (`services.py:106,112`),
`.validate_settings()` (`editor/routes.py:282`, `pipeline/routes.py:129,142,155`),
`.health_check()` (`editor/routes.py:327`), `.settings_schema()` (`editor/routes.py:361`),
`.to_dict()` (`editor/routes.py:368`), and `registry.to_dict()` (`editor/routes.py:247-249`).

**Consequence, frozen:** every `provider.py` body listed above is *unverified code under
first-time test*, not a preserved baseline. The behavior to preserve is the observable output
of the string-branch legacy paths. Owner: 11.4 (contract tests that actually invoke each
previously-unexecuted method), then 14.2 / 14.3 / 15.1 for the domain rewiring.

### 14.2 Selection-store conflict

Two independent stores exist and neither writes to the other. The conflict affects all three
existing provider domains, not only TTS:

| domain | nested selection | legacy frontend selection | actual dispatch readers |
|---|---|---|---|
| TTS | `domains.tts.selected_provider` | `sts-tts-provider` (currently persisted as `inworld`) | nested: pipeline fallback at `services.py:80`; legacy: `useTts.js:142`, `usePipelineForm.js:93`, `SettingsPage.vue:452` and pipeline request construction |
| Storyboard | `domains.storyboard.selected_provider` | `sts-storyboard-provider` (frontend default `gemini`; absent from the current blob) | nested: bulk route fallback at `storyboard/routes.py:315-316`; legacy: `StoryboardPage.vue:28-30`, `usePipeline.js`, `useProviderTabs.js` |
| Animator | `domains.animator.selected_provider` | `sts-asset-provider` (frontend default `grok`; absent from the current blob) | nested: **no generation dispatch reader** (catalog response only at `editor/routes.py:249`); legacy: `usePipeline.js`, `useProviderTabs.js`, Assets UI |

The nested selections are written by `PUT /api/settings/v2` whole-blob replacement
(`editor/routes.py:215-227`). The legacy keys are written independently by `PATCH /api/settings`
through `useSettings.update()` (`useSettings.js:41-49`). Workflow nodes use their saved
`engine` / `provider` configuration and do not inherit any of these default selections.

`settings_manager.set_selected_provider()` (`settings_manager.py:189-198`) exists and has
**zero call sites** — only `__all__` re-exports at `shared/__init__.py:12` and
`providers_common/__init__.py:20,59`.

The frontend selection path is `useProviders.js:66-100`: `GET /api/settings/v2` →
spread-merge a new `selected_provider` → `PUT /api/settings/v2` with the **entire** blob.
`put_settings_v2` calls `save_settings(data)`, a full replace with no `expected_updated_at`
and no field-level merge — a genuine lost-update window between any two concurrent writers.

The current values/defaults happen to agree semantically (`inworld`, `gemini↔gemini_ws`, and
`grok↔grok_automa`), so there is no persisted divergence to repair today. They can silently
diverge on the next write. Animator is worse than a two-store disagreement: selecting it in the
provider modal changes catalog state but does not change legacy route, pipeline, or workflow
dispatch at all.

**Recommendation carried into 10.2 — accepted and frozen in §24:** make
`settings/settings.json` `domains.*.selected_provider` authoritative — it is the intended
backend store, it is already per-domain, and it is the v4 design's stated source of truth.
First wire the missing animator dispatch read. Migrate all three legacy keys by having the legacy
pages read selections from the provider catalog API, keeping read-through fallbacks for one
release, then deleting the keys.
Replace the whole-blob write with a targeted selection endpoint routed through the existing
`set_selected_provider()`. Owners: 10.2 freezes it, 11.5 builds the endpoint, 12.4 moves the
legacy page, 16.1 deletes the loser key.

### 14.3 Env-var side effects

All in `_seed_from_env()` (`settings_manager.py:67-107`), which runs **only when
`settings/settings.json` is absent** (first run):

| env var | effect | line |
|---|---|---|
| `INWORLD_API_KEY` | seeds `per_provider.inworld.api_key` **and flips `domains.tts.selected_provider` to `"inworld"`** | `:85-88` |
| `INWORLD_TTS_MODEL` | seeds `per_provider.inworld.model` | `:90-92` |
| `WAVESPEED_API_KEY` | seeds `per_provider.wavespeed_direct.api_key` | `:94-96` |
| `KIE_AI_API_KEY` | seeds `per_provider.kie_ai.api_key` | `:98-100` |
| `KIE_AI_MODEL` | seeds `per_provider.kie_ai.model` | `:102-104` |
| `STS_SYNC_FOLDER`, `STS_AUTO_SYNC` | seed `general.*` | `:79-83` |

`INWORLD_API_KEY` is the **only** implicit *selection* change; the other four seed values
only. Defaults without env: `kokoro` / `gemini_ws` / `grok_automa`
(`settings_manager.py:148,152,156`).

Separately, a present-but-empty `api_key` is persisted for `kie_ai`, `wavespeed_direct`, and
`inworld` in the live `settings.json`, so "key configured" cannot be inferred from key
presence. Owner: 11.3 (env fallback without returning values), 10.2 (availability states).

### 14.4 Legacy alias tables

Verified verbatim:

- `studio/pipeline/services.py:550` — `id_to_legacy = {"gemini_ws": "gemini", "wavespeed_webhook": "webhook", "wavespeed_direct": "direct"}`, applied at `:551`; consumed at `:552` (`prompt_prefix` only when `sb_provider == "gemini"`) and sent as `payload["provider"]` at `:563` over an **HTTP-to-self** call to `/api/storyboard/generate` (`:566`, blocker B1).
- That storyboard wire value is currently **ignored for dispatch**: `StoryboardGenerateRequest`
  has no model field named `provider` (it is accepted only because `extra="allow"`), its property
  always derives from `provider_override`, and `routes.py:311-316` reads only
  `provider_override` or nested settings. Thus a legacy `provider="webhook"` request can run the
  selected `gemini_ws` provider. Preserve the field as wire compatibility, but owner 14.2 must
  normalize it before dispatch rather than preserving the bug.
- `studio/pipeline/services.py:644` — `id_to_legacy = {"grok_automa": "grok", "kie_ai": "kie-ai"}`, applied at `:645`; consumed at `:664` (`if anim_override == "grok_automa" or provider == "grok"` → grok-specific payload keys).
- `studio/animator/schemas.py:30-36` is the reverse/legacy normalization point:
  `midjourney|grok→grok_automa`, `kie-ai→kie_ai`, and unknown values→`grok_automa`.
- `app.py:248-286` `POST /api/pipeline/preflight` — defaults `storyboard_provider="gemini"` (`:253`) and `asset_provider="grok"` (`:254`), branching at `:266` and `:276` to probe extension connectivity.
- `app.py:198-200` `focus-studio` — `if target == "gemini" … elif target == "grok"`.

Direction matters: the two pipeline tables map **canonical → legacy**; Animator alone also has
the reverse map above. The legacy strings are the wire format of the internal HTTP hop and the
preflight API; the canonical IDs are what the registry and `settings.json` use. Owner: 10.4
(freeze the mapping in both directions),
16.1 (delete once the internal HTTP hop is gone).

### 14.5 Registry bypasses

1. `studio/animator/animation_routes.py:21` — `from .providers.kie_ai import generate_image as kie_ai_generate`, invoked inside `_kie_ai_generate_all`. Violates §8 blocker B8 ("always `registry.get(id)`, never `import`"). Owner: 14.3.
2. `studio/tts/routes.py` — **no registry reference at all**. Every TTS HTTP route dispatches on a raw request string. Owner: 15.2.
3. `studio/workflows/adapters/animator.py:33` reads `settings_manager.get_provider_settings("animator", "kie_ai")` with a **literal provider ID**, hardcoding the adapter to one provider's settings. Owner: 14.3.
4. `studio/storyboard/routes.py` and `animation_routes.py` do call `registry.get()`, but only to validate existence and read settings — dispatch remains the string branch. Owner: 14.2 / 14.3.

### 14.6 Duplicated contracts

`JobHandle` and `JobStatus` are **field-for-field identical** in both files; `SceneResult`
differs only in two field names:

| dataclass | storyboard | animator | identical? |
|---|---|---|---|
| `JobHandle` | `base.py:13-17` — `job_id, status, created_at` | `base.py:12-17` — same | yes |
| `JobStatus` | `base.py:20-28` — `job_id, status, progress, message, result, error` | `base.py:20-28` — same | yes |
| `SceneResult` | `base.py:31-38` — `scene_index, image_url, image_path, thumbnail_url, metadata` | `base.py:31-38` — `scene_index, `**`video_url, video_path`**`, thumbnail_url, metadata` | no — media field renamed |

Related duplication: `studio/<domain>/providers/__init__.py` exists in **three** copies (tts,
storyboard, animator), each exactly 57 lines, structurally identical but **not** byte-identical
(distinct MD5s `2506fb31…`, `941ed83d…`, `64fe87a3…`) because each embeds its domain name and
`init_<domain>_registry` function name.

**Correction to the plan:** step 11.1 says "the four copies of the identical 57-line
`studio/<domain>/providers/__init__.py`". There are **three**, and they are not byte-identical.
The consolidation remains correct; only the count in 11.1 is wrong.

Owner: 11.4 unifies the job dataclasses (one `SceneResult` with a neutral media field plus
domain aliases); 11.1 replaces the three `__init__.py` copies with one shared binding.

### 14.7 Known latent defect — `story` output port

`adapters/story.py:24-27` returns `outputs(script=…, story=with_artifacts(result, path))`.
`registry.py:139` declares only `outputs: [_CONTROL_OUT, _out("script", "script")]`.

**The plan's stated mechanism is wrong and is corrected here.** `_validate_outputs`
(`scheduler.py:958-967`) iterates the **declared** ports and raises `NODE_OUTPUT_MISSING` when
one is absent. It never inspects undeclared keys, so it does **not** drop `story`.
What actually happens:

- `story` survives into `node_outputs[node_id]` (`scheduler.py:729`).
- `_artifact_refs` (`scheduler.py:217-228`) recurses over *all* values, so
  `output/stories/{pid}/story.json` **does** reach `node_record.artifact_refs`
  (`scheduler.py:731`) and the execution record. The plan's "its artifact refs never reach a
  port" is inaccurate for the record; it is accurate that they reach no *port*.
- The payload is nonetheless **unreachable by any consumer**: no edge may target it (edge ports
  must be registry port IDs, §4.1), and static expression validation rejects it —
  `expressions.py:131-134` looks the port up in `get_node_type(...)["outputs"]` and emits
  `EXPRESSION_OUTPUT_MISSING`. Runtime `resolve_configuration` (`expressions.py:160`) would
  return it happily, but validation never lets execution get that far.

Net effect: dead weight in the output dict plus a misleading artifact ref attributed to a port
that does not exist. Severity is low; the remedy in 13.3 (declare the port **or** fold the
artifacts into `script`) is unaffected. Owner: **13.3**, which must also drop the
"`_validate_outputs` drops it" wording and replace the hardcoded `"provider": "gemini"` at
`studio/story/service.py:102`.

## 15. Hard-coded provider decision register

Backend and frontend production decisions on provider/engine literals. Tests excluded. A row may
group several branches in one component; each has an owner.

| # | location | branch | owner |
|---|---|---|---|
| P1 | `app.py:198` | `target == "gemini"` (focus-studio) | 16.1 |
| P2 | `app.py:200` | `target == "grok"` | 16.1 |
| P3 | `app.py:266` | `storyboard_provider == "gemini"` (preflight) | 14.4 |
| P4 | `app.py:276` | `asset_provider == "grok"` (preflight) | 14.4 |
| P5 | `pipeline/services.py:91` | `provider_id == "inworld"` (voice-key selection) | 15.2 |
| P6 | `pipeline/services.py:103` | `provider_id == "inworld"` (dispatch) | 15.2 |
| P7 | `pipeline/services.py:550-552` | storyboard alias table + `sb_provider == "gemini"` | 14.2 |
| P8 | `pipeline/services.py:644-645`, `:664` | animator alias table + `provider == "grok"` | 14.3 |
| P9 | `pipeline/routes.py:325` | `tts_provider == "inworld"` (voice default) | 15.2 |
| P10 | `pipeline/routes.py:630` | `provider == "grok"` | 14.3 |
| P11 | `pipeline/routes.py:1051` | `storyboard_provider == "gemini"` | 14.2 |
| P12 | `animator/animation_routes.py:260` | `provider == "midjourney"` — **unreachable**, no such provider | 14.3 (delete) |
| P13 | `animator/animation_routes.py:266` | `provider_id == "grok_automa"` | 14.3 |
| P14 | `animator/animation_routes.py:297` | `provider_id == "kie_ai"` | 14.3 |
| P15 | `animator/animation_routes.py:314` | `provider_id == "grok_automa"` | 14.3 |
| P16 | `animator/animation_routes.py:333` | `provider_id == "kie_ai"` | 14.3 |
| P17 | `workflows/adapters/storyboard.py:21` | `provider == "gemini_ws"` | 14.2 |
| P18 | `workflows/adapters/animator.py:28` | `provider == "kie_ai"` | 14.3 |
| P19 | `workflows/adapters/animator.py:37` | `provider == "kie_ai"` | 14.3 |
| P20 | `workflows/adapters/animator.py:33` | literal `"kie_ai"` settings lookup | 14.3 |
| P21 | `tts/routes.py:517` | `provider == "inworld"` (voice list) | 15.2 |
| P22 | `tts/routes.py:629` | `provider == "inworld"` (generate) | 15.2 |
| P23 | `tts/routes.py:902` | `provider == "inworld"` (stream reject) | 15.2 |
| P24 | `storyboard/routes.py:324` | `provider_id == "gemini_ws"` | 14.2 |
| P25 | `storyboard/routes.py:605` | `provider == "gemini"` (grab-one, legacy string) | 14.2 |
| P26 | `workflows/registry.py:186` | `engine` static list `["kokoro","inworld"]` — the only domain whose node has no `options_source` | 12.3 / 15.2 |
| P27 | `workflows/registry.py` storyboard + animator config | `display_options.show.provider: ["gemini_ws"]` / `["grok_automa"]` provider-specific field gating | 12.3 |
| P28 | `editor/routes.py:236-238, 260-262, 305-307, 342-344, 397-399` | five handlers each re-importing the three registries and building a literal `{tts,storyboard,animator}` dict | 11.5 |
| P29 | `providers_common/registry.py:177` | `VALID_DOMAINS = {'tts','storyboard','animator'}` | 11.1 |
| P30 | `providers_common/settings_manager.py:270` | duplicate `valid_domains = {"tts","storyboard","animator"}` | 11.1 |
| P31 | `providers_common/settings_manager.py:137-160` | `_default_settings()` hardcodes the same three domains and their default provider IDs | 11.1 / 11.3 |
| P32 | `workflows/options.py:38-50` | `_provider_options(domain)` handles only `storyboard` / `animator` | 12.2 |
| P33 | `story/service.py:102`, `story/routes.py:287` | literal `"provider": "gemini"` in result metadata | 13.3 |
| P34 | `animator/schemas.py:20, 30-36` | legacy default plus `midjourney/grok/kie-ai` normalization and unknown→Grok fallback | 14.3 / 14.4 |
| P35 | `frontend/src/features/settings/composables/useSettings.js:12-14` | legacy defaults for all three domains | 12.4 / 16.1 |
| P36 | `frontend/src/features/tts/composables/useTts.js:142,390,661` | legacy TTS selection and Inworld generation branch | 12.4 / 15.2 |
| P37 | `frontend/src/features/pipeline/composables/usePipelineForm.js:93-107,155` | legacy TTS selection, voice routing, and Inworld voice loading | 12.4 / 15.2 |
| P38 | `frontend/src/features/pipeline/views/PipelinePage.vue:117-125,412,541-545` | TTS preview and niche/preset behavior branch on Inworld | 12.4 / 15.2 |
| P39 | `frontend/src/features/pipeline/components/VoicePicker.vue:18` | Inworld-specific picker UI | 12.4 / 15.2 |
| P40 | `frontend/src/features/storyboard/views/StoryboardPage.vue:28-30,350-411,535,572` | legacy `gemini` / `webhook` selection, payload, and UI branches | 12.4 / 14.2 |
| P41 | `frontend/src/features/pipeline/composables/useProviderTabs.js:15,29,50-55` | legacy Gemini/Grok tab focus and extension reachability | 14.4 / 16.1 |
| P42 | `frontend/src/features/pipeline/composables/usePipeline.js:190-202,236-245,292-301` | reads and sends all three legacy provider selections/defaults | 12.4 / 14.2 / 14.3 / 15.2 |
| P43 | `frontend/src/features/assets/composables/useAssets.js:19,115,314` | legacy Grok default and request field | 12.4 / 14.3 |
| P44 | `frontend/src/features/assets/views/AssetsPage.vue:413-434` | Grok-specific submit/retry behavior | 12.4 / 14.3 |
| P45 | `frontend/src/features/assets/components/GrabberControls.vue:7,39-41,183` | Midjourney/Grok/Kie-specific controls and label | 12.4 / 14.3 |
| P46 | `frontend/src/features/assets/components/AssetCard.vue:11` | legacy Grok provider default | 12.4 / 14.3 |
| P47 | `frontend/src/features/settings/views/SettingsPage.vue:452` | Inworld-vs-Kokoro implementation label | 12.4 / 15.2 |

### 15.1 Parameterized option sources — the blocker for 15.2

`GET /api/workflow/options/<source>` resolves `resolve_options(source)`
(`studio/workflows/options.py:108`), which takes **exactly one argument** and passes no
context. `_RESOLVERS` (`options.py:64-72`) has seven entries and must stay in lockstep with
`ASYNC_OPTION_SOURCES` (`registry.py:30-34`) — enforced by the module-level assert at
`options.py:75-77`.

Consequence today: `_tts_voices()` (`options.py:19-21`) returns `studio.tts.routes.VOICES`, a
static Kokoro list, regardless of the selected engine, so an Inworld node still offers Kokoro
voice IDs. There is no `tts_providers` source at all. `allowed_option_values`
(`options.py:85-105`) caches per source for the process lifetime and fails open. Owner: 10.2
froze the extended envelope in **§23**, 12.2 implements it, 15.2 consumes it.

## 16. Never-executed provider code paths — owner assignment

| path | files | owner |
|---|---|---|
| `TTSProvider.synthesize` + `list_voices` + `shutdown` | `tts/providers/base.py`, `kokoro/provider.py`, `inworld/provider.py` | 11.4 (first test), 15.1 (bring onto Contract v2) |
| `StoryboardProvider.submit`/`poll`/`generate_one` | `storyboard/providers/base.py` + 3 providers | 11.4, 14.2 |
| `AnimatorProvider.submit`/`poll`/`open_url` | `animator/providers/base.py` + 2 providers | 11.4, 14.3 |
| 3 domain `get_provider()` factories | `<domain>/providers/__init__.py:26` | 11.1 (replace with hub resolution) |
| 5 provider `get_provider()` factories | the five `provider.py` files in §14.1 | 11.2 (factory instantiation) |
| duplicate Kokoro singletons `kokoro_instance` / `kokoro_lock` / `generation_inference_lock` (never populated; the live ones are in `tts/routes.py`) | `tts/providers/kokoro/provider.py` | 15.1 (blocker B5 / K1 — collapse to one owner) |

## 17. Compatibility surface vs internal debt

### 17.1 Public compatibility surface (must keep working)

HTTP: `/api/story/*`, `/api/scenes/*`, `/api/tts/*`, `/api/storyboard/*`, `/api/animator/*`,
`/api/providers*`, `/api/settings/v2`, `/api/pipeline/*`, `/api/workflow/*`.
Wire formats: the five request schemas; the legacy alias strings on the internal HTTP hop and
preflight; `sts-tts-provider`, `sts-storyboard-provider`, and `sts-asset-provider` in
`app-config.json` until migrated. The Storyboard bulk route's ignored legacy `provider` field is
accepted compatibility input, but its failure to affect dispatch is debt (§14.4), not behavior to
preserve.
Files: `output/stories/*/story.json`, `output/scenes/*/scenes.json`, `output/tts/*`,
`output/storyboard/*/storyboard.json`, `output/animator/*/{grabber_job,metadata}.json`,
`settings/settings.json` v1 shape.
Workflow: node type IDs, `type_version: 1`, port IDs, and saved node `configuration` keys
(`engine`, `provider`, `webhook_url`, `style`, …) — old workflows must run unedited.
UI: the random-story button, the provider gear modal, the per-domain selectors.
Transports: the two WebSocket URLs (`/ws/storyboard-gemini-image-grabber`,
`/ws/animator-grok-video-grabber`). Browser extensions are versioned independently and cannot
be migrated in lockstep, so these paths and their message types are frozen.

### 17.2 Internal debt (free to change)

The ABC layer and all eight `get_provider()` factories; the three duplicated
`providers/__init__.py`; the duplicated job dataclasses; the string-branch dispatch (P1–P25);
the two hardcoded domain sets (P29, P30); the provider API living in the editor blueprint
(P28); the whole-blob settings write; the internal HTTP-to-self hop (B1); the unreachable
`midjourney` branch (P12); the duplicate Kokoro singletons; the undeclared `story` port; and the
ignored Storyboard legacy selection. The legacy selection keys themselves remain public until
migration even though the duplicate storage design is debt.

### 17.3 Pre-existing defects reconfirmed (not introduced by this migration)

TTS cache key omits provider (`tts/routes.py:854-862`); double loudnorm on cache hit;
storyboard poll counts errors as completion; `_step_scenes` has no stop check;
`midjourney` / `meta_ai` are URL strings, not providers. These stay on the §8 list.

### 17.4 Live-provider availability (gates fixture work)

The WaveSpeed key returns 401; the hosted n8n webhook is retired; OpenRouter's balance is
negative; `grok_automa` requires a human driving a browser; `kie_ai` is the only pinned working
cloud animator. Only Kokoro TTS runs offline end-to-end. Tests marked `@pytest.mark.live` skip
unless `STS_LIVE=1`. Every Phase 11–15 contract test must therefore be fixture-backed.
Owner: 10.4.

### 17.5 Test coverage baseline for the migrated surface

`tests/test_workflow_adapters.py` covers the TTS adapter port mapping and both async adapters'
typed outputs and failure codes with mocked services. `tests/test_scene_generation_v2.py`
covers blueprint planning and annotation. `tests/test_story_routes.py` covers only
classify-webhook derivation — **story generation itself has no test**.
`tests/test_live_providers.py` is live-gated. No test invokes any ABC method. Frontend tests do
not freeze the provider-specific branches P35-P47 or the legacy-selection mappings.
Owner: 11.4 (contract tests), 13.2 (story fixtures).

### 17.6 Divergences from `modular-providers-plan-v4.md`

| v4 said | this plan | resolution |
|---|---|---|
| three domains (`tts`, `storyboard`, `animator`) | five (`+script`, `+scene_blueprint`) | five; the domain catalog becomes data (11.1) |
| "temporary flat↔nested settings adapter, deleted in Phase 9" | no such adapter exists in the tree | dropped; `settings_adapter.py` is absent from `providers_common/` |
| "Discovery: on restart only. No hot reload." | dev hot-reload required (11.2) | 11.2 wins, guarded by `STS_WORKFLOW_DEV_RELOAD` |
| "Pipeline stops knowing provider names" | it still knows them (P5–P11) | unmet goal, now owned by 14.x / 15.x |
| `docs/provider-template/` scaffolds | absent; `providers_common/scaffold.py` (341 lines) exists instead | keep `scaffold.py`; 16.2 owns the kit |
| idle-shutdown deferred to Phase 9 | not in this plan | out of scope |

v4's vocabulary is otherwise adopted unchanged: *manifest*, *capabilities*, *runtime hook*,
*broken-provider isolation*, and *rich job snapshots* (already implemented as `job_meta` in
`services.py`), plus *per-domain provider folders*.

### 17.7 Out of scope — Music and Captions (confirmed working, not migrated)

Neither has a `providers/` package, a provider ID, or any dispatch branch. Music is
`studio/music/selector.py` (`select_music`, `select_random_music`, `recall_last_music`) with a
10-entry history; Captions is `studio/captions/routes.py` (`_group_words_into_captions`,
`CAPTION_PRESETS`). Both are consumed by the `music.select` / `captions.generate` nodes and by
Assemble. They touch the provider platform at exactly two points, both of which must keep
resolving: the `caption_presets` and `story_tones` option sources (`options.py:53-61` and
`:24-26` — the latter reads `studio.music.selector.TONE_MUSIC_MAP`). No migration work;
regression-only.

## 18. Coverage assertion

Every path that reaches a model or provider was enumerated: five domains × {legacy HTTP route,
legacy pipeline step, workflow adapter}, plus the WebSocket transports, the internal
HTTP-to-self hop, the preflight probe, the provider settings/health API, and the legacy frontend
pages/settings consumers. The four
never-provider-driven surfaces (frontend story templates, scene blueprint, music, captions) are
explicitly accounted for. The unexecuted provider path groups (§16) and forty-seven hardcoded
provider-decision entries (§15) each carry an owner step. No item in §13–§17 is left without
an owner.

Open decisions deliberately deferred: the authoritative selection store (recommendation in
§14.2 → **now frozen in §24**), the parameterized option-source envelope (§15.1 → **now frozen
in §23**), the unified job/result/error contract (§14.6 → 10.3), and fixture ownership
(§17.4 → 10.4).

---

# Provider Contract v2 (Phase 10.2 frozen)

> Produced by step 10.2 of [implementation-plan.md](implementation-plan.md).
> Grounded in code at commit `e79ac1c` (2026-08-08); §13–§18 above is the audit this
> contract is built on. Every `file:line` reference was read at that commit.
>
> **Reuse rule.** This contract *extends* the shipped
> `studio/shared/providers_common/` (registry, manifest, settings manager, discovery,
> migrations, runtime hooks, broken-provider isolation). Nothing here authorizes a parallel
> framework. Where v2 differs from today's code the delta is stated with an owner step, so
> Phase 11 is a set of edits to existing modules, never a rewrite.
>
> **What 10.2 does not freeze.** Invocation context, request/result envelopes, job handles,
> and `ProviderError` belong to 10.3. Legacy field/alias mapping tables and fixtures belong
> to 10.4. This section stops at *what a provider is, how it is found, how it is configured,
> and what the browser may see*.

## 19. Domains, packages, identity

### 19.1 Domain catalog — data, not code

Exactly **five** domains are supported. Music and Captions are excluded by owner decision
(§17.7) and have no `DomainSpec`.

| domain id | label | provider package | discovery base | default provider | legacy selection key |
|---|---|---|---|---|---|
| `script` | Script / Story | `studio.story.providers` | `studio/story/providers` | `builtin` (12.3 bridge) | *(none)* |
| `scene_blueprint` | Scene Blueprint | `studio.build_scene_blueprints.providers` | `studio/build_scene_blueprints/providers` | `builtin` (12.3 bridge) | *(none)* |
| `tts` | Text to Speech | `studio.tts.providers` | `studio/tts/providers` | `kokoro` | `sts-tts-provider` |
| `storyboard` | Storyboard | `studio.storyboard.providers` | `studio/storyboard/providers` | `gemini_ws` | `sts-storyboard-provider` |
| `animator` | Animator | `studio.animator.providers` | `studio/animator/providers` | `grok_automa` | `sts-asset-provider` |

The catalog lives in **one** new module, `studio/shared/providers_common/domains.py`,
exporting `DOMAINS: dict[str, DomainSpec]` in the declaration order above.

```python
@dataclass(frozen=True)
class DomainSpec:
    id: str                      # catalog key; also settings.json domains.<id>
    label: str                   # human label for the provider modal
    package: str                 # dotted import path of the provider package
    providers_base: str          # absolute path, built with os.path.join(ROOT_DIR, ...)
    default_provider: str        # last-resort selection; must exist after discovery
    capability_vocabulary: frozenset[str]   # §20.4
    legacy_selection_key: str | None        # app-config.json key being retired (§24)
    request_model: str | None = None        # dotted path — filled by 10.3
    result_model: str | None = None         # dotted path — filled by 10.3
```

Adding a sixth domain is one `DomainSpec` entry plus a provider folder. It must not require
editing the registry class, the settings manager, a route, or a Vue component.

The two `builtin` defaults are intentional sequencing. The hub can register an empty domain in
11.1, but `default_provider` is required to resolve once that domain becomes executable; 12.3
creates both passthroughs before converting either node. Phase 13 may rename/split a bridge and
update its `DomainSpec` default as a data change with a settings/workflow migration. In
particular, `random_template` cannot be the initial Script default: it does not exist until
13.1, and 13.3 requires absent configurations to retain the historical AI generator default.

**This catalog replaces both hardcoded three-domain sets.** `ProviderRegistry.VALID_DOMAINS`
(`registry.py:177`, P29) becomes `frozenset(DOMAINS)`; the duplicate `valid_domains`
in `settings_manager.validate_settings` (`settings_manager.py:270`, P30) reads the same
constant; `_default_settings()` (`settings_manager.py:137-160`, P31) is generated by
iterating `DOMAINS` instead of listing three literals. Owner: **11.1**, in one step, so the
two can never drift again. A test must assert all three derive from `DOMAINS` and that
`settings.json` accepts every catalog domain.

### 19.2 Package layout (frozen)

```
studio/<module>/providers/
  __init__.py            one shared binding (§27) — not a per-domain copy
  <provider_id>/
    manifest.py          REQUIRED — def manifest() -> ProviderManifest
    provider.py          optional — factory + validate_settings + health_check + impl
    settings_schema.py   optional — def settings_schema() -> dict
    __init__.py          optional; MUST NOT be required for discovery
```

Discovery keys on `manifest.py` only (`registry.py:246-249`); folders starting with `_` or
`.` are skipped (`registry.py:243`). Modules are loaded from file paths under synthetic names
`_sts_provider_{domain}_{id}_{manifest|provider|schema}` (`registry.py:273`), which is why
blocker **B8** stands: consumers resolve providers with `registry.get(id)` and never `import`
a provider module. `kie_ai/__init__.py` re-exporting `get_provider` (§14.1) is the one
existing violation and is deleted by 14.3.

Provider folders stay owned by their module. One hub (§27) exposes all domain registries;
it does not move the folders.

### 19.3 Provider identity and versions (frozen)

| field | rule |
|---|---|
| `id` | `^[a-z][a-z0-9_]{0,31}$`; **must equal the folder name** (already enforced, `registry.py:320-323`); unique within its domain. The registry key is the pair `(domain, id)` — the same id may exist in two domains. |
| `aliases` | **new, optional** `list[str]`, each matching `^[a-z][a-z0-9_-]{0,63}$`. Hyphen is deliberately allowed here (but not in canonical ids) because `kie-ai` is a shipped legacy wire value. Legacy wire strings (`gemini`, `webhook`, `direct`, `grok`, `kie-ai`, `midjourney`) move here, retiring the hand-written tables at `pipeline/services.py:550`/`:644` and `animator/schemas.py:30-36` (P7, P8, P34). Resolution order: exact `id` first, then alias. A real id always wins over an alias. If two providers claim the same alias, discovery order wins; the later alias is dropped and both collisions produce provider `warnings`, not `excluded[]` entries because neither provider was excluded. Aliases are never written to settings and never returned as `selected`. The concrete mapping table is 10.4's deliverable; 10.2 freezes only the mechanism. |
| `version` | semver `MAJOR.MINOR.PATCH`, the *implementation* version. Informational: it is never used to gate compatibility, and it is carried into result provenance (10.3). |
| `contract_version` | **new, optional** `int`, default `1` for backward compatibility. `1` = the legacy ABC shape (all seven providers today; never executed, §14.1/§16); every migrated/new v2 manifest must write `contract_version=2` explicitly. The registry loads both; only `2` may be invoked through the 10.3 invocation contract. It must be a positive integer (not `bool`); an unsupported positive version is `MANIFEST_UNSUPPORTED_CONTRACT`, while an invalid type/value is `MANIFEST_FIELDS_INVALID`. |
| `domain` | must equal the owning registry's domain or registration is refused (`registry.py:196-199`). |

Provider IDs in node configurations and `settings.json` are **canonical ids only**; legacy
strings are accepted on input and normalized through the alias table (§8, "registry ids are
canonical").

## 20. Manifest contract

### 20.1 Fields

`ProviderManifest` (`registry.py:17-27`) is the frozen carrier. Required and optional fields:

| field | required | type | default | notes |
|---|---|---|---|---|
| `id` | yes | str | — | §19.3 |
| `label` | yes | str | — | shown in the provider modal and every dropdown |
| `domain` | yes | str | — | must be a `DOMAINS` key |
| `kind` | yes | enum | — | `local` \| `cloud` \| `extension` \| `webhook` (§20.2) |
| `version` | yes | str | — | semver |
| `capabilities` | yes | `dict[str,bool]` | — | may be empty; missing capability keys mean `False` (§20.4). The current truthiness check at `registry.py:314-318` must become a presence/type check (owner 11.2). |
| `requires` | no | `list[str]` | `[]` | settings **key names** that must be non-empty for the provider to be usable (§21.5). Never values. |
| `open_url` | no | `str \| None` | `None` | URL the UI may offer to open for `extension` providers |
| `aliases` | no | `list[str]` | `[]` | new (§19.3); owner 11.2 |
| `contract_version` | no | `int` | `1` | new (§19.3); v2 manifests write `2` explicitly; owner 11.2 |
| `description` | no | `str \| None` | `None` | new; one sentence, browser-safe |
| `docs_url` | no | `str \| None` | `None` | new; must be `http(s)` |
| `environment` | no | `dict[str,str]` | `{}` | new; setting key → environment-variable name for read-time fallback (§22.6); never serialized |

`label` is 1–80 characters and `description` is at most 500 characters. `open_url` and
`docs_url` are at most 2048 characters and must be absolute `https` URLs (`http` is permitted
only for loopback development URLs). This validation happens before either value reaches the
browser, preventing a discovered manifest from supplying a `javascript:`/`data:` URL to
`window.open`. `environment` values must match `^[A-Z][A-Z0-9_]{0,127}$`; its keys must be
settings-schema property names. Environment-variable **names** are internal metadata, not part
of the public settings schema or provider payload.

### 20.2 `kind` semantics (frozen)

- `local` — runs in-process, no network (today: `kokoro`). May own heavy singletons; must
  implement `shutdown()`.
- `cloud` — outbound HTTPS to a third-party API with credentials in settings (today:
  `inworld`, `wavespeed_direct`, `kie_ai`).
- `webhook` — outbound HTTP to a user-supplied URL, validated by `is_safe_webhook_url`
  (today `wavespeed_webhook` is declared `cloud`; 14.2 reclassifies it).
- `extension` — needs a browser extension and a WebSocket runtime; the **only** kind whose
  `register_runtime(app, sock)` is called at boot (`<domain>/providers/__init__.py:47-52`)
  (today: `gemini_ws`, `grok_automa`). The two WS URLs are frozen public surface (§17.1).

### 20.3 Validation and unknown-field policy (frozen)

Manifest validation runs at discovery, in this order — each failure excludes only that
provider (§21.4):

1. `manifest.py` imports without raising.
2. A module-level `manifest` attribute exists and is callable.
3. `manifest()` returns a `ProviderManifest` **or** a dict coercible to one.
4. All required fields of §20.1 are present; required strings are non-empty. An empty
   `capabilities` dict is valid.
5. `manifest.id == folder name`.
6. `manifest.domain` is a `DOMAINS` key and matches the owning registry.
7. Identity and field shapes satisfy §19.3 and §20.1; `kind` is in the §20.2 enum;
   `version` parses as semver; `capabilities` values are `bool`; URLs and environment mappings
   pass their validation rules.
8. `contract_version` is supported by the build.

**Unknown fields — the one behavioral change here.** Today `ProviderManifest(**dict)` raises
`TypeError` on any unrecognized key and the provider is excluded (`registry.py:304-309`), so a
provider folder written against a newer build cannot load on an older one. Frozen v2 policy:
unknown top-level manifest keys are **ignored, logged WARN once, and surfaced** in the
provider's browser payload as `warnings: ["unknown manifest field: <name>"]`. Unknown
*capability* keys follow the same ignore-and-warn rule. An unknown `kind` is a hard
`MANIFEST_FIELDS_INVALID` failure: silently treating a future lifecycle/security class as
`cloud` could execute it with the wrong isolation or runtime hooks. Invalid known-field values
and unsupported contract versions also remain hard failures. Owner: **11.2**.

### 20.4 Capability vocabulary (frozen)

Capabilities are declarative booleans the platform and UI may branch on **generically** — they
are the replacement for branching on a provider id. Values must be `bool`; a missing key means
`False`. Each domain's `DomainSpec.capability_vocabulary` is the closed set for that domain;
unknown keys are ignored and warned (§20.3).

Shared by all five domains:

| capability | meaning | in use today |
|---|---|---|
| `test_connection` | `health_check` performs a real probe worth exposing as a button | all seven |
| `single_scene` | can produce one unit in isolation (one scene, one take) | all seven |
| `batch` | can accept a multi-unit request | all seven |
| `async_job` | returns a job handle and is polled rather than returning inline | storyboard + animator providers (implicit today) |
| `push_callbacks` | pushes progress over an existing transport instead of being polled | `gemini_ws` |
| `cancel` | honors the cancellation token | none yet (10.3 defines the token) |
| `progress` | reports fractional progress, not just terminal states | none yet |

Domain-specific additions:

| domain | capabilities |
|---|---|
| `script` | `structured_sections` (returns hook/build/climax/cta), `language_select`, `offline` (no network — the `random_template` provider from 13.1) |
| `scene_blueprint` | `chaptering` (can split oversized inputs, cf. `chapters.py:31-34`), `coherence_scoring`, `sfx_report` |
| `tts` | `streaming`, `voice_list`, `voice_blend`, `speed_control`, `model_download` |
| `storyboard` | `image_edit`, `watermark_removal`, `prompt_prefix` |
| `animator` | `image_to_video`, `duration_control`, `resolution_select` |

`streaming`, `voice_list`, and `model_download` are already declared by the shipped TTS
manifests; the rest are frozen names for capabilities that exist in the legacy code as
provider-id branches (P5–P25) and become declarative during Phases 14–15.

## 21. Lifecycle, discovery, and isolation

### 21.1 Lifecycle hooks (frozen)

| phase | hook | when | failure policy |
|---|---|---|---|
| discover | *(none — filesystem scan)* | once per process, or on dev reload under `STS_WORKFLOW_DEV_RELOAD` | per-provider exclusion |
| describe | `manifest()` | discovery | exclusion |
| describe | `settings_schema()` | lazy, first request, memoized (`registry.py:107-117`) | returns `None`, WARN; provider still listed with `has_settings: false` |
| configure | `validate_settings(settings) -> list[dict]` | on save, on select, on demand | exception → one redacted root `error` issue; raw exception is internal only |
| probe | `health_check(settings) -> dict \| str \| HealthResult` | explicit user action or TTL cache (§21.5) | exception → `HealthResult(status="fail", message="Health check failed")`; raw exception is logged only after redaction |
| construct | **`create() -> Provider`** (new v2 factory) | lazily, at first invocation | exception → `ProviderError` at the registry boundary (10.3); provider marked `degraded` |
| serve | domain-specific invocation | per request | 10.3 |
| bind | `register_runtime(app, sock)` | once at boot, `kind == "extension"` only | caught and logged (`runtime.py:63-65`); boot continues |
| release | `shutdown()` | registry teardown, dev reload, process exit | best-effort; exceptions logged, never raised; **must be idempotent** |

The v2 factory replaces the eight zero-argument `get_provider()` functions, none of which has
ever executed (§14.1, §16). Frozen rules: `create()` is called **at most once per
`(domain, provider_id)` per process**, through a per-provider construction lock, never at
import time, and never during discovery — so importing a provider package can never start a
model load, a thread, or a socket. Provider code is not called while the hub-wide registry
lock is held. The invocation context frozen by 10.3 is passed to each domain invocation, **not
to the memoized factory**; retaining the first request's project/output/cancellation context
inside a process-wide provider would cross-contaminate later executions. Owner: **11.2**.

`shutdown()` today exists on `Runtime` (`runtime.py:45-47`) and on `TTSProvider` with **zero
callers**. v2 requires the registry to call it for every constructed provider on teardown, in
reverse construction order. Owner: **11.2**.

### 21.2 Registration and discovery order (frozen)

1. Domains initialize in `DOMAINS` declaration order: `script`, `scene_blueprint`, `tts`,
   `storyboard`, `animator` — replacing the fixed three-call sequence at `app.py:90-95`.
2. Within a domain, providers are loaded in **`sorted()` order of folder name**. Today
   `os.listdir` order is used unsorted (`registry.py:239`); sorting is required so discovery
   logs, catalog responses, and "first wins" duplicate resolution are deterministic.
   Owner: **11.1**.
3. Discovery is idempotent — a second `discover()` on a registry that already scanned is a
   no-op (`<domain>/providers/__init__.py:20-23`). Dev reload explicitly resets the flag after
   calling `shutdown()` on constructed providers.
4. Extension runtimes bind after **all** domains have been discovered, never interleaved with
   discovery, so a runtime can rely on the full catalog being present.
5. Registration never touches `app.py` or `studio/workflows/registry.py`.
6. Discovery and dev reload build a private catalog snapshot and publish it with one atomic
   swap. Concurrent requests see either the complete old snapshot or the complete new one,
   never a partially discovered catalog. Providers removed by the swap are shut down only
   after new lookups can no longer acquire them and all pre-swap invocation leases have
   drained; teardown must not close a provider still serving an old-snapshot request.

### 21.3 Duplicate IDs (frozen)

Within a domain, **first registration wins**; the later one is skipped with a WARN
(`registry.py:202-205`, already correct) and recorded as an exclusion with reason
`DUPLICATE_ID`. Cross-domain duplicates are legal (the key is `(domain, id)`). An alias that
duplicates any real id in the same domain is dropped, not the provider. Duplicate registration
must never raise, must never replace the incumbent, and must never abort discovery.

### 21.4 Broken-plugin isolation (frozen)

Every exclusion is *local*: it logs a WARN and continues. A broken provider must never
(a) abort discovery, (b) abort application startup, (c) hide or unregister a healthy provider,
or (d) leak a stack trace or filesystem path into an API response.

Frozen exclusion reason codes; the corresponding current failure paths are bare log lines
(`registry.py:278-323`):

| code | condition | current line |
|---|---|---|
| `MANIFEST_LOAD_FAILED` | spec/loader is `None`, `SyntaxError`, `ImportError`, or any other exception importing `manifest.py` | `:278`, `:284`, `:287`, `:290` |
| `MANIFEST_MISSING` | no `manifest` attribute | `:294` |
| `MANIFEST_RAISED` | `manifest()` raised | `:300` |
| `MANIFEST_INVALID_TYPE` | not a `ProviderManifest` and not a coercible dict | `:308`, `:311` |
| `MANIFEST_FIELDS_MISSING` | a required field is absent or falsy | `:317` |
| `MANIFEST_ID_MISMATCH` | `manifest.id != folder` | `:321` |
| `MANIFEST_DOMAIN_MISMATCH` | wrong domain | `:197` |
| `MANIFEST_FIELDS_INVALID` | invalid id/alias/kind/version/capability/URL/environment field value | new (§19.3, §20.1, §20.3) |
| `MANIFEST_UNSUPPORTED_CONTRACT` | `contract_version` too new | new (§19.3) |
| `DUPLICATE_ID` | id already registered | `:203` |

**Exclusions become data, not just logs.** `ProviderRegistry.excluded() -> [{id, reason_code,
message}]` is new and is surfaced in `to_dict()` so the provider modal can show "3 providers
loaded, 1 excluded" instead of the current silent disappearance. `message` is truncated to
200 characters, stripped to a basename if it contains a path, and passed through
structured redaction plus a generic exception sanitizer; `redact_settings` alone cannot remove
a secret embedded in an arbitrary exception string. Owner: **11.2**.

**Partial degradation.** `provider.py` is optional because callables may live in `manifest.py`
and `_resolve` already falls back across modules (`registry.py:73-81`). Its absence is not by
itself degradation. If a present `provider.py` fails to load, a warning is recorded; the
provider is `degraded` only when the v2 `create` callable can no longer be resolved. A present
`settings_schema.py` that fails to load is degraded, while an intentionally absent schema is
valid and yields `has_settings: false`. A degraded provider may be listed and configured but
must not be constructed or invoked.

### 21.5 Availability vs health (frozen)

Two orthogonal axes. Conflating them is the current bug source: `useProviders.selectProvider`
runs a *validation* call to decide whether a provider "needs configuration"
(`useProviders.js:71`), while the catalog exposes no state at all.

**Availability** — cheap, synchronous, no network, safe to compute on every catalog request:

| state | meaning |
|---|---|
| `available` | registered, its v2 `create` callable resolves, every `requires` key is non-empty after env fallback, and its settings schema is absent or loaded successfully |
| `needs_configuration` | registered and constructable, but a `requires` key is empty after env fallback |
| `degraded` | registered, but required construction callables cannot resolve, a present settings schema failed to load, or `create()` previously raised |
| `unavailable` | discovered but excluded (§21.4); present only in the `excluded[]` list |

**Health** — may perform I/O; runs on explicit user action (`POST /api/providers/<d>/<p>/test`)
or from a TTL cache. Frozen states are exactly today's values: `ok`, `warn`, `fail`, `unknown`
— the first three are what the seven shipped `health_check` bodies return
(`kokoro/provider.py:295-300`, `inworld/provider.py:195-210`, `gemini_ws/provider.py:80`,
`wavespeed_webhook/provider.py:91-102`, `wavespeed_direct/provider.py:90-92`,
`grok_automa/provider.py:97`, `kie_ai/provider.py:227-240`), and `unknown` is the registry's
coercion default (`registry.py:146`). `HealthResult` fields stay
`status, latency_ms, message, details` (`registry.py:30-36`); `details` is passed through
redaction before it leaves the process.

Two frozen corrections: a provider with **no** `health_check` returns `unknown`, not the
current `ok` (`registry.py:157`) — no live provider hits that branch today, since all seven
define the hook, so this is safe. And health **never blocks** selection or execution: a `fail`
provider may still be selected, with the failure surfaced as a warning. Owner: **11.3**.

"Configured" is computed from `requires` after env fallback, never from key presence: the
live `settings.json` stores present-but-empty `api_key` values for `kie_ai`,
`wavespeed_direct`, and `inworld` (§14.3).

## 22. Settings contract

### 22.1 Schema shape

`settings_schema()` returns a JSON-Schema subset object — `{"type": "object", "properties":
{...}, "required": [...]}` — exactly the shape shipped today
(`tts/providers/inworld/settings_schema.py`). Per-property keys: `type`
(`string|number|integer|boolean`), `label`, `description`, `default`, `minimum`, `maximum`,
`multipleOf`, `enum`, and `ui`.

### 22.2 Widget vocabulary (frozen)

| `ui.type` | rendered today | source |
|---|---|---|
| *(absent)* | text input (or number input when `type` is numeric) | fallback |
| `password` | masked input, marked required | `ProviderSettingsForm.vue:30,138` |
| `dropdown` / `select` | select from `ui.options` (strings or `{value,label}`) | `:33-36,46-55` |
| `slider` | range using `minimum`/`maximum`/`multipleOf` | `:38-40,57-67` |
| `toggle` | checkbox | `:42-44` |
| `textarea` | **new** — multi-line text | owner 12.4 |

An unrecognized `ui.type` falls back to a text input and adds a warning; it is never an error.
This is the settings-form counterpart of §20.3.

### 22.3 Conditional fields (frozen)

`ui.show_if: {field_name: [allowed_values]}` — identical semantics to the workflow node
`display_options.show` already in the registry (`registry.py:263,288`): **AND** across keys,
**OR** within a list. Frozen behavior for a hidden field: its stored value is **preserved**,
it is **not** validated as required, and it is **not** sent in the invocation config. The
renderer is new work (owner **12.4**); the shape is frozen now because 15.2 needs it for
provider-specific TTS fields.

### 22.4 Dynamic options in provider settings (frozen)

`ui.options_source: {"source": "<allowlisted id>", "context": {...}}` resolves through the
same envelope as workflow node fields (§23). This is the mechanism that lets the Inworld voice
list appear in the provider modal without a Vue edit. `ui.options` and `ui.options_source` are
mutually exclusive; if both are present, `options_source` wins and a warning is recorded.

### 22.5 Validation, severities, and unknown keys (frozen)

`validate_settings(settings) -> list[dict]`, each `{field, severity, message}` with
`severity ∈ {error, warning, info}`; a raising implementation yields one
`{field: "root", severity: "error", message: "Settings validation failed"}`. The current
`message: str(e)` behavior (`registry.py:133-135`) is replaced because provider exceptions can
contain submitted secrets. The raw exception may be logged only through the shared redacted
logger. `error` blocks saving (`editor/routes.py:410-412`); `warning` and `info` never do.

Unknown keys in *saved* provider settings are **preserved and reported as a `warning`**, never
dropped. Today `put_provider_settings` merges anything with no check
(`editor/routes.py:400-401`); dropping would silently destroy configuration when a user rolls
back to an older provider version. Required-but-empty is an `error`; a hidden field (§22.3) is
exempt.

### 22.6 Secrets and environment (frozen)

A field is a secret if `ui.type == "password"` **or** its key matches `SENSITIVE_KEYS_RE`
(`api_key|token|secret|password|auth|bearer|credential`, `settings_manager.py:214-217`).

- Secrets are stored in `settings/settings.json` in plaintext (unchanged; the file is
  local-only). The contract governs **egress**, not at-rest encryption.
- Secrets must never appear in an API response, log line, error message, execution record, SSE
  frame, exported template, or archive. Every settings payload leaving the process passes
  through `redact_settings` / `redacted_provider_settings`.
- **Live defect recorded here, not fixed by 10.2:** `GET /api/settings/v2`
  (`editor/routes.py:211-212`) and `GET /api/providers/<domain>/<provider_id>/settings`
  (`editor/routes.py:360-366`) return **unredacted** provider settings, including `api_key`.
  `redacted_provider_settings` exists (`settings_manager.py:247-249`) with **zero call sites**
  outside `__all__`. Owner: **11.5**, which must also decide how the modal round-trips a
  redacted value without overwriting the real one (rule: a field whose submitted value is
  exactly the redaction sentinel `"***"` is ignored on save).
- **Env vars are a read-time fallback, never a seed for secrets.** The registry resolves a
  value as `settings[key] or os.environ[manifest.environment[key]]`, and passes the resolved
  settings only to provider validation/health/invocation. The resolved value is never
  written back to `settings.json` and never returned. This replaces copying values in
  `_seed_from_env` (`settings_manager.py:85-104`). Owner: **11.3**.
- **The `INWORLD_API_KEY` selection side effect is frozen as removed.** First-run seeding may
  populate values but must never write `selected_provider` (`settings_manager.py:88`, §14.3).
  Migration: existing installs keep whatever selection is already persisted — no rewrite, no
  reset. Owner: **11.3**.

## 23. Parameterized option sources (frozen)

Freezes §15.1. `GET /api/workflow/options/<source>` currently calls `resolve_options(source)`
with no context (`options.py:108`, `routes.py:196`), which is why `_tts_voices()` returns the
static Kokoro list regardless of engine (`options.py:19-21`) and why no `tts_providers` source
exists at all. 12.2 implements this; 15.2 depends on it.

### 23.1 Request

```
GET /api/workflow/options/<source>?domain=<d>&provider=<p>&node_type=<t>&project_id=<id>
```

The source stays **allowlisted** — `<source>` must be a key of `ASYNC_OPTION_SOURCES`; a
schema-supplied URL is still never fetched (§11). `ASYNC_OPTION_SOURCES`
(`registry.py:30-34`) changes from a list to a dict of specs. Every existing consumer uses
`set(...)` or `in` (`options.py:75`, `tests/test_workflow_options.py:60`,
`tests/test_workflow_registry.py:81`), so the parity assert and its test survive unchanged.

```python
ASYNC_OPTION_SOURCES = {
    "tts_voices": OptionSourceSpec(context=("domain", "provider"), cache="settings"),
    "tts_providers": OptionSourceSpec(context=(), cache="discovery"),      # new (P26)
    "storyboard_providers": OptionSourceSpec(context=(), cache="discovery"),
    "animator_providers": OptionSourceSpec(context=(), cache="discovery"),
    "script_providers": OptionSourceSpec(context=(), cache="discovery"),          # new
    "scene_blueprint_providers": OptionSourceSpec(context=(), cache="discovery"), # new
    "story_tones": OptionSourceSpec(context=(), cache="static"),
    "style_templates": OptionSourceSpec(context=(), cache="static"),
    "export_profiles": OptionSourceSpec(context=(), cache="static"),
    "caption_presets": OptionSourceSpec(context=(), cache="static"),
}
```

**Context validation is an allowlist too.** Only the parameter names in that source's
`context` tuple are accepted; any other query parameter is rejected with
`OPTION_CONTEXT_INVALID` (silently ignoring a misspelling can resolve options for the global
default provider). `domain` must be a
`DOMAINS` key; `provider` must resolve in that domain's registry (id or alias, normalized to
the canonical id before it reaches the resolver); `node_type` must be a registry node type;
`project_id` must survive `sanitize_project_id` unchanged. A declared parameter may be
omitted — the resolver then falls back to the domain's selected provider (§24), which is what
makes existing single-argument callers keep working.

The five per-domain `*_providers` sources make P26 and P32 disappear: the TTS node's `engine`
field stops being a static `["kokoro","inworld"]` list (`registry.py:186`) and
`_provider_options` stops hardcoding two domains (`options.py:38-50`).

### 23.2 Response

```json
{
  "source": "tts_voices",
  "context": {"domain": "tts", "provider": "inworld"},
  "options": [{"value": "Ashley", "label": "Ashley", "group": null, "disabled": false}],
  "generated_at": "2026-08-08T00:00:00Z"
}
```

`context` echoes the **validated, normalized** context so the client can key its cache on the
server's interpretation rather than on its own query string. `group` and `disabled` are
optional and default to `null`/`false`; `{value, label}` remains the minimum, so today's
`_opt()` helper (`options.py:15-16`) is unchanged and the existing client
(`useOptionSources.js:14`, reads `data.options`) keeps working without edits.

### 23.3 Failure semantics (frozen)

| condition | HTTP | code |
|---|---|---|
| unknown `<source>` | 404 | `NOT_FOUND` (unchanged, `routes.py:200`) |
| context parameter invalid, unknown domain/provider, or fails sanitization | 400 | `OPTION_CONTEXT_INVALID` |
| resolver raised — provider unreachable, model missing, extension offline | 503 | `PROVIDER_UNAVAILABLE` (unchanged, `routes.py:198`) |

`OPTION_CONTEXT_INVALID` is the only addition to the stable error-code list in §7; it is
additive and no existing code changes meaning. The 503 body carries a redacted message and
never the provider's raw exception.

**Save-time validation still fails open.** `allowed_option_values` (`options.py:85-105`)
becomes context-aware but keeps its contract from step 6.3: a bad value is rejected, an
unavailable resolver returns `None` and never blocks saving an otherwise-valid workflow. A
context-sensitive value is checked against the canonical provider saved in that same node
configuration (or the selected provider only when the node has no provider field). It is not
validated against a union across providers: that would accept an Inworld-only voice for a
Kokoro node and defer a deterministic configuration error until execution. Existing workflows
remain stable because their saved provider wins over the global selection (§24.1).

### 23.4 Caching and invalidation (frozen)

The current process-lifetime cache keyed by source alone (`_VALUE_CACHE`, `options.py:82`) is
wrong once options depend on settings. Frozen replacement:

- Cache key: `(source, tuple(sorted(normalized_context.items())))`.
- `cache="static"` — process lifetime, as today.
- `cache="discovery"` — invalidated on discovery and on dev reload.
- `cache="settings"` — TTL 300 s **and** explicitly invalidated on
  `PUT /api/providers/<domain>/<provider_id>/settings` and on a selection change (§24.2), for
  that domain only. Changing an API key must make the voice list refetch.
- Bounded: at most 64 entries per source, LRU eviction, so context parameters cannot grow the
  cache without limit.
- The browser cache in `useOptionSources.js` keys on the full request URL rather than the bare
  source string; `clearOptionSourceCache()` stays the test hook.

## 24. Authoritative selection store (frozen)

Freezes §14.2. `settings/settings.json` → `domains.<domain>.selected_provider` is the
**single authority** for every domain. The `app-config.json` keys `sts-tts-provider`,
`sts-storyboard-provider`, and `sts-asset-provider` (`useSettings.js:12-14`) are the losers and
are retired.

### 24.1 Precedence chain (frozen, all five domains)

1. An explicit provider field on the request (`provider_override`, `provider_id`, `engine`).
2. For workflow execution: the node's **saved** `configuration` value.
3. `settings.json` `domains.<domain>.selected_provider`.
4. `DomainSpec.default_provider`.

Environment variables never appear in this chain (§22.6). Rule 2 is load-bearing: switching
the global selection must **not** change how an existing saved workflow runs (§17.1, "old
workflows must run unedited"). Rule 3 is what `animation_routes.py:194` fails to do today —
its comment claims it reads the animator selection and it does not, so selecting an animator
in the modal changes nothing. Wiring that read is a precondition for calling this store
authoritative. Owner: **14.3**.

### 24.2 Write path (frozen)

The whole-blob read-modify-write in `useProviders.js:73-84` (`GET /api/settings/v2` → spread →
`PUT` the entire document, a genuine lost-update window since `put_settings_v2` calls
`save_settings` with no concurrency check, `editor/routes.py:215-227`) is replaced by:

```
PUT /api/providers/<domain>/selection      body: {"provider_id": "inworld"}
→ 200 {"domain", "selected", "availability", "issues": [...]}
```

The handler validates the domain against `DOMAINS`, resolves `provider_id` through id-then-
alias, returns 409 when the id is present in that domain's `excluded[]` catalog and 404 when it
was not discovered at all, and calls
`settings_manager.set_selected_provider()` (`settings_manager.py:189-198`) — which finally
gains its first call site (§14.2). It then invalidates the `cache="settings"` option entries
for that domain (§23.4). A `needs_configuration` or `fail`-health provider **may** be selected;
the response carries the issues so the modal can prompt (matching today's non-blocking
behavior at `useProviders.js:71-95`).

`PUT /api/settings/v2` remains for import/reset of the whole document and must no longer be
used to change a selection. `PATCH /api/settings/v2` is added for field-level deep merge of
everything else. Owner: **11.5**.

### 24.3 Migration of the three legacy keys (frozen)

One-time, on first load after upgrade, per domain, for each of the three keys. The migration
reads `app-config.json.user[legacy_selection_key]` (the shape served by `/api/settings`), not a
top-level key:

1. If `settings.json` has no explicit `selected_provider` for the domain **and**
   `app-config.json.user` holds the legacy key, adopt the legacy value, normalized through the
   alias table (`gemini→gemini_ws`, `grok→grok_automa`, `kie-ai→kie_ai`), and write it once.
2. Otherwise `settings.json` wins; the legacy key is ignored from that moment on.
3. Legacy pages read the selection from `GET /api/providers` instead of `useSettings`, keeping
   a read-through fallback to the legacy key for one release (owner **12.4**).
4. The three keys are deleted from `app-config.json` and from `useSettings.DEFAULTS` (owner
   **16.1**).

Today's values agree semantically (`inworld`, `gemini↔gemini_ws`, `grok↔grok_automa`), so this
migration is a no-op on the current machine — but it must still run, because the two stores can
diverge on the next write.

The migration is a new settings-version step and writes an explicit completion marker/version
atomically with the adopted values. The current `apply_migrations` loop
(`settings_migrations.py:39-45`) skips every registered version greater than or equal to the
stored version, so it cannot run an upgrade migration as written; **11.3 must correct the
sequencing and cover v1→v2, already-v2 idempotence, and a simulated interrupted write**. Reading
the legacy file is injected into the migration/load boundary rather than importing the editor
route's private `_read_app_config` helper.

## 25. Frontend-safe serialization (frozen)

Exactly these provider-instance fields may cross to the browser. The public settings-schema
subset in §22 and the option-source response in §23.2 are the other two provider-contract
payloads; neither may contain settings values or the manifest's internal `environment` map.

`ProviderInstance.to_dict()` v2 — extends the eight fields at `registry.py:159-171`:

```json
{
  "id": "inworld", "label": "Inworld", "domain": "tts", "kind": "cloud",
  "version": "1.0.0", "contract_version": 2, "aliases": [],
  "requires": ["api_key"], "capabilities": {"streaming": false},
  "open_url": null, "docs_url": null, "description": null,
  "has_settings": true, "availability": "needs_configuration", "warnings": []
}
```

`ProviderRegistry.to_dict()` v2 — extends `registry.py:350-357`:

```json
{"domain": "tts", "providers": [...], "selected": "kokoro", "count": 2,
 "excluded": [{"id": "broken", "reason_code": "MANIFEST_RAISED", "message": "..."}]}
```

`requires` carries settings **key names only** — never values, which is what makes it safe to
ship while the values themselves are secrets.

**Never serialized to the browser, under any route:** settings values for secret fields
(§22.6), absolute or relative filesystem paths, module objects or synthetic module names
(`_sts_provider_*`), stack traces, raw provider exception text, environment variable values,
raw third-party API responses, and the `provider_module` / `schema_module` handles. Exclusion
`message` strings are truncated to 200 characters and path-stripped to a basename before they
enter `excluded[]`.

## 26. Zero-touch assertion

Adding a provider to an existing domain must require creating exactly one folder —
`studio/<module>/providers/<id>/` with `manifest.py` and optionally `provider.py` and
`settings_schema.py` — and editing **nothing** else. Specifically it must not require an edit
to:

| surface | why it is satisfied | owner of the remaining gap |
|---|---|---|
| `app.py` | domains initialize from `DOMAINS` through the hub (§27) | 11.1 |
| `studio/workflows/registry.py` | provider dropdowns use `options_source: "<domain>_providers"` (§23.1); the static `engine` list is replaced | 12.3 / 15.2 |
| `studio/workflows/options.py` | `_provider_options(domain)` becomes catalog-driven instead of a two-branch `if` (P32) | 12.2 |
| any route dispatcher | dispatch is `registry.get(id)` + the 10.3 invocation contract, not `if provider_id == …` (P5–P25) | 14.2 / 14.3 / 15.2 |
| any Vue component | the provider modal renders from `settings_schema()` (§22.2) and the node inspector from `config_schema` | 12.4 |
| `settings_manager._default_settings` | generated from `DOMAINS` (P31) | 11.1 |

**The one genuine obstacle, frozen.** Provider-specific *node* fields gated by
`display_options.show.provider: ["gemini_ws"]` / `["grok_automa"]` (`registry.py:263,288-294`,
P27) mean a new storyboard or animator provider today needs a workflow-registry edit to expose
its own options. Frozen resolution: a node's `config_schema` keeps only **provider-agnostic**
fields; every provider-specific field moves into that provider's `settings_schema()` and is
rendered by the inspector as a per-provider sub-form resolved from the node's selected
provider. The existing gated fields keep their current config keys so saved workflows load
unchanged. Owner: **12.3**.

## 27. Registry hub (shape only — 11.1 owns the implementation)

One process-wide hub resolves `(domain, provider_id)` across all five domains and replaces the
five handlers in `editor/routes.py` that each re-import three registries and build a literal
`{tts, storyboard, animator}` dict (`:236-238, 260-262, 305-307, 342-344, 397-399`, P28).
Frozen surface: `hub.domains()`, `hub.registry(domain)`, `hub.get(domain, provider_id)`
(id-then-alias), `hub.list(domain)`, `hub.catalog()`, `hub.shutdown()`. The existing per-module
`registry`, `get_provider`, and `list_providers` imports remain as compatibility facades
(§17.1). The three 57-line `studio/<domain>/providers/__init__.py` copies (§14.6 — three, not
four) collapse into one shared binding parameterized by `DomainSpec`.

## 28. Deltas this contract requires of shipped code

Nothing in §19–§27 is implemented yet. Every delta, with its owner:

| # | delta | current state | owner |
|---|---|---|---|
| D1 | `domains.py` catalog; `VALID_DOMAINS`, `validate_settings`, `_default_settings` derive from it | three hardcoded sets (P29, P30, P31) | 11.1 |
| D2 | sorted discovery order | `os.listdir` order (`registry.py:239`) | 11.1 |
| D3 | one shared `providers/__init__.py` binding | three near-identical copies (§14.6) | 11.1 |
| D4 | registry hub replacing the five literal domain dicts | P28 | 11.1 / 11.5 |
| D5 | `aliases` + `contract_version` in the manifest | hand-written alias tables (P7, P8, P34) | 11.2 |
| D6 | unknown manifest/capability fields ignored + warned | `TypeError` → exclusion (`registry.py:304-309`) | 11.2 |
| D7 | `excluded()` recorded and serialized | WARN log only | 11.2 |
| D8 | v2 zero-argument `create()` factory, memoized, plus real `shutdown()` calls | eight never-executed `get_provider()` factories; `shutdown` never called | 11.2 |
| D9 | `availability` computed and serialized | not present | 11.3 |
| D10 | missing `health_check` → `unknown` | returns `ok` (`registry.py:157`) | 11.3 |
| D11 | env as read-time fallback; no secret seeding; no selection flip | `_seed_from_env` copies values and flips TTS selection (`settings_manager.py:85-88`) | 11.3 |
| D12 | redaction on `GET /api/settings/v2` and `GET /api/providers/*/settings`; `"***"` sentinel ignored on save | both return raw `api_key`; `redacted_provider_settings` has zero call sites | 11.5 |
| D13 | `PUT /api/providers/<domain>/selection`; `PATCH /api/settings/v2` | whole-blob `PUT` from `useProviders.js:73-84` | 11.5 |
| D14 | legacy-key migration + read-through fallback + deletion | two independent stores (§14.2) | 12.4 / 16.1 |
| D15 | animator route reads `domains.animator.selected_provider` | never read (`animation_routes.py:194`) | 14.3 |
| D16 | `OptionSourceSpec` map, context validation, new `*_providers` sources, keyed cache | single-argument `resolve_options`; source-only cache | 12.2 |
| D17 | `OPTION_CONTEXT_INVALID` added to §7 | not present | 12.2 |
| D18 | `ui.show_if`, `ui.options_source`, `textarea` in the settings form | none supported | 12.4 |
| D19 | provider-specific node fields move to provider settings schemas | `display_options.show.provider` gating (P27) | 12.3 |
| D20 | correct settings-migration sequencing and inject the legacy `app-config.json.user` values | current loop cannot advance v1; legacy reader is private to editor routes | 11.3 |
| D21 | atomically publish discovery/reload snapshots and drain old invocation leases before shutdown | current registry mutates its live dict during discovery | 11.2 |

## 29. Phase 10.2 coverage assertion

Frozen by this section: the five-domain catalog and its data shape; package layout; provider
id, alias, and version rules; every required and optional manifest field with its type and
default; the `kind` and capability vocabularies; manifest validation order and the
unknown-field policy; the full lifecycle from discovery through `create()` to `shutdown()`;
registration and atomic discovery order; duplicate-ID/alias resolution; the ten broken-plugin exclusion
reason codes and the isolation guarantees; settings-schema widgets, conditional fields, and
dynamic options; validation severities and the unknown-key policy; secret classification, the
redaction obligation, and env-fallback rules; the availability and health state machines; the
exact browser-safe serialization allowlist and its prohibitions; the parameterized
option-source envelope with its context allowlist, response shape, three failure codes, and
cache invalidation rules; and the authoritative selection store with its precedence chain,
replacement write path, and three-key migration.

Both hardcoded three-domain sets (P29, P30) are replaced by the catalog, and §26 shows that
adding a provider to an existing domain touches no workflow node, route dispatcher, or Vue
component — with the one real obstacle (P27) resolved rather than waved through. Deferred by
design: invocation context, request/result envelopes, job handles, and `ProviderError`
(10.3); alias mapping tables, legacy field compatibility, and fixtures (10.4).

---

# Provider Contract v2 — Invocation, Results, Jobs, Errors (Phase 10.3 frozen)

> Produced by step 10.3 of [implementation-plan.md](implementation-plan.md).
> Grounded in code at commit `57f7477` (2026-08-09). Every `file:line` reference below was
> read at that commit. §13–§18 is the audit; §19–§29 froze *what a provider is*; this section
> freezes *how it is called, what it returns, and how it fails*.
>
> **Implementation owner.** Step **11.4** implements every module named here
> (`providers_common`: invocation context, result envelope, artifact normalization, progress,
> job handle/status, cancellation/timeout helpers, and the single exception boundary). Domain
> request/result models are implemented with their domain migration (13.1–13.4, 14.2/14.3,
> 15.1/15.2). Nothing in §30–§38 exists in code today.
>
> **What 10.3 does not freeze.** The legacy field/alias mapping tables (`engine`,
> `provider_override`, `gemini→gemini_ws`, …), per-domain fixtures, and the node
> `type_version` migration plan belong to **10.4**. This section defines the target shapes;
> 10.4 defines how today's persisted values reach them.

## 30. Invocation context

### 30.1 `ProviderInvocation` (frozen)

One frozen dataclass, `studio/shared/providers_common/invocation.py:ProviderInvocation`,
passed to **every** domain invocation. It is constructed per call, never retained by a
provider, and never passed to the memoized `create()` factory (§21.1).

```python
@dataclass(frozen=True)
class ProviderInvocation:
    # identity
    domain: str                       # DOMAINS key (§19.1)
    provider_id: str                  # canonical id, aliases already resolved (§19.3)
    project_id: str                   # matches PROJECT_ID_RE (adapters/common.py:10)
    execution_id: str = ""            # "" for legacy-route calls outside a workflow run
    node_id: str = ""                 # "" for legacy-route calls
    attempt: int = 1                  # scheduler attempt number (scheduler.py:697)
    invocation_id: str = ""           # uuid4 hex; unique per call, used for job correlation
    # capabilities the caller grants
    output_dir: str = ""              # managed, per-invocation (§30.2)
    stage_artifact: Callable[[str], str] | None = None   # scheduler.py:707
    cancel: CancellationToken = ...   # §30.3 — never None
    progress: ProgressReporter = ...  # §30.4 — never None
    log: ProviderLogger = ...         # §30.5 — never None
    deadline_s: float | None = None   # §35.3; None means the domain default
    settings: Mapping[str, Any] = ... # resolved provider settings, env fallback applied (§22.6)
    options: Mapping[str, Any] = ...  # per-run, non-durable node/request options
```

Frozen rules:

- **`settings` vs `options`.** `settings` are the durable per-provider values from
  `settings/settings.json` with the env read-time fallback already resolved; they may contain
  secrets and must never be echoed into a result. `options` are the per-run values from the
  node's `provider_options` / request body and must never contain secrets. A provider reads
  both and writes neither. This split is what makes `job_meta.resolved_settings_redacted`
  (`pipeline/services.py:166`, `:272`) mechanical rather than per-provider hand-work.
- **No Flask, no `request`, no globals.** The context is the provider's only access to caller
  state. A provider that needs `STS_PORT`, `flask.request`, or `os.environ` is non-conforming
  (blockers B2 and B8).
- **`cancel`, `progress`, and `log` are never `None`.** Today every consumer must write
  `stop = context_value(context, "stop_requested"); if stop and stop():`
  (`adapters/storyboard.py:47-48`, `adapters/animator.py:57-58`). v2 supplies no-op
  implementations so a provider never guards. Owner: **11.4**.
- **`attempt` is informational.** Retry is the caller's decision (§35.2); a provider must not
  implement its own retry of a whole invocation on top of it.

### 30.2 Managed output directory and artifact rules (frozen)

`output_dir` is an absolute path allocated by the platform, always beneath `OUTPUT_DIR`,
always built with `safe_join` (§9). A provider may write **only** inside `output_dir` or to a
path returned by `stage_artifact()`. Any other write is a contract violation; `artifact_ref`
already refuses to reference one (`ARTIFACT_UNMANAGED`, `adapters/common.py:74-82`).

| rule | statement |
|---|---|
| allocation | `output_dir = safe_join(OUTPUT_DIR, <domain-owned relative dir>)`, created before the call. The domain owns the layout, and the existing layouts are preserved verbatim (`output/stories/{pid}`, `output/scenes/{pid}`, `output/tts/{pid}`, `output/storyboard/{pid}/{scene}`, `output/animator/{pid}/{scene}`; §13.1–§13.5). |
| new files | created through `stage_artifact(destination)` where the workflow scheduler supplies one (`ArtifactPromoter.stage_path`, `scheduler.py:135-142`), so a failed invocation publishes nothing. Legacy-route invocations without a promoter write directly, exactly as today. |
| references | every artifact leaves the provider as a **relative POSIX path beneath `OUTPUT_DIR`** — the value `artifact_ref()` already produces (`adapters/common.py:74-82`). |
| absolute paths | **never** appear in a `ProviderResult`, a job status, an error message, an execution record, an SSE frame, or an API response (§36). |
| deletion | a provider may delete only files it created during this invocation. |
| concurrency | two invocations for the same `(domain, project_id)` may not run concurrently; the caller enforces it (workflow: `ProjectLock`, `scheduler.py:61`). |

**Resolved in 15.3.** Absolute `wav_path` / `path` keys no longer leave `tts.generate`
on either port. Port payloads carry relative `artifact_refs` (authoritative) plus a
relative `wav_path` matching the sample-fixture shape; `adapters/timing.py` resolves
through `providers_common.results:resolve_ref`. The in-process `_step_tts` /
`_step_timing` service layer still uses an absolute path between those two functions
only — it never re-enters a port payload, cache entry, or API response. Removing the
absolute keys changed the TTS adapter output shape, so `ADAPTER_CACHE_SCHEMA_VERSION`
was bumped to 2 in the same commit (invalidate, never migrate — §45).

### 30.3 Cancellation token (frozen)

```python
class CancellationToken:
    def is_cancelled(self) -> bool: ...
    def raise_if_cancelled(self) -> None:   # raises ProviderCancelled
    def on_cancel(self, callback: Callable[[], None]) -> None:   # best-effort, idempotent
```

- Backed by the scheduler's existing `stop_requested` callable (`scheduler.py:421`,
  `:708`); the token is a wrapper, not a new mechanism.
- **Cooperative only.** No thread is killed and no process is signalled. A provider that
  declares the `cancel` capability (§20.4) must poll `is_cancelled()` at least every 5 s
  during any wait, and must return or raise within 10 s of the flag being set.
- A provider that does **not** declare `cancel` is not cancelled mid-call; the platform stops
  after the call returns (`scheduler.py:720-721`). This is exactly today's behavior and is why
  all five provider-backed node types currently declare `"cancel": False`
  (`registry.py:158, 197, 243, 267, 296`).
- Cancellation is **not** an error condition to be retried. It maps to `ProviderCancelled` →
  workflow code `CANCELLED` → node status `cancelled` (`scheduler.py:754-766`), never to
  `failed`.
- `on_cancel` callbacks run once, on the thread that first observes cancellation through
  `is_cancelled()` / `raise_if_cancelled()`. The existing scheduler exposes only
  `threading.Event.is_set` as a callable, so a callback cannot run on the thread that calls
  `Event.set` without inventing a second cancellation mechanism. Callbacks must not block or
  raise; exceptions are logged and swallowed.

### 30.4 Progress reporter (frozen)

```python
class ProgressReporter:
    def __call__(self, *, ready: int | None = None, total: int | None = None,
                 fraction: float | None = None, message: str | None = None,
                 unit_index: int | None = None, state: str | None = None) -> None: ...
```

- **Advisory and lossy.** Dropping a progress call must never change the outcome. The
  reporter never raises; a failure inside it is logged and swallowed.
- Only providers declaring the `progress` capability report `fraction`; `fraction` is clamped
  to `[0.0, 1.0]`. Providers declaring `single_scene`/`batch` report `ready`/`total`, which is
  the shape the SSE frame already carries (`{"progress": {"ready": 3, "total": 10}}`, §6) and
  the shape the legacy poll loop emits (`scene_ready`/`scene_total`,
  `pipeline/services.py:611-613`).
- `message` is free text, capped at 200 characters, and passes through redaction before it
  reaches a log, an SSE frame, or an execution record. It must not contain a filesystem path
  or a provider response body.
- The platform **rate-limits** progress to at most one emitted event per second per
  invocation, coalescing intermediate values; the last value before a terminal state is always
  emitted. Without this, a per-scene provider would flood the bounded SSE ring (1000 events,
  §6).
- `ready` must be monotonic non-decreasing within one invocation; a lower value is ignored and
  warned. `total` may only be set once per invocation after the first report.

### 30.5 Redacted logger (frozen)

```python
class ProviderLogger:
    def debug/info/warning/error(self, message: str, **fields) -> None: ...
```

- Every message and every field value passes through
  `studio/workflows/redaction.py:redact` seeded with the invocation's `settings` secrets
  before it reaches loguru. This is the *only* logging surface a provider may use; a provider
  importing `loguru` directly bypasses redaction and is non-conforming.
- Records are automatically tagged `domain`, `provider_id`, `project_id`, `execution_id`,
  `node_id`, `invocation_id`. A provider never formats those into its message.
- `error(...)` writes a log line; it does not fail the invocation. Failure is raising a
  `ProviderError` (§34).
- Only provider-authored `warning` and `error` records are eligible to become execution-record
  log entries; the node record already caps them (§5). The registry boundary's diagnostic
  traceback is explicitly internal-only even though it is emitted at error level: it must
  never be copied into a `ProviderResult`, execution-record log, SSE frame, or API response.

### 30.6 Relationship to `AdapterContext` (frozen)

`AdapterContext` (`adapters/common.py:24-35`) stays as the **workflow scheduler's** contract
with its adapters and does not change shape in Phase 11. `ProviderInvocation` is built *from*
it inside the adapter, so exactly one construction site per domain exists and legacy routes
can build the same object without a scheduler:

| `AdapterContext` | `ProviderInvocation` |
|---|---|
| `project_id` | `project_id` |
| `execution_id`, `node_id` | same |
| `progress: Callable[[str], None] \| None` | wrapped into `ProgressReporter` (`message=` only) |
| `stop_requested: Callable[[], bool] \| None` | wrapped into `CancellationToken` |
| `stage_artifact` | `stage_artifact` |
| `authorize_existing_replace` | stays scheduler-only; not part of the provider contract |
| — | `domain`, `provider_id`, `attempt`, `invocation_id`, `output_dir`, `deadline_s`, `settings`, `options`, `log` |

## 31. Result envelope

### 31.1 `ProviderResult` (frozen, `result_version: 1`)

One envelope for all five domains, `providers_common/results.py:ProviderResult`. The typed
per-domain body lives in `payload`; nothing else varies by domain.

```jsonc
{
  "result_version": 1,
  "domain": "tts",
  "provider_id": "inworld",
  "provider_version": "1.0.0",        // manifest version (§19.3)
  "contract_version": 2,
  "status": "succeeded",              // succeeded | partial | failed (§31.5)
  "payload": { /* domain result body — §32 */ },
  "artifact_refs": ["tts/pm_X/voice.wav", "tts/pm_X/tts.json"],
  "units": [ /* per-unit results — §31.5; [] for single-unit domains */ ],
  "metadata": {"duration_seconds": 28.5},
  "warnings": [{"code": "VOICE_FALLBACK", "message": "…"}],
  "provenance": { /* §31.3 */ },
  "job": null                          // JobStatus snapshot for async providers (§33)
}
```

| field | required | rule |
|---|---|---|
| `result_version` | yes | `1`. Bumped only for a breaking envelope change; readers reject an unknown major with `PROVIDER_RESULT_INVALID`. |
| `domain`, `provider_id` | yes | canonical values; the platform overwrites whatever the provider set, so a provider cannot impersonate another. |
| `provider_version`, `contract_version` | yes | copied from the manifest by the platform, not by the provider. |
| `status` | yes | `succeeded` \| `partial` \| `failed`. A returned `failed` is equivalent to raising `ProviderError` and is converted to one at the boundary; providers should raise. |
| `payload` | yes | must validate against `DomainSpec.result_model` (§32). JSON-serializable, no callables, no open handles, no `bytes`. |
| `artifact_refs` | yes | list of normalized relative refs (§30.2); may be empty; deduplicated, order-stable. |
| `units` | yes | `[]` for `script`/`scene_blueprint`/`tts`; one entry per requested scene for `storyboard`/`animator` (§31.5). |
| `metadata` | no | small, flat, JSON-scalar values only; ≤ 40 keys; strings ≤ 500 chars. For diagnostics and UI, never for control flow. |
| `warnings` | no | `[{code, message, unit_index?}]`; non-fatal. ≤ 50 entries; `message` ≤ 200 chars, redacted. |
| `provenance` | yes | §31.3. |
| `job` | no | present only when the provider declared `async_job`; a terminal `JobStatus` snapshot (§33.2). |

Unknown top-level keys in a returned result are **dropped with a WARN**, mirroring the
manifest policy (§20.3) — a provider written against a newer build must not fail on an older
one. An invalid *known* field is `PROVIDER_RESULT_INVALID` (§34.2).

### 31.2 What may not appear in a result (frozen)

A result is validated at the registry boundary before the caller sees it. Rejected outright:
absolute or UNC filesystem paths in any string field; keys matching
`redaction.is_sensitive_key` (`redaction.py:25-29`); `bytes`; non-JSON types; and any value
larger than the per-field caps above. The raw third-party HTTP body, the raw provider SDK
object, and the provider's exception text are never part of a result — a provider that wants
to surface a remote message must copy a bounded, redacted string into `warnings[].message` or
`ProviderError.message`.

Payload bodies stay small: anything that is not a bounded document goes to disk and is
referenced through `artifact_refs`. This is already the rule for execution records
("large payloads stay as artifact refs — never inlined", §5).

### 31.3 Provenance (frozen)

```jsonc
"provenance": {
  "invocation_id": "…", "domain": "tts", "provider_id": "inworld",
  "provider_version": "1.0.0", "contract_version": 2,
  "settings_version": 2,                       // settings.json version
  "resolved_settings_redacted": {"api_key": "[REDACTED]", "model": "inworld-tts-1"},
  "options": {"speed": 1.0},                   // per-run options, already secret-free
  "selection_reason": "node_config",           // §24.1 rung: request | node_config | settings | default
  "started_at": "ISO", "finished_at": "ISO", "duration_ms": 1234,
  "cache_hit": false
}
```

This generalizes the existing `job_meta` block, which already carries
`provider_id`/`provider_version`/`provider_kind`/`resolved_settings_redacted`/`provider_options`/
`resolved_at`/`settings_version` for TTS only (`pipeline/services.py:162-170`, `:268-276`).
The platform fills provenance; a provider cannot write it. `selection_reason` names which rung
of the §24.1 precedence chain chose the provider, which is what makes "why did this run use
Gemini?" answerable without reading logs. Provenance is persisted into the domain's own
artifact (`tts.json`, `story.json`, `scenes.json`, `storyboard.json`, `grabber_job.json`) and
into `outputs_summary`; it is browser-safe by construction because
`resolved_settings_redacted` is produced by `settings_manager.redact_settings`.

### 31.4 Warnings vs errors (frozen)

A warning never changes `status`. Anything that makes the requested work unusable is an error.
Concretely: a per-scene failure inside a batch is a `unit` with `state: "failed"` plus a
warning; *all* units failing is `status: "failed"` and is raised, never returned as success —
the rule the two adapters already enforce by hand (`adapters/storyboard.py:62-67`,
`adapters/animator.py:75-80`) and that 14.1 must preserve ("all-failed can never be reported
as success").

### 31.5 Partial results (frozen)

Multi-unit domains (`storyboard`, `animator`; any provider declaring `batch`) return one
`UnitResult` per **requested** unit, in requested order:

```jsonc
{ "unit_index": 3,                 // the scene index from the request; stable, not positional
  "state": "failed",               // succeeded | failed | skipped | cancelled
  "artifact_refs": [],
  "metadata": {},
  "error": {"code": "PROVIDER_UNIT_FAILED", "message": "…", "retryable": true} }
```

Frozen rules:

1. `len(units) == len(requested units)`. A unit the provider never attempted is
   `state: "skipped"`, not an omission. Today a scene that never reports simply stays
   `pending` in `scene_statuses` and the poll loop can only infer it by arithmetic
   (`pending = total - ready - errors`, `pipeline/services.py:593`).
2. `unit_index` is the caller's index (the scene `index`), so a partial re-run addresses the
   same units. Positional inference is forbidden.
3. Envelope `status` is derived, never provider-declared, in this precedence order:
   any unit `cancelled` and no unit failed → cancel the invocation (even if an earlier unit
   succeeded); otherwise all succeeded → `succeeded`; otherwise at least one succeeded →
   `partial`; otherwise → `failed` (raised, §31.4). This ordering prevents a cancellation
   arriving after one completed scene from being misreported as ordinary partial success.
4. `artifact_refs` at envelope level is the ordered union of unit refs plus domain-level
   artifacts (the manifest JSON). No unit-level ref may be missing from it.
5. A `failed` unit must carry `error`; a `succeeded` unit must carry at least one
   `artifact_ref` unless the domain declares otherwise.
6. Unit `error.message` obeys §31.2. This closes the current leak at
   `storyboard/routes.py:254`, where `"error": str(e)` writes raw exception text into
   `storyboard.json`, which the storyboard adapter then hands to the `images` port verbatim
   (`adapters/storyboard.py:46`).

**Whether `partial` fails the node is the caller's policy, not the provider's.** Frozen
default for workflow execution: `partial` succeeds the node and records a warning, matching
today (a run with 9/10 images succeeds). 14.1 may add an opt-in per-node "require all units"
setting; it must default off.

## 32. Domain request and result schemas

Each domain gets `studio/<module>/providers/contract.py` exporting `<Domain>Request` and
`<Domain>ResultPayload`, and the dotted paths fill the `DomainSpec.request_model` /
`result_model` fields left blank in §19.1:

| domain | request_model | result_model | shape | artifact rule |
|---|---|---|---|---|
| `script` | `studio.story.providers.contract:ScriptRequest` | `…:ScriptResultPayload` | single unit, sync | `stories/{pid}/story.json` |
| `scene_blueprint` | `studio.build_scene_blueprints.providers.contract:SceneBlueprintRequest` | `…:SceneBlueprintResultPayload` | single unit, sync | `scenes/{pid}/scenes.json` |
| `tts` | `studio.tts.providers.contract:TTSRequest` | `…:TTSResultPayload` | single unit, sync | `tts/{pid}/voice.wav` + `tts.json` |
| `storyboard` | `studio.storyboard.providers.contract:StoryboardRequest` | `…:StoryboardResultPayload` | multi-unit, async | `storyboard/{pid}/storyboard.json` + `{scene}/image.{ext}` |
| `animator` | `studio.animator.providers.contract:AnimatorRequest` | `…:AnimatorResultPayload` | multi-unit, async | `animator/{pid}/grabber_job.json` + `{scene}/*` |

Requests are validated **before** the provider is constructed; a malformed request is
`PROVIDER_REQUEST_INVALID` and is never a provider failure. Unknown request keys are rejected
(unlike results and manifests): a silently ignored request field changes output without
telling anyone.

### 32.1 `script`

```python
ScriptRequest:  # from adapters/story.py + story/schemas.py:21-53
    idea: str = ""                 # free text, ≤ 4000 chars
    category: str                  # story_category, ≤ 80 chars
    style: str = ""                # preset_style (§ style_templates)
    tone: str = ""                 # story_tone
    language: str = "english"      # english | french | spanish
    language_level: str = ""
    target_duration_s: int = 45    # 15–180
    niche_preset: str = ""
    seed: int | None = None        # deterministic providers only (13.1)
```

```python
ScriptResultPayload:
    script_text: str                    # non-empty; the canonical narration text
    sections: dict[str, str]            # hook | build | climax | cta; may be empty for
                                        # providers without `structured_sections`
    word_count: int
    estimated_duration_s: int
    language: str
```

Maps onto today's `generate_story` return (`story/service.py:90-108`) field for field:
`story_text→script_text`, `sections→sections`, `metadata.word_count→word_count`,
`metadata.estimated_duration→estimated_duration_s`. Everything else in today's `metadata`
(`preset_style`, `story_category`, `story_tone`, `duration`, `generation_time`, `timestamp`,
`concept_family`) moves to `metadata`/`provenance`; the hardcoded `"provider": "gemini"`
(`story/service.py:102`, P33) is deleted because `provenance.provider_id` supersedes it.
`pipeline_ref` stays in the persisted `story.json` and is not part of the provider result.
Artifact: exactly one ref, `stories/{pid}/story.json`. Anti-repeat history
(`output/story_history/*`) is a provider-internal side effect and is **not** an artifact ref —
it is not derived from this project and must not be attributed to the node.

### 32.2 `scene_blueprint`

```python
SceneBlueprintRequest:
    script: str
    segments: list[Segment]        # {index, words, start, end, is_filler}; non-filler only
                                   # are numbered, matching services.py:423-426
    style: str = "cinematic"
    style_notes: str = ""          # style_prompt / custom_style_notes
    tone: str = ""
    aspect_ratio: str = "9:16"
```

```python
SceneBlueprintResultPayload:
    scenes: list[Scene]            # {index, image_prompt, start, end, narrative_role, …}
    style_spec: dict
    style_prompt: str
    analysis: dict
    coherence: {"score": float, "warnings": [str], "metrics": dict}
    sfx_report: dict | None        # only when `sfx_report` capability
    total_duration_s: float
```

Preserves the current `_step_scenes` result keys (`pipeline/services.py:500-515`) so
`scenes.json` stays schema-compatible (13.4's "current fixture outputs remain
schema-compatible"). `scene_blueprints`, `visual_bible`, and `custom_style_notes` remain in the
persisted artifact; they are planner inputs, not provider outputs, and 13.4 decides whether to
surface them in `metadata`. Chaptering is a provider-internal decision behind the `chaptering`
capability, not a request field — `should_use_chapters` (`chapters.py:31-34`) is a
payload-size rule, and the caller must not have to know it. `scenes[].index` must be stable
and dense over the non-filler segments; it is the `unit_index` the two visual domains key on.

### 32.3 `tts`

```python
TTSRequest:
    text: str                       # non-empty
    voice: str = ""                 # canonical voice id for the resolved provider
    speed: float = 1.0              # 0.5–2.0
    language: str = ""
    output_basename: str = "voice"  # file stem inside output_dir
```

```python
TTSResultPayload:
    audio_ref: str                  # relative ref to the wav; also in artifact_refs
    duration_seconds: float         # > 0
    sample_rate: int
    format: str = "wav"
    voice: str
    characters_billed: int | None = None
```

The **one voice field** ends the `voice` vs `tts_voice` split that exists only because
dispatch branches on the provider id (`pipeline/services.py:88-94`, P5): the caller resolves
one voice for the resolved provider through the `tts_voices` option source (§23.1), so the
provider receives exactly one. `TTSResult` (`tts/providers/base.py:22-29`) is the ABC shape
being replaced: `audio_path`→`audio_ref` (relative, not absolute), `duration_seconds`,
`format`, `sample_rate` carry over, and `metadata` is split into `metadata` + `provenance`.
The remaining keys of today's `tts.json` (`prompt`, `words`, `approx_tokens`, `rtf`,
`inference_time`, `model`, `visual_style`, `story_tone`, `category`, `timestamp`,
`cache_hit`) move to `metadata`/`provenance` and the file keeps them, so
`tts.json` consumers are unaffected. Artifacts: `tts/{pid}/voice.wav` and `tts/{pid}/tts.json`.
Streaming (`stream()`, `TTSStreamChunk`) is **not** part of the invocation contract: it is a
transport-level capability (`streaming`) used by `/api/tts/stream` and never produces a
`ProviderResult`.

### 32.4 `storyboard`

```python
StoryboardRequest:
    scenes: list[{index: int, prompt: str}]   # non-empty; index is the unit_index
    aspect_ratio: str = "9:16"
    style: str = ""
```

```python
StoryboardResultPayload:
    total: int; ready: int; errors: int
    manifest_ref: str                          # storyboard/{pid}/storyboard.json
```

Per-scene detail lives in `units[]`, not in the payload. Each unit carries
`artifact_refs: ["storyboard/{pid}/{scene}/image.{ext}"]` and
`metadata: {"thumbnail_ref": …, "width": …, "height": …}`. The remote `image_url` from the
third-party CDN (`storyboard/routes.py:233`) is **provider-specific response data** and is
dropped from the result; the downloaded file is the output. `scene_statuses` is retired as a
provider-facing shape — it stays inside `storyboard.json` for the legacy status route
(`routes.py:387-401`, public compatibility surface §17.1) and 14.2 derives it from `units[]`.
`image_model`, `prompt_prefix`, and `auto_type` are provider settings, not request fields
(§26, P27). This keeps the request provider-neutral and avoids freezing `image_model` both as
a durable setting and as a per-run option.

### 32.5 `animator`

```python
AnimatorRequest:
    scenes: list[{index: int, prompt: str, reference_ref: str | None}]
    aspect_ratio: str = "9:16"
    mode: str = "video"            # video | image
```

```python
AnimatorResultPayload:
    total: int; ready: int; errors: int
    manifest_ref: str              # animator/{pid}/grabber_job.json
```

Units carry `artifact_refs` for every produced media file plus
`metadata: {"kind": "video"|"image", "thumbnail_ref": …, "duration_s": …}`. `reference_ref`
is how the declared-but-unused `storyboard` input port (`registry.py:277`) becomes meaningful
for `image_to_video` providers. `quality`, `duration`, `auto_type`, and Kie's
`resolution`/`output_format` are provider settings (P27, §26), not duplicate fields in
`AnimatorRequest`; `arguments`
(`adapters/animator.py:23`) is a free-text passthrough that 14.3 must either type or delete —
it is not part of the frozen request. The remote `urls` list (`animator/routes.py:457`,
`:532`) is provider-specific response data and is dropped, same rule as storyboard's
`image_url`.

## 33. Asynchronous jobs

### 33.1 Unified job types (frozen)

`providers_common/jobs.py` holds **one** definition each, replacing the two field-for-field
duplicates in `storyboard/providers/base.py:13-38` and `animator/providers/base.py:12-38`
(§14.6). Owner: **11.4**.

```python
@dataclass(frozen=True)
class JobHandle:
    job_id: str          # provider-scoped, opaque, stable; ^[A-Za-z0-9_.:-]{1,128}$
    domain: str
    provider_id: str
    project_id: str
    invocation_id: str   # correlates the handle to its ProviderInvocation
    created_at: str      # ISO

@dataclass(frozen=True)
class JobStatus:
    job_id: str
    state: str                   # §33.2
    ready: int = 0
    total: int = 0
    fraction: float | None = None
    message: str | None = None   # ≤ 200 chars, redacted
    units: tuple[UnitResult, ...] = ()  # §31.5; serialized as a JSON array
                                     # and may be partial while running
    error: ProviderErrorPayload | None = None   # §34.1; set only in state="failed"
    updated_at: str = ""
```

`JobHandle` contains stable identity only; live state belongs exclusively to `JobStatus`.
Putting `state` on the frozen handle would either become stale at the first transition or
require replacing the identity object on every poll. Two deliberate changes from the
duplicated dataclasses: `status: str` becomes `state` with a
closed vocabulary (the old field held provider-defined strings), and `result: dict | None`
becomes `units: tuple[UnitResult, ...]` so a partial result is expressible while the job is still
running. `SceneResult` (`image_url/image_path` vs `video_url/video_path`) is replaced by the
one media-neutral `UnitResult` of §31.5; 11.4 keeps thin domain aliases so 14.2/14.3 can diff
against the old shape.

### 33.2 State machine (frozen)

```
submitted ──► running ──► succeeded
     │           │    └──► partial
     │           ├───────► failed
     └───────────┴───────► cancelled
                 └───────► timed_out
```

`JobState` = `submitted | running | succeeded | partial | failed | cancelled | timed_out`.
Terminal: `succeeded`, `partial`, `failed`, `cancelled`, `timed_out`. Transitions are
monotonic — a terminal job never returns to `running`, matching the execution-record rule in
§5. `total` may only be set once, at or before the first `running` status.

Every terminal state maps to exactly one invocation outcome, so a synchronous and an
asynchronous provider are indistinguishable to the caller:

| terminal job state | invocation outcome |
|---|---|
| `succeeded` | `ProviderResult(status="succeeded")` |
| `partial` | `ProviderResult(status="partial")` + warnings |
| `failed` | raise `ProviderError` (code from `JobStatus.error`) |
| `cancelled` | raise `ProviderCancelled` → workflow `CANCELLED` |
| `timed_out` | raise `ProviderError(code="PROVIDER_TIMEOUT", retryable=True)` → workflow `POLL_TIMEOUT` |

**Zero produced units can never be `succeeded`.** A job whose units all failed is `failed`,
which is the defect class currently guarded by hand in both adapters and by the known defect
"storyboard poll counts errors as done" (§8).

### 33.3 Poll and push (frozen)

Providers declare exactly one of two delivery modes through capabilities (§20.4):

- `async_job` without `push_callbacks` — the platform polls `poll(job_id, invocation)`.
  Frozen cadence: first poll after 2 s, then the domain interval, ±10 % jitter. Domain
  intervals are today's values: storyboard 10 s, animator 10 s
  (`pipeline/services.py:573`, `:688`). A poll that raises is retried up to 3 consecutive
  times before the job is failed; the current loop swallows *every* poll exception forever
  (`pipeline/services.py:624-625`), which turns a permanently broken provider into a 30-minute
  wait.
- `push_callbacks` — the provider pushes status through its runtime (WebSocket for
  `gemini_ws` / `grok_automa`, HTTP callback for `wavespeed_webhook`). The platform still
  polls, at a 60 s watchdog interval, so a lost push cannot hang the job.

Push correlation is frozen as the tuple `(domain, provider_id, project_id, job_id)`; a status
whose tuple does not match a live job is **dropped and warned**, never applied. Duplicate
status for a unit already in a terminal state is idempotent and ignored. Both rules are
preconditions for 14.4's "cross-provider/job callbacks cannot contaminate results".

### 33.4 Job persistence (frozen)

A job handle survives a process restart: the platform persists `JobHandle` + last `JobStatus`
next to the domain manifest through `safe_json_write`, and rehydrates on startup — which is
what the animator store already does informally (`grabber_job.json`, in-memory `JobStore`
rehydrated from disk, §13.5). Rehydrated jobs resume polling; a job whose provider is no
longer registered is marked `failed` with `PROVIDER_NOT_FOUND` rather than being retried
forever. Persisted job records obey §31.2 in full.

## 34. `ProviderError`

### 34.1 Shape (frozen)

```python
class ProviderError(Exception):
    code: str                     # §34.2, stable
    message: str                  # safe, human-readable, ≤ 300 chars, redacted
    retryable: bool               # §34.3
    domain: str
    provider_id: str
    details: dict | None          # redacted, JSON-only, ≤ 4 KiB serialized
    recovery_suggestion: str | None
    unit_index: int | None        # set for a per-unit failure
    cause_type: str | None        # exception class name only — never its message
```

`ProviderErrorPayload` is its JSON form and is the value carried in `JobStatus.error` and
`UnitResult.error`. `ProviderCancelled` is the one subclass with fixed semantics
(`code="CANCELLED"`, `retryable=False`).

`cause_type` records `"ConnectionError"` or `"JSONDecodeError"` and nothing else: the class
name is diagnostic, the message is untrusted. The traceback is logged through the redacted
logger and never serialized.

### 34.2 Code catalog (frozen)

Provider-level codes, stable across builds:

| code | meaning | retryable |
|---|---|---|
| `PROVIDER_NOT_FOUND` | no such `(domain, provider_id)` after alias resolution | no |
| `PROVIDER_UNAVAILABLE` | registered but not usable now — degraded, extension offline, model missing | yes |
| `PROVIDER_NOT_CONFIGURED` | a `requires` key is empty after env fallback (§21.5) | no |
| `PROVIDER_REQUEST_INVALID` | the request failed domain validation before dispatch | no |
| `PROVIDER_RESULT_INVALID` | the provider returned a result violating §31 | no |
| `PROVIDER_AUTH_FAILED` | remote rejected credentials (the live WaveSpeed 401, §17.4) | no |
| `PROVIDER_RATE_LIMITED` | remote 429 / quota | yes |
| `PROVIDER_QUOTA_EXHAUSTED` | remote balance/credit exhausted (the OpenRouter case) | no |
| `PROVIDER_TIMEOUT` | invocation or job deadline exceeded (§35.3) | yes |
| `PROVIDER_TRANSPORT_FAILED` | connection error, DNS, TLS, 5xx | yes |
| `PROVIDER_RESPONSE_MALFORMED` | remote responded but the body is unusable | yes |
| `PROVIDER_UNIT_FAILED` | one unit of a batch failed | per-case |
| `PROVIDER_ARTIFACT_MISSING` | a declared artifact was not produced | no |
| `PROVIDER_ARTIFACT_UNMANAGED` | a write outside the managed output directory | no |
| `PROVIDER_FAILED` | wrapped unknown exception (§34.4) | no |
| `CANCELLED` | cooperative cancellation | no |

Mapping to the stable workflow error codes of §7 — the workflow-facing set does **not** grow
for provider internals, so existing clients keep working:

| provider code | workflow code |
|---|---|
| `PROVIDER_UNAVAILABLE`, `PROVIDER_NOT_CONFIGURED`, `PROVIDER_NOT_FOUND` | `PROVIDER_UNAVAILABLE` |
| `PROVIDER_TIMEOUT` | `POLL_TIMEOUT` |
| `CANCELLED` | `CANCELLED` |
| `PROVIDER_ARTIFACT_MISSING`, `PROVIDER_ARTIFACT_UNMANAGED` | `ARTIFACT_MISSING` |
| everything else | `NODE_EXECUTION_FAILED` |

`EXTENSION_NOT_CONNECTED` stays reserved for the extension-runtime probe (`app.py:266`,
`:276`) and is emitted by the platform, not by a provider. **The §7 stable list gains no new
codes** — `PROVIDER_*` values live in the provider layer and travel in
`details.provider_code` when the workflow code is coarser, so a UI can still distinguish an
auth failure from a malformed response without a new top-level code.

### 34.3 Retryability (frozen)

`retryable` describes the *provider's* view; the caller decides whether to act on it. The
scheduler's existing per-node policy is unchanged (`on_error.policy`, `max_attempts` 3,
1000 ms base, ×2 backoff, capped at 60 s — `scheduler.py:878-885`, `:770-776`). New rule:
a `retryable=False` provider error **stops the attempt loop immediately** instead of burning
all three attempts on a permanently invalid API key. Owner: **11.4**.

Retryable and non-retryable classes are fixed by the table above, not per provider. A provider
may not mark `PROVIDER_AUTH_FAILED` retryable to force retries.

### 34.4 The exception boundary (frozen)

Exactly one place wraps provider exceptions: the registry/hub invocation boundary in
`providers_common`. Frozen behavior for any exception that is not already a `ProviderError`:

1. Log the full traceback through the redacted logger, tagged with the invocation identity
   and marked internal-only so §30.5 cannot promote it into an execution-record log entry.
2. Return `ProviderError(code="PROVIDER_FAILED", retryable=False, cause_type=type(exc).__name__,
   message=<generic per-domain sentence>, recovery_suggestion=…)`.
3. **The original exception's `str(exc)` is never copied into `message` or `details`.**

That third rule is the substantive change. Today the raw text propagates all the way into the
persisted execution record: `call_webhook` builds `RuntimeError(f"{label} returned {status}:
{body_text[:200]}")` embedding the third-party response body (`webhooks.py:39`, `:50-62`,
`:112`, `:121`); `_step_scenes` raises bare `RuntimeError` (`pipeline/services.py:429`);
`adapters/story.py:19-22` catches only `StoryServiceError`/`ValueError`, so the webhook
`RuntimeError` passes through; and the scheduler's `_failure_payload` sets
`message = str(exc)` (`scheduler.py:889`). `Redactor` removes key-shaped secrets but not a
provider's response body, an absolute path, or a stack frame. `ArtifactPromoter.promote`
likewise raises `ARTIFACT_MISSING` with the absolute staged path in the message
(`scheduler.py:158`).

Frozen consequence: `_failure_payload` must stop using `str(exc)` for non-`ProviderError`,
non-`AdapterError`, non-`SchedulerError` exceptions and use the wrapped safe message; and
every path-bearing message is reduced to a basename. Owner: **11.4** (boundary), **13.4**
(scene-blueprint webhook errors), **16.4** (final sweep).

`AdapterError` (`adapters/common.py:14-21`) is *not* replaced: it stays the adapter→scheduler
carrier, and 11.4 provides `ProviderError.as_adapter_error()` so the two layers map without
either importing the other's module.

## 35. Cancellation, retry, and timeout

### 35.1 Cancellation (frozen)

| stage | behavior |
|---|---|
| before dispatch | the invocation is not started; node status `cancelled` |
| during a sync call | only providers declaring `cancel` observe it; others complete and the platform discards the result after the call returns (`scheduler.py:720-721`) |
| during an async job | the platform calls `cancel_job(job_id, invocation)` when the provider declares `cancel`, then stops polling; a provider without `cancel_job` has its job abandoned and marked `cancelled` locally |
| after cancellation | staged artifacts are discarded (`ArtifactPromoter.cleanup`, `scheduler.py:760`); already-promoted artifacts from earlier nodes are kept |
| record | `status: "cancelled"`, never `failed`; no retry (`scheduler.py:762-766`, `:794-799`) |

A cancelled job on a remote provider may still consume quota. That is accepted and must be
stated in the provider author guide (16.3), not hidden.

**Defect found while freezing this contract — the one cancellation code that exists is the
wrong one.** Both visual adapters raise `AdapterError("EXECUTION_CANCELLED", …)` when the stop
flag is observed (`adapters/storyboard.py:49`, `adapters/animator.py:59`), but the scheduler
recognizes cancellation only as `code == "CANCELLED"` (`scheduler.py:762`). With the default
error policy (`policy: "stop"` → `max_attempts = 1`, `scheduler.py:695, 881`) the raise falls
through to the ordinary failure path and the node is recorded **`failed`** with code
`EXECUTION_CANCELLED`, while the overall execution is still marked `cancelled`
(`scheduler.py:571`) — an internally inconsistent record. No test covers it, and
`EXECUTION_CANCELLED` appears nowhere else in the repo. Frozen resolution: cancellation is
raised as `ProviderCancelled` → `CANCELLED` (§34.1/§34.2), the only recognized code.
Owner: **11.4**, with a regression test that cancels each visual node and asserts node status
`cancelled`.

### 35.2 Retry and idempotency (frozen)

- **The platform retries invocations; providers do not.** A provider may retry an internal
  HTTP request only when it is read-only or carries a provider-supported idempotency key; it
  must not blindly retry a generation `POST`, because a lost response can otherwise create
  two remote jobs. Today's `call_webhook` retries every request 3 times / 2-4-8 s
  (`webhooks.py:9-10`); 13.2/13.4 must either add an idempotency key for generation calls or
  disable those internal retries before dispatch moves behind this boundary.
- A retried invocation gets a **new** `invocation_id` and an incremented `attempt`. Any job
  submitted by the failed attempt must be cancelled or abandoned before the retry; two live
  jobs for one `(domain, project_id)` are a contract violation.
- Retry is only safe because artifacts are staged: a failed attempt publishes nothing
  (`promoter.promote()` runs only on success, `scheduler.py:728`).
- For multi-unit domains, retry re-requests **only** units not in a terminal `succeeded`
  state; already-produced artifacts are reused. This is 14.1's "restart reconciliation".
- Non-retryable errors (§34.3) skip the remaining attempts.

### 35.3 Timeouts (frozen)

Two independent deadlines. Both are platform-owned; a provider never decides how long the
caller waits.

| scope | value | source |
|---|---|---|
| single outbound request | provider setting, default 180 s | `call_webhook(timeout=180)`, `webhooks.py:18` |
| `script` invocation | 300 s | `generate_story` uses 120 s per webhook call (`story/service.py:79`) with retries |
| `scene_blueprint` invocation | 600 s | 180 s per call, 300 s in chapter mode, up to 3 attempts (§13.2) |
| `tts` invocation | 900 s | local model load + synthesis; no current explicit limit |
| `storyboard` job | 1800 s (30 min) | `pipeline/services.py:572`, `adapters/storyboard.py:38` |
| `animator` job | 7200 s (120 min) | `pipeline/services.py:687`, `adapters/animator.py:45` |

`ProviderInvocation.deadline_s` overrides the domain default and is the single value a
provider may read to size its own waits. Exceeding it is `PROVIDER_TIMEOUT` /
`JobState.timed_out` → workflow `POLL_TIMEOUT`, with any units already terminal preserved as a
`partial`-shaped diagnostic in `details` (the invocation still fails). The current code
instead raises a bare `RuntimeError`/`AdapterError("NODE_TIMEOUT", …)` with no partial data
(`pipeline/services.py:627`, `adapters/storyboard.py:51`, `adapters/animator.py:61`);
`NODE_TIMEOUT` is not in the §7 stable set and is retired in favor of `POLL_TIMEOUT`.
Owner: **11.4** for the helper, **14.1** for the job service.

## 36. Egress assertion — the four prohibited classes

No **raw provider exception**, **credential**, **arbitrary filesystem path**, or
**provider-specific response** may reach a workflow record, an SSE frame, a cache entry, an
exported template, or any API response. Enforcement points and the current violations:

| # | class | current violation | enforcement in v2 | owner |
|---|---|---|---|---|
| L1 | raw exception | `scheduler.py:889` `message = str(exc)` for any adapter exception | §34.4 wrapping; `_failure_payload` uses the safe message | 11.4 |
| L2 | raw exception | `webhooks.py:39,50-62` embeds up to 200–500 chars of the third-party body in the exception text, unhandled by `adapters/story.py:19-22` and `_step_scenes` | webhook helpers raise `ProviderError` with a generic message; body only in the redacted log | 13.2 / 13.4 |
| L3 | raw exception | `storyboard/routes.py:254` `"error": str(e)` persisted into `storyboard.json` and returned on the `images` port (`adapters/storyboard.py:46`) | per-unit `error` is a `ProviderErrorPayload` (§31.5 rule 6) | 14.2 |
| L4 | raw exception | `registry.py:135` `ValidationIssue(message=str(e))` and `:156` `HealthResult(message=str(e))` | already frozen by §22.5 / §21.1 as generic messages | 11.3 |
| L5 | credential | `GET /api/settings/v2` and `GET /api/providers/*/settings` return unredacted `api_key` (§22.6) | `redacted_provider_settings` on both routes | 11.5 |
| L6 | credential | provider settings reaching a result | `settings` are input-only; `provenance.resolved_settings_redacted` is the only echo (§31.3) | 11.4 |
| L7 | filesystem path | `tts` ports carried absolute `wav_path` / `path` | **resolved 15.3** — relative `artifact_refs` (+ relative `wav_path`); `timing.align` uses `resolve_ref` (§30.2 / §44) | 15.3 |
| L8 | filesystem path | `scheduler.py:158` `ARTIFACT_MISSING: Staged artifact was not created: {staged}` | messages are basename-only (§34.4) | 11.4 |
| L9 | provider response | remote `image_url` (`storyboard/routes.py:233`) and `urls` (`animator/routes.py:457,532`) cross into port payloads | dropped from results; downloaded files are the output (§32.4, §32.5) | 14.2 / 14.3 |
| L10 | provider response | `scene_statuses` returned verbatim on the `images` port | replaced by `units[]`; `scene_statuses` stays inside the legacy status route only | 14.2 |

Enforcement is mechanical, not by review: 11.4 adds a result/error validator that rejects
absolute paths, sensitive keys, and oversized fields at the boundary, and a test asserts a
provider raising `RuntimeError("key sk-abc123 at C:\\secret\\file.txt")` produces an execution
record containing neither the key, the path, nor the class-specific text.

Existing guarantees that already hold and must not regress: `Redactor` runs on every persisted
record, SSE frame, and log entry (`scheduler.py:685-686`, `:731`, `:844`, `:875`);
`_summarize` reduces payload strings to lengths (`scheduler.py:194-214`); a result whose
redaction differs from itself is never cached (`scheduler.py:732-733`).

## 37. Deltas this contract requires of shipped code

Continues §28. Nothing below exists today.

| # | delta | current state | owner |
|---|---|---|---|
| D22 | `providers_common/invocation.py` — `ProviderInvocation`, `CancellationToken`, `ProgressReporter`, `ProviderLogger` | only `AdapterContext` with two optional callables (`adapters/common.py:24-35`) | 11.4 |
| D23 | `providers_common/results.py` — `ProviderResult`, `UnitResult`, provenance, `resolve_ref` | adapters return bare dicts + `with_artifacts` | 11.4 |
| D24 | `providers_common/jobs.py` — one `JobHandle`/`JobStatus`/`JobState`, media-neutral `UnitResult` | duplicated dataclasses in two `base.py` files (§14.6) | 11.4 |
| D25 | `providers_common/errors.py` — `ProviderError`, `ProviderCancelled`, the code catalog, `as_adapter_error()` | `AdapterError`, `SchedulerError`, `StoryServiceError`, bare `RuntimeError` | 11.4 |
| D26 | single exception boundary that never copies `str(exc)` | `scheduler.py:889` copies it | 11.4 |
| D27 | non-retryable errors stop the attempt loop | all failures consume `max_attempts` (`scheduler.py:770`) | 11.4 |
| D28 | result/error egress validator (absolute paths, sensitive keys, size caps) | none | 11.4 |
| D29 | progress rate limiting + monotonic `ready` | ad-hoc `_emit` per poll (`services.py:606-614`) | 11.4 / 14.1 |
| D30 | five `providers/contract.py` request/result models; `DomainSpec.request_model`/`result_model` filled | fields left `None` in §19.1 | 13.1–13.4 / 14.2 / 14.3 / 15.1 |
| D31 | poll cadence with jitter and a 3-strike poll-failure limit | poll exceptions swallowed forever (`services.py:624-625`) | 14.1 |
| D32 | push correlation tuple + duplicate-status idempotence | none | 14.4 |
| D33 | job persistence/rehydration for both visual domains | informal, animator only (§13.5) | 14.1 |
| D34 | per-unit retry that reuses succeeded units | whole-node retry regenerates everything | 14.1 |
| D35 | `POLL_TIMEOUT` replaces the ad-hoc `NODE_TIMEOUT` code | `NODE_TIMEOUT` is not in the §7 stable set | 11.4 / 14.1 |
| D36 | cancellation raises `CANCELLED`, not `EXECUTION_CANCELLED` | a cancelled visual node records as `failed` (§35.1) | 11.4 |
| D37 | one voice field in the TTS request | `voice` vs `tts_voice` chosen by a provider-id branch (P5) | 15.2 |
| D38 | remote URLs dropped from storyboard/animator results | `image_url` / `urls` cross into ports | 14.2 / 14.3 |
| D39 | `provenance` replaces the TTS-only `job_meta` and the hardcoded `"provider": "gemini"` (P33) | `job_meta` in TTS only; literal in story metadata | 11.4 / 13.3 |
| D40 | generation POSTs are not transport-retried without provider idempotency support | `call_webhook` retries every request and can duplicate remote work after a lost response | 13.2 / 13.4 |

## 38. Phase 10.3 coverage assertion

Frozen by this section: the shared invocation context with its identity, managed output
directory, cancellation token, progress reporter, and redacted logger, plus its mapping to the
existing `AdapterContext`; the versioned `ProviderResult` envelope with artifact rules,
metadata and warning caps, provenance, and the prohibited-content list; exact request and
result schemas for all five domains — `script`, `scene_blueprint`, `tts`, `storyboard`,
`animator` — each mapped field-by-field onto the shape the current code produces, together
with the `DomainSpec.request_model`/`result_model` paths left blank by 10.2; unambiguous
partial results through a per-unit `UnitResult` keyed on the caller's index, with derived
envelope status and the rule that zero produced units can never be success; one job contract
replacing the two duplicated dataclasses, with a closed state machine whose five terminal
states map one-to-one onto invocation outcomes so synchronous and asynchronous providers are
indistinguishable to callers; poll cadence, push correlation, and job persistence; and
`ProviderError` with a stable code catalog, fixed retryability classes, a mapping onto the §7
workflow codes that adds none, and a single wrapping boundary that never copies raw exception
text.

Cancel, retry, and timeout are frozen end to end, including the six domain deadlines taken
from today's values, the rule that a non-retryable error stops the attempt loop, the rule that
a generation POST is retried only with provider-supported idempotency, and one
defect found while freezing the contract: the visual adapters raise `EXECUTION_CANCELLED`,
which the scheduler does not recognize as cancellation, so a cancelled Storyboard or Animator
node is currently recorded as `failed` inside an execution the same scheduler marks
`cancelled`. §36
enumerates all ten current egress violations across the four prohibited classes with an owner
each and a mechanical enforcement point, so no raw provider exception, credential, arbitrary
filesystem path, or provider-specific response can reach a workflow record or an API response.
Deferred by design to 10.4: legacy field/alias mapping tables, node `type_version` migrations,
and the deterministic fixture set that makes these schemas testable without live credentials.

---

# Provider Platform — Migration Map, Fixtures, Implementation Gate (Phase 10.4 frozen)

> Produced by step 10.4 of [implementation-plan.md](implementation-plan.md).
> Grounded in code at commit `5330f9e` (2026-08-09). Every `file:line` reference below was read
> at that commit, not carried over from an earlier section.
>
> §13–§18 audited the current paths, §19–§29 froze *what a provider is*, §30–§38 froze *how it is
> called and how it fails*. This section freezes the last missing piece: **how every value that is
> already persisted or already on the wire reaches those shapes**, what fixtures make that testable
> without credentials, and which contract obligations cannot be met without a deliberate shim.
>
> **Implementation owner.** Nothing in §39–§48 is code today. Each row names its owner step.
> 10.4 itself writes no production code; its output is this contract plus the plan corrections
> in §47.

## 39. Compatibility policy (frozen)

Three verbs, and only three, apply to every shape in this section:

| verb | meaning | when a value is missing | observable effect |
|---|---|---|---|
| **passthrough** | v2 accepts the legacy name as-is; no rewrite, no deprecation | legacy default applies | none |
| **upgrade** | the legacy value is rewritten to its v2 form at a named boundary, and the rewrite is recorded | v2 default applies | the upgraded form is returned and persists on the next explicit save |
| **reject** | the value is refused with a stable code | n/a | a `4xx`/validation issue, never a silent fallback |

Rules that bind all three:

1. **No manual edits.** A workflow saved before the migration, a `settings.json` written before
   the migration, a legacy `POST` body sent by a legacy page, and an execution/cache record on
   disk must all keep working with zero user action. This is §17.1 restated as an executable
   requirement; §48 makes it a test.
2. **Upgrade is idempotent.** Running an upgrade twice equals running it once. Every upgrade
   step below is specified so that re-running it on already-upgraded data is a no-op.
3. **Upgrade is recorded and read-safe.** Node-config upgrades land in
   `extensions.type_version_migrations` (`migrations.py:15,125`) in the returned copy and persist
   only on explicit Save, matching the existing non-destructive loader
   (`tests/test_workflow_persistence.py:216-257`). Settings upgrades bump `settings.json.version`
   atomically during load. A workflow read never writes its source document.
4. **Reject is never a fallback.** The current code silently substitutes a provider when the
   requested one is unknown (`storyboard/routes.py:320-322`, `animator/schemas.py:36`). Under v2
   an unknown provider ID is a `PROVIDER_NOT_FOUND` error
   (§34.2), except at the two documented alias boundaries in §40.3.
5. **Support window.** Legacy request fields and legacy provider strings are supported until
   step **16.1** removes the internal HTTP hop and the legacy pages that emit them. Persisted
   shapes (settings, workflow JSON, execution/cache records) have **no** removal date: their
   upgrade paths are permanent.

## 40. Legacy request-field map (frozen)

### 40.1 Provider-selection fields

Several legacy names select a provider today. All are frozen as inputs; §24.1 already fixed the
precedence between them. `v2 target` is the single field name the provider platform reads.

| # | field | read at | default when absent | v2 target | verb | owner |
|---|---|---|---|---|---|---|
| F1 | `engine` (workflow node config, `tts.generate`) | `registry.py:185-186` (schema), `adapters/tts.py:11` (`merged.get("engine","kokoro")`) | `"kokoro"` | `provider_id` | upgrade (§41.3 M1) | 12.3 |
| F2 | `provider` (workflow node config, `storyboard.generate` / `animator.generate`) | `registry.py:255-256`, `:280-281`; `adapters/storyboard.py:57`, `adapters/animator.py:66` | `"wavespeed_webhook"` / `"grok_automa"` | `provider_id` | upgrade (§41.3 M2, M3) | 12.3 |
| F3 | `provider_override` (HTTP body) | `storyboard/routes.py:311`; `animator/schemas.py:18,32` | `None` | `provider_id` | passthrough | 14.2 / 14.3 |
| F4 | `provider` (HTTP body, legacy) | `animator/schemas.py:20,35-36`; Storyboard grab-one at `storyboard/routes.py:603`; accepted but ignored by Storyboard bulk at `:311-316`; pipeline defaults at `pipeline/schemas.py:93-94` | `"midjourney"` (animator), `"webhook"` (storyboard), `"grok"` (pipeline animator) | `provider_id` via §40.3 | passthrough + alias; bulk Storyboard activation is C5 | 14.2 / 14.3 |
| F5 | `tts_provider` / `tts_provider_override` (pipeline body) | `pipeline/schemas.py:39,85`; consumed `services.py:77-82` | `"kokoro"` | `provider_id` | passthrough | 15.2 |
| F6 | `storyboard_provider` / `storyboard_provider_override` | `pipeline/schemas.py:87,93`; consumed `services.py:546,551`, then sent as the currently ignored bulk `provider` field at `:563` | `"webhook"` | `provider_id` via §40.3 | passthrough + alias; dispatch effect begins with C5 | 14.2 |
| F7 | `animator_provider_override` / `provider` | `pipeline/schemas.py:89,94`; consumed `services.py:640,645` | `"grok"` | `provider_id` via §40.3 | passthrough + alias | 14.3 |
| F8 | `storyboard_provider` / `asset_provider` (preflight) | `app.py:253-254` | `"gemini"` / `"grok"` | `provider_id` via §40.3 | passthrough + alias | 14.4 |

`script` and `scene_blueprint` appear in no row: neither their routes
(`story/routes.py:197-341`, `build_scene_blueprints/routes.py:263-372`) nor their node configs
(`registry.py:140-157`, `:235-242`) accept any provider field at all. Their v2 selection is
**new surface**, not a migration — 12.3 initially resolves an absent field to its byte-equivalent
`builtin` bridge. Phase 13 replaces that bridge with the historical concrete provider (`"gemini"`
for script, `"n8n"` for scene blueprint) while retaining `builtin` as an input alias, so workflows
saved both before and during the bridge window keep running the same service. Owners: **12.3**,
**13.1–13.3** (script), **13.4** (scene blueprint).

### 40.2 Option dictionaries and the unknown-key rule

| # | dict | read at | merge order today | v2 treatment | owner |
|---|---|---|---|---|---|
| O1 | `provider_options` (node config, `tts.generate`) | `registry.py:191`; `adapters/tts.py:12` | copied to `tts_provider_options` | retained as `provider_options`; per-run options (§22.6), validated against the provider settings schema | 12.3 / 15.2 |
| O2 | `tts_provider_options` | `pipeline/schemas.py:86`; `services.py:97` | `{**provider_settings, **options}` — request wins | unchanged order; unknown keys become a `warning`, not an error | 15.2 |
| O3 | `storyboard_provider_options` | `pipeline/schemas.py:88`; `services.py:547` | `{**provider_settings, **data.provider_options}` at `storyboard/routes.py:330` | same | 14.2 |
| O4 | `animator_provider_options` | `pipeline/schemas.py:90`; `services.py:641,653` | request options override, then `_kie_ai_options.update(provider_settings)` inverts the precedence for Kie AI | **corrected**: request wins for every provider | 14.3 |
| O5 | `segment_config` (node config) | `registry.py:221` | passed straight through | not a provider dict; untouched | — |

Unknown keys are accepted everywhere today, structurally: `PipelineRunRequest`
(`pipeline/schemas.py:99`), `GrabberStartRequest` (`animator/schemas.py:38`), and `ScenePrompt`
(`animator/schemas.py:12`) all declare `model_config = {"extra": "allow"}`. Freezing that
behavior is required by rule 1 of §39 — a legacy page sending a field this plan never inventoried
must not start failing. The v2 rule is therefore **accept, warn, drop before dispatch**:
an unknown key never reaches a provider, never reaches a result, and never contributes to a
fingerprint. The warning uses the §22.5 `unknown_key` severity, and O4's inverted precedence is
the one deliberate behavior change in this table — it is a defect fix, recorded in §47 as C4.

### 40.3 Provider identity: the canonical ID and alias table (frozen, both directions)

§14.4 inventoried three separate mapping sites pointing in two directions. This is the single
table that replaces them; it is data for the `aliases` manifest field (D5, owner 11.2), not code.

| domain | canonical ID | legacy aliases accepted (input) | legacy string emitted (output, until 16.1) | emitted at |
|---|---|---|---|---|
| `tts` | `kokoro` | — | `kokoro` | `tts/routes.py:721` |
| `tts` | `inworld` | — | `inworld` | `tts/routes.py:783` |
| `storyboard` | `gemini_ws` | `gemini` | `gemini` | `services.py:550`, `app.py:253` |
| `storyboard` | `wavespeed_webhook` | `webhook` | `webhook` | `services.py:550` |
| `storyboard` | `wavespeed_direct` | `direct` | `direct` | `services.py:550` |
| `animator` | `grok_automa` | `grok`, `midjourney` | `grok` | `services.py:644`, `animator/schemas.py:35`, `app.py:254` |
| `animator` | `kie_ai` | `kie-ai` | `kie-ai` | `services.py:644`, `animator/schemas.py:35` |
| `script` | `gemini` (the current AI story service) | `builtin` (the 12.3 bridge ID) | — | new (13.2) |
| `script` | `random_template` | — | — | new (13.1) |
| `scene_blueprint` | `n8n` | `builtin` (the 12.3 bridge ID) | — | new (13.4) |

Frozen rules:

1. **Aliases are input-only and lossless.** Resolution is id-first, then alias (§20.3). An alias
   never appears in a `ProviderResult`, a `provenance` block, an execution record, or
   `settings.json`; only the canonical ID is persisted.
2. **`midjourney` is an alias, not a provider.** `animator/schemas.py:35` maps it to
   `grok_automa` and `animation_routes.py:260` still branches on it (P12, unreachable). The alias
   survives; the branch is deleted by 14.3.
3. **The output column is a wire-compatibility shim with an end date.** The legacy strings exist
   only because `services.py` reaches its own HTTP API (blocker B1) and because
   `/api/pipeline/preflight` publishes them. When 16.1 removes the internal hop, the output
   column is deleted and canonical IDs go on the wire; the input column stays.
4. **`script` and `scene_blueprint` have no pre-Phase-10 provider vocabulary**, but each accepts
   the transitional `builtin` ID that 12.3 necessarily persists before the real Phase 13 provider
   packages land. The alias is permanent input compatibility. `script` is the one domain that gains
   a *second* provider during migration (`random_template`, 13.1); the default becomes `gemini` so
   the random-story UI action selects `random_template` explicitly rather than changing the domain
   default.

### 40.4 The Storyboard internal-hop null defect (new finding, owner 14.2)

`services.py:551` is `id_to_legacy.get(sb_override) if sb_override else …`. A `.get()` with no
default returns `None` for any ID outside the three-entry table, and that `None` is then sent as
`payload["provider"]` at `services.py:563`. The current bulk Storyboard route does not read that
legacy field at all: it reads only `provider_override` and otherwise uses stored settings
(`storyboard/routes.py:311-316`). Thus the null is real wire output, but it is not currently a
dispatch blocker; the legacy field is dead on this endpoint.

The Animator mapping at `services.py:644-645` is not the same defect. Its result is used only to
decide whether to add Grok-specific options; the request sends the canonical `provider_override`
at `:652`, so no null provider identity crosses that boundary. Both hand-written tables are still
retired in favor of §40.3, but only Storyboard needs the passthrough fix: before 14.2 starts honoring
the legacy bulk field, an unmapped canonical ID must pass through unchanged. A regression test with
the fixture provider must assert the Storyboard wire value is its canonical ID, not `null`.

## 41. Workflow node configs and `type_version` (frozen)

### 41.1 Current state, verified

- Every node type in the registry declares `type_version: 1` — 23 occurrences, `registry.py:69`
  through `:489`, with the five provider-touching nodes at `:133` (`story.generate`), `:177`
  (`tts.generate`), `:227` (`scenes.blueprint`), `:247` (`storyboard.generate`), `:271`
  (`animator.generate`).
- **Zero migrations are declared.** `migrations` appears only as a lookup
  (`migrations.py:82`), a validator for generated definitions (`registry.py:550-567`), and an
  internal field stripped from the served payload (`registry.py:608`). No node defines one.
- The machinery is complete and strict: `migrate_workflow` (`migrations.py:44-127`) requires
  **every hop**, raising `NodeMigrationError` when a hop is missing (`migrations.py:85-88`), and
  `is_supported` demands exact equality (`registry.py:621-623`).

### 41.2 The bump rule (frozen)

Because a missing hop raises rather than degrades, and because `load_workflow_state` runs
`migrate_workflow` before validation (`persistence.py:181,189`), the rule is absolute:

> **Bumping `type_version` on a node without shipping the `N → N+1` migration in the same commit
> makes every saved workflow containing that node unloadable.**

Therefore: a provider migration step may bump a node's `type_version` **only** when it renames,
removes, or re-types a persisted config key. Adding an optional key with a default, changing a
label, or changing an `options_source` does **not** bump the version — those are compatible under
the existing config-schema validation and would only invalidate caches for no benefit (§45).
Every migration is a pure `dict -> dict` function, declared as a `module:function` string so
generated definitions and built-ins share one form (`migrations.py:31-41`).

### 41.3 The four frozen migrations

These are the complete set of `type_version` bumps the provider platform is permitted to make.
Anything not listed here keeps `type_version: 1`.

| # | node | v1 → v2 change | migration | owner |
|---|---|---|---|---|
| M1 | `tts.generate` | `engine` → `provider_id`; existing `provider_options` retained | `cfg["provider_id"] = cfg.pop("engine", "kokoro")`; `provider_options`/`voice`/`speed` untouched | 12.3 |
| M2 | `storyboard.generate` | `provider` → `provider_id`; `prompt_prefix`/`auto_type` move into per-run provider options (D19/P27) | `cfg["provider_id"] = cfg.pop("provider", "wavespeed_webhook")`; move the two gated keys into `cfg["provider_options"]` | 12.3 |
| M3 | `animator.generate` | `provider` → `provider_id`; `mode`/`quality`/`duration`/`auto_type` move into per-run provider options | `cfg["provider_id"] = cfg.pop("provider", "grok_automa")`; move the gated keys into `cfg["provider_options"]` | 12.3 |
| M4 | `story.generate`, `scenes.blueprint` | accept an absent `provider_id` with the default that reproduces today's hard-wired service | adapter/selection code uses `cfg.get("provider_id") or ("gemini" \| "n8n")` without mutating the saved configuration — **no bump required**, since nothing is renamed | 12.3; verified 13.3 / 13.4 |

M1–M3 bump to `type_version: 2` and ship their migration in the same commit. M4 is deliberately
**not** a bump: a non-mutating read fallback is sufficient because the key is new and optional.
Using `setdefault` would change the fingerprinted configuration and invalidate the cache it is
supposed to preserve (`cache.py:50-55`). The migration values are exactly
today's effective defaults, so a saved workflow produces byte-identical requests after upgrade —
that equivalence is the acceptance test in §48.

Two consequences that must not be missed:

1. **Node ports do not change.** No migration in this table alters a port ID or type, so no saved
   edge is invalidated and §3's compatibility matrix is untouched.
2. **`display_options.show.provider` disappears with M2/M3.** The gating key is renamed, so any
   remaining `display_options` referencing `provider` must be updated in the same commit or the
   field silently stops showing. Owner **12.3** verifies this in the inspector.

### 41.4 Future versions and downgrade

Already correct and frozen as-is: a stored version above the installed one marks the workflow
`read_only` with a `FUTURE_NODE_VERSION` warning rather than failing (`migrations.py:69-80`), and
validation is told to tolerate it (`persistence.py:189`). There is no downgrade path and none is
added — a user who opens a v2 workflow on an older install gets a readable, non-editable graph.

## 42. Saved provider settings (frozen)

Current on-disk shape, read verbatim from `settings/settings.json`: `{"version": 1, "general":
{...}, "domains": {"tts"|"storyboard"|"animator": {"selected_provider", "per_provider": {...}}}}`,
with `_default_settings` writing `"version": 1` (`settings_manager.py:140`).

| # | change | verb | detail | owner |
|---|---|---|---|---|
| S1 | add `script` and `scene_blueprint` domains | upgrade | added with the §19.1 transitional `builtin` selection and an empty `per_provider`; existing domains untouched | 11.1 / 11.3 |
| S2 | adopt the three `app-config.json` legacy selection keys | upgrade | exactly as frozen in §24.3, normalized through §40.3 | 11.3 / 12.4 |
| S3 | unknown domain / unknown provider already present in the file | passthrough | preserved verbatim, reported as a `warning`; never deleted, because a provider directory may return | 11.3 |
| S4 | `version` bumped to `2` | upgrade | written atomically together with S1+S2 | 11.3 |
| S5 | secret values already stored in `per_provider.*.api_key` | passthrough | stay where they are; only their *serialization* changes (redaction, D12) | 11.3 / 11.5 |
| S6 | Script selection `builtin` → `gemini` | upgrade | when the 12.3 bridge is replaced, rewrite only the transitional value; preserve `random_template` or any other explicit selection | 13.2 / 13.3 |
| S7 | Scene Blueprint selection `builtin` → `n8n` | upgrade | when the 12.3 bridge is replaced, rewrite only the transitional value | 13.4 |

Two defects block S1–S4 and are restated here so 11.3 cannot miss them. S6 and S7 are later,
sequential settings migrations with their own version bumps; they must not be folded into v2 before
their replacement providers exist:

- **`apply_migrations` cannot run an upgrade.** `settings_migrations.py:41-46` skips every
  registered version `>= current_version`, so a v2 migration never runs on a v1 file, and the
  function never writes `data["version"]` back. §24.3 already assigned the correction to **11.3**;
  §48's acceptance list makes v1→v2, already-v2 idempotence, and an interrupted write the three
  required tests.
- **`validate_settings` hardcodes the three domains** (`settings_manager.py:270`), so S1's two
  new domains would be reported as `Unknown domain` warnings on every load. D1 (owner 11.1)
  replaces this set with the catalog; S1 must not land before it.

`_seed_from_env` is *not* in this table. It runs only when the file is absent
(`settings_manager.py:49-54`), and D11 (owner 11.3) already removes its two side effects: copying
secret values into the file (`:87`, `:96`, `:100`) and flipping the TTS selection to `inworld`
(`:88`). After D11, a fresh install with `INWORLD_API_KEY` set gets `kokoro` selected and the key
read at request time — a deliberate behavior change, listed in §47 as C1.

## 43. Legacy API envelopes (frozen)

Every envelope below is **passthrough**: the top-level key set is frozen, and the migration may
only *add* keys. No legacy consumer breaks, because no key it reads is removed or re-typed.

| route | envelope (verified) | v2 additions | owner |
|---|---|---|---|
| `POST /api/story/generate` | `{"success": true, "project_id", "story_text", "sections", "duration", "estimated_duration", "language", "story_category", "story_tone", "preset_style", "provider", "word_count", "generation_time", "timestamp", "concept_family"}` (`story/routes.py:276-292`) | `provider` becomes the resolved canonical ID instead of the literal `"gemini"` (P33) | 13.3 |
| `POST /api/scenes/generate` | `{"project_id", "scenes", "style", "style_spec", "style_prompt", "timestamp", "generation_time", "total_duration"}` (`build_scene_blueprints/routes.py:350-363`) | `provider` added | 13.4 |
| `POST /api/tts/generate` | flat dict incl. `"provider": "kokoro"` (`tts/routes.py:721`) / `"inworld"` (`:783`) | none | 15.2 |
| `POST /api/storyboard/generate` | Gemini branch: `{"status": "running", "project_id", "total", "provider"}`; webhook/direct branch: `{"status": "running", "project_id", "total"}`; HTTP 202 (`storyboard/routes.py:346-359`) | `provider` may be added to the webhook/direct variant; existing keys and types stay unchanged | 14.2 |
| `GET /api/storyboard/status/<id>` | `{"project_id", "status", "total", "ready", "errors", "scene_statuses", …}` | `units[]` added alongside `scene_statuses`, which stays (§36 L10) | 14.2 |
| `POST /api/animator/grabber/start` | `{"job_id", "total", "status"}` | none | 14.3 |
| workflow API | `{"error": {"code","message","details?"}}` on failure (§6) | unchanged; §34.2 adds no new §7 code | 11.4 |

The one asymmetry worth stating plainly: the legacy routes return flat success dicts while the
workflow API returns the `{"error": {...}}` envelope. **They are not unified.** Unifying them
would break every legacy page for no benefit to this migration; §17.1 already classes the legacy
envelopes as public compatibility surface.

## 44. Output paths and artifacts (frozen — no relocation)

| domain | managed path | built at |
|---|---|---|
| `script` | `output/stories/<project_id>/…` | `adapters/story.py:23` (path returned by the service) |
| `scene_blueprint` | `output/scenes/<project_id>/scenes.json` | `adapters/scenes.py` via `config.SCENES_DIR` |
| `tts` | `output/tts/<project_id>/voice.wav` + `tts.json` | `services.py:99-101`; `adapters/tts.py:14` |
| `storyboard` | `output/storyboard/<project_id>/storyboard.json` + images | `adapters/storyboard.py:20,73` |
| `animator` | `output/animator/<project_id>/grabber_job.json` + assets | `adapters/animator.py:44` |

**No path changes.** Relocating artifacts would strand every existing project and invalidate every
cache entry through `upstream_artifact_fingerprints` for zero contract benefit. §30.2 already made
`artifact_refs` (relative, `output/`-rooted) authoritative; what changes is only *which key the
consumer reads*, not where the bytes live.

L7 is resolved (step 15.3):

1. `artifact_refs` is authoritative (11.4 onward).
2. Absolute `wav_path` / `path` no longer leave `tts.generate` on either port; relative
   `wav_path` remains for sample-fixture / `tts_metadata` shape compatibility.
3. `adapters/timing.py` resolves through `resolve_ref`. `ADAPTER_CACHE_SCHEMA_VERSION`
   bumped to 2 in the same commit so every prior TTS/alignment cache entry is a clean miss
   rather than a silent shape mismatch.

## 45. Execution and cache records (frozen)

| record | version field | verified | migration |
|---|---|---|---|
| execution record | `schema_version: 1` | `models.py:45` | **none** — records are append-only history, never re-read for execution |
| node execution record | `schema_version: 1` | `models.py:65,73` | none |
| cache entry | `cache_schema_version: 1` | `cache.py:22,167,207` | **none** — invalidate, never migrate |
| adapter cache schema | `adapter_cache_schema_version: 1` | `cache.py:23,55` | bumped deliberately (below) |

Frozen rules:

1. **Execution records are never migrated.** They are a historical log. A record written under v1
   is read only for display; a reader encountering an unknown `schema_version` shows it and does
   not attempt to interpret provider-specific fields.
2. **Cache entries are invalidated, not upgraded.** The fingerprint already contains
   `type_version` and `adapter_cache_schema_version` (`cache.py:50-55`), and a mismatch yields a
   clean miss with the reason `type_or_version_changed` or `adapter_schema_changed`
   (`cache.py:117-120`). That is the correct and only mechanism.
3. **Which changes must bump `ADAPTER_CACHE_SCHEMA_VERSION`.** Any change to what an adapter
   *returns* for identical inputs — the §31 result envelope, dropping remote URLs (D38), adding
   `provenance` (D39), or the L7 removal in §44 — is invisible to the config/input fingerprint and
   therefore requires a bump in the same commit unless that affected node's `type_version` also
   changes in that commit. An earlier global bump does not cover a later output change: cache entries
   written between the two commits carry the newer global version but the older output. Owner 11.4
   bumps only if its adapter outputs change; each domain owner applies this rule again.
4. **The cost is bounded and stated.** A global bump invalidates every cached node result, so the first
   run after upgrade recomputes everything. This is preferable to the alternative — a stale cached
   payload in the old shape being handed to a v2 consumer — and it is why rule 2 forbids migrating
   cache entries.
5. **M1–M3 (§41.3) invalidate their own nodes' caches** through `type_version`, which is the
   desired behavior: the config changed shape, so the previous result is not provably reusable.

## 46. Fixture map and ownership (frozen)

### 46.1 What exists, and the gap

`studio/workflows/fixtures/` is frozen, offline-reproducible, and manifest-hashed (§10, step 2.5),
and `pytest.ini:3` gates live tests behind `STS_LIVE=1`, honored by
`tests/test_live_providers.py`. That covers **port payloads**. It does not cover **provider
boundaries**: today there is no fake provider anywhere in the repo, and adapter tests fake the
orchestration instead — `tests/test_workflow_adapters.py` monkeypatches `_step_tts`,
`_step_scenes`, `_step_storyboard`, i.e. the very functions the migration replaces. Those tests
verify the adapter contract and will keep passing while the provider layer beneath them is
rewritten, which is exactly the coverage gap this step must close.

The archived JSON in `_dev/fixtures/` (`scene-output-v1.json`, `scene-output-v2.json`,
`scene-output-n8n-wrapped.json`, `alignment-sample.json`, `request-sample.json`) is real recorded
provider output but is referenced by no test. `scene-output-n8n-wrapped.json` is promoted to a
first-class fixture by 13.2, since it is the only recorded example of the n8n envelope the scene
blueprint provider must parse.

### 46.2 The two fixture layers (frozen)

| layer | root | owner | purpose |
|---|---|---|---|
| **port fixtures** (existing) | `studio/workflows/fixtures/` | already frozen; unchanged by this migration | what flows *between* nodes |
| **provider fixtures** (new) | `tests/fixtures/providers/<domain>/<provider_id>/` | 11.4 creates the layout; each domain step fills it | what crosses the *provider* boundary |

A provider fixture directory contains, per provider: `request.json` (the frozen §32 domain
request), `raw_response.json` (recorded provider payload, secrets stripped, absolute paths
stripped), and `expected_result.json` (the §31 `ProviderResult` the adapter must produce from it).
Media bytes are **not** re-recorded — a provider fixture referencing media points into
`studio/workflows/fixtures/media/`, so the repo keeps exactly one copy of every byte.

### 46.3 Ownership per boundary

| domain | provider | fixture source | owner |
|---|---|---|---|
| `script` | `gemini` | recorded n8n story response, secrets stripped | 13.1 / 13.3 |
| `script` | `random_template` | hand-written deterministic template request/result | 13.1 |
| `scene_blueprint` | `n8n` | `_dev/fixtures/scene-output-n8n-wrapped.json` promoted + `scene-output-v2.json` | 13.2 / 13.4 |
| `tts` | `kokoro` | synthesized locally — `voice.wav` already exists and is reproducible | 15.1 / 15.2 |
| `tts` | `inworld` | recorded response, key stripped; audio replaced by the fixture WAV | 15.2 |
| `storyboard` | `gemini_ws` | recorded extension WebSocket frames | 14.2 |
| `storyboard` | `wavespeed_webhook` | recorded webhook callback body | 14.2 |
| `storyboard` | `wavespeed_direct` | recorded direct API body (the key is 401 — §17.4; the *shape* is still recordable from the archived body) | 14.2 |
| `animator` | `grok_automa` | recorded Automa payload + job manifest | 14.3 |
| `animator` | `kie_ai` | recorded job submit/poll pair | 14.3 |
| all five | `fixture_provider` | **hand-written**, no recording | 11.2 |

`fixture_provider` is the load-bearing one: a deterministic in-repo provider package registered in
every domain, used to prove discovery, duplicate handling, broken-plugin isolation (11.2), the
result/error envelope (11.4), and — critically — §26's zero-touch assertion and §40.4's total
alias mapping, both of which need a provider that is *not* in any hardcoded list.

### 46.4 Rules (frozen)

1. **No fixture requires credentials or network.** A provider contract test runs from
   `raw_response.json`; recording is a one-time human act, never part of the test.
2. **Recording is sanitized at record time**: no API keys, no absolute paths, no wall-clock
   timestamps, no account identifiers. A fixture-sanitization validator runs over `request.json`,
   `raw_response.json`, and `expected_result.json` in CI. The stricter §36 egress validator runs over
   `expected_result.json` and actual `ProviderResult` values, not raw provider responses: a raw
   Storyboard/Animator response may need a synthetic remote URL to exercise the code that must remove
   it before egress.
3. **Live tests stay gated** behind `pytest.ini:3` / `STS_LIVE=1` and are never the only coverage
   of a boundary. Every provider in §46.3 has an offline fixture even where the live credential
   works.
4. **Fixture drift is mechanical.** Provider fixtures get the same manifest-with-SHA-256 treatment
   as the port fixtures (§10), so an accidental edit fails a test rather than silently changing
   the meaning of every provider test.
5. **The three unusable live providers** (WaveSpeed 401, retired n8n webhook, human-driven
   `grok_automa` — §17.4) are exactly why 46.3 is mandatory: for these, the offline fixture is the
   *only* possible verification, and their migration steps cannot be gated on live access.

## 47. Contract-vs-code review — the deliberate shims

Reviewing §19–§46 against the shipped code, five obligations cannot be met without a deliberate
compatibility shim or an acknowledged behavior change. Each is accepted here rather than
discovered mid-implementation.

| # | obligation | why the code cannot meet it cleanly | frozen decision | owner |
|---|---|---|---|---|
| C1 | §22.6 — env vars are read-time fallbacks that never change a selection | `_seed_from_env` flips TTS to `inworld` when `INWORLD_API_KEY` is set (`settings_manager.py:85-88`) and this machine's `settings.json` already records `"selected_provider": "inworld"` | the *existing* file is left alone (it is now an explicit user choice); only future seeding stops flipping. Fresh installs behave differently from today — accepted | 11.3 |
| C2 | §24.1 rule 3 — `settings.json` is authoritative for every domain | `animation_routes.py:194` never reads `domains.animator.selected_provider` (D15/§24.1) | wiring it changes what an existing animator run selects when the modal and settings disagree. Accepted, and 14.3 must state the resulting behavior in its record | 14.3 |
| C3 | §32.4 / §36 L9 — remote URLs never cross into results | `image_url` is persisted inside `storyboard.json` (`storyboard/routes.py:233`) and re-read by `adapters/storyboard.py:46`, so old manifests on disk contain them | reading an old manifest strips the field at load; the *file* is not rewritten. A shim, deliberately, because rewriting user projects to satisfy an egress rule is worse than filtering on read | 14.2 |
| C4 | §22.6 — request options override stored settings | `_kie_ai_options.update(provider_settings)` inverts precedence for Kie AI only (§40.2 O4) | corrected to request-wins for all providers. A behavior change for anyone relying on the inversion; no evidence anyone does | 14.3 |
| C5 | §24.1 — an explicit legacy request provider wins over stored settings | the bulk Storyboard route ignores its accepted-extra `provider` field and reads only `provider_override`; the pipeline sends only `provider` (`services.py:563`) | 14.2 normalizes `provider_override` first, then the legacy `provider` alias, then stored settings. Activating the previously dead legacy field is an intentional behavior correction when it disagrees with settings | 14.2 |

Two further review findings change no contract but do change later steps:

- **§40.4 remains a 14.2 compatibility obligation, not an 11.2 discovery blocker.** The current
  Storyboard bulk route ignores the possibly-null legacy field, and Animator transmits its canonical
  override separately. The fixture provider becomes the regression case when 14.2 activates legacy
  Storyboard field handling.
- **M4 (§41.3) removes a planned bump.** Adding `provider_id` to `story.generate` and
  `scenes.blueprint` was assumed to need a version bump; it does not, and not bumping preserves
  every existing cache entry for those nodes. Owner **12.3** supplies a non-mutating fallback;
  **13.3** and **13.4** verify it through the migrated domain implementations.

No later step needs its scope changed beyond these two notes; every other obligation in §19–§46
is reachable with the owners already assigned in §28 and §37.

## 48. Implementation gate

### 48.1 Acceptance criteria for the phases that follow

Each is a test, not a review item, and each names the step that must make it pass.

| # | criterion | owner |
|---|---|---|
| A1 | A workflow JSON saved before the migration loads, validates, and executes with no manual edit, for all five provider nodes | 11.4 / each domain step |
| A2 | M1–M3 are byte-equivalent: a v1 node config, migrated, produces the identical provider request to the v1 path | 12.3; reverified 14.2 / 14.3 / 15.2 |
| A3 | `settings.json` v1 → v2 upgrades, is idempotent on re-run, and survives a simulated interrupted write | 11.3 |
| A4 | Every legacy request field in §40.1 and every alias in §40.3 resolves to the correct canonical provider | 11.2 |
| A5 | A registered fixture provider absent from every hardcoded list is discoverable, invocable through the standard runtime, and never transmits `null` through the Storyboard compatibility hop (§40.4) | 11.2 / 11.4 / 14.2 |
| A6 | Every legacy envelope in §43 keeps its full key set | each domain step |
| A7 | Provider contract tests for all ten production domain/provider pairs pass with no network and no credentials | 11.4 + each domain step |
| A8 | Fixture sanitation passes over every fixture; the §36 egress validator passes over every `expected_result.json` and actual provider result | 11.4 |
| A9 | For every output-shape migration, a cache entry written immediately before that change is a clean miss, never a stale hit | 11.4 + each output-changing domain step |

### 48.2 Baseline verification (2026-08-09, commit `5330f9e`)

Recorded before any Phase 11 code lands, so a later regression is attributable:

- `venv/Scripts/python.exe -m pytest tests/ -q` — **224 passed, 10 skipped, 62 subtests**
  (the 10 skips are `tests/test_live_providers.py`, gated by `STS_LIVE`).
- `cd frontend && npm run test` — **154 passed across 25 files**.
- `cd frontend && npm run build` — production build succeeds (`✓ built in 1.22s`).
- `venv/Scripts/python.exe -m studio.workflows.docs --check` — `OK: generated workflow
  documentation matches contracts and registry.`

Phase 10 changed documentation only, so these are the numbers any Phase 11 regression is measured
against. They are **three backend and four frontend tests above** the counts recorded at the Phase
9 gate (221 / 150). The delta is accounted for and is not Phase 10's: `cc0e3ba` added
`tests/test_loop_engineering_agents.py`, and `8132931` plus `d276aec` added workflow-canvas
frontend tests — all three landed between the Phase 9 gate and Phase 10. The four Phase 10 commits
touched no test file. Re-measuring rather than copying the older figures is the point: an
unexplained delta at the Phase 11 gate is a regression, and it can only be read as one against a
freshly measured baseline.

## 49. Phase 10.4 coverage assertion

Frozen by this section: a three-verb compatibility policy with an idempotence rule, a write-once
rule, and a stated support window that separates removable wire compatibility from permanent
persisted-shape compatibility; the complete legacy request-field map — eight provider-selection
fields with their read sites, defaults, and v2 targets, and five option dictionaries with their
merge order and the accept-warn-drop rule for the unknown keys that three `extra="allow"` models
accept today; one canonical provider ID and alias table replacing the three mapping sites §14.4
found, valid in both directions with an explicit end date for the emitted legacy strings; the
`type_version` bump rule derived from the fact that a missing migration hop raises rather than
degrades, together with the exact four config migrations the platform is permitted to make and
the reason two of them require no bump at all; the settings upgrade path with its two blocking
defects restated against their owners; the frozen legacy API envelopes with their additive-only
rule and the deliberate decision not to unify them with the workflow error envelope; the frozen
artifact layout and the staged retirement of the absolute TTS path keys; the invalidate-never-
migrate rule for cache entries with per-change `ADAPTER_CACHE_SCHEMA_VERSION` bumps when a node
version bump does not already invalidate the affected entry, and their stated cost; and a two-layer
fixture map that adds a provider-boundary layer beside the existing port fixtures, with per-boundary
ownership for all ten production domain/provider pairs plus the
`fixture_provider` that makes the zero-touch assertion testable.

The contracts were reviewed against the shipped code: five obligations that need a deliberate
shim or an acknowledged behavior change are recorded in §47 with their owners, and two review
findings correct later work — the Storyboard legacy field is activated with total alias passthrough
in 14.2, while the Animator path is recognized as already carrying its canonical override, and the
`story.generate`/`scenes.blueprint` version bump is dropped as unnecessary. Nine acceptance criteria
and a freshly measured baseline (224 backend tests with 10
live skips, 154 frontend tests, a clean production build, and no generated-doc drift) close the
gate.
Phase 11 can begin without inventing semantics: every value that is persisted or on the wire today
has a named verb, a named boundary, and a named owner.
