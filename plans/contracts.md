# Scriptase — Machine Contracts

Frozen schemas, API shapes, and error codes. Reviewers check implementations against this
file; the orchestrator's review prompts cite it by name.

> **Status: FROZEN at step 0.4 (2026-08-14).**
> Adapted from V2's contracts under Scriptase import paths, extended with Scriptase
> domain schemas, and verified against working ported code. Where this file and working
> code disagree, **the code wins** and this file is corrected in the same commit.
> Implementations in Phases 1–10 build against these shapes; they do not invent parallel
> ones.

Conventions: field names are snake_case; timestamps are ISO-8601 UTC / RFC 3339 strings;
ids are opaque strings with a documented prefix; every persisted document carries
`schema_version` (or `result_version` / `type_version` where noted); forward-only
migrations, never destructive rewrites. Secrets are write-only — never returned in an API
response, workflow JSON, Job snapshot, execution record, SSE event, log, error, archive,
notification, or export.

---

## 0. Scope map — every schema Phases 1–10 touch

| Schema / contract | Frozen here | Implemented at |
|---|---|---|
| Node definition, port types, port IDs | §1 | ported (0.2); presentation via `GET /api/workflow/node-types` |
| Workflow JSON document | §1.4 | ported |
| Execution record + SSE | §1.5–1.6 | ported |
| Provider result envelope + `ProviderError` | §1.7–1.8 | ported |
| Provenance (incl. seed / request_id / model_revision) | §2 | extended 0.4; instance id at 3.1; per-unit use at 8.3 |
| Artifact | §3 | 1.2 |
| Scene identity + re-segmentation | §4 | 1.6 (implemented) |
| ChannelProfile | §5 | 1.1 / 1.3 |
| Job | §6 | 1.4 / 1.5 |
| ProviderInstance | §7 | 3.1 / 3.2 |
| SceneSpec | §8 | 5.1 (implemented) |
| Timing strategy AUTO + alignment schema | §8.1 | 5.3 (implemented) |
| ReviewIssue + repair routing table | §9 | 7.2 / 8.1 |
| Stage projection | §10 | 2.2 |
| ApprovalCheckpoint | §11 | 2.6 |
| Budget / admission control | §12 | 3.5 / 9.3 |
| Error codes (workflow + provider + Scriptase) | §13 | ported + additive |
| Repair history entry | §9.1 | 8.4 |
| Cost accounting record | §12.1 | 9.3 |
| Execution modes | §6 | 9.1 |
| Secret references | §7 | 3.4 |
| V2 import mapping | §14 | 10.1 |

---

## 1. Inherited from V2 — adapted

Package renames applied during the port: `studio` → `scriptase`,
`workflows` → `engine`, `providers_common` → `providers`, `story` → `script`,
`build_scene_blueprints` → `scene_director`, `storyboard` → `image`,
`animator` → `video`, `editor` → `compose`. **Node type keys, port ids, and port types
did not rename** — saved workflows store them.

### 1.0 Node definition

A node type is a registry entry with:

- stable `type` key (e.g. `tts.generate`, `storyboard.generate`)
- `type_version` (positive integer; migrations are forward-only and refuse skipped hops)
- ports (`inputs[]` / `outputs[]` with stable `id`, `type`, `required`, `multiple`)
- `config_schema` (JSON Schema + widget hints)
- capabilities (e.g. `provider_capable`, cache, cancel)
- dotted `module:function` executor string — **internal only; never serialized to the browser**

The backend registry (`scriptase/engine/registry.py`) is authoritative. The frontend
renders entirely from `GET /api/workflow/node-types` and hardcodes nothing but SVG icon
paths and port colours.

Adapter signature: `(inputs, config, context) -> dict[port_id, payload]`. Explicit node
config beats inherited channel/settings config; an **empty string is not explicit**.

### 1.1 Port types & compatibility matrix

Adapted from V2 at step 0.2, ahead of the rest of section 1, because the generated node
author guide reads this prose verbatim and the doc-drift gate depends on it. The type
inventory is deliberately stated here as prose only — `scriptase/engine/registry.py` is the
executable source of truth for the list itself.

Types (v1): `control, text, script, project_id, project_settings, audio_file, tts_metadata, alignment, segments, scenes, image_prompts, storyboard_images, animation_assets, captions, music_track, editor_project, export_profile, video_file, generic_json`.

Compatibility rule: **exact type match only.** No wildcard: `generic_json` connects only to `generic_json`. `stub.input`/`stub.output` resolve their dynamic type from configuration at validation time and then obey exact-match. Additional rules: no in→in / out→out; single-value inputs reject a second edge; DAG only (cycle rejection); control edges distinct from data edges. Every payload that references files carries `{artifact_refs: [relpaths]}` alongside inline JSON; integrity check = existence + nonzero size.

Data edges establish both a dependency and a typed value. Control edges establish only a
dependency and never satisfy a required data input. A node with a connected `trigger` waits
for that control predecessor as well as all required data. An unconnected optional `trigger`
does not block a node. A node emits `control` only after successful completion; skipped,
failed, and cancelled propagation is handled explicitly by scheduler policy rather than by
fabricating a success token. These rules make Manual Trigger useful without making it
mandatory for partial or isolated execution.

### 1.2 Node type keys survive the rename

Step 0.2 renamed packages and provider **domain ids**, not the graph contract. Node type
keys (`story.generate`, `storyboard.generate`, `animator.generate`, `scenes.blueprint`),
port ids, and port types (`storyboard_images`, `animation_assets`) are unchanged, because a
saved workflow stores them. What did change is summarized in §1.3.1 below.

### 1.3 Stable port IDs (core production nodes)

| node type | inputs (`id:type`, `?` optional) | outputs (`id:type`) |
|---|---|---|
| `trigger.manual` | — | `control:control` |
| `project.setup` | `trigger:control?` | `control:control`, `settings:project_settings` |
| `script.input` | `trigger:control?` | `control:control`, `script:script` |
| `story.generate` | `trigger:control?`, `settings:project_settings?` | `control:control`, `script:script` |
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
| `utility.set_value` | `trigger:control?`, `value:generic_json?` | `control:control`, `value:generic_json` |
| `utility.condition` | `trigger:control?`, `value:generic_json` | `true:generic_json?`, `false:generic_json?` |
| `utility.wait` | `trigger:control?`, `value:generic_json?` | `control:control`, `value:generic_json` |
| `utility.merge` | `values:generic_json` (`multiple`) | `control:control`, `value:generic_json` |

Utility semantics (condition skip/join, merge skip-tolerance, wait non-cacheability) are
as implemented in the ported scheduler; do not re-derive them.

### 1.3.1 Rename axes that *did* change

| Axis | V2 | Scriptase |
|---|---|---|
| Provider domain id | `scene_blueprint`, `storyboard`, `animator` | `scene_director`, `image`, `video` |
| Option source id | `scene_blueprint_providers`, `storyboard_providers`, `animator_providers`, `storyboard_image_models` | `scene_director_providers`, `image_providers`, `video_providers`, `image_models` |
| Adapter module | `adapters/story.py`, `scenes.py`, `storyboard.py`, `animator.py`, `editor.py` | `adapters/script.py`, `scene_director.py`, `image.py`, `video.py`, `compose.py` |
| Settings `domains` block key | `scene_blueprint`, `storyboard`, `animator` | renamed by settings migration **v5** |

`providers/domains.py` carries `DOMAIN_ALIASES` and `canonical_domain()` — the single
translation point. Aliases are **input only**; nothing serializes them back out.

### 1.4 Workflow JSON schema

`schema_version: 1`. Persisted under `output/workflows/{workflow_id}.json` via
`safe_json_write`; soft-delete to `output/TRASH/workflows/`.

| field | rule |
|---|---|
| document | JSON object, UTF-8, max 2 MiB after encoding, max nesting depth 20 |
| `schema_version` | required integer, exactly `1` |
| `workflow_id` | server-generated on create; `^wf_[A-Z0-9]{6}$` |
| `name` | required trimmed string, 1–120 characters |
| `description` | string, 0–2,000 characters |
| `nodes` | required array, 0–200 unique nodes |
| `edges` | required array, 0–500 unique edges |
| node `id` | `^[A-Za-z][A-Za-z0-9_-]{0,63}$`, unique |
| node `type` | required registry key, max 80 characters |
| node `type_version` | required positive integer supported by the registry |
| node `name` | trimmed string, 1–120 characters |
| node `position.x/y` | finite number in `[-1000000, 1000000]` |
| node `configuration` | JSON object, max 256 KiB per node, schema-validated |
| node `disabled` | required boolean |
| edge `id` | `^[A-Za-z][A-Za-z0-9_-]{0,63}$`, unique |
| edge endpoints/ports | existing node IDs and registry port IDs; max 64 characters each |
| edge `edge_type` | `data` or `control`, matching source/target port types |
| `variables` | finite JSON object, max 64 KiB |
| `viewport` | finite `x/y`; `zoom` in `[0.1, 1.5]` |
| `settings.on_error` | `stop` in v1 |
| timestamps | RFC 3339, server-owned |

V1 rejects unknown fields at the document, node, and edge levels. Forward-compatible
metadata lives under a bounded `extensions` object (optional, ignored by execution,
round-tripped). JSON numbers must be finite.

**Expressions** (whitelist-only): a string containing exactly one whole-value reference
`{{ nodes.<node_id>.outputs.<port_id> }}`, `{{ workflow.project_id }}`, or
`{{ variables.<name>[.<nested>...] }}`. No interpolation, operators, calls, or other roots.
Node-output references must name a strict graph ancestor in the selected execution scope.

**IDs:** API IDs must match `^wf_[A-Z0-9]{6}$` or `^ex_[A-Z0-9]{6}$` (or `^pm_[A-Z0-9]{6}$`
for projects) before `safe_join`. Never normalize invalid IDs into acceptance.

### 1.5 Execution record

```jsonc
{
  "schema_version": 1,
  "execution_id": "ex_XXXXXX",
  "workflow_id": "wf_XXXXXX",
  "workflow_snapshot": { /* full workflow JSON at run time */ },
  "project_id": "pm_XXXXXX",
  "run_mode": "full|node_with_deps|node_isolated|selected|from_node|retry_failed|retry_failed_desc",
  "scope_node_ids": ["n_tts"],
  "status": "running|succeeded|failed|cancelled|partial|awaiting_approval",
  "started_at": "ISO", "finished_at": "ISO|null",
  "nodes": {
    "n_tts": {
      "status": "idle|invalid|queued|running|waiting|awaiting_approval|succeeded|failed|cancelled|skipped|stale",
      "attempts": 1, "duration_ms": 5230,
      "fingerprint": "sha256…", "cache": {"hit": false, "reason": "config_changed"},
      "from_sample_data": false,
      "resolved_inputs_summary": {"script": {"chars": 812}},
      "outputs_summary": {"audio_file": {"artifact": "tts/pm_X/voice.wav", "duration_s": 28.5}},
      "artifact_refs": ["tts/pm_X/voice.wav"],
      "source_artifact_ids": ["art_XXXXXX"],  // step 4.1 — inputs from the artifact library
      "logs": [{"ts": "ISO", "level": "info", "message": "…"}],
      "error": null
    }
  }
}
```

Persisted at `output/workflows/executions/{execution_id}.json` (atomic, redacted). Payload
bodies are never persisted — only summaries and relative artifact refs. Status transitions
are monotonic; terminal states cannot return to running. `awaiting_approval` is added by
step 2.6 as a durable pause that **releases the worker thread**.

**Standalone input sources (step 4.1 / §9.1).** `POST /api/workflow/run` accepts optional
`input_bindings` (`{node_id: {port_id: binding}}`) and/or `input_overrides`
(`{node_id: {port_id: payload}}`), plus `current_job_id` for `current_job` bindings.
Binding `source` is one of: `current_job`, `job`, `library`, `upload`, `manual`, `sample`,
`run_deps`. Resolved source artifact ids are recorded on the node as `source_artifact_ids`
(and mirrored under `resolved_inputs_summary.source_artifact_ids`). Artifact library routes:
`GET/POST /api/artifacts`, `GET /api/artifacts/<id>`, `GET /api/artifacts/<id>/payload`,
`POST /api/artifacts/upload`, `POST /api/artifacts/resolve-inputs`.

**Test Node (step 4.2 / §9).** `POST /api/jobs/<job_id>/test-node` runs
`node_isolated` for the given `target_node_ids` with optional `input_bindings`.
It returns `202 {job, execution_id, project_id, status, run_mode, target_node_ids}`
and **never** rewrites the Job's `status`, `current_stage`, `artifacts`, or
`execution_id`. Sample bindings stamp `from_sample_data` on the node record so
stub-derived output is never mistaken for real output.

**Cache fingerprint** inputs: node type, type version, configuration, inputs, upstream
artifact fingerprints, adapter cache schema version. Artifact integrity is re-verified on
lookup.

### 1.6 API surface & SSE

Workflow blueprint: `workflows_bp`, no url_prefix. Provider and workflow routes are
**loopback-only**. Errors use one envelope everywhere:

```json
{ "error": { "code": "WORKFLOW_INVALID", "message": "…", "details": {} } }
```

| endpoint | success shape |
|---|---|
| `GET /api/workflows` | `{workflows:[summary], total:n}` |
| `POST /api/workflows` | `201 {workflow}` |
| `GET /api/workflows/<id>` | `{workflow}` |
| `PUT /api/workflows/<id>` | `{workflow}` (`409 WORKFLOW_CONFLICT` on stale) |
| `DELETE /api/workflows/<id>` | `{deleted:true, workflow_id}` |
| `POST /api/workflows/import` | `201 {workflow}` |
| `GET /api/workflows/<id>/export` | attachment JSON |
| `GET /api/workflow/node-types` | `{registry_version, node_types, port_types, categories, sample_payloads?, dev_reload_enabled?}` — **no executor internals** |
| `GET /api/workflow/templates` | `{templates:[{template_id, workflow}]}` |
| `POST /api/workflow/validate` | `{valid, problems, warnings}` |
| `POST /api/workflow/run` | `202 {execution_id, project_id, status:"queued"}` |
| `POST /api/workflow/executions/<id>/stop` | `202 {execution_id, status:"cancelling"}` |
| `GET /api/workflow/executions/<id>` | `{execution}` |
| `GET /api/workflow/executions/<id>/events` | SSE; `Last-Event-ID` replay from bounded ring (1000) |
| `GET /api/workflow/executions` | `{executions:[summary], total:n}` |

SSE frame:

```jsonc
{ "sequence": 12, "execution_id": "ex_123", "node_id": "n_tts",
  "status": "running", "attempt": 1, "timestamp": "ISO",
  "duration_ms": 0, "summary": "…",
  "progress": {"ready": 3, "total": 10},
  "from_sample_data": false }
```

Monotonic `sequence` per execution; terminal event has `node_id: null`.

### 1.7 Provider result envelope

`result_version: 1`. One envelope for all domains (`scriptase/providers/results.py`):

```jsonc
{
  "result_version": 1,
  "domain": "tts",
  "provider_id": "kokoro",
  "provider_version": "1.0.0",
  "contract_version": 2,
  "status": "succeeded",          // succeeded | partial | failed
  "payload": { /* domain body */ },
  "artifact_refs": ["tts/pm_X/voice.wav"],
  "units": [],                    // one UnitResult per requested unit for batch domains
  "metadata": {},                 // ≤40 keys, scalar values, strings ≤500
  "warnings": [{"code": "…", "message": "…", "unit_index?": 0}],
  "provenance": { /* §2 */ },
  "job": null                     // JobStatus snapshot for async providers
}
```

Platform overwrites `domain` / `provider_id` / versions so a provider cannot impersonate
another. Unknown top-level keys are dropped with a WARN. Egress validation rejects absolute
paths, sensitive keys (unless redaction markers), `bytes`, non-JSON types, and oversized
fields.

**UnitResult** (multi-unit domains — image/video; any `batch` provider):

```jsonc
{
  "unit_index": 0,                // caller's index; stable, not positional
  "state": "succeeded",           // succeeded | failed | skipped | cancelled
  "artifact_refs": [],
  "metadata": {},
  "error": null,                  // required when state=failed
  // Optional per-unit reproducibility overrides (step 8.3). Sparse: omit when
  // the unit inherits envelope provenance.
  "seed": 42,
  "request_id": "…",
  "model_revision": "…",
  "provider_id": "…",
  "provider_instance_id": "…",
  "selection_reason": "fallback_after:inst_main"
}
```

Envelope `status` is **derived** from units (cancel > all-succeeded > any-succeeded partial >
all-failed raised). `len(units) == len(requested)`; unattempted units are `skipped`.

### 1.8 ProviderError

Stable `code`, safe `message`, platform-owned `retryable` flag, redacted `details`.
**Retryability is owned by the platform, not the provider.** Raw exception text never
enters `message` or `details`.

### 1.9 Redaction surfaces

Applied to: execution records, queue records, SSE events, workflow documents,
notifications, archives, logs, provider result provenance (`resolved_settings_redacted`
is the only sanctioned settings echo). Environment fallbacks may be *used*, never *returned*.

Music and Captions are **local single-implementation services, not provider domains**.
Their mode/tone/preset fields look like provider selection and are not.

---

## 2. Provenance — generation reproducibility

Platform-authored; a provider never writes this block. Extended at step 0.4 **before any
Scriptase Job records exist**, because these fields cannot be retrofitted onto past runs.

```
Provenance
- invocation_id
- domain
- provider_id                  # provider type id (discovered package id)
- provider_instance_id         # configured instance that ran (step 3.1)
- provider_version
- contract_version
- settings_version
- resolved_settings_redacted   # only sanctioned settings echo
- options                      # per-run options, secret-free
- selection_reason             # request | node_config | settings | channel | default
                               # | fallback_after:<instance_id>
- started_at / finished_at / duration_ms
- cache_hit
- seed                         # int | null — generation seed when the provider exposes one
- request_id                   # provider-side correlation id when available
- model_revision               # provider-reported model/version string when available
- cost                         # {amount, currency, unit_count, unit} | null
```

**Harvesting rule.** The platform lifts `seed`, `request_id`, and `model_revision` from
result `metadata` (and a caller-supplied `seed` from invocation `options`). Values are
**never invented**: missing stays `null` / `""`. `model` in metadata is accepted as a
fallback for `model_revision` when no explicit revision is present.

**Per-unit rule (blocking for step 8.3):** a fallback run produces units from different
provider instances. When a unit's producer differs from the envelope, the unit carries its
own sparse overrides (`seed`, `request_id`, `model_revision`, `provider_id`,
`provider_instance_id`, `selection_reason`). When those fields are absent, the unit inherits
envelope provenance. This shape is frozen now; runtime fallback lands in 8.3.

**Why now.** Snapshotting configuration is not reproducibility with generative providers:
same config, different image. Pinning seed + request id + model revision is also what makes
§12.1-style repair instructions ("preserve character and composition, change lighting to
sunrise") achievable rather than a re-roll.

---

## 3. Artifact

Replaces V2's `artifact_refs: list[str]` naming convention with a real type. Implemented at
1.2.

```
Artifact
- id                       # "art_XXXXXX"
- schema_version
- job_id
- scene_id                 # nullable; set for per-scene media
- kind                     # script | audio | alignment | segments | scene_spec |
                           # image | video | captions | music | timeline | export
- version                  # 1-based, monotonic per (job_id, scene_id, kind)
- content_hash             # sha256 of the file or canonical JSON
- path                     # relative, managed, forward-slash, under output/
- size_bytes
- mime
- provenance_ref           # -> the Provenance record that produced it
- generation               # nullable; compact comparison snapshot (step 4.3)
  - provider_id
  - provider_instance_id
  - seed                   # int | null
  - prompt_revision        # product comparison axis; often mirrors model_revision
  - model_revision
  - request_id
  - invocation_id
  - selection_reason
- created_at
- superseded_by            # nullable artifact id
- from_sample_data         # bool; stub-derived output is never mistaken for real output
```

Rules:

- **Immutable and additive.** A repair creates version N+1 and sets `superseded_by` on
  version N. It never overwrites or deletes.
- **Attempt history (step 4.3).** `GET /api/artifacts/<id>/history` and
  `GET /api/artifacts/history?job_id=&kind=&scene_id=` return the full version chain
  (oldest first) with generation axes. `GET /api/artifacts/compare?left=&right=` returns
  a side-by-side pair plus `axes.{provider_instance_id,seed,prompt_revision}` diffs.
  Values are never invented — missing stays null / empty.
- The existing staging/promotion flow (`ArtifactPromoter`) still owns writing files; the
  Artifact records what it produced.
- `path` is always relative to the managed output root. **An absolute path in an artifact
  record or a port payload is a contract violation.**
- Cache artifact-integrity re-hashing continues to operate on `path` and `content_hash`.
- **Store layout (resolved):** keep V2's per-module output directories (`output/tts/`,
  `output/scenes/`, …) for V2 import compatibility (10.1). Add an **artifact index**
  (content-addressed metadata) alongside them at 1.2 — not a parallel blob store that
  relocates files.

---

## 4. Scene identity

Implemented at 1.6 (`scriptase.scenes`, segmenter service stamps ids). Scenes in V2
are array indices; the review and repair design is per-scene, and re-segmentation
shifts every index.

```
Scene
- id                       # "scn_XXXXXX" — stable across re-segmentation
- job_id
- ordinal                  # presentation order only; NOT identity
- start / end / duration
- segment_words
- superseded_by            # nullable; set when re-segmentation replaces this scene
```

**Re-segmentation rule.** When the segmenter reruns, each resulting scene either:

1. **rebinds** to an existing scene id when its span is materially unchanged (artifacts and
   open issues carry over), or
2. **supersedes** one or more prior scenes (prior artifacts marked superseded; open issues
   re-targeted to the successor), or
3. is **new** (no inherited artifacts or issues).

**Rebind threshold (resolved):** a candidate rebinds when both (a) temporal IoU of
`[start, end]` with a prior scene ≥ **0.6** and (b) the longer span is at most **1.5×** the
shorter. Ties go to the highest IoU; a prior scene may rebind to at most one successor. The
constants are configuration on the segmenter service with these defaults — change them only
with a migration note.

No open issue or artifact may remain bound to a scene id that no longer resolves.
Test-enforced at 1.6.

---

## 5. ChannelProfile

Per product §15.1. Implemented at 1.1 / 1.3.

```
ChannelProfile
- id / name / version / schema_version
- branding          { logo_asset_id, enabled, position, size, opacity, margin }
- content           { niche, language, audience, script_style, tone, mood,
                      hook_style, cta_style, duration_target }
- visual_direction  { style, pattern, palette, lighting, camera, character_style,
                      continuity, negative_prompt, references[] }
- audio_defaults    { tts_provider_instance_id, voice, speed, music_profile,
                      loudness, ducking }
- captions          { preset, position, font_treatment, animation }
- provider_defaults { script, tts, scene_director, image, video, review }  # instance ids
- fallback_policies { <stage>: { primary, fallbacks[] } }                  # instance ids
- review_policy     { thresholds, max_repairs, escalation, human_checkpoints[] }
- budget            { max_generations, max_cost, currency }
- export_defaults   { aspect_ratio, resolution, fps, profile }
- default_workflow_id
```

`visual_direction.pattern` is **structured**, never free text:

```
pattern: [ { narrative_role: "hook",           shot: "extreme close-up" },
           { narrative_role: "explanation",    shot: "medium cinematic" },
           { narrative_role: "emotional_beat", shot: "wide environmental" },
           { narrative_role: "ending",         shot: "symbolic visual" } ]
```

`provider_defaults` and `fallback_policies` hold **provider instance ids**. A Channel may
override safe non-secret generation defaults (model, aspect ratio, prompt suffix, voice). It
never holds credentials. Logo upload goes through the managed branding endpoint — never a
browser-supplied filesystem path.

---

## 6. Job

Per product §15.2. Implemented at 1.4 / 1.5.

```
Job
- id / schema_version
- channel_id
- channel_snapshot         # non-secret channel config + provider INSTANCE REFERENCES
- workflow_id / workflow_version
- execution_mode           # manual | assisted | automatic
- source                   { mode, topic, idea, pasted_script, references[] }
- status                   # queued | running | awaiting_approval |
                           # completed | failed | cancelled
- status_reason            # nullable free-text code: approval | budget | user_pause | …
- current_stage
- artifacts[]              # artifact ids
- scenes[]                 # scene ids
- issues[]                 # review issue ids
- repair_history[]         # RepairHistoryEntry ids (§9.1)
- budget_spent             { generations, cost }
- execution_id
- created_at / started_at / completed_at
```

Rules:

- The snapshot captures non-secret configuration and provider **instance references** only.
  Secrets resolve from the instance at runtime and never enter a Job.
- Job status **derives** from the execution record so the two cannot disagree.
- A Job is an orchestration object, not a node. It never appears in the node registry.
- **`paused` vs `awaiting_approval` (resolved):** one status value `awaiting_approval` with
  `status_reason` distinguishing approval checkpoints, budget ceilings, and explicit user
  pause. No separate `paused` enum member.

`source.mode` values for the Script stage: `automatic | topic | idea | paste | manual`.

---

## 7. ProviderInstance

Per product §15.3, extended for the type/instance split. Implemented at 3.1 / 3.2.

```
ProviderInstance
- instance_id              # unique within a domain
- provider_type            # the discovered package id (folder/manifest id)
- domain
- display_name
- enabled
- settings                 # non-secret; secrets held as {"$secret": "<ref>"}
- limits                   { rate, quota, max_concurrency }
- capabilities[]           # from the type manifest
- availability             # available | needs_configuration | degraded
- health_state / last_health_check
```

Settings store shape (post-3.1):

```
domains: { <domain>: { selected_instance_id, instances: {
             <instance_id>: { type, label, settings } } } }
```

Pre-3.1 documents used `domains.<domain>.{selected_provider, per_provider.<id>}`;
settings migration v6 rewrites them to the shape above with selection intact
(`instance_id == type` for each migrated default binding).

Rules:

- Provider **type** is discovered from the filesystem; provider **instance** is
  user-created configuration. Two instances of one type are independent in settings,
  availability, and health.
- Construction is memoized per `(type, instance_id)`; the exclusivity lock keys on the
  same pair.
- `manifest.environment` env-fallback is per **type** and applies to the default instance
  only once instances exist.
- **No credential is ever stored inline.** Secret references (`{"$secret": "<ref>"}`)
  resolve at call time (step 3.4). Environment variables are a read-time fallback only —
  never seeded into settings, never returned to the browser.

---

## 8. SceneSpec

Per product §11. Implemented at 5.1
(`scriptase.modules.scene_director.providers.contract:SceneSpec`). Carried on the
stable scene id from §4. `SceneItem` is a backward-compatible alias of `SceneSpec`.

```
SceneSpec
- scene_id
- narration
- visual_description
- image_prompt
- motion_prompt
- camera
- lighting
- mood
- continuity               # e.g. "same protagonist and wardrobe as previous scene"
- narrative_role           # hook | buildup | explanation | emotional_beat | peak |
                           # transition | cta | ending | text_accent
- overlay_hints / sfx_hints
```

`SceneBlueprintResultPayload.scenes` is `list[SceneSpec]`. The Image and Video adapters
consume `SceneSpec` via `from_scene_specs` / `coerce_scene_specs`, not loose dicts.
**No prompt text lives outside a provider package** — the Scene Director composes from
Channel visual direction and the provider owns wording. Round-trips through the provider
result envelope (enforced by `tests/test_scene_spec.py`).

Step 5.2 freezes structured Channel visual direction as typed request inputs on
`SceneBlueprintRequest` (`scriptase.modules.scene_director.providers.contract`):

```
SceneBlueprintRequest
- script / segments / style / style_notes / tone / aspect_ratio
- visual_direction   { style, pattern[{narrative_role, shot}], palette, lighting,
                       camera, character_style, continuity, negative_prompt,
                       references[] }   # structured; never free-text pattern
```

A Job's `channel_snapshot.visual_direction` is forwarded via channel settings and the
`project.setup` settings port. Pattern entries override the planner's default camera
grammar so two Channels with different patterns produce measurably different SceneSpecs
from the same script (`tests/test_channel_visual_direction.py`).

### 8.1 Timing strategy AUTO

Per product §10. Implemented at 5.3
(`scriptase.modules.timing.service:_step_timing`). Node type remains `timing.align`;
user-facing display name is **Timing** (V2: Force Alignment).

Strategy AUTO:

```
TTS audio.native_word_timing == true AND usable word_timings?
  YES -> normalize_word_timings + _validate_alignment
  NO  -> Whisper / stable-ts force-alignment (_run_alignment)
```

TTS domain capability `native_word_timing` (in `providers/domains.py` vocabulary).
When a provider grants it and returns `word_timings` in result metadata, dispatch
stamps `native_word_timing: true` and the timings onto the TTS audio/metadata ports.
Timing reads them from the audio port only — no graph edge change.

Canonical alignment artifact / port payload keys (no strategy discriminator):

```
project_id, source_file, folder, transcript, alignment, word_count,
inference_time, timestamp
```

Each `alignment[]` entry is `{word, begin, end}` (floats, seconds). Provider spellings
`start`/`end`, `text`/`token` are accepted at normalise time and rewritten to this
shape. The segmenter and captions consume only this schema; they cannot determine
which strategy ran (`tests/test_timing_strategy.py`).

### 8.2 Prompt evaluation harness

Implemented at 5.4 (`scriptase.providers.prompt_eval`). Extends the provider
golden-fixture layer (§ provider fixtures under `tests/fixtures/providers/`)
with structural expectations so a prompt change has a regression signal without
exact-text equality on free-form `image_prompt` wording and without spending
provider credits.

```
tests/fixtures/prompt_eval/<domain>/<case_id>/
  case.json                 # source: provider_fixture | inline | offline_planner
  expected_structure.json   # structural axes + rules
```

Structural axes (compared when present): `scene_count`, `roles[]`, `types[]`,
`indexes[]`. Rules (boolean / list checks, never free-form text):
`indexes_dense_from_zero`, `first_not_text`, `last_not_text`,
`roles_in_vocabulary`, `types_in_vocabulary`, `nonempty_image_prompt`,
`required_fields`, `must_include_roles`, `min_scene_count`, `max_scene_count`.

Also checks the Scene Director system prompt builder for required instructional
markers (`SCENE_DIRECTOR_PROMPT_MARKERS`). Offline only —
`python -m scriptase.providers.prompt_eval --check`
(`tests/test_prompt_eval.py`).

### 8.3 Image and video capability vocabularies

Step 6.1. Image and video are separate domains with closed routing vocabularies
declared on `DomainSpec.capability_vocabulary` (plus `SHARED_CAPABILITIES`):

| Domain | Routing capabilities |
|---|---|
| `image` | `text_to_image`, `image_edit`, `reference_image`, `inpainting` |
| `video` | `image_to_video`, `text_to_video`, `reference_image`, `duration_control` |

Providers declare a subset of their domain vocabulary in the manifest. Unknown
keys are dropped with a discovery warning and never appear in the catalog,
capability API, selector, node inspector, or step detail UI
(`tests/test_image_video_domains.py`). The catalog domain payload includes
`capability_vocabulary` so the browser can refuse undeclared keys even if a
stale row carries one.

### 8.4 Optional image dependency (video)

Step 6.2 / product §7.4. The `animator.generate` storyboard port remains
optional (`storyboard:storyboard_images?`). Routing is capability-based
(`scriptase/modules/video/routing.py`):

| Graph shape | Required / preferred capability | Behaviour |
|---|---|---|
| Storyboard edge connected | Prefer `image_to_video` | Default full-video path; stills feed i2v providers |
| No storyboard edge | Require `text_to_video` | Scene Director prompts only; `image_to_video`-only providers fail with `PROVIDER_REQUEST_INVALID` |

A text_to_video-only provider may still run when storyboard is connected
(stills are ignored). Never silently substitute a different provider.

Built-in templates: `full_video` keeps Storyboard → Animator (i2v);
`text_to_video` omits the image node and selects `kie_ai`
(`tests/test_optional_image_dependency.py`).

---

## 9. ReviewIssue

Per product §15.4. Implemented at 7.2.

```
ReviewIssue
- id / schema_version
- job_id
- scene_id                 # nullable
- target_node_id
- target_artifact_id
- issue_type               # visual_mismatch | continuity_break | motion_defect |
                           # audio_defect | timing_drift | segmentation_defect |
                           # script_defect | technical_defect | policy_violation
- severity                 # low | medium | high | critical
- confidence               # 0.0–1.0
- reason                   # human-readable, safe, bounded
- suggested_action         # regenerate | re-prompt | adjust | escalate | accept
- repair_instruction       # what to preserve and what to change
- attempt_count
- status                   # open | repairing | resolved | escalated | accepted
- created_at / resolved_at
```

**Free-form text is not an acceptable review output.** A reviewer that cannot produce a
structured issue fails; automation depends on structure.

Routing table (§12.2) — table-driven, not scattered conditionals.
Implemented at 8.1 as `scriptase.review.policy` (`OWNERSHIP_TABLE` /
`route_issue` / `route_problem`). Problem keys and preferred registry node
types are the machine surface; labels are presentation.

| Detected problem | problem_key | Routes to | node_types (preferred first) |
|---|---|---|---|
| Script too long, wrong tone, weak hook | `script_content` | Script | `story.generate`, `script.input` |
| Pronunciation or voice problem | `pronunciation_voice` | TTS | `tts.generate` |
| Words do not align with audio | `alignment_mismatch` | Timing | `timing.align` |
| Poor or overlong scene boundaries | `scene_boundaries` | Segmenter | `segment.run` |
| Visual concept does not represent narration | `visual_concept` | Scene Director | `scenes.blueprint` |
| Wrong character, object, or style in a still | `image_subject_style` | Image Generator | `storyboard.generate` |
| Motion deformation, instability, poor animation | `motion_deformation` | Video Generator | `animator.generate` |
| Caption outside safe area, branding missing | `caption_branding` | Composer | `assemble.project`, `captions.generate`, `timeline.project` |
| Render corruption, codec failure | `render_codec` | Export | `export.video` |

Disambiguation (still table-driven): `observed.problem_key` wins; else
`check_id` via `CHECK_ID_PROBLEM`; else `issue_type` via
`ISSUE_TYPE_DEFAULT_PROBLEM`. `visual_mismatch` defaults to Image; Scene
Director ownership for a concept mismatch is selected by
`observed.problem_key = visual_concept`.

### 9.1 RepairHistoryEntry

Implemented at 8.4.

```
RepairHistoryEntry
- id / schema_version
- job_id
- issue_id
- scene_id                 # nullable
- routed_to_node_type
- provider_instance_id
- action                   # regenerate | re-prompt | adjust | escalate | accept | fallback
- instruction              # bounded; what was preserved / changed
- input_artifact_ids[]
- output_artifact_ids[]    # new versions; prior ones superseded
- provenance_ref
- result                   # resolved | failed | escalated | degraded
- created_at
```

---

## 10. Stage projection

Implemented at 2.2. The mechanism that keeps the Production and Workflow views from
diverging.

```
StageProjection
- workflow_id / workflow_version
- stages[]  { key, label, ordinal, node_ids[], status, provider_capable,
              active_provider_instance_id?, artifacts[], issues[] }
```

Rules:

- The projection is **computed from the graph on the backend**. A hardcoded step array in
  the frontend is a contract violation.
- Default production projection order: Script, Voice, Timing, Segments, Scenes, Images,
  Videos, Review, Composer, Export.
- Side branches (captions, music, branding, validators) collapse into the stage where they
  merge. Adding a parallel branch changes the graph without adding a step.
- Stage status derives from its member nodes' execution records. There is no separate
  status store.
- Step actions map onto existing run modes only
  (`full`, `node_with_deps`, `from_node`, `node_isolated`, `retry_failed`, …). **No new
  execution path may be introduced for the Production view.**
- `-P` never appears in a stage or node name. Provider capability is metadata.

---

## 11. Approval checkpoints

Implemented at 2.6. Assisted mode and the Approve action.

```
ApprovalCheckpoint
- job_id / execution_id / node_id / stage_key
- reason                   # script_approval | critical_issue | budget_ceiling | policy
- created_at / expires_at  # nullable
- status                   # awaiting | approved | rejected | expired
- decided_by / decided_at
```

Rules:

- `awaiting_approval` **releases the worker thread** and persists the resume point. Blocking
  a pool thread on human input is a contract violation.
- The state survives a process restart and resumes from exactly where it paused.
- Manual mode approves explicitly; Automatic mode pauses only on configured unrecoverable
  conditions.

---

## 12. Budget and admission control

Implemented at 3.5 (enforcement) and 9.3 (accounting). Repair budgets and
escalation (step 8.2) reuse the same pre-flight gate via
`scriptase.review.repair` (`decide_issue_repair` / `plan_job_repairs` /
`process_job_repairs`).

- Budget is checked **pre-flight**: work that would exceed a Channel's or Job's ceiling is
  refused before the provider is called. Post-hoc reporting is not enforcement.
- A single bounded global work pool replaces per-project drain threads, preserving
  per-project FIFO ordering.
- Repair budgets are enforced through the same path: maximum attempts per issue
  (`review_policy.max_repairs`), maximum generations and cost per Job (`budget` +
  `budget_spent`), escalation on low confidence or repeated failure
  (`REPAIR_LIMIT_REACHED` / issue status `escalated`), and configured safe
  degradation (`review_policy.thresholds.safe_degradation`, e.g. `video: keep_still`).
  An unfixable issue escalates instead of looping; a Job that hits its repair budget
  stops with `status_reason=budget` rather than continuing to spend.

### 12.1 Cost record

```
CostRecord
- job_id / execution_id / node_id / unit_index?
- provider_instance_id
- amount                   # decimal as string or fixed-point int (minor units)
- currency                 # ISO 4217; recorded as reported
- unit_count / unit        # e.g. tokens, images, seconds
- recorded_at
```

**Currency (resolved):** record in the provider's reported currency at write time; convert
only at report time (9.3). Do not normalise on ingest — exchange rates are not an
engine concern.

---

## 13. Error codes

### 13.1 Workflow codes (ported)

`WORKFLOW_INVALID`, `WORKFLOW_CONFLICT`, `UNKNOWN_NODE_TYPE`,
`UNSUPPORTED_NODE_VERSION`, `PORT_TYPE_MISMATCH`, `MISSING_REQUIRED_INPUT`,
`CYCLE_DETECTED`, `PROJECT_LOCKED`, `NODE_EXECUTION_FAILED`, `ALIGNMENT_EMPTY`,
`WEBHOOK_FAILED`, `WEBHOOK_NOT_FOUND`, `WEBHOOK_PAYLOAD_INVALID`,
`PROVIDER_UNAVAILABLE`, `EXTENSION_NOT_CONNECTED`, `POLL_TIMEOUT`, `EXPORT_FAILED`,
`CANCELLED`, `ARTIFACT_MISSING`, `CACHE_INTEGRITY`, `STUB_PAYLOAD_INVALID`,
`SAMPLE_FIXTURE_MISSING`, `OPTION_CONTEXT_INVALID`, `EXPRESSION_VALUE_UNAVAILABLE`,
`REQUEST_TOO_LARGE`, `LIMIT_EXCEEDED`, `NOT_FOUND`.

Failure payload:
`{code, node_id?, node_name?, message, details_redacted?, attempt?, timestamp?, recovery_suggestion?}`.

### 13.2 Provider codes (ported)

Platform-owned retryability. Core set includes:
`PROVIDER_FAILED`, `PROVIDER_TIMEOUT`, `PROVIDER_TRANSPORT_FAILED`,
`PROVIDER_RESPONSE_MALFORMED`, `PROVIDER_RESULT_INVALID`, `PROVIDER_AUTH_FAILED`,
`PROVIDER_RATE_LIMITED`, `PROVIDER_UNIT_FAILED`, `PROVIDER_ARTIFACT_MISSING`,
`PROVIDER_ARTIFACT_UNMANAGED`, `PROVIDER_REQUEST_INVALID`, `PROVIDER_CANCELLED`
(and the remainder of the ported 16-code taxonomy in `scriptase/providers/errors.py`).

### 13.3 Scriptase codes (new)

| Code | Meaning | Retryable |
|---|---|---|
| `CHANNEL_NOT_FOUND` | Referenced channel id does not resolve | no |
| `CHANNEL_INVALID` | Channel document failed schema validation | no |
| `JOB_NOT_FOUND` | Referenced job id does not resolve | no |
| `JOB_INVALID` | Job document or create draft failed schema / source validation | no |
| `JOB_TERMINAL` | Operation invalid for a completed/failed/cancelled job | no |
| `ARTIFACT_NOT_FOUND` | Artifact id does not resolve | no |
| `ARTIFACT_SUPERSEDED` | Operation targeted a superseded artifact version | no |
| `SCENE_NOT_FOUND` | Scene id does not resolve after re-segmentation | no |
| `PROVIDER_INSTANCE_NOT_FOUND` | Instance id does not resolve in its domain | no |
| `BUDGET_EXCEEDED` | Pre-flight check refused the work | no |
| `APPROVAL_REQUIRED` | Execution paused awaiting a human checkpoint | n/a |
| `REPAIR_LIMIT_REACHED` | Issue exhausted its repair budget; escalated | no |
| `SECRET_REF_UNRESOLVED` | Secret reference could not be resolved at call time | no |
| `STAGE_PROJECTION_INVALID` | Graph could not be projected into stages | no |
| `QUALITY_GATE_FAILED` | Early image/video quality gate blocked progression | no |

### 13.4 Domain-rename aliases

Provider **domain ids** renamed (`scene_blueprint` → `scene_director`, etc.); workflow and
provider **error codes** did not. Domain aliases live only in
`providers/domains.py` (`DOMAIN_ALIASES` / `canonical_domain()`). No error-code alias table
is required. Settings domain keys migrate via settings migration **v5**.

---

## 14. Deferred items and owners

Recorded at the 0.4 gate. Implementation steps own delivery; this section owns the
decision freeze.

| Item | Decision / note | Owner step |
|---|---|---|
| Artifact store layout | Keep V2 per-module dirs; add artifact index alongside | 1.2 |
| Scene rebind threshold | IoU ≥ 0.6 and span ratio ≤ 1.5× (configurable defaults) | 1.6 |
| Job `paused` vs `awaiting_approval` | Single status + `status_reason` | 2.6 / 1.4 |
| Cost currency normalisation | Record as reported; convert at report time | 9.3 |
| Error-code rename for domains | None — domains alias, codes do not | — |
| Per-unit provenance runtime | Shape frozen in §1.7 / §2; runtime fallback | 8.3 |
| Provider type/instance split | `provider_instance_id` populated; settings `instances` map | 3.1 |
| Secret references | `{"$secret": "<ref>"}` wire form frozen; resolver in `ProviderInstance.resolve_settings`; secret store + settings migration v7 | 3.4 |
| Durable approval engine state | Status token frozen; worker-release behaviour | 2.6 |
| Stage projection endpoint | Shape frozen in §10 | 2.2 |
| SceneSpec round-trip | Shape frozen in §8; `tests/test_scene_spec.py` | 5.1 |
| Channel visual direction → Director | Typed `VisualDirectionInput` on request; pattern diverges SceneSpecs; prompt text under `providers/` | 5.2 |
| Timing strategy AUTO | Native word timings when advertised; else force-align; identical alignment schema | 5.3 |
| Prompt evaluation harness | Structural drift over golden fixtures + offline planner; prompt-builder markers; no credits | 5.4 |
| Image / video domain split | Separate capability vocabularies; undeclared caps never offered | 6.1 |
| Optional image dependency | Storyboard optional; text_to_video without image node; full_video i2v unchanged | 6.2 |
| Review provider domain | Uses standard result envelope + ReviewIssue | 7.3 |
| V2 project import | Map niche presets → Channels; keep output/ layout | 10.1 / 1.3 |
| Indexed storage for runs/queue/jobs | Performance only; no schema meaning change | 10.2 |
| Crash recovery / reconciliation | Startup scan of executions + jobs | 10.3 |

---

## 15. Spec-vs-code resolutions (Phase 0)

Discrepancies resolved **in favour of working ported behaviour**:

| # | Topic | Resolution |
|---|---|---|
| R1 | Module path names | Scriptase package layout (§0 renames); node type keys unchanged |
| R2 | Assemble inputs | Typed input ports for readiness; adapter still keys off `project_id` + disk layout |
| R3 | Storyboard vs animator → assemble | Mutually exclusive; assemble consumes `animation_assets` only |
| R4 | Absolute paths in port payloads | Forbidden; export adapter audited in 0.3; egress validator enforces |
| R5 | Provider ABC layer | Dead; not ported. Invocation + result envelope are the live contract |
| R6 | Music / Captions as providers | Not provider domains; local services; no migration required |
| R7 | Pipeline routes | Not ported; workflow engine is the only orchestrator |
| R8 | Provenance identity fields | Working fields kept (`invocation_id`, `provider_id`, …); reproducibility fields additive |
| R9 | `selection_reason` vocabulary | Working values (`request`, `node_config`, `settings`, `default`) retained; Scriptase adds `channel` and `fallback_after:<id>` |
| R10 | `GET /api/workflow/node-types` payload | Working shape includes `categories`, `sample_payloads`, `dev_reload_enabled` beyond the minimal triple |

---

## 16. Phase 0 gate record (step 0.4)

**Complete**

- Engine + provider platform ported and green under `scriptase.*` imports (0.2).
- Media modules lifted; no business logic imports from `routes.py`; absolute-path port
  payload test green (0.3).
- `plans/contracts.md` covers every schema Phases 1–10 touch (this file).
- `Provenance` carries `seed`, `request_id`, and `model_revision` through the result
  envelope (`scriptase/providers/results.py`, harvested in `boundary.build_provenance`).
- Per-unit reproducibility overrides frozen (sparse on `UnitResult`) for 8.3.
- App boots via `create_app()` and serves the full node catalogue from
  `GET /api/workflow/node-types` (24 node types at freeze time, including production,
  utility, stub, and scaffold_check nodes).

**Deferred** — see §14.

**Blocks Phase 1?** No. Phase 1 may start on this freeze.
