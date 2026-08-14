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

**46 steps across 11 phases.** Critical path:
0.1 → 0.2 → 0.3 → 0.4 → 1.1 → 1.2 → 1.4 → 1.5 → 2.2 → 2.3 → 3.1 → 1.6 → 5.1 → 7.2 → 8.1 → 8.3 → 9.1.

Treat these four with the most care — mistakes there corrupt artifacts, strand issues, or
report failed provider work as successful:

- **3.1** (provider instance identity) — touches the catalog key space, settings shape, every
  provider route, and the exclusivity lock key. Channels, fallback, and per-instance health
  all sit on it.
- **1.6** (stable scene ids) — get this wrong and every repair that touches Segmenter silently
  rebinds issues and artifacts to the wrong scene.
- **8.3** (per-unit provenance) — decide the shape before writing fallback execution, not
  during.
- **10.2** (indexed storage) — must be behind the existing interfaces with the engine suite
  passing unchanged, or cache correctness is at risk.

Three constraints that are easy to underestimate:

- **`type_version` migrations are unforgiving by design.** The ported runner refuses to skip a
  hop and marks future-version documents read-only. Every node configuration change in
  Phases 5–7 needs its migration written in the same step, or saved workflows break.
- **Music and Captions stay out of the provider platform.** They are local, single-implementation
  services with no provider dimension; their mode, tone, and preset fields look like provider
  selection and are not. The requirement on them is no regression, not migration.
- **Live providers are partly unavailable.** Tests touching them stay behind the `live` marker.
