> **ARCHIVED — delivered in full.** 70 steps across Phases 0–16, completed
> 2026-08-13 to 2026-08-16. Superseded by `plans/implementation-plan.md`, which
> renumbers the prototype rebuild as a fresh Phase 0. Kept as the record of what
> was built and why; the contracts it froze are still authoritative.

# Scriptase — Implementation Plan

Executable plan for the loop-engineering orchestrator. Authoritative spec:
[proposition-final.md](proposition-final.md). Frozen machine contracts:
[contracts.md](contracts.md). Product reference:
`Scriptase_Architecture_Development_Reference.docx` (cited below as §N).

**Format is load-bearing.** `loop_engineering.py` parses `## Phase N — Title`,
`### N.M Title`, and a literal `**Done when:**` line per step, and detects progress from
commit subjects containing `step N.M`. Do not reformat headings.

**Core principle (§3, §19):** nodes are the execution model, steps are the user experience.
One node-based engine is authoritative; the Production view is a projection of that same
graph, never a second engine.

**Repo strategy:** Scriptase is a fresh repository that selectively ports from
ScriptToScene-Studio-V2 (`D:\@Workspace\@Development\@Scripts\@Python\ScriptToScene-Studio-V2`,
referred to below as **V2**). Proven engines are lifted verbatim, tangled subsystems are
rebuilt on the way in, dead weight is left behind. The port ledger is in
[proposition-final.md](proposition-final.md).

---

## Phase 0 — Repo genesis, port, and contract freeze

Nothing in Phases 1–10 is safe until the ported foundation is proven green under its new
import paths. Do not start Phase 1 on an amber board.

### 0.1 Scaffold and plan documents

Initialise the repository: `git init`, `.gitignore` (must exclude `venv/`, `output/`,
`node_modules/`, `static/dist/`, `logs/`, `__pycache__/`, and
`develop/loop-engineering/live-verification/n8n-data/`, which carries several thousand
copied n8n build assets). Create the package skeleton from the layout in
proposition-final.md, the venv, `pytest.ini` with the `live` marker, and the frontend
Vite/Vitest configuration. Write `CLAUDE.md` at the repo root and a
`.claude/settings.local.json` permission allowlist — headless agents cannot answer
permission prompts, and a denied `npm test` silently cripples the builder. Seed
`plans/contracts.md`. Reset `develop/loop-engineering/runtime/state.json` to
`{"done": [], "history": []}`; the copied file carries V2's 82 completed step ids and
would mark this plan's phases done.

**Done when:** `develop\loop-engineering\run.bat --status` parses this plan, reports 46 steps across 11 phases, and names step 0.2 as next.

### 0.2 Lift the engine and provider platform

Copy V2's `studio/workflows/` into `scriptase/engine/` and `studio/shared/providers_common/`
into `scriptase/providers/`, with their tests, then apply the mechanical rename pass
(`studio`→`scriptase` and the module renames in proposition-final.md). This includes
`cache.py`, `scheduler.py` (with `ProjectLock` and `ArtifactPromoter`), `registry.py`,
`validation.py`, `expressions.py`, `events.py`, `redaction.py`, `migrations.py`,
`config_migrations.py`, the trigger trio, `asset_gc.py`, `project_archive.py`,
`scaffold.py`, `contract_tests.py`, and `docs.py`, plus `io_utils.py` and `security.py`.
Provider **domain ids** rename with the packages (`scene_blueprint`→`scene_director`,
`storyboard`→`image`, `animator`→`video`); domains are data in `providers/domains.py`,
which is exactly the change that module was designed to absorb. Carry an alias map so
imported V2 settings still resolve. No behaviour changes beyond renaming.

**Done when:** every ported engine and provider test passes under the new import paths with zero skips beyond `@pytest.mark.live`, and both generated-doc drift checks are green.

### 0.3 Lift the media modules and rebuild the tangles

Port `scriptase/modules/*` from V2, rebuilding the four subsystems the survey flagged as
tangled: extract the Whisper/stable-ts aligner (`_run_alignment`, `_validate_alignment`,
`_fix_gaps_with_audio`, `_fix_zero_duration_words`) out of `timing/routes.py` into
`timing/service.py`; extract `_group_words_into_captions` and `CAPTION_PRESETS` out of
`captions/routes.py` into `captions/service.py` and `captions/presets.py`; move
`_apply_segmenter_timing`, `_normalize_webhook_response`, and
`generate_with_chapters_chunked` out of the scene-director `routes.py` into its service
layer; split the 2,821-line editor `routes.py` into separate blueprints (app settings, SFX
library, project discovery, assemble, archive, fonts/overlays, export). `VideoProcessor`
keeps its clean `dict in → .process(path)` boundary and is not rewritten. Audit every
adapter for absolute-path leakage into port payloads — V2's `adapters/export.py` still
emits an absolute `"path"`, violating the rule its TTS adapter enforces. Do **not** port
`pipeline/routes.py`, the legacy step pages, the dead provider ABC layer, or
`providers_common/http_client.py`.

Handed over by 0.2, which ported each domain's `providers/` package and the modules those
import at module scope so the platform could register and validate providers at all:

- **Restore five deferred test modules** from V2 with the code they exercise —
  `test_workflow_adapters`, `test_workflow_utilities`, `test_provider_first_execution`,
  `test_provider_platform_gate`, `test_provider_transports` — plus
  `BlueprintRegistrationTests` (`test_provider_api`) and `AppConfigKeyRetirementTests`
  (`test_provider_cleanup`), both of which register `editor_bp` and so must be rewritten
  against the split blueprints rather than restored verbatim.
- **Close the two `routes.py` imports the port carried in**:
  `video/providers/grok_automa` reaches into `video/routes` for its WebSocket runtime, and
  `scene_director/service` imports three helpers from its own `routes`.
- **Re-add `pipeline/services.py`'s successor to `AUDITED_SURFACES`** in
  `test_provider_extensibility`, at whatever path the `_step_*` functions land.
- **Relocate `scriptase/modules/pipeline`** — 0.2 renamed the four adapter imports of
  `studio.pipeline.services` mechanically rather than guessing their 0.3 homes.
- **Retire `modules/niches/`** — 1.3 migrates the presets into starter Channels.

**Done when:** no module imports business logic from a `routes.py`, a test proves no port payload contains an absolute filesystem path, and the ported adapter suite is green.

### 0.4 Contract freeze and gate

Adapt V2's `contracts.md` (node, port, execution-record, API, and error contracts) into
`plans/contracts.md` and add the new Scriptase sections: `Artifact`, `ChannelProfile`,
`Job`, `ProviderInstance`, `ReviewIssue`, `SceneSpec`, and the stage-projection contract.
Extend `Provenance` with generation-reproducibility fields — provider seed, request id, and
model revision — **now**, while nothing has been recorded yet. Snapshotting configuration is
not reproducibility with generative providers: same config, different image. This is also
what makes §12.1-style repair instructions ("preserve character and composition, change
lighting to sunrise") achievable rather than a re-roll. Record what is deferred and who owns
it, and resolve any doc/code conflict in favour of working behaviour.

**Done when:** contracts.md covers every schema Phases 1–10 touch, `Provenance` carries seed/request-id/model-revision through the result envelope, and the app boots and serves the full node catalogue from `GET /api/workflow/node-types`.

---

## Phase 1 — Domain foundation: Artifacts, Channel, Job

The walking-skeleton milestone (§4, §15). Artifacts come **before** Job because
`Job.artifacts[]`, `ReviewIssue.target_artifact_id`, `repair_history[]`, the cross-Job input
picker, and "repair the smallest responsible scope" all key off them.

### 1.1 ChannelProfile model and store

Pydantic model per §15.1: `branding`, `content`, `visual_direction`, `audio_defaults`,
`provider_defaults`, `fallback_policies`, `review_policy`, `export_defaults`,
`default_workflow_id`, plus `version`. Persist with atomic `safe_json_write` and
forward-only versioned migrations, matching the settings-store pattern already ported.
`visual_direction.pattern` is **structured** — an ordered map of narrative role to shot
direction (`hook → extreme close-up`, `explanation → medium cinematic`, …) — never one
free-text field (§4.2). This is what makes Scene Director deterministic and a Channel
genuinely reusable instead of a saved prompt.

**Done when:** a Channel round-trips create/read/update/delete with a version bump, and schema validation rejects a malformed pattern block with a structured error.

### 1.2 Artifact model, content-addressed store, and versioning

Replace V2's `artifact_refs: list[str]` convention — a naming convention, not a type — with
a real `Artifact`: stable id, kind, owning job, owning scene (nullable), version, content
hash, relative managed path, size, mime, provenance reference, and `superseded_by`.
Versions are immutable and additive (`image_v1`, `image_v2`), so a repair never erases the
evidence of what it replaced (§17). Keep the existing `ArtifactPromoter` staging/promotion
flow and the cache's artifact-integrity re-hashing intact; this layer sits above them and
records what they produce. Provide a resolver so adapters keep emitting relative refs and
gain artifact identity for free.

**Done when:** regenerating any artifact produces a new immutable version with the prior one still resolvable and marked superseded, and the engine's cache-integrity tests pass unchanged.

### 1.3 Channel API, UI, and preset migration

CRUD routes and a Channel editor page, with logo upload through the managed-branding
endpoint already ported (never a browser-supplied filesystem path). Seed starter Channels
by migrating V2's `_data/niche_presets.json` — `niche`, `visual_style`, `story_tone`,
`voice`, `speed`, `duration` map onto `content`, `visual_direction`, and `audio_defaults`.
Channels reference provider **instance ids**, never duplicated account configuration (§14).

**Done when:** every niche preset appears as an editable starter Channel and a new Channel can be created, edited, and deleted end-to-end in the browser.

### 1.4 Job model and store

Per §15.2: `channel_id`, `channel_snapshot`, `workflow_id`, `workflow_version`,
`execution_mode`, `source {mode, topic, idea, pasted_script, references}`, `status`,
`current_stage`, `artifacts[]`, `issues[]`, `repair_history[]`, `execution_id`, timestamps.
The snapshot rule is absolute (§4.3, §21): capture non-secret Channel configuration and
provider **instance references** only. Secrets resolve from the provider instance at
runtime and never enter a Job, an execution record, an export, or a log.

**Done when:** starting a Job writes a snapshot that a redaction test proves contains no credential, and a Job survives a process restart with its status and artifact set intact.

### 1.5 Job orchestration over the ported engine

A Job wraps `execution_manager.start()`; it does **not** become a node (§19). Channel
defaults reach node configuration through the ported `inherited_config()` precedence —
explicit node config beats inherited channel config, and an empty string is not explicit.
Job status derives from the execution record rather than being tracked separately, so the
two can never disagree.

**Done when:** a Job created from a Channel runs the default workflow through to export, and its artifacts match a direct workflow run of the same graph byte-for-byte.

### 1.6 Stable scene identity and the re-segmentation rule

Scenes in V2 are array indices inside `scenes.json`. The entire review and repair design is
per-scene (`ReviewIssue.scene_id`, per-scene repair, "do not regenerate all scenes because
one fails"), and §12.2 explicitly allows an issue to route back to **Segmenter** — at which
point every downstream index shifts and every open issue and generated artifact silently
points at the wrong scene. Give scenes stable ids that survive re-segmentation, carry the
ordinal separately as presentation data, and define explicitly what happens to a scene's
artifacts and open issues when its boundaries change (rebind, supersede, or invalidate).

**Done when:** re-running the segmenter with different parameters keeps stable ids for unchanged scenes, and a test proves no open issue or artifact is left bound to a scene that no longer exists.

### 1.7 project.setup reads the Job's channel snapshot

V2's `project.setup` node carried `channel_name`, the logo block, `tone`, `style`, and
`aspect_ratio` — a proto-Channel. It stops being the source of identity and becomes a
reader and per-workflow override of the Job's channel snapshot, so saved V2-era workflows
keep running.

**Done when:** a saved V2-era workflow containing `project.setup` runs inside a Job and takes channel values wherever its own configuration is empty.

---

## Phase 2 — Production view

§3.1 and §18. Non-negotiable: the same nodes, registry, execution records, artifacts, and
provider configuration back both views. Two views of one system, not two implementations.

### 2.1 Port the workflow builder frontend

Bring V2's `features/workflow/` (Vue Flow canvas, dagre auto-layout, registry-driven
inspector, execution panel), `features/providers/` (catalog store and schema-driven forms),
and `shared/` (api client, error envelope handling, schema helpers, composables) across
with their Vitest suites. The frontend renders entirely from `GET /api/workflow/node-types`
and hardcodes nothing but SVG icon paths and port colours — preserve that property.

**Done when:** the canvas loads, validates, runs a workflow, and streams execution over SSE in the new repo, with every ported frontend test green.

### 2.2 Stage projection, derived from the graph

An endpoint projects a workflow graph into an ordered stage list. The projection is
**computed from the graph**, never a hardcoded step array in the frontend — that is the only
thing that actually enforces §3's rule. Side branches (captions, music, branding,
validators) collapse into the stage where they merge, so the Production view stays simple
while the DAG stays honest.

**Done when:** the default workflow projects to Script, Voice, Timing, Segments, Scenes, Images, Videos, Review, Composer, Export, and adding a parallel caption branch changes the graph without adding a step.

### 2.3 Production page

The §3.1 step list with live per-step status, driven by the same SSE stream the canvas
consumes — including its ring-buffer reset-snapshot and `Last-Event-ID` resume behaviour.
No second polling mechanism.

**Done when:** running one Job updates the Production view and the Workflow canvas simultaneously from a single execution, and both survive a mid-run page reload without losing state.

### 2.4 Step detail panel

Per §18: Run, Test, Regenerate, Run From Here, View Input, View Output, Provider, History,
Approve. Each maps onto an existing ported run mode (`node_with_deps`, `from_node`,
`node_isolated`, `retry_failed`) — no new execution paths are introduced. Provider selection
appears only where the stage is provider-capable and the selected mode requires one (§6,
§19); `-P` never appears in a stage name.

**Done when:** each action on a step produces the same execution record a canvas-initiated run would, proven by a test comparing both records field by field.

### 2.5 Job creation and Script stage modes

Step 0 is Job creation: Channel picker, topic/idea/paste input, workflow choice, execution
mode. The Script stage exposes Automatic, Topic→Script, Idea→Script, Paste Script, and
Manual/Edit (§6). Provider UI is shown only in the modes that need one; Paste and Manual
require no provider at all.

**Done when:** a Job created with Paste Script runs to export with no script provider configured or reachable.

### 2.6 Durable approval state in the engine

§8's Assisted mode pauses at configured checkpoints and §18 offers an Approve action, but
the ported engine has no pause — its states are queued, running, succeeded, failed,
cancelled, partial. Implemented naively a checkpoint blocks a worker thread for as long as
the human takes. Add an `awaiting_approval` state that releases the worker, persists the
resume point, survives a restart, and resumes on approval or expires by policy. This is an
engine primitive, not UI work, and Phase 9 consumes it.

**Done when:** a Job pauses at a checkpoint holding no worker thread, survives a full process restart, and resumes from exactly where it paused on approval.

---

## Phase 3 — Provider instances, capabilities, and secret references

§7. All four gaps are real and each has one identifiable blocker in the ported platform.

### 3.1 Split provider type from provider instance

Today one identity does four jobs at once: folder name = manifest `id` = catalog key =
settings key = wire value, and the catalog builder actively rejects duplicates. Introduce
`instance_id` as a separate axis; settings become
`instances: {<instance_id>: {type, label, settings}}`; memoize provider construction per
`(type, instance_id)`; key the `exclusive_execution` lock on the same pair; add the path
segment to provider routes. `resolve_settings`, availability, `validate_settings`, and
`health_check` are already pure functions of a passed-in settings dict and work per
instance unchanged — that is the load-bearing piece of good news. This is the highest-risk
step in the plan; land it alone.

**Done when:** two instances of one provider type hold independent settings, availability, and health state, and a V2 settings file migrates forward with its selection intact.

### 3.2 Instance-aware API and UI

Provider routes, the generic `provider` and `provider_options` node widgets, the frontend
catalog store, and the option-source context all key on instance. V2's
`GET /api/workflow/options/<source>` already accepts `(domain, provider)` context; widen it
to instance so a dropdown can follow the selected instance.

**Done when:** a node can select two instances of the same provider type and each resolves its own model and voice lists through the option-source endpoint.

### 3.3 Capability selector and fallback schema

Capabilities are declared per domain and per provider but are only ever consumed as feature
gates — nothing asks "give me a provider in this domain supporting this capability". Add a
selector returning ordered candidates for a capability query. Persist `fallback_policies`
(primary plus ordered fallbacks, per stage) from day one even though the runtime resolves a
single instance in v1 (§7.3); execution lands in 8.3.

**Done when:** the selector returns correctly ordered candidates for a capability query, and a persisted fallback chain round-trips through Channel and Job without being executed.

### 3.4 Secret references

Replace plaintext credentials in the settings store with `{"$secret": "<ref>"}` indirection.
The whole resolution path is one function, `ProviderInstance.resolve_settings()`. Redaction
actually simplifies, because a reference is not itself a secret. Note that
`manifest.environment` env-fallback is per **type** and becomes ambiguous once instances
exist — scope it to the default instance and document that.

**Done when:** no credential appears anywhere in the settings store, and the egress-validation and redaction suites pass on every domain.

### 3.5 Global work pool and pre-flight budget check

V2 runs one drain thread per project, unbounded, with no global cap and no admission
control — ten scheduled Channels means ten schedulers with no ceiling. There is also no cost
model at all beyond price strings in dropdown labels. Replace per-project drain threads with
a single bounded work pool preserving per-project FIFO ordering, and add a **pre-flight**
budget check that refuses to start work that would exceed a Channel's or Job's ceiling,
rather than reporting the overrun afterwards.

**Done when:** N concurrent Jobs never exceed the configured global worker ceiling while preserving per-project ordering, and a Job whose next stage would exceed its budget is refused before the provider is called.

---

## Phase 4 — Standalone node execution

§9. The ported engine already supports `node_isolated` with stub auto-attach and pinned
stub outputs; this phase is the input-sourcing experience, now backed by 1.2's artifacts.

### 4.1 Artifact library and input picker

Supply a node's required inputs from the current Job, a previous Job, the artifact library,
a managed upload, a manual value, a generated sample stub, or by running the missing
dependencies (§9.1).

**Done when:** a Video Generator node runs standalone against a scene and image chosen from a different Job, with the source artifacts recorded in the resulting execution record.

### 4.2 Test Node panel

The §9 interface wired to `node_isolated`. Results keep the ported "from sample data"
marker so stub-derived output is never mistaken for real output, and a test run never
advances the Job.

**Done when:** testing a node leaves the Job's status, current stage, and artifact set unchanged, proven by a test asserting all three before and after.

### 4.3 Attempt history and comparison

Surface 1.2's immutable versions: per-node attempt history with side-by-side comparison of
artifact versions, the resolved provider instance, and the prompt revision used.

**Done when:** regenerating a scene image shows both versions side by side with their provider instance, seed, and prompt revision.

---

## Phase 5 — Scene Director

§5.1 and §11. Formalises the ported scene-blueprint logic under a clearer contract and
product name. The script becomes visual scenes here — Segmenter only decides where narration
divides.

### 5.1 SceneSpec contract

Per §11: narration, visual description, image prompt, motion prompt, camera, lighting, mood,
continuity, and overlay/SFX hints, carried on the stable scene id from 1.6. Extends the
ported `SceneItem` and result payload, which are already pydantic with a strict envelope.

**Done when:** every SceneSpec field round-trips through the provider result envelope and the image and video adapters read SceneSpec rather than loose dicts.

### 5.2 Channel visual direction feeds the Director

The structured pattern, palette, lighting, camera, continuity rules, negative prompts, and
references from 1.1 become typed request inputs. No prompt text lives outside a provider
module.

**Done when:** two Channels with different patterns produce measurably different scene specs from the same script, and a scan proves no prompt text exists outside provider packages.

### 5.3 Timing strategy AUTO

Rename Force Alignment to Timing (§10). When the TTS provider advertises native word
timing, normalise and validate it; otherwise run alignment. Downstream consumes one
canonical alignment artifact either way.

**Done when:** both strategies produce an identical alignment schema and the segmenter cannot determine which one ran.

### 5.4 Prompt evaluation harness

Scene Director and Review are prompt-driven, and a prompt change currently has no regression
signal. Extend the ported golden-fixture machinery
(`tests/fixtures/providers/<domain>/<provider>/{request,raw_response,expected_result}.json`)
into a prompt-eval harness: a small set of scripts with expected scene structure, run
offline against recorded responses, reporting structural drift rather than exact-text
equality.

**Done when:** a deliberate prompt regression is caught by the harness offline, with no provider credits spent.

---

## Phase 6 — Image and video split with capability routing

§7.4. Do not hard-code image as a mandatory input to every video provider.

### 6.1 Separate image and video domains

Give each its own capability vocabulary — `text_to_image`, `image_edit`, `reference_image`,
`inpainting` for image; `image_to_video`, `text_to_video`, `reference_image`,
`duration_control` for video — declared per provider and surfaced in the node and step UI.

**Done when:** each domain declares its capabilities per provider and the UI shows them, with a test asserting an undeclared capability is never offered.

### 6.2 Optional image dependency

A `text_to_video` provider consumes Scene Director output directly, while the default
workflow still routes through image-to-video for visual consistency.

**Done when:** a workflow with no image node runs to export using a text-to-video provider, and the image-to-video path still works unchanged.

---

## Phase 7 — Review

§12. Deterministic technical checks run first; expensive AI review is never the only
validation layer.

### 7.1 Technical validators

File exists, readable media, resolution, duration, aspect ratio, audio presence, frame
count, expected artifact count (§12.4). No provider required.

**Done when:** each validator has a failing fixture and emits a structured issue rather than free text.

### 7.2 ReviewIssue schema and store

Per §15.4: `target_node_id`, `target_artifact_id`, scene id, `issue_type`, `severity`,
`confidence`, `reason`, `suggested_action`, `repair_instruction`, `attempt_count`, and
`status`. Free-form text is not an acceptable review output (§21) — automation depends on
structure.

**Done when:** review returns only structured issues, enforced by a schema test that rejects a free-text result.

### 7.3 Review provider domain

Add a sixth domain with `image_review`, `video_review`, `text_review`, and
`structured_output` capabilities. Adding a domain is explicitly a data change in the ported
platform, so this must require no framework redesign.

**Done when:** a semantic reviewer returns structured issues through the standard result envelope and error boundary, and adding it required no change outside its own package and the domain catalogue.

### 7.4 Early quality gates

An image gate before video generation and a video gate before final review (§12.3). This is
where the money is saved: a bad source image must be repaired before it is animated.

**Done when:** a deliberately bad source image is caught and repaired before any video generation call, proven by asserting the video provider was never invoked.

---

## Phase 8 — Repair Router

§12.1 and §12.5. Repair the smallest responsible scope; never regenerate every scene
because one failed.

### 8.1 Routing policy

Each issue routes to the node responsible for fixing it, per the §12.2 ownership table —
script length and tone to Script, pronunciation to TTS, misalignment to Timing, poor
boundaries to Segmenter, wrong visual concept to Scene Director, wrong subject to Image,
deformation to Video, caption and branding to Composer, codec failure to Export. Table-driven,
not conditional logic scattered through the engine.

**Done when:** every issue type in the §12.2 table routes to its owning node, enforced by a table-driven test.

### 8.2 Targeted repair with budgets and escalation

Per-scene repair using the stable ids from 1.6. Maximum attempts per issue, maximum
generations and cost per Job, escalation to human review on low confidence or repeated
failure, and configured safe degradation — keep the still image when video generation
repeatedly fails (§12.5). Repairs consume 3.5's pre-flight budget check.

**Done when:** an unfixable issue escalates instead of looping, and a Job that reaches its repair budget stops with a clear reason rather than continuing to spend.

### 8.3 Fallback execution and per-unit provenance

Activate 3.3's chains. The blocker to resolve first: the ported result envelope and
provenance are single-provider by construction, while a fallback run produces units from
different providers. Make provenance per-unit and record why each instance was chosen — the
`selection_reason` field already exists as the designated slot for
`fallback_after:<instance>`.

**Done when:** a primary-instance failure falls through to the next instance and the record shows exactly which instance, seed, and model revision produced each unit.

### 8.4 Repair history

Persist every issue, routing decision, action, provider instance, prompt revision, and
result, tied to the superseded artifact versions from 1.2 (§12.5).

**Done when:** a repaired Job's history reconstructs the full sequence including every superseded artifact version and the reason each repair was attempted.

---

## Phase 9 — Automation

§8. Unattended execution is a first-class feature, not a batch script.

### 9.1 Execution modes

Manual, Assisted, and Automatic, with configured checkpoints and the §8 automatic policy
block (retry budgets, fallback after retry exhaustion, pause only on critical semantic
issues, maximum repair cycles per scene, safe degradation, automatic export when quality
gates pass). Assisted consumes 2.6's `awaiting_approval` state.

**Done when:** an Automatic Job runs start-to-export with no human input, and the same Job in Assisted mode pauses at exactly its configured checkpoints and nowhere else.

### 9.2 Channel-driven triggers

The ported schedule, watch-folder, and webhook triggers create **Jobs** rather than raw
executions, and a Channel can carry a content cadence. Fix V2's defect where trigger
services only start under `__main__` and therefore never run under a WSGI server.

**Done when:** a scheduled Channel creates and completes a Job unattended with the queue record showing its trigger source, and triggers run under both the dev server and a WSGI host.

### 9.3 Cost accounting and reporting

Accumulate generation count and cost per Job and per Channel on the provenance records from
0.4, and surface them in the Job view. The enforcement half already landed in 3.5; this is
the accounting and reporting half.

**Done when:** a completed Job reports accumulated generation count and cost per stage and per provider instance, reconciling with its provenance records.

---

## Phase 10 — Migration and hardening

### 10.1 V2 import

Import existing V2 projects, artifacts, workflows, and settings. Provider-domain renames and
settings-shape aliases live in exactly one documented migration module (§21).

**Done when:** a V2 project imports and re-exports without manual edits, and its saved workflows validate and run.

### 10.2 Indexed storage for runs, queue, jobs, and notifications

V2 lists executions, queue records, and notifications by scanning and parsing every file per
call, and rewrites the entire execution record — including the full workflow snapshot — plus
a backup copy on **every node status transition**, roughly sixty full-document writes per
twenty-node run. Introduce a SQLite index behind the existing repository interfaces and make
node status transitions incremental. Artifacts and media stay on disk.

**Done when:** listing five hundred executions is constant-query rather than a full scan, a twenty-node run performs an order of magnitude fewer full-document writes, and the entire engine suite passes unchanged.

### 10.3 Crash recovery and startup reconciliation

V2 never reconciles pending or running records on boot, `ProjectLock` has no pid-liveness
check so one stale lockfile means a project is locked forever, and staging directories
accumulate. Automatic mode is precisely where crashes happen unattended, so this is what
makes §8 true rather than aspirational.

**Done when:** a hard kill mid-run leaves no permanently-running execution, no stale lock, and no orphaned staging directory after the next boot.

### 10.4 Observability, generated docs, and final gate

Replace the blanket silent exception handlers in the trigger loops and notification dispatch
with logged failures. Regenerate the node and provider references from the live registry
with drift checks. Run the full end-to-end acceptance from proposition-final.md.

**Done when:** all verification commands are green, generated docs show no drift, and a fresh clone completes the end-to-end acceptance run from Channel creation to export.

---

## Phase 11 — Wire the correction loop

Phases 7 and 8 built the Reviewer and the Repair Router and never connected them. In a real
run **no ReviewIssue is created and no repair fires**: `plan_job_repairs`,
`process_job_repairs`, and `apply_repair_plan` (`scriptase/review/repair.py:900, 1221, 1268`)
have zero callers outside tests, no `review.*` node is registered, and the `review` provider
domain is the only one of six with no node consuming it. This phase writes almost no new
logic — it wires up roughly 6,500 existing, tested lines.

### 11.1 Register the review node and expose gate configuration

Add a provider-capable `review.run` node against the orphaned `review` domain, built from the
existing `_provider_field` / `_provider_options_field` helpers
(`scriptase/engine/registry.py:133-164`). Its executor wraps `run_technical_validators()`
(`scriptase/review/technical.py:986`) and, when an instance is selected, the `semantic`
reviewer. Declare the quality-gate keys `skip_quality_gate`, `image_gate_max_repairs`, and
`image_gate_semantic` in the Image and Video `config_schema` — they are read at
`scriptase/review/gates.py:712-797` but declared nowhere, so no user can reach them. Write the
`type_version` migrations in this same step; the runner refuses to skip a hop.

**Done when:** `review.run` appears in the node catalogue with its config rendering in the inspector, the three gate keys are settable from the UI, and saved workflows migrate without manual edits.

### 11.2 Emit ReviewIssues during a real run

Call `create_from_technical` and `create_from_review_result` from the review adapter and
persist through `scriptase/review/store.py:69-90`. Attach the issue ids to the Job through the
projection path that already reads them (`scriptase/jobs/stage_projection.py:439-501`).

**Done when:** a Job run against a deliberately broken artifact ends with persisted ReviewIssues carrying target node, target artifact, severity, and confidence.

### 11.3 Fire the Repair Router from job orchestration

Wire `plan_job_repairs` → `apply_repair_plan` → `process_job_repairs` into
`scriptase/jobs/orchestration.py`, which today contains no reference to review or repair at
all. Route through the frozen §12.2 ownership table (`scriptase/review/policy.py:34-76`, entry
point `route_issue()` at `:367`). Bound every cycle by the Channel's
`review_policy.max_repairs` and the pre-flight budget check
(`scriptase/jobs/budget.py:247`). Prove escalation before proving repair: this step introduces
re-execution into a path that has never re-executed.

**Done when:** a bad scene image is repaired at the responsible node only, re-reviewed, and the Job continues; and an issue that exceeds `max_repairs` escalates instead of looping.

### 11.4 Surface issues and repair history in Production

Render `stage.issues` in `StepDetailPanel.vue` — the projection already carries them and no
frontend code reads them. Add a repair-history pane backed by the existing read-only endpoint
`GET /api/jobs/<job_id>/repair-history` (`scriptase/jobs/routes.py:302`), which nothing
currently calls.

**Done when:** a repaired Job shows each issue, the node it was routed to, what was retried, and the superseded artifact versions.

### 11.5 Rename Scene Blueprint to Scene Director

The node still carries V2's display name "Scene Blueprint" (`scriptase/engine/registry.py:349`),
which is why the stage is hard to find in the library. Change the display name and description
only — the type key `scenes.blueprint` must not change, per contracts §1.2.

**Done when:** the node library and Production both show "Scene Director", and a saved V2-era workflow still loads and runs unchanged.

---

## Phase 12 — Simplify the canvas and make providers usable

### 12.1 Node visibility

Add a `hidden` flag to registry definitions and honour it in the `groups` computed at
`frontend/src/features/workflow/components/NodeLibrary.vue:14-31`. Hide the utility and
testing nodes and anything outside the Full Video path. Nodes stay registered and executable,
so saved workflows and the test suite are unaffected. Add a "Show all nodes" toggle so the
palette is recoverable. Make visibility explicit rather than relying on `CATEGORY_ORDER`
(`:12`), which silently drops any category missing from the array.

**Done when:** the library shows only the Full Video stages by default, the toggle reveals the rest, and every hidden node still runs.

### 12.2 Full Video as the default canvas

Opening `/workflow` with nothing saved currently shows an empty canvas reading "Drag a node
from the library to start building". Load the Full Video template instead
(`scriptase/engine/templates.py:39`).

**Done when:** a fresh install opens a complete, runnable Full Video graph and Production's workflow dropdown is populated on first use.

### 12.3 Mount the real provider selector on nodes

`frontend/src/features/providers/components/ProviderSelector.vue` already implements
availability states, disabled-with-reason entries, a health probe, capability badges, and a
settings gear — and is mounted by nothing. Give it a controlled `modelValue` mode (props in,
emit out) beside its current catalog-bound mode, then use it in place of the bare `<select>`
at `ConfigField.vue:242-256` for `type === 'provider'`. The option source already returns
configured instances, so instance selection is preserved.

**Done when:** the node inspector shows per-instance health and availability, and an unconfigured instance is visibly unusable instead of failing at run time.

### 12.4 A Settings route for provider instances

There is no Settings page, so credentials cannot be entered from the browser at all. Add
`/settings/providers` mounting the finished-but-unmounted `ProviderConfigurator.vue` and
`ProviderSettingsModal.vue` (which already has Test Connection and Save), plus create, rename,
and delete of named instances against the existing `/api/providers/*` routes. Secrets stay
write-only.

**Done when:** a user can add a second named instance, enter its key, test the connection, and select it on a node without editing a file, and no credential is ever echoed back.

### 12.5 Document and script the add-a-provider path

`scriptase/providers/scaffold.py` already generates a conforming provider package per domain.
Wire it to a documented one-command path and regenerate the provider author guide from the
live hub.

**Done when:** adding a provider requires creating and registering its package alone, proven by the existing extensibility test that fails if any other file changes.

---

## Phase 13 — Serial queue and real node testing

### 13.1 Run Jobs strictly in queue

`GLOBAL_WORK_POOL_SIZE` (`config.py:138`) defaults to 4, so Jobs run four at a time. Default it
to 1 for strict submission-order execution, keeping `SCRIPTASE_GLOBAL_WORKERS` as the
override, and surface queue position in the Production and Run Queue views. The per-project
FIFO and fair rotation in `scriptase/engine/execution.py:175-200` already provide the
ordering.

**Done when:** three Jobs started together execute strictly one after another, each showing its queue position, and raising the override restores concurrency.

### 13.2 Accept a provider override on a test run

Add a one-shot `provider_instance_id` to `POST /api/jobs/<job_id>/test-node`
(`scriptase/jobs/routes.py:373`) and the workflow run path, resolved for that execution only
and recorded in provenance's `selection_reason`. It must never mutate the node's stored
configuration.

**Done when:** one node can be tested against two instances back to back, each result recording which instance produced it, with the saved node config unchanged.

### 13.3 Test any node from the canvas, with a provider picker

`TestNodePanel.vue` already handles per-port input binding, run-mode derivation, and Job
safety, but is reachable only from Production stage rows and shows the provider as read-only
text (`:157-162`). Add a provider picker wired to 13.2 and open the panel from the canvas node
context menu, replacing the three blind isolation items at `WorkflowPage.vue:1044-1046` that
fire immediately with no inputs and no provider choice.

**Done when:** right-clicking any node opens the test panel with input pickers and a provider choice, and a test run never advances the bound Job.

---

## Phase 14 — Video editor and export library

The backend is already ported: `scriptase/modules/compose/` is a refactored split of V2's
editor routes, and all 33 endpoints the editor calls plus the seven export-library routes in
`compose/export_routes.py` are live. This phase is a frontend port.

### 14.1 Shared prerequisites

Port `frontend/src/shared/utils/format.js` from V2 (missing here, used by both features) and
add the three CSS custom properties `editor.css` expects and the current theme lacks:
`--bg-darker`, `--border-subtle`, `--text-dim`.

**Done when:** both exist and the frontend suite stays green.

### 14.2 Port the timeline editor

Copy `frontend/public/js/editor/*` verbatim — `video-editor.js` (12,106 lines), `preview.js`,
`export-api.js`, `utils.js` — they are self-contained ES modules using only `fetch`, DOM ids,
and `window.*`. Then port the Vue host `frontend/src/features/editor/*`: `EditorPage.vue`,
`useEditor.js`, `editor-shell-html.js`, `editor-inline-scripts.js`, eight dialog components,
and `editor.css`. Replace the Pinia `stagingStore` import in `useEditor.js` with
`sessionStorage` plus route query, since this app has no Pinia. Add the `/editor` route, which
fixes the dead "Open in Timeline Editor" button at `ExecutionPanel.vue:175-179` that currently
navigates to a blank page. Port it as-is; it has no test suite to catch a rewrite going wrong.

**Done when:** an assembled project opens in the editor, scenes reorder, audio tracks play, edits persist to `work@in@progress.json`, and an export starts.

### 14.3 Port the export library

Copy `frontend/src/features/export-library/*` — idiomatic Vue 3 with no legacy bridge, whose
only missing dependency is `format.js` from 14.1 — and add the `/exports` route.

**Done when:** every exported video is listed with thumbnail, duration, resolution, and aspect ratio, and download, ZIP, delete, and folder-sync all work.

### 14.4 Open both in their own windows

Open `/editor` and `/exports` through `window.open` with sized features, from Production, the
workflow execution panel, and the nav, so Production keeps running while you edit.

**Done when:** both open as separate windows, survive a reload, and remain directly linkable by URL.

---

## Phase 15 — Bundled Chromium and the extensions

Two production providers are extension transports: a real logged-in browser is mandatory
because Grok and Gemini have no usable API for this. The WebSocket hubs already exist
(`scriptase/modules/video/ws_runtime.py:35`, `scriptase/modules/image/gemini_ws.py:40`).
Nothing about Chromium exists in V2's Python, so there is no app code to untangle.

### 15.1 Chromium bootstrap in PowerShell

Rewrite V2's 253-line `launch-chromium.bat` as a PowerShell module beside `tools/launch.ps1`:
download ungoogled-Chromium from the GitHub releases API when `bin/chromium/` is empty rather
than vendoring the 183 MB zip, extract it, and maintain `data/chromium-profile/`. The
persistent profile is the entire point — it holds the Google and Grok logins.

**Done when:** a clean checkout downloads and launches Chromium once, and later launches reuse it in about a second.

### 15.2 Port the four extensions

Bring `STS-grok-sync`, `STS-gemini-sync`, `STS-devtools-extension`, and
`ai-web-auto-extension` into `tools/extensions/`, and pin them by their existing hardcoded
ids, which survive a copy. Port blocker: the extensions hardcode `ws://localhost:5050` while
Scriptase serves on 5000 — make the endpoint configurable and inject the real port at launch
rather than hardcoding either value, or the sockets silently never connect and it looks like a
provider bug.

**Done when:** all four load pinned in the profile and both provider hubs report a connected socket.

### 15.3 Launcher sequencing

Follow V2's proven order: Flask first because the extensions need the WebSocket, then
Chromium, then Vite. Open the app through CDP `json/new` against the existing window instead
of spawning a second browser. A Chromium failure must be non-fatal; a Vite failure stays
fatal.

**Done when:** `start.bat` yields a Chromium window with the app and provider tabs loaded, and a Chromium failure still leaves a working app in the default browser.

### 15.4 The ai-web-auto backend

A separate repository with its own venv and a `:8765` server — the most tangled dependency
carried over from V2. Vendor it under `tools/automation/ai-web-auto/`, provision its venv from
the main launcher, and start it only when its port is free.

**Done when:** the launcher starts it when absent, skips it when already listening, and its absence degrades to a warning rather than blocking startup.

---

## Phase 16 — Script virality analyzer

Greenfield. V2's `resources/niche-analyzer/` is four sample media files its own notes marked
for deletion, and no scoring logic has ever existed. What is reusable is the taxonomy.

### 16.1 Deterministic scoring module

New `scriptase/modules/viral/` scoring measurable signals, reusing V2's structure: the
mandated Hook / Build / Climax / CTA sections, the fifteen hook archetypes from
`_ANGLE_STARTERS`, and the `narrative_role` enum already flowing through Scene Director. Score
hook presence and position, opening-line strength against the archetypes, pacing and word rate
against the target duration, open loops, CTA presence, and section balance. Offline,
deterministic, unit-testable, and free to run.

**Done when:** a known-strong and a known-weak script produce clearly separated scores with per-dimension reasons, and identical input always scores identically.

### 16.2 The script.analyze node

Provider-capable against a new optional `viral` domain that defaults to the deterministic
scorer, so an LLM judge can be added later without changing the node contract. Sits after
Script and emits a typed score plus dimension breakdown.

**Done when:** the node runs inside the Full Video graph and emits a typed result that the Composer path ignores and Review can read.

### 16.3 Script-stage panel and Review integration

Show the score and its dimension breakdown on the Script stage in Production, before the
expensive stages run. Emit a ReviewIssue when the score falls below the Channel threshold so
the Repair Router — live as of 11.3 — routes a weak hook back to Script.

**Done when:** a weak script surfaces a low score before TTS runs, and an Assisted-mode Job pauses at the script checkpoint.

---

## Phase 17 — Adopt the prototype design system

`prototype/scriptase-prototype.html` is the visual and behavioural target. It defines a
complete "machined control-room" system — tinted ink elevation layers, a blue→violet duotone
accent used only on primary and active states, layered shadows with a top hairline so
surfaces read as lit, and spring easing. The app currently uses an unrelated token set
(`--bg-dark`, `--accent-primary`, …). Swap it wholesale: a half-themed app looks broken.

### 17.1 Port the token set and primitives

Replace `frontend/src/styles/theme.css` with the prototype's `:root` block — the ink scale
(`--bg`, `--bg-2`, `--panel`, `--panel-2`, `--raise`, `--line`, `--line-soft`, text ramp),
the duotone accent pair and `--accent-grad`, status colours (`--run`, `--ok`, `--fail`,
`--warn`, `--queue`, `--sched`) with their dim partners, `--panel-grad` and `--panel-grad2`,
`--hairline-top`, the three radii, `--shadow` / `--shadow-sm` / `--glow`, `--ease-spring`,
and the three font stacks. Keep the current names as deprecated aliases mapped onto the new
values so nothing goes unstyled mid-phase.

**Done when:** every prototype token exists in the theme, the production build succeeds, and no view renders with an unresolved custom property.

### 17.2 Restyle the shipped views onto the new system

Bring Production, Channels, Providers and the export library onto the new primitives: raised
panels use the panel gradient plus the top hairline, the duotone accent appears only on
primary and active states, and status badges use the status ramp. The Editor keeps its own
teal identity deliberately — it mirrors the ported ScriptToScene editor and is excluded from
this sweep.

**Done when:** no component references a deprecated alias, the four views match the prototype visually, and the Editor retains its distinct teal theme.

### 17.3 The UX floor

The prototype treats these as baseline rather than extras: an animated first-run welcome
overlay with an Enter Studio button, auto-skipped on deep links; keyboard control (arrow keys
through the job list, Enter to expand, Space to select, E for editor, R to run, slash for
search, question mark for the shortcuts sheet, Escape to close); a five-second Undo toast for
destructive actions instead of a confirm dialog; focus-visible rings on every control;
reduced-motion honoured by disabling pulses, flows and spinners; tablist semantics with
aria-current on the nav; aria-labels on icon-only buttons; live-region toasts; and a
responsive collapse below 820px with no horizontal overflow.

**Done when:** every listed affordance works, reduced-motion disables all looping animation, and a 375px viewport shows no horizontal scrollbar.

---

## Phase 18 — Information architecture and the Schema view

The prototype's nav is Script, Production, Schema, Library, Channels, Providers — ordered
create, run, monitor, output, configure. Schema is a read-only projection of the running job;
it never executes anything, which is the one rule the whole project hangs off.

### 18.1 The six-destination nav and routes

Rename the exports route to `/library`, add `/script` and `/schema`, promote provider
settings to a top-level `/providers`, and render the nav in the prototype's order with an
icon per item. Keep redirects from every previous path so existing links and the editor's
deep links survive.

**Done when:** all six destinations route correctly, the nav matches the prototype's order and labels, and every previous route redirects rather than returning a 404.

### 18.2 The Schema graph, projected from the engine

A read-only canvas rendering the workflow as nodes and edges on a virtual grid. Structure
comes from the backend node registry and the stage projection, never a hardcoded array in the
frontend. Drag to reposition and right-click to realign (auto-layout, snap to grid, reset,
fit and centre); two-finger scroll pans and pinch or Ctrl+wheel zooms anchored to the cursor.
Positions are cosmetic; structure is fixed.

**Done when:** the graph renders from the registry, all navigation and realign actions work, and no frontend file contains a hardcoded node or edge list.

### 18.3 Live animation and the node inspector

Each node reflects the running job: pending dim, active with a glow and live percent, done
green, failed red, and skipped dashed and struck through. Edges into the active node animate
with a flowing dash, and a pill shows job, stage and percent. Clicking a node opens a panel
with its input, output and error for the current job plus status and resolved provider.
Freeze view stops the canvas repainting and must never pause execution — pausing production
is the Production row's job.

**Done when:** a running job animates the graph live, the inspector stays in sync as stages advance, and Freeze view demonstrably leaves the job running.

### 18.4 Node actions in the inspector, including test with a provider override

Retiring the editable canvas would otherwise delete step 13.3's capability, so it moves here.
The inspector carries a Test action with input bindings and a one-shot provider-instance
override, reusing the existing test panel and the `provider_instance_id` parameter from 13.2.
Failures surface as the prototype specifies: the node glows red with an inline tooltip, a
panel lists node, stage, job, reason and error code with Locate node and Retry, and a topbar
badge counts errors across jobs.

**Done when:** any node can be tested from the inspector against a chosen instance without advancing the bound Job, and a failed node is locatable from the topbar badge in one click.

### 18.5 Retire the editable canvas

With Schema carrying projection, inspection and per-node testing, remove the editable canvas
route from the UI. The engine stays authoritative and workflows remain editable through the
API and templates, so this removes a surface rather than a capability. Delete the route and
its nav entry; leave the node registry, templates and every backend contract untouched.

**Done when:** the editable canvas route is gone, the Full Video template still loads and runs, and the backend workflow API and its tests are unchanged.

---

## Phase 19 — Channel becomes the format, not just the look

The prototype's inherit-with-override pattern: set the house style once on the Channel, and
let a single script or job diverge without changing it. Four field groups, each shipping its
`type_version` migration in the same step.

### 19.1 Script template

Add a script template to the Channel: a plain-language structure brief plus an ordered
section outline such as Hook, Turn, Why, Reframe, Landing. Seed every starter Channel with a
sensible template and ship a default for Channels that lack one.

**Done when:** a Channel round-trips its brief and ordered sections, existing Channels migrate to the default template, and the editor renders the sections as reorderable chips.

### 19.2 Visual style prompt and prompt composition

Add a visual style prompt to the Channel's visual direction. The per-scene image prompt
composes as scene subject plus channel visual style plus mood plus aspect — the script
decides what is in frame, the Channel decides how it looks. Compose in exactly one place,
consumed by both Scene Director and the image provider, and show a live example of the
composed prompt in the Channel editor.

**Done when:** two Channels produce visibly different composed prompts from the same scene subject, and the composition lives in a single module with no duplicated string building.

### 19.3 Narration processing

Add remove-silence and speed to the Channel's audio defaults, applied within the TTS stage as
parameters rather than as separate nodes. A script may override them, and the UI shows
"inherited" until changed. The active values appear as a compact badge on the Schema TTS
node.

**Done when:** a Channel's narration settings reach TTS, a per-script override wins over them, and the Schema TTS badge reflects whichever is active.

### 19.4 Music library, thumbnail and the watermark picker

Add a music folder with its track list, a channel thumbnail, and a logo with a nine-position
watermark picker. Uploads go through the existing managed-asset endpoint with type and size
validation — never a browser-supplied filesystem path.

**Done when:** a Channel stores a track list, thumbnail and positioned logo, and the export applies the watermark at the chosen position across 9:16, 16:9 and 1:1.

---

## Phase 20 — The Script studio

A new subsystem in which scripts are first-class artifacts owning their text and their
narration, so a Job built from one skips Script and TTS entirely.

### 20.1 Script model and store

Persist a script with id, title, body, channel, origin (auto, paste, idea or manual), created
date, word count, estimated duration, and a narration block carrying state (none, generating,
ready), voice, duration and an audio artifact reference. Reuse the artifact store from step
1.2 for the audio rather than introducing a second one.

**Done when:** a script round-trips through create, read, update, delete and list, and its narration audio resolves through the artifact store.

### 20.2 The studio surface

Browse and search the library, open and edit a script, and create one by Auto, Paste or
Topic to Idea. Auto and Idea follow the selected Channel's template from 19.1 and show a
preview naming the template with its section chips; pasted and hand-written scripts are left
untouched.

**Done when:** all three create modes work, generated scripts visibly follow the Channel's section outline, and Paste requires no script provider at all.

### 20.3 Narration in the studio

Generate and regenerate narration for a script with an inline player, a voice picker
defaulting to the Channel's voice, and per-script overrides of remove-silence and speed shown
as inherited until changed.

**Done when:** a script gains playable narration, regenerating supersedes the previous audio without erasing it, and an overridden value is visibly distinct from an inherited one.

### 20.4 The virality panel

Surface the Phase 16 deterministic scorer per script as an overall gauge plus the
per-dimension breakdown, run on demand and cached. Advisory only — it never blocks saving a
script.

**Done when:** scoring a script shows an overall grade with per-dimension detail, re-scoring identical text returns an identical result, and no cloud provider is required.

---

## Phase 21 — Production as a batch orchestrator

### 21.1 Batch job creation

Configure a job as Channel, then script source, then execution mode, and add many to a batch
before running. The script source accepts an existing studio script, and the flow supports
selecting several scripts to create one job each.

**Done when:** five selected scripts become five queued jobs in one flow, each carrying its own channel snapshot.

### 21.2 Serial drain with a first-class pause

The queue drains one job at a time, which step 13.1 already defaults to. Add Pause and Resume
as a real job state: a paused job holds its queue slot so nothing advances past it, and
resumes from the same stage rather than restarting. Model pause in the engine, not as a
stop-then-recreate.

**Done when:** pausing the running job stops the queue advancing, resuming continues from the same stage with prior artifacts intact, and a paused job survives a process restart.

### 21.3 Jobs reuse a script's narration

When a job's source is a studio script with ready narration, Script and TTS are skipped: the
stage projection reports them as skipped for that job, and Schema renders them dashed and
struck through. The audio comes from the script's artifact instead of being regenerated.

**Done when:** a job built from a narrated script runs without invoking any script or TTS provider, and both stages report as skipped in Production and Schema.

### 21.4 The forty-eight hour archive calendar

Recent jobs show as full rows or cards; anything older packs into a date strip that expands
on click and remains searchable by name. One component serves both Production and the
Library.

**Done when:** a single component drives both views, older items collapse into the date strip, and search finds a collapsed item without expanding it first.

### 21.5 Failure handling and advisories

A failure is scoped to one job and never stops the batch — the queue keeps draining. The row
shows a red bar, a failed badge, the failing stage, and an error banner with the stage rail.
Offer Retry, Retry Failed, Duplicate and Remove. Retry must invoke the Phase 8 Repair Router
to repair the smallest responsible scope, not restart from stage zero as the prototype
simplifies. Add the language-mismatch advisory when a script's language differs from its
Channel's.

**Done when:** one job failing leaves the rest draining, Retry repairs the failed scope rather than restarting, and a language mismatch warns before the job runs.

---

## Phase 22 — Library and Providers

### 22.1 The Library gallery

Every finished video as a searchable gallery, filterable by channel, with per-item Editor and
Export actions, reusing the calendar from 21.4. A Library button on a finished Production row
deep-links to that video.

**Done when:** a finished job deep-links from Production into the Library, and filtering by channel and searching by name both work.

### 22.2 Providers page with a simulate console

One provider per capability with connection status, configuration, Test connection, and a
Simulate request console showing a per-kind dummy request and response round-trip for API,
extension and n8n providers. Keys stay masked and are never returned by any response.

**Done when:** each provider kind simulates a round-trip without touching a real endpoint, and a redaction test proves no response carries a credential.

---

## Step count and sequencing

| Phase | Steps | Notes |
|---|---|---|
| 0 — Genesis, port, contract freeze | 0.1–0.4 (4) | Sequential. 0.2 and 0.3 gate everything. |
| 1 — Artifacts, Channel, Job | 1.1–1.7 (7) | 1.2 before 1.4; 1.6 before Phase 5. |
| 2 — Production view | 2.1–2.6 (6) | 2.2 before 2.3/2.4; 2.6 is an engine change, land it alone. |
| 3 — Provider instances | 3.1–3.5 (5) | **3.1 lands alone.** 3.5 is a scheduler change. |
| 4 — Standalone execution | 4.1–4.3 (3) | Depends on 1.2. |
| 5 — Scene Director | 5.1–5.4 (4) | Depends on 1.6. 5.4 can parallel 5.2. |
| 6 — Image/video split | 6.1–6.2 (2) | Depends on 3.3. |
| 7 — Review | 7.1–7.4 (4) | 7.1 and 7.2 before 7.3. |
| 8 — Repair Router | 8.1–8.4 (4) | 8.3 needs the per-unit provenance decision first. |
| 9 — Automation | 9.1–9.3 (3) | 9.1 consumes 2.6; 9.3 consumes 3.5. |
| 10 — Migration and hardening | 10.1–10.4 (4) | 10.2 must not change engine behaviour. |
| **11 — Wire the correction loop** | 11.1–11.5 (5) | Sequential. **11.3 changes run behaviour** — land it alone. |
| **12 — Canvas and provider UX** | 12.1–12.5 (5) | 12.3 before 12.4; 12.1/12.2 independent. |
| **13 — Serial queue and testing** | 13.1–13.3 (3) | 13.2 gates 13.3. |
| **14 — Editor and export library** | 14.1–14.4 (4) | 14.1 first; 14.2/14.3 parallel after it. |
| **15 — Chromium and extensions** | 15.1–15.4 (4) | 15.2 is the port blocker; 15.4 is optional-degrading. |
| **16 — Virality analyzer** | 16.1–16.3 (3) | 16.3 depends on 11.3 being live. |
| **17 — Prototype design system** | 17.1–17.3 (3) | 17.1 first; 17.2 depends on it. |
| **18 — IA and the Schema view** | 18.1–18.5 (5) | **18.4 before 18.5** — it rescues 13.3's capability. |
| **19 — Channel as format** | 19.1–19.4 (4) | Each ships its own migration. 19.1 gates 20.2. |
| **20 — Script studio** | 20.1–20.4 (4) | 20.1 before the rest; needs 19.1 and 19.3. |
| **21 — Batch orchestrator** | 21.1–21.5 (5) | 21.2 and 21.3 are engine changes. 21.3 needs 20.1. |
| **22 — Library and Providers** | 22.1–22.2 (2) | 22.1 reuses 21.4's calendar. |

**93 steps across 23 phases** — 70 delivered (Phases 0–16), 23 remaining (Phases 17–22).

Phases 17–22 rebuild the front end against `prototype/scriptase-prototype.html`, the clickable UI/UX reference. It is a projection reference, not an engine: the node engine stays authoritative and every new view reads from it.

Phase 0–10 critical path (complete):
0.1 → 0.2 → 0.3 → 0.4 → 1.1 → 1.2 → 1.4 → 1.5 → 2.2 → 2.3 → 3.1 → 1.6 → 5.1 → 7.2 → 8.1 → 8.3 → 9.1.

Phase 11–16 critical path: **11.1 → 11.2 → 11.3 → 12.3 → 12.4 → 13.2 → 13.3 → 16.2 → 16.3**.
Phase 17–22 critical path: **17.1 → 18.1 → 18.2 → 18.3 → 18.4 → 18.5**, then **19.1 → 19.3 → 20.1 → 20.2 → 20.3 → 21.1 → 21.2 → 21.3**. Phase 22 is independent of that chain once 21.4 exists.

Phases 14 and 15 are independent of that chain and can run in any order — 14 is a frontend
port over an already-finished backend, 15 is launcher and extension work that touches no app
code.

Treat these four from the delivered phases with the most care — mistakes there corrupt
artifacts, strand issues, or report failed provider work as successful:

- **3.1** (provider instance identity) — touches the catalog key space, settings shape, every
  provider route, and the exclusivity lock key. Channels, fallback, and per-instance health
  all sit on it.
- **1.6** (stable scene ids) — get this wrong and every repair that touches Segmenter silently
  rebinds issues and artifacts to the wrong scene.
- **8.3** (per-unit provenance) — decide the shape before writing fallback execution, not
  during.
- **10.2** (indexed storage) — must be behind the existing interfaces with the engine suite
  passing unchanged, or cache correctness is at risk.

And one from the remaining phases:

- **11.3** (repair from orchestration) — introduces re-execution into a path that has never
  re-executed. Bound it with `review_policy.max_repairs` and the pre-flight budget from the
  first commit, and prove escalation before proving repair.

Four constraints that are easy to underestimate:

- **`type_version` migrations are unforgiving by design.** The ported runner refuses to skip a
  hop and marks future-version documents read-only. Every node configuration change in
  Phases 5–7, 11.1, and 12.1 needs its migration written in the same step, or saved workflows
  break.
- **Hiding nodes must never become deleting them.** 12.1 keeps every node registered and
  executable; only its visibility changes. Deleting node types would break saved workflows and
  the tests that prove the engine works.
- **Music and Captions stay out of the provider platform.** They are local, single-implementation
  services with no provider dimension; their mode, tone, and preset fields look like provider
  selection and are not. The requirement on them is no regression, not migration.
- **Live providers are partly unavailable.** Tests touching them stay behind the `live` marker.
