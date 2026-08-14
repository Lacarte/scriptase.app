# ScriptToScene Studio — Visual Workflow Builder (FINAL, best-of-both)

> Definitive implementation brief, merged from `proposition-merged.md` (authoritative contracts,
> deterministic scheduling, security, observability, testing) and the earlier `proposition-final.md`
> (concrete n8n/Automa patterns, schema-driven config examples, research notes).
>
> Scope decisions (locked by the project owner):
> - **Expressions/data-mapping → deferred to the last phase.** V1 passes data only through typed connections.
> - **Persisted execution history + bottom Execution Inspector → included.**
> - **Versioning → `schema_version` + `type_version` fields from day 1; NO migration framework yet.**
>   Unknown node types or unsupported versions block execution with a useful error; migration tooling
>   is built only when a breaking change first requires it.

## Objective

Upgrade ScriptToScene Studio into a professional node-based video-production workflow builder inspired by the best interaction patterns in n8n and Automa. Users drag processing nodes from a library onto a canvas, connect typed ports, configure nodes, save reusable workflows, execute all or part of a graph, and inspect live per-node results and past runs.

"Node-based" means a visual workflow graph. It does **not** mean migrating the backend to Node.js. Use architectural and UX ideas from n8n and Automa, but do not copy their source code (license incompatibility).

## Repository and working rules

Repository: `D:\@Workspace\@Development\@Scripts\@Python\ScriptToScene-Studio-V2`

Before changing implementation code:

1. Read `README.md` completely; find and follow all applicable `AGENTS.md` / `CLAUDE.md` files.
2. Inspect current git status and preserve unrelated user changes.
3. Audit the Vue routes and feature modules (`frontend/src/app/router.js`, `frontend/src/features/`), Flask blueprints, pipeline orchestration, provider registries, persistence helpers (`studio/io_utils.py`), SSE/WebSocket systems, editor, and export engine.
4. Produce the Phase 0 architecture artifacts and get the design internally consistent before implementation.
5. Implement and verify one phase at a time. Do not claim later-phase behavior is complete early.

Preserve:

- Python/Flask backend; Vue 3, Vite, Vue Router, Pinia frontend
- Existing `studio/*` processing modules and provider registries
- Existing SSE and WebSocket integrations; FFmpeg assembly/export behavior
- Project IDs and output directory conventions
- `safe_json_write` / atomic writes / backup recovery (`studio/io_utils.py`)
- Path traversal and loopback protections (`security.py` — apply to workflow ids too)
- Soft deletion through `output/TRASH`
- Existing projects, fixed pipeline, module pages, timeline editor, and export library

Do not rewrite working TTS, alignment, segmentation, scene generation, storyboard, animation, caption, music, editor, or export logic. Put thin workflow adapters around those capabilities.

## Current architecture to build upon

- `studio/pipeline/routes.py` currently orchestrates `_step_tts`, `_step_timing`, `_step_segment`, `_step_scenes`, `_step_storyboard`, `_step_assets`, `_step_assemble`, `_step_export`; progress streams over SSE (`/api/pipeline/progress/:job_id`), long provider work also uses WebSockets.
- Every step persists its output as JSON under `output/` (voice.json, alignment.json, segmented.json, scenes.json, …) — these artifacts and their metadata are the natural values carried by graph edges.

The workflow builder is a new feature, not a destructive replacement:

```text
frontend/src/features/workflow/
studio/workflows/
```

Keep `/pipeline` and all current feature routes operational. Add a separate `/workflow` route.

Clear vocabulary throughout:

- **Workflow** — reusable graph definition (recipe)
- **Execution** — one immutable run record of a workflow
- **Project** — generated media and editable timeline state
- **Export** — rendered output video

## Architectural decisions

### 1. Vue Flow for the canvas

Use `@vue-flow/core`, `@vue-flow/background`, `@vue-flow/minimap`, `@vue-flow/controls`, plus `@dagrejs/dagre` for optional tidy-up layout. (Both n8n and Automa landed on Vue Flow — it's Vue-3-native and gives handles, zoom/pan, minimap, and selection out of the box.) Do not build graph interaction primitives manually when Vue Flow supports them.

### 2. One authoritative node registry (backend-owned, no drift)

Avoid independent frontend and backend registries that can drift. The **backend registry is authoritative** for stable node types, versions, ports, configuration schemas, capabilities, and executor binding. Expose a safe, presentation-ready form through:

```text
GET /api/workflow/node-types
```

The response omits callable objects and internal implementation details. The frontend may keep presentation overrides (Vue icon component mappings, widget hints) but must not redefine execution contracts.

The same registry drives: backend graph validation, execution dispatch, node library entries, node card metadata, default configuration, schema-driven inspector forms, port rendering, connection validation, and capability controls (retry, cancel, preview, partial execution).

Every node definition declares: `type, type_version, display_name, description, category, icon, inputs, outputs, config_schema, defaults, executor, validation rules, retry/cancel/preview support`.

Concrete shape of one served entry (n8n `INodeTypeDescription` / Automa `tasks`-object pattern — one object drives everything, zero per-node UI code):

```jsonc
{
  "type": "tts.generate",
  "type_version": 1,
  "display_name": "Text to Speech",
  "description": "Generate narration audio from script text",
  "category": "audio",           // input, audio, timing, scene, ai, assets, video, output, utility
  "icon": "mic",
  "inputs":  [{ "name": "script", "type": "script", "required": true, "multiple": false }],
  "outputs": [{ "name": "audio", "type": "audio_file" }, { "name": "metadata", "type": "tts_metadata" }],
  "config_schema": [
    { "name": "engine", "label": "Engine", "type": "options", "options": ["kokoro", "inworld"], "default": "kokoro" },
    { "name": "voice",  "label": "Voice",  "type": "options", "options_source": "tts_voices", "default": "af_heart" },
    { "name": "speed",  "label": "Speed",  "type": "number", "min": 0.5, "max": 2.0, "step": 0.1, "default": 1.0 },
    // display_options: conditional visibility, re-evaluated on every value change (n8n NDV pattern)
    { "name": "blend",  "label": "Voice blend", "type": "string", "default": "",
      "display_options": { "show": { "engine": ["kokoro"] } } }
  ],
  "executor": "studio.workflows.adapters.tts",
  "supports_retry": true,
  "supports_cancel": true
}
```

### 3. Typed data edges and separate control semantics

Edges carry typed values and artifact references, not merely execution order. This is the backbone: it is what makes nodes safely connectable, replaceable, individually testable, cacheable, and retryable.

Initial port types:

```text
control, text, script, project_id, project_settings, audio_file, tts_metadata,
alignment, segments, scenes, image_prompts, storyboard_images,
animation_assets, captions, music_track, editor_project,
export_profile, video_file, generic_json
```

Each input declares whether it is required and whether it accepts multiple connections. Each output declares its type. Compatibility rules are explicit and centrally testable; do not silently treat `generic_json` as compatible with everything.

Connection validation (enforced client-side in `onConnect` AND server-side):

- Reject cycles (first release is a DAG; loops out of scope)
- Reject input-to-input and output-to-output connections
- Reject incompatible data types — with a toast explaining why in plain language
- Reject a second edge into a single-value input
- Highlight compatible targets while dragging a connection; color handles by data type
- Show missing required inputs as a badge on the node
- Mark downstream cached results **stale** when an edge changes
- Distinguish control edges from data edges

### 4. Deterministic DAG execution (ready queue, not raw stack)

Use a dependency-aware ready queue based on a validated DAG:

1. Validate the workflow and requested execution scope.
2. Build adjacency and reverse-dependency maps once (Automa's O(1) `sourceHandle → targets` lookup).
3. Determine the required subgraph for the requested run mode.
4. Add a node to the ready queue only when its required inputs are resolved or safely restored from cache — multi-input nodes (Assemble, Merge) wait for all connected inputs.
5. Use a stable tie-breaker (saved node order, then node ID) so plans and tests are deterministic.
6. Execute through adapters, persist results in `run_data[node_id]`, emit events, release downstream nodes.
7. V1 runs ready nodes sequentially; design the scheduler so bounded parallel execution of independent nodes can be added later without changing contracts.

Do not use a raw depth-first stack that can mishandle multi-input joins.

## Workspace UX

`WorkflowPage.vue` with five regions:

**Left — node library**: search; nodes grouped by category and color; name, icon, short description; drag to canvas using projected screen→canvas coordinates; recently used; built-in templates. The n8n killer trick: when a connection is dropped on empty canvas, show only type-compatible node types and auto-connect the selected one.

**Center — canvas**: dot-grid background; infinite pan/zoom (~minZoom 0.1, maxZoom 1.5); 20px snap grid; minimap colored by category; fit-to-view and tidy-up; multi-selection and group movement; custom arrow edges with hover deletion; animated running edges with post-run item summaries ("10 segments", "28.5s audio"); sticky notes (node groups may follow later). One generic `NodeCard.vue` driven by registry metadata — compact: category strip, icon, custom label, validation badge, execution status, typed handles, concise result summary. Full configuration never expands inside the canvas.

**Right — node inspector**: forms rendered generically from the registry `config_schema`. Widgets: string, textarea, number with constraints, boolean, options, async options, JSON editor with validation. Conditional visibility via `display_options`, required-field errors, descriptions, defaults. **Security:** async option sources are backend-approved identifiers or same-origin endpoints — never a schema-provided unrestricted fetch target. Actions: rename, enable/disable, duplicate, replace, delete, retry/error policy when supported. When run data exists, show **last resolved input | parameters | last output** side by side (n8n's NDV layout, simplified) so the user configures against real data.

**Bottom — execution inspector**: run history; node timeline; selected node inputs/outputs; structured logs and errors; duration and attempts; cache hit/miss and stale reason. Default to summaries for large values with explicit expansion. Never put secrets or unrestricted local file contents in the browser.

**Top — toolbar**: New, Open, Save, Save As, Duplicate; Import/Export JSON; Undo, Redo; Validate; Run Node, Run Node in Isolation (stubs), Run Selected, Run From Node, Run Workflow; Stop; Build/Open Project when an editor project exists; dirty-state indicator.

Keyboard: Delete selection; Ctrl/Cmd+D duplicate; Ctrl/Cmd+C/V copy/paste a minimal workflow fragment (works across workflows); Ctrl/Cmd+Z / Ctrl/Cmd+Shift+Z undo/redo.

Replacing a node preserves position, custom name, compatible configuration, and compatible connections; warns about incompatible connections before removing them; is undoable.

Live canvas status colors: gray idle, blue queued, animated blue running, yellow waiting, green succeeded, red failed, muted disabled/skipped, orange stale.

## Initial node catalog

### Core production nodes — required first

| Category | Node | Required inputs | Principal outputs | Existing capability |
|---|---|---|---|---|
| Input | Manual Trigger | None | `control` | Workflow start |
| Input | Script Input | None | `script` | Pipeline form input |
| Input | Existing Project Input | None | `project_id`, `editor_project` | Existing project data |
| Input | Project Setup | None | `project_settings` | Current pipeline settings + branding (see dedicated section) |
| Audio | Text to Speech | `script` | `audio_file`, `tts_metadata` | `studio/tts` |
| Timing | Force Alignment | `audio_file`, `script` | `alignment` | `studio/timing` |
| Scene | Segmenter | `alignment` | `segments` | `studio/segmenter` |
| AI | Scene Blueprint | `segments` | `scenes`, `image_prompts` | `studio/build_scene_blueprints` |
| Assets | Storyboard | `scenes` | `storyboard_images` | `studio/storyboard` |
| Assets | Animator | `scenes` | `animation_assets` | `studio/animator` |
| Audio | Background Music | settings / optional project context | `music_track` | `studio/music` |
| Video | Caption Generator | `alignment` | `captions` | `studio/captions` |
| Video | Assemble Project | audio, scenes, ≥1 supported asset source | `editor_project` | Existing assembly step/editor |
| Output | Timeline Project | `editor_project` | `editor_project`, `project_id` | Existing timeline persistence |
| Output | Video Export | `editor_project` | `video_file` | Existing FFmpeg exporter |
| Output | Workflow Output | any declared value | selected outputs | Workflow boundary |
| Testing | Sample Input stub | None | any (dynamic `port_type`) | Sample fixtures (see stub section) |
| Testing | Result Viewer stub | any (dynamic) | pinned payload passthrough | Execution records / cache |

Whether storyboard images and animation assets are mutually exclusive, combinable, or selectable per scene must be encoded in the Assemble Project adapter contract **after auditing the existing assembly logic** (Phase 0).

### Project Setup node (owner-requested)

A first-class **Project Setup** node (`project.setup`) sits at the head of the workflow — typically before TTS — and carries the project's identity and defaults as a single typed `project_settings` value that fans out to any node that needs it. Configuration schema (all rendered by the generic inspector, nothing bespoke):

```jsonc
{
  "config_schema": [
    // Identity
    { "name": "project_name",  "label": "Project name",  "type": "string", "default": "" },
    { "name": "channel_name",  "label": "Channel name",  "type": "string", "default": "" },

    // Branding / logo watermark
    { "name": "logo_enabled",  "label": "Show logo on video", "type": "boolean", "default": false },
    { "name": "logo",          "label": "Logo image", "type": "media_asset", "accept": ["png", "jpg", "webp"],
      "display_options": { "show": { "logo_enabled": [true] } } },
    { "name": "logo_position", "label": "Logo position", "type": "options", "default": "top_right",
      "options": ["top_left", "top_right", "bottom_left", "bottom_right", "center"],
      "display_options": { "show": { "logo_enabled": [true] } } },
    { "name": "logo_size",     "label": "Logo size (% of width)", "type": "number", "min": 2, "max": 40, "default": 10,
      "display_options": { "show": { "logo_enabled": [true] } } },
    { "name": "logo_opacity",  "label": "Logo opacity", "type": "number", "min": 0.05, "max": 1.0, "step": 0.05, "default": 0.9,
      "display_options": { "show": { "logo_enabled": [true] } } },
    { "name": "logo_margin",   "label": "Logo margin (px)", "type": "number", "min": 0, "max": 200, "default": 32,
      "display_options": { "show": { "logo_enabled": [true] } } },

    // Creative defaults
    { "name": "tone",          "label": "Story tone", "type": "options", "options_source": "story_tones", "default": "" },
    { "name": "style",         "label": "Visual style", "type": "options", "options_source": "style_templates", "default": "cinematic" },
    { "name": "aspect_ratio",  "label": "Aspect ratio", "type": "options", "options": ["9:16", "16:9", "1:1"], "default": "9:16" }
  ]
}
```

Rules:

- **`media_asset` widget**: uploads go through a dedicated endpoint into a managed branding directory (e.g. `output/branding/`), with type/size validation and thumbnail preview in the inspector — never a browser-supplied filesystem path (same security posture as everything else). Uploaded logos are reusable across workflows via a small picker (upload new / choose existing).
- **Consumers**: `project_settings` is an *optional* input on downstream nodes — Scene Blueprint reads `tone` and `style` as defaults for prompt generation; Assemble Project and Video Export read the logo block and `aspect_ratio`; Caption/Export surfaces may use `channel_name` (e.g. outro/watermark text) later. A node's own configuration always **overrides** the incoming defaults (explicit beats inherited), and the inspector shows inherited values as placeholder hints.
- **Logo rendering** happens at export: the FFmpeg export engine gains a logo-overlay pass (positioned, scaled, alpha-blended — same pattern as the existing grain overlay). It must survive every export profile (9:16, 16:9, 1:1) with position computed from the output resolution.
- The node itself executes instantly (it just validates and emits its settings), so it is cheap in every run mode and trivially cacheable.
- Extensibility: future identity fields (intro/outro clips, default music, brand colors, caption preset) are new `config_schema` entries on this node — no new machinery.

### Additional nodes — after core execution is stable

Story Generator, Set Value, Merge, Condition, Wait/Delay, Note/Comment. Define Merge and Condition semantics (ports, skip behavior, join behavior) before enabling them; nothing implicit.

## Isolated node runs — sample-data stubs (owner-requested)

Any node must be runnable **by itself**, even when nothing is connected to it. The mechanism is a pair of small helper nodes, auto-attached when a node lands alone on the canvas:

**Auto-attach behavior.** When a node is dropped on the canvas with no connections, the editor automatically spawns:

- one compact **Sample Input** stub per *required* input port, pre-connected to that port and pre-filled with a bundled sample fixture matching the port's data type (a mini `alignment`, a 3-segment `segments` payload, a short sample `script`, a tiny `audio_file` fixture, …);
- one compact **Result Viewer** stub connected to the node's principal output.

Stubs render visually distinct from real nodes: roughly half-height cards, dashed border, muted color, a "sample" badge. When the user later drags a *real* edge into a stubbed input, the stub for that port is removed automatically (undoably). Auto-attach can be toggled off in workflow settings; stubs can also be added manually from the library ("Testing" category) or via node context menu → "Attach test stubs".

**Sample Input stub (`stub.input`).**

- Configuration: `port_type` (set automatically from the port it was spawned for) and `payload` (the sample data). Its output port type resolves dynamically from `port_type`; connection validation reads the resolved type — a stub is never a `generic_json` wildcard.
- The payload is **editable**: clicking the stub opens the standard inspector with a JSON/text editor (widget chosen by port type), pre-filled with the registry fixture and validated against that port type's expected shape before a run.
- At execution time the stub completes instantly, returning its payload as a normal typed output. Every downstream result produced from stub data carries a visible **"from sample data"** marker on the node card, in the execution inspector, and in the persisted execution record, so sample-derived artifacts are never mistaken for real ones.
- For file-backed types (`audio_file`, `storyboard_images`, …) the payload is an artifact reference into bundled fixture files under `studio/workflows/fixtures/` — stubs never accept arbitrary local filesystem paths from the browser (same security posture as async option sources).

**Result Viewer stub (`stub.output`).**

- Before a run: shows the connected port's type and "no data yet". After a run: shows a concise summary (item counts, duration, filenames) with click-to-expand full JSON in the bottom panel — same redaction rules as everywhere else.
- **Editable = pinning.** The viewer's captured payload can be edited and marked *pinned*; a pinned viewer then acts as a data source for anything connected downstream, letting the user hand-tune intermediate data (e.g. tweak segment boundaries) without re-running upstream nodes. Pinning rides on the Phase 4 fingerprint/cache machinery: a pinned payload is simply a cache entry that wins until unpinned, and it marks descendants stale when edited.

**Registry contract.** Every port type declares a `sample` fixture (with per-node-type override via `sample_input` on an input declaration). Fixtures are produced once by running the real pipeline on a tiny script and freezing the artifacts; they ship in the repo and are served with the node-types payload (inline for small JSON, by reference for media files).

**Run mode.** "Run node in isolation" executes exactly the node plus its attached stubs — no upstream resolution, no cache lookup needed. This is the fastest way to test one node's configuration and is the primary reason stubs exist.

## Persistence model

### Workflow definition

Store under a dedicated output directory with sanitized IDs, atomic writes, backups, and soft deletion (`output/TRASH`):

```json
{
  "schema_version": 1,
  "workflow_id": "wf_AB12CD",
  "name": "Full Video",
  "description": "Complete ScriptToScene production flow",
  "nodes": [
    {
      "id": "n_tts",
      "type": "tts.generate",
      "type_version": 1,
      "name": "Narration",
      "position": { "x": 320, "y": 200 },
      "configuration": { "engine": "kokoro", "voice": "af_heart", "speed": 1.0 },
      "disabled": false
    }
  ],
  "edges": [
    {
      "id": "e_script_tts",
      "source_node": "n_script",
      "source_port": "script",
      "target_node": "n_tts",
      "target_port": "script",
      "edge_type": "data"
    }
  ],
  "variables": {},
  "viewport": { "x": 0, "y": 0, "zoom": 1 },
  "settings": { "on_error": "stop" },
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

- Serialize only this documented shape; strip Vue Flow runtime fields (Automa does exactly this).
- `variables` is reserved for the expressions phase — persisted empty from day 1 so the schema never changes for it.
- Import must validate size, schema, IDs, node count, edge count, configuration values, and versions before saving.
- **Versioning policy (locked):** store `schema_version` and `type_version` from day 1. Unknown future fields may be preserved when safe, but unknown node types or unsupported node versions **block execution with a useful error**. Do NOT build a migration framework now — build it when the first breaking change requires it.

### Execution record

Persist per run: `execution_id, workflow_id, workflow snapshot, project_id, requested run mode/scope, overall status, timestamps, per-node status, attempt count, duration, fingerprints, resolved input summaries, output artifact metadata, structured logs, structured errors`.

Large payloads and media remain files; execution JSON stores safe relative artifact references plus metadata. **Never** persist API keys, authorization headers, cookies, tokens, or unredacted provider responses — anywhere (workflow JSON, execution records, browser state, logs, errors, clipboard fragments, exported templates).

## API surface

Workflow definitions live under the plural `/api/workflows`; engine operations under `/api/workflow/*` (deliberate split — avoids route collisions with `/<workflow_id>`):

```text
GET    /api/workflows
POST   /api/workflows
GET    /api/workflows/<workflow_id>
PUT    /api/workflows/<workflow_id>
DELETE /api/workflows/<workflow_id>          # soft delete
POST   /api/workflows/import
GET    /api/workflows/<workflow_id>/export

GET    /api/workflow/node-types
POST   /api/workflow/validate
POST   /api/workflow/run
POST   /api/workflow/executions/<execution_id>/stop
GET    /api/workflow/executions/<execution_id>
GET    /api/workflow/executions/<execution_id>/events
GET    /api/workflow/executions?workflow_id=...
```

`POST /api/workflow/run` accepts a saved workflow ID or an unsaved validated snapshot, plus run mode and selected node IDs. Returns at least `execution_id`, `job_id` (if retained for compatibility), and `project_id` when allocated.

Reuse the existing SSE `_emit` pattern. Emit **monotonically sequenced** events so reconnecting clients can ignore duplicates and recover current state:

```json
{
  "sequence": 12,
  "execution_id": "ex_123",
  "node_id": "n_tts",
  "status": "running",
  "attempt": 1,
  "timestamp": "ISO-8601",
  "duration_ms": 0,
  "summary": "Generating narration"
}
```

## Backend package

```text
studio/workflows/
    __init__.py
    routes.py        # Flask blueprint
    models.py        # workflow/execution dataclasses
    registry.py      # authoritative node registry
    validation.py    # schema, ports, cycles, required inputs, scope
    persistence.py   # workflows + execution records (safe_json_write)
    scheduler.py     # deterministic ready-queue engine
    events.py        # sequenced SSE emission
    cache.py         # fingerprints, staleness
    redaction.py     # secret scrubbing for records/logs/errors
    expressions.py   # (final phase only)
    adapters/
        tts.py  timing.py  segmenter.py  scenes.py  storyboard.py
        animator.py  captions.py  music.py  editor.py  export.py
```

Adapters call stable service functions. If pipeline step functions are too route-coupled to reuse safely, **extract shared service functions without changing existing endpoint behavior**, then have both the fixed pipeline and workflow adapters call them. Do not make workflow adapters call Flask routes over HTTP from inside the same process.

## Execution behavior

Node states: `idle, invalid, queued, running, waiting, succeeded, failed, cancelled, skipped, stale`.

Run modes: complete workflow; one node + required upstream; **one node in isolation (sample-data stubs — see the dedicated section)**; selected nodes + required upstream; from a node through affected descendants; retry failed node; retry failed node + affected descendants.

Cancellation is cooperative, reusing existing provider/export stop mechanisms where available. A cancelled run must not report success after a late worker finishes. Prevent simultaneous runs from corrupting the same project via a **per-project execution lock** with atomic promotion of completed artifacts. Preserve partial successful results when safe.

### Caching and staleness (n8n's pin-data superpower — nearly free here since every step already persists JSON)

Compute a node fingerprint from a canonical representation of: node type + version, relevant configuration, resolved inputs and upstream artifact fingerprints, and adapter/cache schema version.

A cached result may be reused only if: the fingerprint matches, all referenced artifacts still exist and pass basic integrity checks, the previous run succeeded, and the user did not request forced regeneration. Graph/configuration/variable/upstream changes mark affected descendants **stale**. Persist enough information to explain why a cache was missed.

Do not assume per-project artifact names alone make cache reuse safe — multiple workflows or branches may target the same project.

### Error policy

Supported per node, only where the capability permits: stop workflow; retry with bounded attempts + delay/backoff; continue through an **explicit error output** (a control path, not a data output containing an exception object); skip an optional node.

Every failure includes: node ID, node name, stable error code, user-facing message, redacted technical details, attempt, timestamp, recovery suggestion.

## Autosave, undo, and recovery

- Debounced draft autosave, separate from explicit named-workflow Save / Save As.
- Unsaved-change indicator + navigation warning.
- Atomic persistence, backup recovery, bounded version history.
- Soft-delete saved workflows through `output/TRASH`.
- Undo/redo command stack: add, move, delete, connect, disconnect, configuration change, disable, replace. Coalesce drag movement into one undo command, not one per pointer event.

## Built-in templates

Ship valid, typed, versioned templates:

- **Full Video** (also the backward-compat representation of the current fixed pipeline): Manual Trigger → Project Setup + Script Input → TTS; Project Setup.settings → Scene Blueprint, Assemble Project, Video Export; Script + TTS.audio → Force Alignment → Segmenter → Scene Blueprint → Storyboard and/or Animator; Alignment → Captions; Audio + Scenes + Assets + optional Captions/Music → Assemble Project → Video Export.
- **Narration Only**: Manual Trigger → Script Input → Text to Speech → Workflow Output.
- **Storyboard Only**: Manual Trigger → Script Input → TTS; Script + TTS → Force Alignment → Segmenter → Scene Blueprint → Storyboard → Workflow Output.
- **Re-export Existing Project**: Manual Trigger → Existing Project Input → Video Export → Workflow Output.

Keep the existing pipeline UI and API active regardless.

## Data mapping and expressions (FINAL PHASE ONLY — scope decision)

V1 configuration values are literals or connected inputs. In the last phase, add a **deliberately small** expression language:

```text
{{ nodes.script_input.outputs.text }}
{{ nodes.tts.outputs.audio }}
{{ workflow.project_id }}
{{ variables.aspect_ratio }}
```

Rules: no Python `eval`, no JavaScript evaluation, no arbitrary template execution. Parse and validate references before execution; permit references only to upstream nodes in the selected subgraph; provide a visual upstream-output picker (select or drag a value into a field); preserve typed values instead of stringifying everything; clear errors for missing/stale references; no access to environment variables, secrets, arbitrary attributes, or filesystem paths. The `variables` schema field and config renderer are designed for this from Phase 1, so it bolts on without schema changes.

## Delivery phases (each phase leaves the app working and independently reviewable)

### Phase 0 — audit and contracts

Deliver before implementation: current architecture findings; proposed directory structure; complete node catalog with input/output contract table based on **actual artifacts**; workflow JSON schema; execution JSON schema; registry contract and API shapes; backward-compatibility strategy; security/threat review; risks, open decisions, phased checklist. Resolve discrepancies between this brief and the actual code **in favor of preserving working behavior**, and document the adjustment.

### Phase 1 — canvas and persistence MVP

Install Vue Flow + dagre; add `/workflow` without touching `/pipeline`; implement the backend registry + `GET /api/workflow/node-types`; build workflow Pinia store, node library, generic cards, canvas, inspector shell, toolbar; drag/drop, move, connect, disconnect, select, delete, tidy-up; typed connection checks + cycle detection in both client and server; save/load minimal versioned workflow JSON with atomic persistence; import/export validated JSON; display the current fixed pipeline as a template. No execution yet.

### Phase 2 — configuration and validation

Schema-driven inspector widgets with `display_options` conditional fields; backend-approved async option sources; required-input and configuration badges (node card + inspector); full server-side validation endpoint; dirty state, draft autosave, leave protection; **stub node types with auto-attach/auto-detach UX and editable sample payloads (rendering + editing only, execution comes in Phase 3)**. *(No expressions, no migration framework — version fields + block-with-error only.)*

### Phase 3 — core execution and observability

Extract reusable services where route-bound pipeline steps require it; adapters for core production nodes; deterministic scheduler + per-project locking; execution record persistence; full-workflow, single-node-with-dependencies, and **isolated single-node (stub-fed) runs with sample-derived markers**; sequenced SSE events; live canvas states, logs, summaries, errors, stop; open generated projects in the existing timeline editor.

### Phase 4 — partial runs and resilience

Selected-node and run-from-node modes; fingerprints, cache reuse, stale propagation; **Result Viewer pinning (edited payloads as winning cache entries)**; bounded retries and explicit error paths; retry-failed flows; run history + detailed input/output inspection in the bottom panel; secret redaction tests and artifact integrity checks.

### Phase 5 — power UX, utilities, and expressions

Undo/redo; copy/paste; duplicate and replace node; context menus and keyboard shortcuts; sticky notes; recently used; additional templates; Merge, Condition, Set Value, Wait only after semantics and tests exist. **Last: the expression language + visual output-data picker** per the section above.

## Testing and verification

Backend tests: workflow schema validation; registry serialization and version lookup; port compatibility and cardinality; required inputs; cycle detection; deterministic execution planning; multi-input readiness; partial-scope calculation; retry, cancellation, skip, failure propagation; fingerprints, cache reuse, stale propagation, missing artifacts; concurrent project locking; save/load/import/export round trips; path traversal rejection and soft deletion; secret redaction; compatibility with existing projects and fixed pipeline behavior; (final phase) expression parsing/sandboxing.

Frontend tests: adding/moving nodes; connecting compatible ports; rejecting incompatible or duplicate connections; inspector configuration and conditional fields; renaming, disabling, replacing, deleting; undo/redo and copy/paste; save/reopen and import/export; validation display; full, selected, and single-node run requests; SSE reconnect/deduplication; progress and error states.

After every phase: run the relevant backend tests; run frontend tests; run the production frontend build; exercise the changed behavior in the running app via `start-dev.bat`; report changed files, exact test/build results, known limitations, and remaining phases. If the frontend currently lacks a test runner, add and configure one deliberately in the appropriate phase rather than claiming frontend tests ran.

## Definition of done

The upgrade is complete only when a user can:

1. Create a blank workflow.
2. Drag the core Script Input, TTS, Alignment, Segmenter, Scene Blueprint, Storyboard/Animator, Assembly, and Export nodes onto the canvas.
3. Connect only compatible ports and understand rejected connections.
4. Configure all core nodes from the inspector.
5. Save, close, reopen, import, and export workflows without data loss.
6. Run one node with its dependencies, selected nodes, downstream nodes, or the complete workflow.
6b. Drop a single node on an empty canvas, get auto-attached editable sample-input and result-viewer stubs, run it in isolation, and see the result clearly marked as sample-derived.
7. Watch accurate node-level progress and stop a run.
8. Inspect redacted inputs, outputs, durations, logs, attempts, errors, and cache decisions — for current and past runs.
9. Retry failed work without rerunning unaffected successful nodes.
10. Replace, duplicate, disable, delete, copy/paste, and undo node operations safely.
11. Add notes and use built-in templates.
12. Build a project that opens in the current timeline editor.
13. Export a valid video through the existing FFmpeg engine.
14. Continue using existing projects, module pages, the fixed pipeline, and the export library without migration-related data loss.

## Scope guardrails

- First release is a DAG; arbitrary loops are out of scope.
- Core video-production nodes take priority over generic automation utilities.
- One generic schema-driven node UI is preferred, but specialized preview components are allowed when media UX genuinely requires them.
- Registry metadata is authoritative, but adapters remain normal tested Python code; do not encode arbitrary executor logic in JSON.
- Expressions wait until the final phase; the migration framework waits until a breaking change exists.
- Never store credentials anywhere (definitions, records, browser state, logs, errors, clipboard, templates).
- Do not remove the fixed pipeline until a later, explicit migration decision backed by parity tests and user approval.

---

# Extension brief — Provider plugin platform (Phases 10–16)

> Added 2026-08-08. The brief above specifies the Workflow Builder (Phases 0–9, delivered). This
> section is the authoritative spec for the provider-plugin migration that
> [implementation-plan.md](implementation-plan.md) breaks into Phases 10–16. Phase 10 gates the plan
> against *this* section and the real code.

## Objective

Make every AI module provider-driven. Script generation (random template and AI), Scene Blueprint,
TTS, Storyboard, and Animator each get a provider interface and a registry entry.
Workflow nodes stay generic: they declare `provider` + `provider_options` and nothing provider-specific.
The UI populates itself from provider metadata and settings schemas. Adding a provider means writing and
registering a provider package — no edit to a node definition, adapter, route dispatcher, or Vue
component.

## Architectural decisions

1. **Extend, do not replace.** `studio/shared/providers_common/` already provides discovery, manifests,
   settings, health, and broken-provider isolation. The platform generalizes it; it does not introduce a
   parallel framework.
2. **Domains are data.** A domain catalog replaces every hardcoded domain set. The five supported
   domains are `script`, `scene_blueprint`, `tts`, `storyboard`, `animator`. Adding a sixth must be a
   data change, not a redesign.
2b. **Music and Captions are out of scope** (owner decision, 2026-08-08). Neither is an AI module:
   `music.select` picks a file from the local `resources/sounds/` library, and `captions.generate`
   groups words from the alignment output using local presets. Neither has a second implementation,
   a remote call, or a provider dimension in its node configuration, so a provider layer would add
   indirection and buy nothing. They keep their current nodes, adapters, services, APIs, and legacy
   pages. The requirement on them is *no regression*, not migration.
3. **One registry hub, module-owned provider folders.** Providers live beside the module they serve;
   one hub resolves `(domain, provider_id)` for the whole process.
4. **One versioned result envelope.** Every domain returns typed content inside a common envelope with
   provider/domain/version, artifact refs, metadata, warnings, and provenance. Async providers share one
   job handle/status/progress/terminal-state contract.
5. **One error boundary.** Provider failures become `ProviderError` (stable code, safe message,
   retryable flag, redacted details) at the registry boundary. No raw provider exception, credential,
   filesystem path, or provider-specific response crosses into workflow records or API responses.
6. **Failure is isolated.** One provider's import, health, execution, or shutdown failure cannot hide
   healthy providers, block startup, or take down Flask.

## What must be preserved

- Every current provider ID, alias, default, and saved settings file.
- All existing artifacts and output paths (`voice.json`, `scenes.json`, `captions.json`, media files).
- Legacy request/response envelopes for the TTS, Story, Scene, Storyboard, Animator, Music, and Caption
  routes, and the external Automa/extension/callback URLs.
- Saved workflows: they upgrade through `type_version` migrations and run without manual edits.
- Node type keys, port IDs, and port types — the provider migration must not change the graph contract.

## Known starting conditions (verified in code, 2026-08-08)

- The provider ABC layer (`TTSProvider`, `StoryboardProvider`, `AnimatorProvider`, and all seven
  `get_provider()` factories) has **zero call sites**. Execution branches on `if provider_id == …`
  into legacy modules. This work is first-time wiring, not a refactor of running code.
- Two provider-selection stores coexist (`settings/settings.json` and `app-config.json`); one must win.
- `GET /api/workflow/options/<source>` takes no parameters, so no dropdown can depend on the selected
  provider until that contract is extended.
- `studio/shared/providers_common/scaffold.py` and `docs/provider-template/README.md` already exist.

## Security rules

Secrets are write-only: never echoed by an API, never present in workflow JSON, execution records, SSE
events, logs, errors, archives, notifications, or exported templates. Environment fallbacks may be
*used* but never *returned*. Provider metadata sent to the browser is an explicit allowlist — no
callables, no absolute paths, no resolved credentials. Callback correlation is scoped by
domain/provider/job/project, idempotent, bounded, and redacted.

## Definition of done

The provider platform is complete only when:

1. All five domains dispatch exclusively through registered providers, and Music and Captions still
   run unchanged through their local services.
2. No generic node definition, workflow adapter, shared dispatcher, or Vue component contains a
   concrete provider ID — proven by an allowlist scan, not by inspection.
3. A conforming provider can be added to any domain by creating and registering its package alone,
   proven by a test that fails if any other file changes.
4. Every domain returns the standard result envelope, and every failure the standard `ProviderError`.
5. Old workflows, saved settings, legacy API requests, and existing artifacts keep working with no user
   action.
6. Provider selection, settings, health, and capability UI are generated from catalog metadata on both
   the workflow canvas and the legacy pages.
7. A broken provider degrades to a reported health state and nothing else.
8. The provider reference is generated from the live hub, and docs drift checks fail on contract change.

## Scope guardrails

- Providers own remote/local generation mechanics only. Orchestration, staging, promotion, and execution
  events belong to the shared runtime.
- A provider may never modify a node definition, adapter, route, or generic UI component.
- Domain result schemas stay typed; "pass through whatever the provider returned" is not acceptable.
- Compatibility aliases live in exactly one documented migration module.

---

## Research notes backing these choices

- **Vue Flow everywhere**: n8n migrated from jsPlumb, Automa from Drawflow — both landed on `@vue-flow/core`.
- **Single authoritative registry** (Automa `tasks` object; n8n `INodeTypeDescription`): one contract drives palette + rendering + defaults + forms + validation + dispatch. Backend-owned here to eliminate frontend/backend drift.
- **Schema-driven config with conditional visibility** (n8n NDV `displayOptions`): a new node is data, not code.
- **Connection map + handle-encoded routing** (Automa `WorkflowEngine.init`): edges → `{source: targets}` map, O(1) next-node lookup; error branch = explicit fallback path.
- **Deterministic ready-queue over raw stack** (hardened version of n8n `WorkflowExecute`): multi-input joins wait for all inputs; stable ordering makes plans testable; parallelism can be added later.
- **Pin/cache upstream outputs for partial runs** (n8n `pinData` + partial-execution graph): this app already persists every step's JSON, so "run from here" is nearly free — but fingerprints + locks make it *safe*, not just cheap.
- **Serialize minimal node shape** on save (Automa): documented persistent shape only, runtime props stripped.
- **Typed edges carry real data**: the single most important property — it is what allows nodes to be connected, replaced, tested individually, cached, retried, and reused safely.
