# Workflow Builder — Implementation Plan (digestible steps)

> Companion to [proposition-final.md](proposition-final.md) (the authoritative spec).
> This plan breaks the original Workflow Builder delivery and its provider-platform
> extension into small, independently verifiable steps.
> Each step is a commit-sized unit (roughly half a day to two days), has explicit
> "done when" criteria, and leaves the app working.
>
> Grounded in the actual codebase (verified 2026-08-04):
> - `app.py` imports and registers 14 blueprints at lines 71–84 — `workflows_bp` follows the same startup pattern.
> - `frontend/src/app/router.js` lazy-loads feature pages — `/workflow` follows the pattern.
> - `studio/pipeline/routes.py` is ~2,400 lines with `_step_*` functions embedded (lines 1242–2371)
>   — service extraction (step 3.1) is the highest-risk step in the plan.
> - Backend tests exist (`tests/test_*.py`, pytest). Vitest, Vue Test Utils, jsdom,
>   and an initial frontend smoke test were added during step 0.3.
> - Existing modules to wrap: `studio/{tts, timing, segmenter, build_scene_blueprints,
>   storyboard, animator, captions, music, editor}` + assemble/export steps in pipeline routes.
>
> Provider-platform extension audit (verified 2026-08-08, re-verified against the code 2026-08-08):
> - `studio/shared/providers_common/registry.py` already supplies discovery, manifests, health,
>   settings, and failure isolation, but its domains are limited to TTS, Storyboard, and Animator
>   (`ProviderRegistry.VALID_DOMAINS`, `registry.py:177`). `settings_manager.validate_settings`
>   hardcodes the **same** three-domain set independently — both must change together.
> - **The provider ABC layer is currently dead code on every execution path.** `TTSProvider.synthesize`,
>   `StoryboardProvider.submit/poll`, `AnimatorProvider.submit/poll`, and the `get_provider()` factory in
>   all seven provider packages have **zero call sites** outside their own modules. The registry supplies
>   metadata, settings, and health only; execution then hard-branches on `if provider_id == …` into the
>   legacy modules (`pipeline/services.py:59-276`, `storyboard/routes.py:307-353`,
>   `animator/animation_routes.py:191-211`, `tts/routes.py:517/629/902`). Phases 11–15 therefore
>   **wire these interfaces up for the first time** — the existing `provider.py` bodies have never run and
>   must be treated as unverified, not as behavior-preserving baselines.
> - Story/script generation and Scene Blueprint AI execute concrete services directly and do not yet
>   have domain provider registries or provider packages of any kind.
> - **Music and Captions are deliberately out of scope** (owner decision, 2026-08-08). Neither is an AI
>   module: `music.select` picks a file from the local `resources/sounds/` library by tone/random/specific
>   mode, and `captions.generate` groups words from the alignment output using local presets. Neither node
>   has a provider dimension in its configuration — no provider IDs appear in either definition — so a
>   provider layer would add indirection and buy nothing. They keep their current nodes, adapters, and
>   services unchanged. The supported domains are therefore **five**: `script`, `scene_blueprint`, `tts`,
>   `storyboard`, `animator`. If a generated-music or translated-caption source ever appears, add the
>   domain then; the node/adapter seam already exists.
> - `studio/workflows/registry.py` keeps node ports/executors generic but still embeds provider IDs
>   and provider-specific configuration fields (9 occurrences); the Vue provider components in
>   `frontend/src/features/providers/` are reusable foundations.
> - Two competing provider-selection stores exist: `settings/settings.json`
>   (`domains.<domain>.selected_provider`) and `app-config.json` (`sts-tts-provider`). The UI writes the
>   former by whole-blob read-modify-write through `PUT /api/settings/v2`;
>   `settings_manager.set_selected_provider()` exists but is never called.
> - The provider HTTP API lives in `studio/editor/routes.py:230-372`, not in a provider blueprint.
> - `python -m studio.shared.providers_common.scaffold` and `docs/provider-template/README.md`
>   **already exist** — the plugin SDK work extends them rather than creating them.
> - `GET /api/workflow/options/<source>` takes **no parameters** (`resolve_options(source)` only), so
>   provider-dependent dropdowns are impossible without extending that contract (see 10.2 / 12.2).
> - Prior design doc for the existing infrastructure: `_dev/docs/plans/modular-providers-plan-v4.md`.
>   Reuse its vocabulary and phase numbering rather than contradicting it.

## Working agreements (apply to every step)

- One step = one commit (or a small stack). Never mix service extraction with behavior change.
- After each **phase**: run `pytest`, run frontend tests, run `npm run build` in `frontend/`, smoke-test in the running app (`start-dev.bat`), and record results before starting the next phase.
- `/pipeline`, module pages, timeline editor, and export library must work after every single step.
- New backend runtime code goes in `studio/workflows/`; new frontend runtime code in `frontend/src/features/workflow/`. Nothing else moves except deliberate integration points and the extraction in 3.1.
- Follow existing conventions: feature folders, composables, Pinia stores, `safe_json_write` (`studio/io_utils.py`), and `safe_join` (`studio/security.py`). Workflow and execution IDs require strict prefix/format validation; do not silently accept the altered result of `sanitize_project_id`.

---

## Phase 0 — Audit, contracts, and test infrastructure

No workflow runtime or UI feature code belongs in this phase. Development-only test
configuration and small deterministic fixture assets are allowed.

### 0.1 Artifact & step audit → node contract table
Read `studio/pipeline/routes.py` step functions (`_step_tts` … `_step_export`, `_load_prior_results`, `_emit`) and each wrapped module. For every planned node, document: stable input/output **port IDs**, port types, required/optional and cardinality rules, exact input artifacts (file + dict shape), output artifacts, config keys actually consumed, cancellation/retry support, determinism, and side effects on `output/{project_id}/`.
Resolve the open question: how Assemble treats storyboard images vs animation assets (audit `_step_assemble` at line 1919 and `_step_assets` at 1813) — encode the answer in the Assemble adapter contract.
**Deliverable:** `_dev/loop-engineering/phases-plans/contracts.md` with the input/output contract table.
**Done when:** every node in the catalog maps to a real function + real artifacts; every edge in every built-in template names real ports; project/source-folder identity propagation is explicit; and discrepancies vs the spec are documented and resolved in favor of working behavior.

### 0.2 Freeze the machine contracts
In the same doc, freeze: workflow JSON schema (with `schema_version`, `type_version`, reserved `variables`), execution record schema, the served node-type shape, exact HTTP request/response envelopes and status codes, the full API route list, SSE event shape (with `sequence` and standard SSE `id`/`Last-Event-ID` replay), port-type compatibility matrix, control-edge readiness semantics, dynamic-port resolution for `stub.input`, `stub.output`, and `workflow.output`, and stable error codes. Include security/threat notes: strict ID validation, `safe_join`, redaction points, import limits, endpoint authorization/loopback policy, approved async option sources, and managed-media rules.

Define the fixture inventory and validation schema in this step. Capture or generate the actual sanitized fixtures before step 2.5, when they are first consumed. Prefer deterministic local media generation and provider-mocked JSON; a Phase 0 gate must not depend on live n8n/provider availability.

**Done when:** the contracts are internally consistent; every persistent and served field has a type, required/optional status, limits, and unknown-field policy; templates validate against named ports; and later phases can code against them without redesign.

### 0.3 Test infrastructure
Establish and record the backend baseline. Add **Vitest + @vue/test-utils + jsdom** to `frontend/` with an `npm run test` script and one trivial smoke test that mounts a component. Add a reproducible development dependency declaration for pytest instead of relying on packages installed only inside one local venv.

**Done when:** `npm run test` and `npm run build` pass; the backend suite is green, or a pre-existing environment-sensitive failure has a tracked resolution (dependency pin, corrected test/code, or explicit quarantine with owner approval). Merely recording a failure is not a green Phase 0 gate. CI/dev docs note exact commands and supported Node/Python versions.

### 0.4 Phase 0 consistency review and gate
Validate `contracts.md` against `proposition-final.md` and the repository one final time. Check every built-in template edge, node port, artifact filename, API route, status enum, and ID/path rule. Record completed, deferred, and blocked items with evidence; do not label draft prose as a frozen machine contract.

**Done when:** there are no unresolved contradictions; fixture capture has an owner and deadline before 2.5; test results are current; and Phase 1 can begin without inventing contract semantics.

### Phase 0 review status — 2026-08-04

- **0.1: complete.** The module/artifact audit, named port contracts, control readiness, source artifacts, and Storyboard/Animator/Assemble discrepancy are documented.
- **0.2: complete for Phase 0.** Field constraints, HTTP envelopes/status codes, strict IDs, SSE `Last-Event-ID` replay, security limits, and fixture validation rules are frozen. The actual deterministic fixture files are an explicit prerequisite of step 2.5, where they are first used.
- **0.3: complete.** `requirements-dev.txt` tracks pytest; backend is 14 passed plus 2 subtests; Vitest is 1 passed; the production frontend build succeeds; supported runtimes are recorded in `contracts.md`.
- **0.4: complete.** The corrected contracts and plan are internally consistent and Phase 1 can begin without inventing graph, persistence, API, or replay semantics.

**Phase 0 is gated complete.** The next implementation step is 1.1. Fixture files remain a
tracked prerequisite of 2.5, not a hidden Phase 0 dependency.

Phase 0 verification commands:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
Set-Location frontend
npm ci
npm test
npm run build
```

---

## Phase 1 — Canvas & persistence MVP (no execution)

### 1.1 Dependencies + route shell
Install `@vue-flow/core`, `@vue-flow/background`, `@vue-flow/minimap`, `@vue-flow/controls`, `@dagrejs/dagre`. Add `/workflow` route in `router.js` → new `features/workflow/views/WorkflowPage.vue` with the five empty layout regions (library / canvas / inspector / bottom panel / toolbar) and nav entry.
**Done when:** page renders with an empty Vue Flow canvas; `/pipeline` untouched; `npm run build` passes.

### 1.2 Backend registry + node-types endpoint
Create `studio/workflows/{__init__.py, registry.py, routes.py}`; register `workflows_bp` in `app.py`. `registry.py` holds the authoritative core catalog (all core + testing nodes from the spec table, including `project.setup` with its branding/logo schema, with `type`, `type_version`, ports, `config_schema`, defaults, capabilities). `GET /api/workflow/node-types` serves the presentation-safe form (no executor internals).
**Done when:** endpoint returns the full catalog; pytest covers serialization, version fields, and that no callable/internal fields leak.

### 1.3 Workflow store + node library panel
Pinia store (`features/workflow/stores/workflow.js`) holding nodes/edges/viewport/dirty state; fetch node-types on mount. Left panel: search, category groups with colors, name+icon+description, drag source (`dataTransfer` carries node type).
**Done when:** all catalog nodes appear grouped and searchable; drag starts (drop handled next step).

### 1.4 Canvas + generic NodeCard
Drop → project screen→canvas coords → insert with registry defaults. One generic `NodeCard.vue`: category strip, icon, label, typed handles, placeholder status/validation badges. Move, multi-select, group move, Delete key, 20px snap grid, minimap colored by category, controls, fit-to-view, dagre tidy-up button.
**Done when:** a user can drag out and arrange the full pipeline visually; Vitest covers add/move/delete store mutations.

### 1.5 Typed connection validation (client)
`onConnect` rules from the spec: type compatibility (explicit matrix from 0.2 — no implicit `generic_json` wildcard), single-input cardinality, no in→in / out→out, cycle rejection, duplicate rejection. Handle colors by port type; highlight compatible targets while dragging; plain-language rejection toasts.
**Done when:** every rule has a Vitest case; invalid connections are impossible on canvas.

### 1.6 Workflow persistence (backend + save/load)
`studio/workflows/{models.py, validation.py, persistence.py}`: full CRUD at `/api/workflows` (list/create/get/update/soft-delete→TRASH), strict `wf_` ID validation plus `safe_join`, atomic writes, minimal serialized shape (strip Vue Flow runtime props). Server-side re-validation of types/ports/cycles on save. Toolbar: New, Open, Save, Save As, Duplicate.
**Done when:** save → reload → reopen round-trips losslessly; pytest covers round-trip, path-traversal rejection, soft delete, unknown-type/version rejection with useful errors.

### 1.7 Import/export + fixed-pipeline template
`POST /api/workflows/import` (validate size/schema/ids/counts before saving), `GET /api/workflows/<id>/export`, and `GET /api/workflow/templates`. Ship the **Full Video** template representing the current pipeline; template picker in the workflow toolbar/library surface.
**Done when:** exported file re-imports cleanly; template opens as a correctly connected, valid graph. **Phase 1 gate:** full test + build + manual smoke pass.

### Phase 1 review status — 2026-08-04

- **1.1–1.5: reviewed and strengthened.** Vue Flow route/canvas, backend-owned registry, generic cards, store, and typed client validation are present. Dynamic ports now reject unsupported types, and capability flags no longer advertise cancellation paths the existing providers do not expose.
- **1.6: complete.** Workflow CRUD uses strict IDs, `safe_join`, atomic JSON writes/backups, optimistic timestamps, server-side schema/port/cardinality/cycle validation, bounded requests and extension data, finite-number and maximum-depth enforcement, RFC 3339 identity timestamps, soft deletion, and persisted-shape-only frontend serialization.
- **1.7: complete.** Import/export and the server-validated Full Video template are wired into the toolbar with New, Open, Save, Save As, Duplicate, Import, Export, template selection, dirty-state prompts, and viewport restoration.
- Automated gate: 40 backend tests plus 2 subtests and 21 frontend tests pass; the production build and a live Flask create/load/update/delete and template API round trip pass.
- Manual visual gate: pending because the in-app browser surface was unavailable during this review. Verify drag/drop, toolbar overflow at the target window size, minimap, connection feedback, save/reopen, and template fit-to-view once in the running app before beginning Phase 2.

**Phase 1 is implementation-complete but awaits the documented manual visual smoke check.**

---

## Phase 2 — Configuration & validation

### 2.1 Schema-driven inspector renderer
Right panel renders forms generically from `config_schema`: string, textarea, number (constraints), boolean, options, JSON editor with validation. Defaults, descriptions, rename/disable/duplicate/delete actions.
**Done when:** every core node is configurable with zero per-node UI code; Vitest covers widget rendering per schema type.

#### Step 2.1 review status — 2026-08-04

- **Complete and strengthened.** The generic inspector covers every Phase 2.1 widget and node action without per-node UI code. Selection is document-scoped and cleared on removal; save/save-as preserve valid selection; duplication retains extension metadata while respecting persisted name and coordinate bounds.
- Automated gate: inspector/store coverage is included in the frontend suite and the production build passes. Manual visual verification remains part of the Phase 2 gate.

### 2.2 Conditional fields + validation badges + server validate
`display_options.show/hide` re-evaluated on every change (e.g. TTS `blend` only for kokoro). Missing-required and invalid-config badges on node cards and in the inspector. `POST /api/workflow/validate` returns structured problems; Validate toolbar button surfaces them.
**Done when:** client and server agree on validity for seeded good/bad workflows (pytest + Vitest).

#### Step 2.2 review status — 2026-08-04

- **Complete and strengthened.** Conditional visibility and required-field semantics now match on both sides. Client badges cover unsupported versions, malformed or unknown configuration fields, type/range/pattern/option/JSON/media violations, and required inputs; malformed validation envelopes correctly return HTTP 400 while graph-invalid drafts remain structured HTTP 200 results.
- Automated gate: backend and frontend validation regressions pass with the full suites and production build. Manual badge and conditional-field verification remains part of the Phase 2 visual gate.

### 2.3 Approved async option sources + media_asset widget
`options_source` identifiers resolved through a backend allowlist (e.g. `tts_voices` → existing voices endpoint; `story_tones`, `style_templates`; provider lists via existing provider registries). No schema-provided URLs are ever fetched. Add the `media_asset` inspector widget for Project Setup's logo: upload endpoint into `output/branding/` with type/size validation, thumbnail preview, and an upload-new / pick-existing chooser; never accept raw filesystem paths from the browser.
**Done when:** TTS voice, tone, style, and provider dropdowns populate live; a logo uploads, previews, persists in workflow JSON as a managed reference, and survives save/reload; a test proves unknown identifiers and disallowed file types are rejected.

### 2.4 Dirty state, draft autosave, leave protection
Debounced draft autosave (separate from explicit save), unsaved-change indicator, navigation warning, draft recovery on reopen.
**Done when:** killing the tab mid-edit loses nothing; explicit save clears dirty state.

### 2.5 Sample-data stubs — node types + auto-attach UX (no execution yet)
Capture/generate and validate the fixture inventory defined in 0.2 before building the UI; fixtures must be deterministic, sanitized, small, and independent of live providers. Add `stub.input` (Sample Input) and `stub.output` (Result Viewer) to the registry with dynamic `port_type` resolution in the compatibility matrix. Frontend: dropping a node with no connections auto-spawns one pre-connected Sample Input stub per required input and one Result Viewer on the principal output; half-height dashed rendering with "sample" badge; connecting a real edge to a stubbed input removes that stub (undoably); auto-attach toggle in workflow settings; manual attach via library "Testing" category and node context menu. Stub payloads editable in the inspector with per-port-type validation; file-backed types reference bundled fixtures only (never browser-supplied paths).
**Done when:** dropping a lone Segmenter shows editable stubs wired up; Vitest covers auto-attach, auto-detach-on-real-edge, undo, and payload validation; server-side validation accepts stub graphs. **Phase 2 gate.**

---

## Phase 3 — Core execution & observability

### 3.1 Service extraction (highest-risk step — pure moves only)
Extract the `_step_*` bodies from `studio/pipeline/routes.py` into importable service functions (e.g. `studio/pipeline/services.py` or per-module services), leaving routes as thin callers. **No behavior change**: same artifacts, same SSE events, same error paths.
**Done when:** existing pytest suite passes; a full run through the classic `/pipeline` UI produces identical artifacts (compare `pipeline.json` + outputs before/after).

### 3.2 Node adapters
`studio/workflows/adapters/` wrapping the extracted services (tts, timing, segmenter, scenes, storyboard, animator, captions, music, assemble via editor, export) plus the trivial `project.setup` adapter (validate + emit settings). Adapters translate node inputs/config → service args, and service results → typed outputs + artifact refs; consumers of `project_settings` apply the explicit-beats-inherited rule (own config overrides incoming defaults). Extend the FFmpeg export engine with the **logo-overlay pass** (position/size/opacity/margin from settings, correct across all export profiles — same pattern as the grain overlay). Never call Flask routes over HTTP in-process.
**Done when:** each adapter has a pytest exercising it against a fixture project (mock providers where needed); an export with logo enabled renders the watermark at the right position in 9:16, 16:9, and 1:1.

### 3.3 Deterministic scheduler + project locking
`studio/workflows/scheduler.py`: validated-DAG ready queue, reverse-dependency maps, multi-input wait, stable tie-breakers (saved order, then id), sequential v1 execution, disabled-node skip, per-project execution lock with atomic artifact promotion.
**Done when:** pytest covers ordering determinism, multi-input readiness (Assemble waits for all inputs), diamond graphs, disabled skip, and lock contention.

### 3.4 Execution records + redaction
`models.py` execution dataclasses; persist records (snapshot, per-node status/durations/attempts, resolved input summaries, artifact refs, structured logs/errors) via `persistence.py`; `redaction.py` scrubs secrets from everything persisted or emitted.
**Done when:** a run produces a complete record; a redaction test seeds a fake API key through config/logs/errors and proves it never appears in any persisted or emitted byte.

### 3.5 Run + stop endpoints, sequenced SSE
`POST /api/workflow/run` (id or validated snapshot; full-workflow, node+deps, and **node-in-isolation** modes first), `POST /api/workflow/executions/<id>/stop` (cooperative, reuses existing stop mechanisms), `GET .../events` streaming monotonically sequenced events via the `_emit` pattern. Each SSE message uses `id: <sequence>`; reconnect reads the standard `Last-Event-ID` header and replays later buffered events. Isolated mode: `stub.input` executes instantly returning its payload as a typed output; every downstream result produced from stub data is flagged `from_sample_data` in events and the persisted execution record.
**Done when:** pytest covers run→events→terminal-state, stop mid-run (a cancelled run never later reports success), isolated stub-fed execution, ordered replay after `Last-Event-ID`, and reset behavior when the requested event is older than the retained buffer; the client deduplicates by `sequence`.

### 3.6 Live canvas states + minimal bottom panel
Wire SSE to the store: status colors (idle/queued/running/waiting/succeeded/failed/cancelled/skipped/stale), animated running edges, post-run edge summaries, "from sample data" markers on stub-fed results, Stop button. Result Viewer stubs display their captured output summary (read-only at this phase). Bottom panel v1: current run's node list with status/duration/error; click a finished node → its output JSON. "Open in Timeline Editor" when an `editor_project` exists.
**Done when:** the Full Video template runs end-to-end from the canvas, produces a project that opens in the timeline editor, and exports video through the existing FFmpeg engine. **Phase 3 gate.**

---

## Phase 4 — Partial runs & resilience

### 4.1 Remaining run modes
Selected-nodes+deps, from-node-through-descendants, retry-failed, retry-failed+descendants. Scope calculation in `validation.py`/`scheduler.py`; toolbar + context-menu entries.
**Done when:** pytest covers subgraph scope for each mode on branch/diamond graphs; UI can run any mode.

### 4.2 Fingerprints, cache reuse, stale propagation
`cache.py`: canonical fingerprint (type+version, relevant config, upstream artifact fingerprints, adapter schema version). Reuse only on fingerprint match + artifacts exist + integrity check + prior success + no forced regen. Edge/config/upstream changes mark descendants stale (orange). Persist cache-hit/miss reasons.
**Done when:** re-running an unchanged workflow re-executes zero nodes; changing one upstream config re-executes exactly the affected subgraph (pytest-proven).
Also in this step: **Result Viewer pinning** — an edited viewer payload becomes a winning cache entry (validated against the port type) that feeds downstream nodes until unpinned, and editing it marks descendants stale; pinned state is visible on the stub card.

#### Step 4.2 review status — 2026-08-04

- **Complete.** Canonical node fingerprints include resolved defaults, typed inputs, topology-qualified upstream output/artifact fingerprints, type version, and adapter cache schema version. Persistent cache entries are workflow/project/node scoped, atomic, and contain only component hashes plus reusable outputs.
- Reuse fails closed for forced regeneration, prior failure/absence, configuration/input/upstream/schema changes, malformed entries, missing/empty/modified artifacts, non-JSON outputs, and sensitive outputs. Every decision is persisted on the node execution record, and cache misses caused by a prior result surface a transient stale state before execution.
- Frontend graph/config edits mark the affected node and descendants stale without treating cosmetic rename/move changes as computation changes. Result Viewers support typed, validated pinned payloads; the pin wins independently of upstream changes, feeds downstream nodes, persists in workflow JSON, and is visible on the card.
- Automated verification: 115 backend tests plus 38 subtests and 80 frontend tests pass; the production frontend build succeeds.

### 4.3 Retry policies + explicit error outputs
Per-node `on_error`: stop / bounded retry with delay/backoff / continue via explicit error output (control path) / skip-optional — only where capability flags permit. Structured failure payloads (stable code, user message, redacted details, attempt, recovery suggestion).
**Done when:** pytest covers each policy including backoff timing and error-branch routing.

#### Step 4.3 review status — 2026-08-04

- **Complete.** Nodes persist a capability-gated `on_error` policy for stop, bounded retry, explicit error-control routing, or optional skipping. Retry attempts use bounded exponential backoff, retain per-attempt diagnostics, and emit retry events without publishing staged artifacts from failed attempts.
- Failure records and events include node identity, stable code, user message, redacted details, attempt, timestamp, and recovery suggestion. Handled failures finish as `partial`; ordinary success paths never activate error branches.
- The generic inspector exposes only supported policies and retry bounds. Automated verification: 121 backend tests plus 38 subtests and 81 frontend tests pass; the production frontend build succeeds.

### 4.4 Run history + deep inspection UI
Bottom panel full version: execution list (`GET /api/workflow/executions?workflow_id=`), node timeline, per-node resolved inputs/outputs/logs/errors/attempts, cache decisions and stale reasons. Summaries by default, explicit expansion for large values.
**Done when:** a failed run can be diagnosed and retried from the UI without rerunning successful nodes. **Phase 4 gate.**

#### Step 4.4 review status — 2026-08-04

- **Complete.** The bottom panel loads newest-first persisted history for the active workflow, opens full execution records, and presents a duration-scaled node timeline with status, attempts, sample-data state, and per-node selection.
- Deep inspection shows bounded input/output/artifact summaries with explicit JSON expansion, structured current and per-attempt errors, recovery suggestions, logs, cache hit/miss decisions, and cache/stale reasons. Failed nodes expose retry-failed and retry-failed-plus-descendants actions; these use partial-run scope and preserve unaffected successful work.
- Automated verification: 121 backend tests plus 38 subtests and 84 frontend tests pass; the production frontend build succeeds. The in-app browser surface was unavailable, so the final interactive layout smoke check remains to be performed when that surface is available.

---

## Phase 5 — Power UX, utilities, expressions

### 5.1 Undo/redo command stack
Commands: add, move (drag coalesced into one command), delete, connect, disconnect, config change, disable, replace. Ctrl+Z / Ctrl+Shift+Z.
**Done when:** every canvas operation round-trips through undo/redo (Vitest on the command stack).

#### Step 5.1 review status â€” 2026-08-04

- **Complete.** The workflow store now has a bounded runtime-only command history for add, atomic multi-node move, delete, connect, disconnect, configuration, disable, and replace. Compound add-with-stubs and real-edge stub replacement operations undo and redo as single commands; new edits invalidate redo, and document loads clear history.
- The canvas exposes Undo/Redo controls and handles Ctrl+Z / Ctrl+Shift+Z outside editable fields. Tidy-up and group dragging each produce one move command.
- Automated verification: all 92 frontend tests pass, including dedicated round-trip command-stack coverage, and the production frontend build succeeds.

### 5.2 Clipboard, duplicate, replace, context menus
Copy/paste minimal workflow fragments (works across workflows), Ctrl+D duplicate, right-click context menus, "Replace with…" preserving position/name/compatible config/connections with warning for incompatible ones (undoable). Drop-connection-on-empty-canvas → compatible-filtered palette → auto-connect.
**Done when:** each operation has a test and is undoable.

#### Step 5.2 review status — 2026-08-04

- **Complete.** Selected nodes copy as versioned, document-independent workflow fragments with only internal edges; paste remaps node/edge IDs and supports positioning on another workflow. Ctrl+D duplicates a selected node or subgraph, including internal connections.
- Node, edge, and pane context menus expose copy, paste, duplicate, enable/disable, delete/disconnect, existing run/sample actions, and replacement. Replacement retains identity, name, position, shared configuration, and type-compatible connections, and confirms before removing incompatible connections.
- Dropping an unfinished connection on empty canvas opens a palette filtered to compatible ports and inserts plus connects the chosen node atomically. Clipboard, duplication, replacement (compatible and incompatible cases), and insert-and-connect all round-trip through undo/redo.
- Automated verification: all 98 frontend tests pass, including 6 focused step 5.2 domain/UI tests, and the production frontend build succeeds.

### 5.3 Notes, recently used, remaining templates
Sticky notes; recently-used section in the library; ship **Narration Only**, **Storyboard Only**, **Re-export Existing Project** templates (valid and typed).
**Done when:** all templates validate and run.

#### Step 5.3 review status — 2026-08-04

- **Complete.** Sticky notes are editable, colorable, draggable, persisted in workflow extensions, and covered by undo/redo without entering the execution DAG. The node library keeps a bounded local recently-used section based on actual palette/insert usage.
- Narration Only, Storyboard Only, and Re-export Existing Project are versioned, typed built-ins. All four built-in templates pass authoritative validation and execute successfully through the deterministic scheduler with adapter boundaries mocked.
- Automated verification: 121 backend tests plus 38 subtests and 101 frontend tests pass; the production frontend build succeeds.

### 5.4 Utility nodes (semantics first)
Merge, Condition, Set Value, Wait — define ports, skip/join behavior, and scheduler semantics in `contracts.md` first, then implement with pytest coverage. Story Generator node wrapping `studio/story`.
**Done when:** a branched workflow (Condition → two paths → Merge) executes correctly, including skip propagation.

#### Step 5.4 review status — 2026-08-04

- **Complete.** Utility ports and runtime semantics are frozen in `contracts.md`. Condition
  emits exactly one value branch, ordinary inactive descendants propagate `skipped`, and Merge
  is the explicit skip-tolerant join that consumes active inputs in saved-edge order after all
  predecessors resolve. Set Value, cooperative/cancellable Wait, and array/first/object Merge
  modes are registered and executable through the generic workflow UI.
- Story Generator wraps an importable `studio.story` service, reusing its prompts, webhook,
  parser, artifact persistence, and diversity history while emitting the existing `script` type.
- Automated verification: 129 backend tests plus 38 subtests and 102 frontend tests pass; the
  production frontend build succeeds. Focused tests execute both Condition outcomes through two
  paths into Merge and verify skip propagation, utility edge cases, integer timing validation,
  cancellation, and the Story Generator adapter boundary.

### 5.5 Expressions & data mapping (deferred scope, last)
`expressions.py`: deliberately small parser for `{{ nodes.x.outputs.y }}`, `{{ workflow.project_id }}`, `{{ variables.* }}` — no eval, upstream-only references, typed value preservation, sandbox tests (no env/secrets/attribute/filesystem access). Visual upstream-output picker in the inspector; pre-execution expression validation.
**Done when:** expression-driven config runs correctly and the sandbox test suite passes.

#### Step 5.5 review status — 2026-08-04

- **Complete.** Whole-value expressions support typed upstream outputs, the immutable execution
  project ID, and nested workflow variables through a fixed non-evaluating grammar. Static
  validation enforces real non-control output ports, strict graph ancestry, and selected-run scope;
  resolved values are schema-validated before fingerprinting and adapter execution.
- The inspector provides workflow-variable JSON editing and a visual picker containing only data
  outputs from graph ancestors. Expression mode works for every schema widget without coercing
  referenced arrays, objects, numbers, or booleans to strings.
- Sandbox coverage rejects interpolation, operators, calls, environment/secret roots, arbitrary
  attributes, and filesystem access. Automated verification: 140 backend tests plus 38 subtests
  and 105 frontend tests pass; the production frontend build succeeds. The in-app browser surface
  was unavailable, so the Phase 5 interactive expression-picker smoke check remains outstanding.

### Phase 5 gate — Workflow Builder Definition of Done
Walk the 14-point Definition of Done checklist in [proposition-final.md](proposition-final.md) in the running app; fix anything that fails; record the results. This closes the original Workflow Builder brief. It is **not** the end of the plan — Phases 6–9 harden and scale it, Phases 10–16 deliver the provider platform, and Phase 17 handles distribution. The project-wide final gate is 16.5 followed by Phase 17.

---

## Phase 6 — Hardening & production readiness

The feature is built; this phase makes it safe under real conditions. Sources: the outstanding
findings from the 2026-08-04 adversarial review that Phases 3–5 did not absorb, plus the two
surfaces no automation has ever touched (live providers, legacy-UI relationship).

### 6.1 Live-provider verification
Every suite runs on fixtures; run the full pipeline template through the workflow runner against
the real providers (TTS, alignment, storyboard, animator, export). Fix what breaks. Capture
provider quirks as tests marked `@pytest.mark.live`, skipped unless `STS_LIVE=1` is set, so the
orchestrator's fixture-based validation stays green and deterministic.
**Done when:** one full live run from script to playable export succeeds through the workflow runner, and the live-marked tests document each provider's verified behavior.

#### Step 6.1 review status — 2026-08-05

- **Complete (one provider externally blocked).** A full live run — script → Kokoro TTS →
  stable-whisper alignment → segmenter → scene blueprint (n8n + OpenRouter LLM) → Kie AI
  assets → captions → music → assemble → timeline → FFmpeg export — succeeded through
  `ExecutionManager`/`WorkflowScheduler` and produced a playable 1080×1920 mp4 with video and
  audio streams (ffprobe-verified). `tests/test_live_providers.py` (marker `live`, registered
  in the new `pytest.ini`, gated on `STS_LIVE=1`) documents each provider's verified behavior:
  9 passed, 1 documented skip.
- Live infrastructure findings: the hosted Railway n8n no longer serves the scene-blueprint
  webhook (workflow inactive, API key revoked) and the OpenRouter balance is negative, which
  rejects paid models with HTTP 402 while free models still complete. Live verification now
  self-hosts n8n from the repo's own workflow export with a pinned free model
  (`_dev/loop-engineering/live-verification/setup_local_n8n.py`; procedure in that folder's
  README). The WaveSpeed key is rejected upstream on every model (HTTP 401 "Invalid API key"),
  so the storyboard branch is removed from the live document and its test skips with the
  reason recorded until a valid key is configured (`STS_LIVE_STORYBOARD=1` restores it);
  grok_automa remains non-automatable by design (human-driven browser).
- Product fixes from live breakage, each with a fixture regression in
  `tests/test_workflow_adapters.py`: empty node-config values no longer mask inherited
  project settings (`inherited_config` — the template's Project Setup tone was silently
  discarded by the music/scenes empty schema defaults, failing runs with `MUSIC_NOT_FOUND`);
  storyboard and animator adapters now fail with `STORYBOARD_FAILED`/`ANIMATOR_FAILED` when
  every scene errors instead of reporting success with zero assets.
- Automated verification: 143 backend tests plus 38 subtests pass with the live suite
  correctly skipped when `STS_LIVE` is unset; no frontend code changed in this step.

### 6.2 Persistence hardening
`persistence.py`: atomic trash move with no `.bak` resurrection path, single-writer file locking
around read-modify-write cycles, monotonic `updated_at` so optimistic concurrency cannot alias
within the same millisecond, and a delete path that works on a stored workflow that no longer
parses or validates.
**Done when:** a concurrency test with two interleaved writers corrupts nothing and loses neither write's conflict signal, and a hand-corrupted workflow file can be trashed via the API.

#### Step 6.2 review status — 2026-08-05

- **Complete.** `persistence.py` now serializes every read-modify-write cycle (update, delete)
  behind a per-workflow single-writer lock: an in-process per-path `threading.Lock` for app
  threads plus a blocking exclusive OS lock (`msvcrt.locking`/`fcntl.flock`) on a `.json.lock`
  sidecar for cross-process safety. An instrumented two-writer test proves the critical section
  never overlaps, exactly one writer wins, the loser receives `WorkflowConflict`, and the stored
  document still parses and validates.
- `updated_at` is strictly monotonic: when the clock has not advanced past the stored value, the
  new stamp is the previous timestamp plus one microsecond, so optimistic-concurrency tokens can
  never alias within the same instant (frozen-clock test covers two same-instant updates).
- The trash move is resurrection-proof: the `.bak` rotates into trash **before** the primary
  (an interruption leaves the primary intact instead of a resurrecting backup), moves use
  atomic `os.replace` with a cross-volume fallback, destination names are collision-guarded,
  and no `{id}.json*` remnant stays in `output/workflows/` after deletion.
- Delete no longer routes through `load_workflow`: the conflict check reads `updated_at`
  directly from the primary file without the `.bak` restore side effect and is skipped when the
  file no longer parses, so a hand-corrupted workflow (and its backup) can be trashed via
  `DELETE /api/workflows/<id>` — verified end-to-end through the Flask test client, including
  the post-delete 404 that proves no backup resurrection.
- Automated verification: 148 backend tests plus 38 subtests pass (10 gated live tests skipped);
  no frontend code changed in this step.

### 6.3 Request hardening
Enforce body-size limits that chunked transfer encoding cannot bypass; validate submitted
`options_source` values server-side against the allowlisted resolvers; cap branding upload size
and count. All rejections use the standard error envelope.
**Done when:** pytest proves an oversized chunked request, an invalid option value, and an oversized upload are each rejected with the envelope and correct status code.

#### Step 6.3 review status — 2026-08-05

- **Complete.** JSON endpoints now read the body through a bounded stream read
  (2 MiB + 1 byte) instead of trusting the `Content-Length` header, so a chunked request
  (terminated stream, no declared length) is rejected `413 REQUEST_TOO_LARGE` with the standard
  envelope; non-empty bodies still require a JSON content type, preserving the CORS-preflight
  requirement for cross-origin callers. The DELETE route was moved onto the same bounded reader.
- Submitted values for `options_source` config fields are validated server-side against the
  allowlisted resolver's current values (`allowed_option_values` in `options.py`, process-lifetime
  cached). A bad value fails a save with the `422 WORKFLOW_INVALID` envelope naming the exact
  config path; an unavailable resolver fails open so a missing provider never blocks saving,
  and non-string values are rejected rather than crashing set membership.
- Branding uploads cap the whole multipart request at 6 MiB via per-request
  `max_content_length` — Werkzeug enforces it while reading the stream, chunked included, and a
  blueprint `RequestEntityTooLarge` handler converts the failure to the `413` envelope with no
  file written. The library itself is capped at 50 stored logos (`409 LIMIT_EXCEEDED`), counted
  by allowed extension before any multipart parsing.
- Automated verification: `tests/test_workflow_request_hardening.py` proves the oversized
  chunked JSON request, oversized chunked and declared multipart uploads, invalid/valid/
  non-string option values, fail-open resolver behavior, and the count cap — each rejection
  asserting the envelope and status code. Full backend run: 160 passed, 38 subtests,
  10 gated live tests skipped; no frontend code changed in this step.

### 6.4 Client error-truth
Parse the `{error:{code,message}}` envelope on every remaining API call in the workflow store
(save/load/list/import paths), block Save with a visible reason while any JSON widget holds
invalid text, and fix the number-widget DOM desync so the displayed value always matches state.
**Done when:** Vitest covers envelope surfacing for each store API path, and Save is disabled with a visible reason while any field is invalid.

#### Step 6.4 review status — 2026-08-05

- **Complete.** The shared API client now parses the standard `{error:{code,message}}`
  envelope on every non-OK response, throwing errors that carry the backend's message,
  stable code, HTTP status, and optional details instead of a raw
  `METHOD path → status: body` string. Every workflow-store API path — node-types, open,
  save (create and update), save-as, import, workflow list, templates, run, stop,
  execution refresh, and run history — surfaces that envelope through its store error ref
  as `message [CODE]`, including the two list paths that previously threw with no
  handling at all.
- Save is truthfully blocked while any JSON widget holds unparseable text: JSON config
  fields and the workflow-variables editor register with a store-level invalid-field
  registry (`saveBlockedReason`), the toolbar disables Save/Save As/Duplicate with the
  reason visible as a red toolbar alert naming the node and field, and
  `saveWorkflow`/`saveAs` themselves refuse (without an API call) so the block holds even
  outside the button. Blocks release when the text is fixed, the field is hidden or
  unmounted, the node is deselected, or a new document loads — matching where invalid
  text can actually live.
- The number widget's DOM can no longer desync from state: clamped input that lands on
  the unchanged stored value, cleared input, and unparseable input all force the input
  element back to the value actually kept, and updates are emitted only when the value
  really changes.
- Automated verification: 26 new Vitest cases (client envelope parsing, all 12 store
  surfacing paths, save gating at store/widget/inspector/page level, number-widget sync)
  bring the frontend suite to 131 passed across 16 files; the production build succeeds.
  No backend code changed in this step.

### 6.5 Legacy UI bridge
The canvas becomes the default landing surface. Legacy step pages stay reachable behind explicit
navigation, with cross-links both ways for the same project; routes that no surface links to
anymore are removed. No behavior changes inside the legacy pages themselves.
**Done when:** opening the app lands on the workflow builder, each surface links to the other, and no dead routes remain.

#### Step 6.5 review status — 2026-08-05

- **Complete.** The root route now redirects to `/workflow`, so opening the app lands on the
  workflow canvas; the sidebar lists the Workflow Builder as the primary surface with the
  legacy pipeline dashboard explicitly below it ("Legacy Pipeline Dashboard").
- Cross-links run both ways: the workflow toolbar gains a "Legacy → Pipeline" link to the
  step-by-step dashboard, and the legacy pipeline header (now badged "Legacy") gains an
  "Open Workflow Builder" link. Project-scoped bridging already existed and is preserved —
  the execution panel's "Open in Timeline Editor" carries `?project=` into the legacy editor,
  and legacy pages keep their own `?project=` hand-offs. No behavior inside legacy pages
  changed; both additions are pure hash-history navigation links.
- Dead-route removal: the `/timing` → `/alignment` alias redirect, which no surface linked to,
  is deleted; a route test asserts every remaining route is either the root redirect or a
  surface-linked page.
- Automated verification: 4 new Vitest cases (default-landing redirect, legacy pipeline
  reachability, no-dead-routes allowlist, workflow-toolbar legacy link) bring the frontend
  suite to 135 passed across 18 files; the production build succeeds. No backend code changed
  in this step.

### 6.6 Docs and onboarding
A user guide for building, validating, and running workflows (including sample-data stubs, run
modes, and draft recovery), plus a node reference generated from the backend registry so it
cannot drift from the code.
**Done when:** a newcomer can build and run the pipeline template using only the docs, and the node reference is generated, not hand-written.

#### Step 6.6 review status — 2026-08-05

- **Complete.** `docs/workflow-guide.md` provides a newcomer path from setup through the
  built-in Full Video template, node configuration, server validation, saving, full and
  partial run modes, sample-data stubs, cache/staleness diagnostics, retries, import/export,
  and browser draft recovery. The root README links directly to both workflow documents and
  its Windows quick start now names the existing `start-prod.bat` launcher.
- `studio.workflows.docs` generates `docs/workflow-nodes.md` from the presentation-safe
  backend registry and validated built-in templates. The reference covers every registry
  port type, category, node type/version, capability, input/output port, configuration field,
  constraint, default, and template; its generated-file header documents the regeneration
  command and source of truth.
- Automated drift protection compares the committed reference byte-for-byte with fresh
  generator output, exercises `--check`, checks registry coverage and internal-field
  redaction, verifies the required guide topics, and keeps the README entry point covered.
  Verification: 9 documentation tests passed (23 subtests); the full project suite passed
  with 169 tests and 61 subtests (10 live-provider tests skipped).

---

## Phase 7 — Triggers & automation

Until now every run is a human clicking Run. This phase makes workflows fire themselves:
scheduled, file-driven, and webhook-driven runs, serialized through a queue, with notifications.

### 7.1 Run queue
Queue model persisted next to executions: pending/running/done/failed/cancelled, source
(manual/schedule/watch/webhook), requested run mode. Triggered runs enqueue; the existing
project lock drains the queue one run per project at a time. Queue panel in the bottom UI
with cancel-pending.
**Done when:** two runs triggered for the same project serialize (pytest-proven) while runs for different projects do not block each other, and pending runs can be cancelled from the UI.

#### Step 7.1 review status — 2026-08-05

- **Complete.** Every accepted run now creates an atomic queue record under
  `output/workflows/queue/`, keyed by its execution ID, with the requested mode, target nodes,
  project, source (`manual`, `schedule`, `watch`, or `webhook`), timestamps, and the persisted
  `pending` → `running` → `done|failed|cancelled` lifecycle. Execution records and SSE streams
  retain their existing IDs and envelopes.
- Dispatch uses one FIFO worker per project. Runs for the same project therefore enter the
  existing project lock one at a time, while different projects have independent workers and can
  execute concurrently. Pending cancellation atomically updates both queue and execution records,
  emits a terminal SSE event, and guarantees the cancelled request is skipped by its worker.
- `GET /api/workflow/queue` serves the persisted queue for a workflow and
  `POST /api/workflow/queue/<execution_id>/cancel` rejects anything except a pending run. The
  bottom Runs & diagnostics UI now includes a queue strip with source/mode/status and a Cancel
  action for pending items; the Pinia store refreshes it on load, manual refresh, enqueue, and
  terminal events.
- Automated verification: the full backend suite passes with 173 tests and 61 subtests
  (10 live-provider tests skipped); the full frontend suite passes with 137 tests across 18 files;
  the production frontend build succeeds. Dedicated queue tests prove same-project serialization,
  cross-project overlap, persistence, source/mode capture, endpoint behavior, and pending
  cancellation that never executes.

### 7.2 Scheduled runs
Per-workflow cron-style schedules (persisted in workflow `settings`), a scheduler tick service
started with the app, enable/disable per schedule, next-fire display in the UI. Missed fires
while the app was closed run at most once on startup (catch-up policy: latest only).
**Done when:** an accelerated-clock pytest proves a schedule enqueues exactly one run at the right time, catch-up fires at most once, and disabled schedules never fire.

#### Step 7.2 review status â€” 2026-08-05

- **Complete.** Workflows persist up to 16 independently enabled five-field UTC cron schedules
  in `settings.schedules`; server validation rejects malformed expressions, duplicate/invalid
  schedule IDs, unknown fields, and invalid enable flags.
- The app starts a daemon tick service alongside the Flask server. Runtime cursors live under
  `output/workflows/schedule-state/`, separate from workflow definitions, so ticks do not disturb
  optimistic edit tokens. Each cursor advances before queue dispatch, scheduled executions use
  the Phase 7.1 queue with `source: schedule`, and startup catch-up selects only the latest missed
  fire. Disabled intervals advance the cursor without firing and are never replayed on re-enable.
- The workflow toolbar now opens Scheduled runs settings with add/remove and per-schedule enable
  controls, UTC cron editing, catch-up policy guidance, and a server-computed next-fire display.
  Unsaved schedule edits explicitly ask the user to save before recalculating.
- Automated verification: the full backend suite passes with 176 tests and 61 subtests
  (10 live-provider tests skipped); the frontend suite and production build pass. Dedicated
  accelerated-clock tests prove exact-time enqueueing, tick idempotence, latest-only catch-up,
  disabled behavior, cron validation, and next-fire metadata.

### 7.3 Watch-folder trigger
A workflow can watch a configured folder for files matching a pattern; a stable-size debounce
avoids half-written files; the file feeds the script input (or a configured port) of the run.
Processed files move to a `processed/` subfolder to prevent re-triggering.
**Done when:** dropping a file into a watched tmp folder triggers exactly one queued run carrying the file's content, half-written files do not trigger, and processed files never re-trigger (pytest with tmp dirs).

#### Step 7.3 review status — 2026-08-05

- **Complete.** Each workflow can persist one enabled watch folder with an absolute path,
  filename glob, and optional text/script input-port destination. With no explicit port, file
  content replaces the enabled Script Input value in the execution snapshot without changing the
  saved workflow.
- A daemon polling service starts with the app. It requires an unchanged size and modification
  timestamp for at least one second, accepts bounded UTF-8 text, atomically claims stable matches,
  queues them with `source: watch`, and moves successful claims into `processed/`. Failed enqueue
  attempts restore the source file for a later retry; processed files are outside the scan root.
- The workflow toolbar now opens Watch folder settings for enablement, absolute folder path,
  filename pattern, and compatible port selection. Server validation rejects malformed settings,
  missing targets, and non-text destinations.
- Automated verification: the backend suite passes with 179 tests and 61 subtests (10 live-provider
  tests skipped); the frontend suite passes with 139 tests across 20 files; the production build
  succeeds. Dedicated tmp-directory tests prove stable-write debounce, exactly-once queueing,
  content injection, pattern/disable behavior, and processed-file isolation.

### 7.4 Webhook trigger
Loopback-only `POST /api/workflow/hooks/<workflow_id>/<token>` starts a queued run; per-workflow
random token, regenerable in the UI; JSON payload validated and mapped to declared typed inputs.
Invalid token or payload rejected with the standard error envelope.
**Done when:** a valid POST enqueues a run with the mapped payload, invalid token/payload/oversize are rejected with the envelope, and the endpoint refuses non-loopback binds.

#### Step 7.4 review status — 2026-08-05

- **Complete.** Saved workflows can enable a webhook and declare up to 32 required/optional dotted
  JSON payload paths mapped to unique, enabled data-input ports. Payload values are validated by
  their resolved static or dynamic port type before they become scheduler input overrides, and
  accepted requests enter the Phase 7.1 queue with `source: webhook`.
- Each workflow gets a cryptographically random URL-safe token under separate private runtime state
  (`output/workflows/hook-tokens/`), keeping credentials out of workflow exports and execution
  snapshots. The settings dialog reveals and copies the loopback URL and regenerates its token with
  immediate invalidation of the previous URL; token responses are marked `Cache-Control: no-store`.
- The hook accepts JSON objects up to 64 KiB, compares tokens in constant time, uses the standard
  error envelope for missing/disabled hooks and invalid typed payloads, rejects non-loopback clients,
  and refuses all requests whenever `STS_BIND_HOST` is not loopback-only.
- Automated verification: the backend suite passes with 184 tests and 61 subtests (10 live-provider
  tests skipped); the frontend suite passes with 141 tests across 21 files; the production build
  succeeds. Dedicated tests cover valid typed mapping and queue source, required/invalid payloads,
  oversize rejection, token rotation, workflow validation, remote clients, and exposed server binds.

### 7.5 Run notifications
Per-workflow notification settings: on completion/failure, emit a Windows toast and append to a
persisted notification log surfaced in the UI (badge + list). Outbound webhook notification as
an optional channel.
**Done when:** failed and successful runs each produce the configured notification record (pytest), and the UI shows unseen-notification state.

#### Step 7.5 review status — 2026-08-05

- **Complete.** Per-workflow settings independently enable completion and failure records, Windows
  toast delivery, and an optional outbound HTTP(S) webhook. Terminal dispatch is idempotent per
  execution and channel failures remain delivery metadata instead of changing workflow results.
- Records persist under `output/workflows/notifications/`; local-only list and acknowledge APIs
  expose total and unseen counts. The workflow toolbar now shows an unseen badge, and its notification
  center combines channel settings with the persisted success/failure history.
- Automated verification: the backend suite passes with 188 tests and 61 subtests (10 live-provider
  tests skipped); the frontend suite passes with 142 tests across 22 files; the production build
  succeeds. Dedicated tests cover success/failure records, idempotent channel delivery, bounded
  webhook payloads, unseen acknowledgement, settings validation, and notification-center behavior.

---

## Phase 8 — Node developer kit

Turns the builder from a feature into a platform: creating a node becomes one command plus a guide.

### 8.1 Node scaffolder
`python -m studio.workflows.scaffold <node_key>` generates a registry entry, adapter skeleton,
config schema stub, and a passing test file, wired into the palette on next start. Refuses
existing keys and invalid port types.
**Done when:** running the scaffolder for a demo node yields a palette-visible, configurable, executable node whose generated tests pass unmodified.

#### Step 8.1 review status — 2026-08-05

- **Complete.** `python -m studio.workflows.scaffold <node_key>` creates a source-controlled JSON
  registry entry, editable adapter skeleton, JSON config-field stub, and node-specific smoke tests.
  Repeatable `--input ID:TYPE` and `--output ID:TYPE` options use the registry's frozen port
  vocabulary; invalid port types, reserved/duplicate port IDs, existing node keys, and existing
  target files are refused without overwriting them.
- Generated definitions are discovered when the workflow registry imports, so the existing
  node-types endpoint exposes them to the palette on the next application start and the scheduler
  resolves their generated adapter normally. Built-in registry contract tests now require the core
  catalog as a subset so developer nodes can extend it without weakening per-node validation.
- End-to-end verification scaffolded `scaffold_check.echo` through the real CLI: the node was
  registry-visible, configurable, executable, and both generated tests passed unchanged. The
  temporary demo files were then removed. The focused suite passes with 17 tests; the complete
  workflow backend suite passes with 172 tests and 59 subtests.

### 8.2 Dev hot-reload
Behind a dev-mode flag: registry and adapter modules reload on file change without restarting
Flask; the frontend refetches node-types on a reload signal. Never active in normal runs.
**Done when:** with the flag on, editing a node definition updates the palette without a server restart; with the flag off, nothing watches or reloads (tests cover the guard).

#### Step 8.2 review status — 2026-08-05

- **Complete.** `start-dev.bat` enables the narrowly scoped `STS_WORKFLOW_DEV_RELOAD`
  flag; normal `app.py` runs leave the watcher stopped and the reload SSE endpoint hidden.
- A dependency-free background watcher observes workflow registry, generated definition, and
  adapter files. Generated catalogs validate before an atomic swap, loaded adapter modules are
  refreshed after edits, and failed/partial saves keep the last valid catalog serving.
- Successful reloads publish a dev-only SSE signal. The workflow store opens that stream only
  when the node-types response advertises dev mode, then force-refetches the complete registry so
  the palette updates without restarting Flask.
- Guard, change detection, live registry replacement, invalid-edit safety, endpoint visibility,
  and frontend refetch behavior are covered. Verification passes with 199 backend tests, 10
  skipped tests, and 61 subtests; all 140 workflow frontend tests and the Vite production build
  also pass.

### 8.3 type_version migrations
Nodes declare config migrations between `type_version`s; documents upgrade on load with a
recorded migration trail; unknown future versions load read-only with a warning instead of
crashing.
**Done when:** a stored workflow with an old node version opens upgraded and re-saves at the new version (pytest covers a two-hop migration chain), and a future-version document is view-only with a visible warning.

#### Step 8.3 review status — 2026-08-05

- **Complete.** Node definitions may declare backend-only `migrations` keyed by source
  `type_version`; each callable or generated-node `module:function` reference transforms only the
  node configuration and every intermediate hop is required. Migration declarations and callables
  are stripped from the presentation-safe registry response.
- Loads apply migrations to a copy before validation, append a bounded audit trail under
  `extensions.type_version_migrations`, and leave the stored file untouched until the user saves.
  The editor marks a migrated workflow dirty so that Save persists the current node version and
  trail through the existing optimistic-concurrency path.
- Known node types from a future version load with their configuration and incident edges preserved,
  plus explicit `read_only`, warning, and migration metadata. The editor displays a view-only warning,
  disables graph/config mutations and execution, and the backend independently rejects update
  attempts with `WORKFLOW_READ_ONLY`.
- Verification passes with 201 backend tests (10 live-provider tests skipped, 61 subtests), all 145
  frontend tests across 22 files, and the Vite production build. Dedicated coverage exercises a
  two-hop migration, non-destructive load and re-save, future-version preservation/API refusal, and
  frontend migrated/read-only state.

### 8.4 Node-author guide
A written guide (docs/ or in-app) walking scaffold → schema → adapter → test → ship, generated
partly from `contracts.md` and the registry so port types and rules cannot drift. Validated by
building one real node following only the guide.
**Done when:** the demo node from 8.1 is rebuilt following only the guide, and the guide's port/type tables are generated from the registry.

#### Step 8.4 review status — 2026-08-05

- **Complete.** `docs/workflow-node-author-guide.md` walks the complete scaffold → schema →
  adapter → test → ship path, including schema widgets, capabilities, migrations, adapter context,
  artifact safety, structured errors, verification commands, and release checks.
- The guide is generated by `python -m studio.workflows.docs`: allowed port types and the complete
  node-port matrix come from the presentation-safe live registry, while frozen connection semantics
  are read from `contracts.md` section 3. `--check` now fails if either generated document drifts.
- The exact `scaffold_check.echo` demo used to verify step 8.1 was rebuilt from the guide and committed
  as a palette-visible testing node. Its scaffold-generated smoke tests remain unchanged; an added
  behavior test proves connected input takes precedence over its configurable fallback value.
- Verification passes with 209 backend tests (10 live-provider tests skipped, 62 subtests), all 145
  frontend tests across 22 files, the Vite production build, and both generated-document drift checks.

---

## Phase 9 — Scale & asset lifecycle

New node types and automated triggers will multiply workflows, runs, and artifacts; this phase
keeps execution fast and disk usage bounded.

### 9.1 Parallel branch execution
The scheduler runs independent DAG branches concurrently under a bounded worker pool while
keeping SSE event ordering deterministic per node and the run-level record consistent.
Per-node concurrency opt-out for adapters that are not thread-safe (Kokoro singleton et al.).
**Done when:** a diamond workflow executes both branches concurrently (measured overlap in pytest), results and event streams are deterministic, and opted-out adapters never overlap.

#### Step 9.1 review status — 2026-08-05

- **Complete.** The scheduler dispatches ready nodes through a bounded worker pool (four workers
  by default, configurable for tests/embedding) while retaining stable saved-order planning and
  waiting for every predecessor before a convergence node becomes ready.
- Node transitions atomically update the in-memory and persisted execution record before their SSE
  notification. Per-node status/retry/error order remains deterministic, and returned outputs and
  errors are normalized back into stable topological order regardless of completion timing.
- Registry capability `parallel_safe: false` makes an adapter exclusive within a run and shares a
  process-wide lock across runs. TTS uses this conservative opt-out to protect the Kokoro singleton.
- Pytest measures real overlap between both sides of a diamond and proves opted-out TTS nodes never
  overlap. Verification passes with 211 backend tests (10 live-provider tests skipped, 62 subtests),
  all 145 frontend tests, the Vite production build, and generated-document drift checks.

### 9.2 Concurrent runs across projects
Multiple runs for different projects execute simultaneously; the same project still serializes
through the Phase 7 queue. Run history and SSE streams stay correctly scoped per execution.
**Done when:** pytest proves two projects run at the same time without cross-talk in events, records, or artifacts, and same-project runs still serialize.

#### Step 9.2 review status — 2026-08-05

- **Complete.** The Phase 7 per-project FIFO workers already provide the required scheduling
  boundary: runs for distinct projects use separate workers, while every run for one project stays
  on that project's single queue worker.
- A barrier-based pytest now requires two project runs to overlap and publishes an artifact from
  each run through its execution-scoped staging directory. It verifies that persisted execution
  records, workflow history summaries, monotonically sequenced SSE buffers, artifact references,
  and artifact bytes contain only the matching execution and project identities.
- The existing queue regression continues to hold two same-project runs behind one worker while a
  different project proceeds, proving the same-project concurrency maximum remains one.
- Verification passes with 212 backend tests (10 live-provider tests skipped, 62 subtests), all 145
  frontend tests across 22 files, the Vite production build, and generated-document drift checks.

### 9.3 Asset garbage collection
An orphan scan lists artifacts under `output/` referenced by no execution record or pinned
payload; a GC command (UI + CLI) deletes only listed orphans, with a dry-run default and a
protected-paths allowlist.
**Done when:** GC removes seeded orphans and provably never touches referenced or pinned artifacts (pytest builds both cases), and dry-run reports without deleting.

#### Step 9.3 review status — 2026-08-05

- **Complete.** One conservative scanner powers the local-only API, workflow toolbar dialog, and
  `python -m studio.workflows.asset_gc` CLI. The CLI and API default to dry-run reports; permanent
  deletion requires an explicit flag or confirmed UI action with exact selected paths.
- Execution-record `artifact_refs` and managed paths nested in pinned Result Viewer payloads are
  retained. Workflow runtime state and `TRASH` are protected by a path-prefix allowlist, symlinks
  are never followed or deleted, and every deletion request is checked against a fresh orphan scan.
- Verification passes with 216 backend tests (10 live-provider tests skipped, 62 subtests), all 146
  frontend tests across 23 files, and the Vite production build. Dedicated tests prove orphan
  deletion, dry-run behavior, protected/reference/pin retention, stale-path refusal, API behavior,
  CLI behavior, and explicit UI selection.

### 9.4 Project archive & restore
Export a project (workflow, executions, referenced artifacts, branding) as one archive file;
restore recreates it under a new or original ID with references rewritten. Used for backup and
machine moves.
**Done when:** archive → delete → restore round-trips a fixture project with byte-identical referenced artifacts and a workflow that validates and runs.

#### Step 9.4 review status — 2026-08-05

- **Complete.** Saved workflow projects can be downloaded as one versioned `.sts-project.zip`
  containing the workflow, matching execution records, referenced managed artifacts, and referenced
  branding. A SHA-256 manifest inventories every member before restore.
- Restore can preserve or regenerate both workflow and project IDs. Workflow snapshots, execution
  records, artifact references, and project-bearing artifact paths are rewritten consistently;
  execution ID collisions are also remapped. Existing files are never overwritten.
- Archive intake rejects traversal, symlinks, duplicate or undeclared members, unsupported versions,
  unsafe compression ratios, excessive file/count/total sizes, corrupt hashes, and invalid restored
  workflows. Files are staged and promoted only after complete validation, with rollback on failure.
- The workflow toolbar exposes project selection, archive download, and restore ID choices. A
  successful restore refreshes and opens the restored workflow.
- Verification passes with 221 backend tests (10 live-provider tests skipped, 62 subtests), all 147
  frontend tests across 24 files, the Vite production build, and generated-document drift checks.
  Dedicated tests prove archive/delete/restore with original and new IDs, byte-identical artifacts,
  reference rewriting, pinned-viewer retention, restored-workflow execution, integrity/traversal
  refusal, API behavior, and UI restore options.

### 9.5 Large-canvas performance
Profile and fix canvas behavior at 150+ nodes: memoized node cards, viewport-culled rendering
if needed, debounced persistence, and a generated large-workflow fixture for regression use.
**Done when:** the 150-node fixture loads, pans, and drags without dropped-frame stalls (documented measurement), and interaction tests on the fixture pass.

#### Step 9.5 review status — 2026-08-05

- **Complete.** Canvas projection now preserves element identity for unchanged nodes, node-card
  subtrees are memoized by visible state, and Vue Flow enables viewport culling at 100 nodes.
  Drag positions persist only at drag-stop, while the existing 1,000 ms trailing draft debounce
  keeps serialization outside rapid interaction.
- A deterministic generator owns the checked-in 150-node fixture. The full-page regression proves
  fixture load, culling activation, cosmetic pan behavior, drag persistence, and delayed draft
  serialization; it also guards fixture drift and stable element identity.
- The repeatable 721-update benchmark recorded p95 projection times of 0.086–0.090 ms and maximums
  of 0.756–0.812 ms across three runs, with zero updates exceeding the 16.67 ms frame budget.
  Method, scope, raw results, and a browser paint spot-check procedure are documented in
  `docs/workflow-canvas-performance.md`.
- Verification passes with 221 backend tests (10 live-provider tests skipped, 62 subtests), all
  150 frontend tests across 25 files, the Vite production build, and generated-document drift
  checks.

---

## Phase 10 — Provider architecture audit & contracts

This is the Phase 0 equivalent for the provider-plugin migration. No production dispatch or UI
behavior changes belong in this phase. The audit starts from the provider foundation already in
`studio/shared/providers_common/` and the TTS, Storyboard, and Animator provider packages; it must
also account for the provider-ID branches that remain in their routes/adapters and the currently
non-provider-driven Story and Scene Blueprint modules. Music and Captions are out of scope by owner
decision (see the audit header); audit them only to confirm they stay working, not to migrate them.

### 10.1 Current-path and compatibility audit
Trace every way the legacy pages, pipeline services, workflow adapters, settings UI, and tests invoke
script/story generation, scene-blueprint AI, TTS, Storyboard, and Animator. Inventory
all provider IDs, aliases, request fields, settings keys, environment fallbacks, output files, async
callbacks, WebSocket/Automa hooks, and hard-coded provider branches. Include the frontend random-story
templates in `frontend/src/shared/data/stories.js` and `useRandomStory.js`, the current Gemini/n8n story
service, scene-blueprint webhooks, and provider-specific node fields in `studio/workflows/registry.py`.
Record which behavior is public compatibility surface and which is internal debt.

Read `_dev/docs/plans/modular-providers-plan-v4.md` first — it is the design doc the existing
`providers_common` infrastructure was built from — and reconcile its vocabulary with this plan.
The audit must explicitly answer these already-identified items rather than rediscover them:
1. **Dead-interface inventory.** For each of the seven existing providers, record whether its
   `provider.py` body, `get_provider()` factory, and ABC methods have ever executed. Mark every
   never-executed path as unverified work in Phases 14/15, not as a preserved baseline.
2. **Selection-store conflict.** `settings/settings.json` `domains.*.selected_provider` vs
   `app-config.json` `sts-tts-provider`; the unused `settings_manager.set_selected_provider()`; and the
   whole-blob `PUT /api/settings/v2` read-modify-write in `useProviders.js`. Decide which is
   authoritative and record the migration for the other.
3. **Env-var side effects.** First-run seeding (`settings_manager.py:67-107`) flips
   `selected_provider` to `inworld` when `INWORLD_API_KEY` is present. Record every such implicit
   selection change.
4. **Legacy alias tables.** `pipeline/services.py:550` and `:644`
   (`gemini_ws→gemini`, `wavespeed_webhook→webhook`, `wavespeed_direct→direct`, `grok_automa→grok`,
   `kie_ai→kie-ai`) plus the legacy-alias branches in `app.py:253-276`.
5. **Registry bypasses.** `animator/animation_routes.py:21` imports `generate_image` directly from
   `.providers.kie_ai`; `tts/routes.py` never touches the registry at all.
6. **Duplicated contracts.** `JobHandle`/`JobStatus`/`SceneResult` are defined twice, once each in the
   storyboard and animator `base.py`.
7. **Known latent defect.** `adapters/story.py` returns a `story` output port that
   `studio/workflows/registry.py` does not declare, so `_validate_outputs` silently drops it and its
   artifact refs never reach a port. Assign it a fix owner (13.3).

**Done when:** `contracts.md` contains an evidence-linked provider migration matrix for every listed
module and current provider, with entry points, inputs, outputs, side effects, IDs/aliases, settings,
and callers; all seven items above are answered with file/line evidence; every hard-coded provider
decision and every never-executed provider code path has an owner step; and no current legacy or
workflow execution path is unaccounted for.

### 10.2 Freeze plugin, manifest, and settings contracts
Extend `contracts.md` with Provider Contract v2, reusing `ProviderRegistry`, `ProviderManifest`,
`settings_manager`, discovery, migrations, runtime hooks, and broken-provider isolation rather than
building a parallel framework. Freeze the supported domains — exactly five: `script`,
`scene_blueprint`, `tts`, `storyboard`, `animator` (Music and Captions are excluded by owner decision;
the catalog must make adding a domain later a data change, not a redesign); package layout; provider
ID/version rules; manifest
metadata; capabilities; factory/lifecycle hooks; settings-schema widgets and conditional fields;
secret/env handling; availability/health states; and frontend-safe serialization. Provider folders
remain owned by their module, while one registry hub exposes all domain registries.

Two contracts must be frozen here because later steps are impossible without them:
- **Parameterized option sources.** `GET /api/workflow/options/<source>` currently resolves
  `resolve_options(source)` with no arguments, so no dropdown can depend on the selected provider.
  Freeze the extended, still-allowlisted shape (source + validated context such as domain/provider ID)
  plus its caching and failure semantics; 12.2 implements it and 15.2 depends on it for per-provider
  voice lists.
- **Single authoritative selection store.** Freeze which of `settings/settings.json` and
  `app-config.json` owns the selected provider, how the loser is migrated, and the replacement for the
  whole-blob `PUT /api/settings/v2` read-modify-write. This applies to all three legacy keys
  (`sts-tts-provider`, `sts-storyboard-provider`, `sts-asset-provider`), not only TTS; the contract must
  also account for the current Animator route never reading `domains.animator.selected_provider`.

**Done when:** the contract specifies every required/optional manifest and settings field, validation
and unknown-field policy, lifecycle and shutdown behavior, registration/discovery order, duplicate-ID
handling, broken-plugin isolation, and exactly which metadata is safe to send to the browser; the
parameterized option-source envelope and the authoritative selection store are both frozen with their
migration paths; the domain catalog replaces **both** hardcoded three-domain sets
(`ProviderRegistry.VALID_DOMAINS` and `settings_manager.validate_settings`); and adding a provider to an
existing domain requires no edit to a workflow node, route dispatcher, or Vue component.

### 10.3 Freeze invocation, result, job, and error contracts
Define a shared invocation context (project/execution/node identity, managed output directory,
cancellation token, progress callback, redacted logger) plus domain request/result schemas. Keep
domain results typed—script document, scene-blueprint document, TTS audio, storyboard scene assets,
animation scene assets—inside one versioned result envelope with
provider/domain/version, artifact refs, metadata, warnings, and provenance. Standardize async job
handles/status/progress and terminal states. Define `ProviderError` with stable code, safe message,
retryable flag, redacted details, provider/domain, and optional recovery suggestion; unknown exceptions
must be wrapped at the registry boundary.

**Done when:** all five domains have exact request/result schemas and artifact rules; synchronous and
asynchronous providers share terminal/error semantics; partial per-scene results are unambiguous;
cancel/retry/timeout behavior is frozen; no raw provider exception, credential, arbitrary filesystem
path, or provider-specific response can cross into workflow records or API responses.

### 10.4 Migration map, fixtures, and implementation gate
Freeze compatibility mappings for legacy request fields (`engine`, `provider`, `provider_override`,
domain-specific option dictionaries), current provider IDs, saved provider settings, workflow node
configs/type versions, legacy API envelopes, output paths, and execution/cache records. Create or
identify deterministic fixtures for every domain and provider boundary; live providers remain gated.
Review the new contracts against the real code and update later steps if any adapter or provider cannot
meet them without a deliberate compatibility shim.

**Done when:** every persisted/API shape has an upgrade or passthrough strategy; old workflows and
legacy requests are expected to run without manual edits; fixture ownership is explicit; provider
contract tests can be written without live credentials; baseline pytest, Vitest, production build,
and generated-doc drift checks pass; and Phase 11 is unblocked without inventing semantics.

---

## Phase 11 — Shared provider platform

### 11.1 Generalize the registry into a domain hub
Extend `studio/shared/providers_common/registry.py` so supported domains are declared through a
domain catalog rather than the current `VALID_DOMAINS` set (`registry.py:177`) — and retire the
duplicate hardcoded domain set in `settings_manager.validate_settings` (`settings_manager.py:270`) in
the same step, so the two can never drift. Replace the three copies of the 57-line
`studio/<domain>/providers/__init__.py` (tts, storyboard, animator — structurally identical, differing
only in domain name and `init_<domain>_registry`; see contracts §14.6) with one generated/shared
binding. Add a process-wide registry hub that can
list and resolve `(domain, provider_id)` while preserving the existing per-module `registry`,
`get_provider`, and `list_providers` imports as compatibility facades. Domain registration must bind
the request/result contract and provider search path once; individual provider registration must not
touch `app.py` or the workflow registry.

**Done when:** all five domains can register with the hub; existing TTS/Storyboard/Animator imports
still work; duplicate domains/providers fail deterministically; discovery order is stable; and tests
prove one broken or duplicate provider cannot hide healthy providers or stop application startup.

#### Step 11.1 review status — 2026-08-09

- **Complete.** `studio/shared/providers_common/domains.py` holds the five-domain catalog
  (contracts §19.1) and is now the only place a domain name is written down. D1 is closed:
  `ProviderRegistry.VALID_DOMAINS` is `DOMAIN_IDS`, `settings_manager.validate_settings` tests
  membership in `DOMAINS`, and `_default_settings()` generates its `domains` block from the
  catalog, so all three derive from one source and a test asserts it.
- `providers_common/hub.py` adds the process-wide `ProviderHub` with the frozen §27 surface
  (`domains`, `registry`, `get`, `list`, `catalog`, `shutdown`) plus `discover`/`discover_all`/
  `bind_runtimes`. D3 is closed: the three 57-line `providers/__init__.py` copies are now
  three-line `bind_domain(<domain>)` facades that still export `registry`, `discover`,
  `get_provider`, `list_providers`, and `init_<domain>_registry`, and `registry` is literally the
  hub's registry object. D2 is closed — discovery iterates `sorted(os.listdir(...))`.
- D4 is done for the five literal `{tts, storyboard, animator}` dicts in `editor/routes.py`
  (P28): the four lookup handlers share one `_resolve_provider()` over the hub, and
  `/api/providers` returns `hub.catalog()`. That response now carries all five domains;
  `script` and `scene_blueprint` list zero providers until 12.3 lands their bridges. The
  frontend reads `data.domains[<domain>]` by key and never iterates, so the extra keys are inert.
  `app.py` replaces the fixed three-call startup sequence with `init_providers(app, sock)`, which
  discovers in catalog order and binds extension runtimes only after every domain is discovered
  (contracts §21.2 items 1 and 4).
- **Adjustment recorded:** discovery is re-entrant. `inworld/provider.py` imports
  `studio.tts.providers.base`, which executes the `studio.tts.providers` package body mid-scan;
  once startup — not the package body — triggers the first scan, that re-entry ran a second full
  scan and re-registered every provider. `discovery_scan` now marks `_discovered` *before* the
  scan rather than after. `hub.get`/`list`/`catalog` discover lazily so callers that never went
  through startup still see the catalog, and `hub.shutdown()` clears registries in place instead
  of dropping the objects the facades hold.
- **Deferred as already assigned:** alias resolution in `hub.get` (D5, 11.2), exclusion records
  (D7, 11.2), the `create()` factory and real provider `shutdown()` (D8, 11.2), and atomic
  snapshot publication (D21, 11.2). `ProviderRegistry` takes an optional `valid_domains` so a hub
  over a custom catalog can prove a sixth domain is a data-only change.
- Verification passes with 252 backend tests (10 live-provider tests skipped, 62 subtests), all
  154 frontend tests across 25 files, the Vite production build, and generated-document drift
  checks.

### 11.2 Provider discovery, factories, and lifecycle isolation
Upgrade discovery to validate the whole provider package (`manifest.py`, `provider.py`, optional
`settings_schema.py` and runtime hooks) before atomic registration. Instantiate providers through a
factory instead of module-level ID branching, cache only where declared, and shut down initialized
instances safely. Preserve extension/WebSocket startup through `call_provider_runtime`, but drive it
from manifest capabilities rather than provider IDs. Dev hot-reload swaps only a fully valid provider
catalog and retains the last good version after an invalid edit.

**Done when:** adding/removing a fixture provider directory changes the catalog on restart (and in
guarded dev reload) with no central provider list edit; failed import/init/runtime/shutdown is isolated
and reported as provider health metadata; and no half-loaded catalog becomes visible to requests.

#### Step 11.2 review status — 2026-08-09

- **Complete.** `providers_common/validation.py` is new and holds the frozen §20.3 validation order,
  the ten §21.4 reason codes, and `sanitize_message()`. Validation is pure — it imports nothing,
  touches no filesystem, and never raises — so `registry._load_provider` now decides
  *load → describe → validate → collect* and returns either an instance or an exclusion.
- D6 is closed: unknown top-level manifest keys and unknown capability keys are ignored, logged, and
  surfaced as `warnings[]` instead of raising `TypeError`. An unknown `kind`, a non-`bool` capability
  value, a non-semver `version`, a bad id/alias shape, and a `javascript:`/`data:`/non-loopback-`http`
  URL stay hard failures. The old truthiness check on `capabilities` became a presence/type check, so
  an empty capability dict is valid.
- D5 is closed: `ProviderManifest` gains `aliases` and `contract_version`. Aliases resolve *after* all
  providers are registered, so a real id always beats an alias; a colliding alias is dropped with a
  warning on **both** providers and excludes neither.
- D7 is closed: `ProviderExclusion` / `ProviderRegistry.excluded()` are surfaced in `to_dict()`, and
  `/api/providers` now answers `{count, excluded[]}` per domain. Messages are truncated to 200
  characters, path-stripped to a basename, secret-masked, and stripped of `_sts_provider_*` names.
- D21 is closed: `CatalogSnapshot` is immutable, `build_snapshot()` scans into a private builder, and
  `publish()` swaps it in with one assignment. A rescan is invisible to readers until it completes.
  Providers dropped by a swap are `retire()`d — new leases are refused, in-flight
  `lease()` holders drain (5s cap), and only then does `shutdown()` run.
- D8 is closed: `ProviderInstance.create()` is memoized per `(domain, provider_id)` behind a
  per-instance lock, never runs at import or during discovery, and never runs under the hub lock.
  `hub.create()` is the entry point; `registry.shutdown_instances()` tears down in reverse
  construction order. `init_providers` arms `atexit`, so `shutdown()` is a live path rather than the
  never-called hook it was. The two undeclared caches (`_cached_validation`, `_cached_health`) are
  deleted; only the schema memo the contract declares remains.
- Runtime binding moved to `hub._bind_runtime`, selected by `kind == "extension"` and reported back
  through the new `RuntimeBinding` result; a failed `register_runtime()` becomes a provider warning
  instead of a bare boot log, and never aborts startup.
- **Adjustment recorded — the runtime selector was already manifest-driven.** The step text asks to
  "drive it from manifest capabilities rather than provider IDs", but 11.1 had already replaced id
  branching with `kind`, and §20.2 freezes `extension` as the only kind that binds. Rather than
  re-derive selection from `push_callbacks` (which would give a WebSocket runtime to a future
  `cloud` provider), selection stays on `kind` and a provider that declares `push_callbacks` without
  being an `extension` is warned about.
- **Adjustment recorded — `get_provider` is kept as a factory fallback.** §21.1 says `create()`
  *replaces* the eight never-executed `get_provider()` functions. Rewriting all seven provider bodies
  belongs to 14.2/14.3/15.2, so `create` resolves first and `get_provider` second. `create()` was
  added to `kokoro` and `inworld`, which had no factory at all; all seven shipped providers now
  construct and shut down, verified end to end.
- **Adjustment recorded — reload rejects *regressions*, not all exclusions.** "Swaps only a fully
  valid catalog" read literally would let one permanently broken folder freeze the catalog forever.
  `hub.reload()` therefore publishes a candidate unless a currently-registered provider would come
  back excluded. Adding or removing a folder still takes effect; an invalid edit to a live provider
  keeps the last good catalog and is reported in `ReloadReport.retained`. The workflow dev reloader
  now watches `manifest.py` / `provider.py` / `settings_schema.py` under every `DomainSpec`
  `providers_base` and calls `hub.reload(domains)` for the domains that changed.
- Verification passes with 310 backend tests (10 live-provider tests skipped, 88 subtests), all 154
  frontend tests across 25 files, the Vite production build, and generated-document drift checks.
  Both guards were mutation-checked: disabling lease draining and disabling regression detection each
  fail their test.
- **Deferred as already assigned:** `availability` computation and serialization (D9, 11.3), missing
  `health_check` → `unknown` (D10, 11.3), the `description`/`docs_url`/`environment` manifest fields
  and env fallback (11.3), and folding `ProviderConstructionError` into the shared `ProviderError`
  boundary (11.4).

### 11.3 Manifest v2 and settings validation
Extend `ProviderManifest` and settings schemas with label/description, domain, kind, version, contract
version, capabilities, availability requirements, defaults, deprecation/alias metadata, and safe UI
hints. Validate settings server-side from the provider schema, separate durable secret settings from
portable per-run options, support environment fallbacks without returning their values, and migrate
existing settings through `settings_migrations.py`. Reuse the current generic provider settings
components rather than creating domain-specific forms.

**Done when:** malformed manifests/settings are rejected with stable issues; secret values are write-
only and redacted from logs, workflow snapshots, archives, APIs, and errors; existing selected-provider
and provider-settings files migrate losslessly; and every manifest can round-trip through its public
metadata representation without leaking internal callables or paths.

#### Step 11.3 review status — 2026-08-09

- **Complete.** `providers_common/settings_schema.py` is new and is the leaf of the settings import
  chain: it owns `SENSITIVE_KEYS_RE`, the `"***"` sentinel, the §22.2 widget vocabulary (including
  the frozen `textarea`), `ui.show_if` evaluation, schema validation, `split_settings`, `redact`,
  `apply_settings_patch`, and `invocation_config`. `settings_manager` and `validation` now build on
  it, so nothing imports settings *storage* to learn what a secret is.
- `ProviderManifest` gains `description`, `docs_url`, and `environment`, plus `public_dict()` — the
  §25 representation, which is asserted to round-trip through `validate_manifest` for every shipped
  manifest and to carry no `environment` names, callables, or paths. Validation rejects a
  non-`https` `docs_url` (loopback `http` excepted), a >500-character or control-character
  `description`, and an environment name that is not `^[A-Z][A-Z0-9_]{0,127}$`.
- D9 is closed: `ProviderInstance.availability()` implements §21.5 — `available`,
  `needs_configuration` (a `requires` key empty *after* env fallback), `degraded` (no resolvable
  factory, a `create()` that already raised, or a present-but-failed settings schema). It is
  serialized in `to_dict()` and reaches `/api/providers` through `hub.catalog(settings_for=…)`,
  which reads the settings document once rather than once per provider. The fourth frozen state
  `unavailable` has no producer by construction: an excluded provider is an `excluded[]` entry,
  never a `ProviderInstance`.
- D10 is closed: a provider with no `health_check` now answers `unknown`, not `ok`.
- `resolve_settings()` implements the §22.6 read-time fallback. It is applied to provider
  validation, health, and invocation only; a resolved value is never written back and never
  serialized, which is asserted against `/api/settings/v2`, the provider-settings read, and
  `/api/providers`. `_seed_from_env` no longer copies `INWORLD_API_KEY`, `WAVESPEED_API_KEY`, or
  `KIE_AI_API_KEY` into `settings.json`, and the `INWORLD_API_KEY` → `selected_provider` side
  effect is gone (§14.3, §22.6).
- Server-side settings validation now runs from the provider schema before the provider hook:
  required-but-empty is an `error`, an unknown saved key is a preserved `warning`, a hidden
  (`ui.show_if`) field is exempt from `required` and excluded from the invocation config, an
  unrecognized `ui.type` is a `warning`, and `ui.options` + `ui.options_source` together warn with
  `options_source` winning. Issues are sorted, so the same settings always produce the same list.
  A raising `validate_settings` now yields the frozen `{root, error, "Settings validation failed"}`
  instead of `str(e)`, which could contain the submitted key.
- The §22.6 live defect is fixed rather than deferred. `GET /api/settings/v2` and
  `GET /api/providers/<d>/<p>/settings` are redacted, and the three write paths
  (`PUT /api/settings/v2`, `PUT`/`POST` provider settings and validate/test) restore a sentinel
  submission from the stored value, so the whole-blob round-trip in `useProviders.js` cannot erase
  a key. `redacted_provider_settings` finally has call sites. `/test` also stopped trying to
  `jsonify` a `HealthResult` dataclass and redacts provider-authored `details`.
- **Leak found and closed while covering "archives".** `_kie_ai_options` merged the whole `kie_ai`
  settings dict — including `api_key` — into `grabber_job.json` under `output/`, which project
  archives copy. `kie_ai_generate()` resolves the key itself and never read it from there, so both
  call sites (`animation_routes.py:305`, `workflows/adapters/animator.py:33`) now merge
  `portable_provider_settings()`, the non-secret half of `split_settings`.
- `apply_migrations` is corrected: it keys on the **target** version, runs every target greater
  than the stored one, and stamps the version per step. The v2 migration adopts the three legacy
  `app-config.json` selections through the alias table, backfills domain blocks added to the
  catalog after the file was written, and is a no-op when `settings.json` already holds a
  selection. The legacy file is read through an injected
  `settings_manager._read_legacy_user_settings()` rather than the editor blueprint's private
  helper. Tests cover v1→v2, alias normalization, explicit-selection precedence, losslessness,
  already-v2 idempotence, an odd/missing version, and an interrupted write (`os.replace` fails →
  v1 stays on disk, no temp file leaks, the next load retries and completes).
- The repository's own `settings/settings.json` migrated on this run: version 1→2, all three
  existing selections preserved verbatim, `per_provider` untouched, `script` and `scene_blueprint`
  backfilled from the catalog. The `sts-tts-provider: inworld` legacy key was correctly ignored
  because `settings.json` already held an explicit selection.
- **Adjustment recorded — the shipped manifests stay at `contract_version=1`.** §19.3 says a v2
  manifest writes `2` explicitly and that only `2` may be invoked through the 10.3 invocation
  contract, which 11.4 implements. Declaring `2` now would claim an invocability that does not yet
  exist, so the seven providers gain the v2 *metadata* fields and keep `contract_version=1` until
  11.4/14.x rewrites their bodies.
- **Adjustment recorded — no `deprecated` manifest field was invented.** The step text names
  "deprecation/alias metadata", but the §20.1 field table and the §25 serialization list are frozen
  without one. Deprecation is therefore carried by `aliases`: the legacy wire strings from §14.4
  (`gemini`, `webhook`, `direct`, `grok`, `midjourney`, `kie-ai`) are now declared on the five
  providers that own them. The hand-written tables in `pipeline/services.py` and
  `animator/schemas.py` are untouched — retiring them is 14.2/14.3's work.
- **Adjustment recorded — schema validation checks `enum`, not `ui.options`.** Only a declared
  `enum` gates a value. The live `settings.json` stores a Kokoro voice (`af_bella`) under the
  Inworld provider, whose voice list is a `ui.options` dropdown; treating widget options as a
  closed set would have started rejecting saves of pre-existing configuration.
- Verification passes with 372 backend tests (10 live-provider tests skipped, 112 subtests), all
  154 frontend tests across 25 files, the Vite production build, and generated-document drift
  checks. Three guards were mutation-checked: reverting the migration comparison, the sentinel
  drop, and the `unknown` health default each fail their tests. No Vue component changed — the
  existing generic `ProviderSettingsForm` renders the redacted secret and round-trips it unchanged.
- **Deferred as already assigned:** moving the provider API into its own blueprint and the targeted
  `PUT /api/providers/<domain>/selection` endpoint (11.5), `ui.options_source` resolution and the
  `textarea`/`show_if` renderers (12.2/12.4), and folding validation issues into the shared
  `ProviderError` boundary (11.4).

### 11.4 Standard provider runtime and error boundary
Implement the contract from 10.3 in `providers_common`: invocation context, typed result envelope,
artifact normalization, progress events, job handle/status, cancellation/timeout helpers, and the
single exception boundary that maps provider failures to `ProviderError`. Unify the duplicated
`JobHandle`/`JobStatus`/`SceneResult` definitions (declared separately in the storyboard and animator
`base.py`) into one shared async-job contract, and provide adapters for the existing `TTSResult` and
those job types so the domain migrations can be diffed against today's dict payloads.

**Behavior-preserving means the *legacy* path, not the ABC path.** The ABC methods and `get_provider()`
factories have never executed, so the baseline to preserve is the observable output of the current
`if provider_id == …` branches in `pipeline/services.py`, `storyboard/routes.py`,
`animator/animation_routes.py`, and `tts/routes.py` — captured as fixtures before any rewiring. Treat
every existing `provider.py` body as unverified code under first-time test. Provider output is staged
and validated before promotion to managed output directories.

The migration machinery already has a two-hop save/load round-trip test
(`tests/test_workflow_persistence.py`), so this step must not invent a production node-version bump
solely to test it. If adopting the standard result envelope changes a workflow adapter's output in
this step, bump `ADAPTER_CACHE_SCHEMA_VERSION` (`studio/workflows/cache.py:23`) in the same commit.
Later output-shape changes must independently bump that version unless the affected node's
`type_version` changes in the same commit; an earlier bump cannot invalidate cache entries written
after it.

**Done when:** contract tests cover sync success, async success, progress, cancellation, timeout,
retryable and terminal errors, malformed results, partial scene failure, unmanaged/missing artifacts,
and secret-bearing exceptions; every previously-unexecuted provider method is covered by at least one
test that actually invokes it; recorded legacy-path fixtures match the new envelope field-for-field or
each difference is explicitly approved; and workflow-facing errors keep stable codes and never expose
raw provider objects or traceback text.

#### Step 11.4 review status — 2026-08-09

- **Complete.** Six new modules implement the 10.3 contract in one import chain with no
  cycles: `errors` (a leaf, on `validation` only) → `invocation` / `results` → `jobs` →
  `boundary`, plus `legacy` and `fixtures` beside them. Nothing imports `studio.workflows.*`
  at module level — `redaction`, `AdapterError`, and `safe_join` are all reached lazily, so
  the provider layer and the workflow layer still do not depend on each other's package
  (§34.4).
- D22 is closed: `ProviderInvocation` is frozen, carries the §30.1 field set, and `cancel`,
  `progress`, and `log` are never `None`. `build_invocation()` is the one construction site
  and maps `AdapterContext` field for field (§30.6); passing `context=None` builds the same
  object for a legacy route with no scheduler. `CancellationToken` latches, so re-probing
  after the scheduler tears its event down cannot un-cancel a call, and a probe that raises
  is swallowed rather than failing the invocation.
- D29 is closed: `ProgressReporter` rate-limits to one event per second per invocation,
  coalesces intermediate values, always emits the last value before a terminal state,
  enforces monotonic `ready` and write-once `total`, clamps `fraction`, and pushes every
  message through redaction, path stripping, and the 200-character cap. It never raises, and
  a sink that raises is logged and dropped.
- D23 and D28 are closed. `ProviderResult` derives `status` from `units` rather than trusting
  the provider (§31.5 rule 3, cancellation first), rejects a duplicate `unit_index` and a
  `failed` unit with no error, and unions unit refs into the envelope. `validate_egress()`
  runs at the boundary over both the envelope and the platform-authored provenance, and
  rejects absolute/UNC paths, sensitive keys, `bytes`, non-JSON values, and the §31.1 caps.
- D24 is closed: the two field-for-field duplicate `JobHandle`/`JobStatus`/`SceneResult`
  blocks in `storyboard/providers/base.py` and `animator/providers/base.py` are deleted, and
  both modules re-export the one definition in `providers_common/jobs.py`. `status` became
  `state` over a closed vocabulary, `result: dict | None` became `units`, and `SceneResult`
  *is* `UnitResult` — the `image_url`/`video_url` split is gone. `terminal_outcome()` maps
  each of the five terminal states onto exactly one invocation outcome, including "zero
  produced units can never be `succeeded`".
- D25, D26, and D35/D36 are closed. `ProviderError` sanitizes its message on construction, so
  no subclass can build a leaky one; `wrap_exception()` logs the traceback through the
  internal-only channel and returns a generic per-domain sentence, never `str(exc)`.
  `scheduler._failure_payload` now uses `safe_failure_message()`, which copies text only from
  `SchedulerError`/`AdapterError`/`ExpressionError`/`ProviderError`, and even then strips
  paths and masks `key=value` pairs. Both visual adapters raise `ProviderCancelled` →
  `CANCELLED` and `PROVIDER_TIMEOUT` → `POLL_TIMEOUT`, retiring `EXECUTION_CANCELLED` and
  `NODE_TIMEOUT`.
- D27 is closed: `is_retryable_failure()` ends the attempt loop on a `retryable=False`
  provider error. An exception that declares nothing is still retried, so no existing node
  changes behavior.
- Egress: L1 (`str(exc)` in `_failure_payload`), L6 (settings echoed into a result), and L8
  (the absolute staged path in `ARTIFACT_MISSING`) are closed here. L4 is extended — 11.3
  fixed a health hook that *raises*, and three shipped hooks *return* `{"status": "fail",
  "message": str(e)}`, which `ProviderInstance.health_check` now sanitizes too. L3's machinery
  exists (`legacy._unit_error` turns the persisted `str(e)` into a bounded
  `ProviderErrorPayload`); wiring it into the live route stays 14.2's.
- §46's second fixture layer exists: `tests/fixtures/providers/<domain>/<provider_id>/` with
  `request.json` / `raw_response.json` / `expected_result.json`, a SHA-256 manifest, a
  `generate.py`, and two deliberately different validators — record-time `validate_sanitation`
  over all three files, and the stricter §36 `validate_egress` over `expected_result.json`
  only, so a raw response may keep the synthetic remote URL that exercises the code removing
  it. Three legacy boundaries are recorded (`tts/kokoro`, `storyboard/wavespeed_webhook`,
  `animator/kie_ai`) and each is asserted to reach the envelope field for field; a per-key
  test proves the only two dropped TTS keys are the ones with a named owner (`wav_path`,
  §36 L7; `job_meta`, D39).
- The `fixture_provider` of §46.3 is written and load-bearing: it is the first manifest in the
  repo to declare `contract_version=2`, it appears in no hardcoded list, and every runtime
  contract test drives it — sync success, async submit/poll/cancel, progress, cancellation,
  timeout, retryable and terminal errors, malformed and unknown-key results, partial and
  all-failed units, unmanaged and missing artifacts, and a secret-bearing exception.
- **Two defects found by first-time test, in code that had never executed.** Both animator
  providers read `studio.animator.routes._asset_jobs`, an attribute that module has never
  defined — every `poll()` and every Kie AI `submit()` would have raised `AttributeError`.
  And all five visual `poll()` bodies counted `scene_statuses[...]["status"] == "complete"`, a
  value neither domain has ever written (both write ready/error). They are corrected onto the
  real store and one shared `status_from_scenes()`, which also applies the zero-produced-units
  rule in one place. `kie_ai._generate_images` also persisted a raw `str(e)` into a file under
  `output/`; it is sanitized now.
- **Adjustment recorded — `JobStatus(status="unknown")` became `failed`/`PROVIDER_NOT_FOUND`.**
  The old provider-defined `"unknown"` is not in the §33.2 vocabulary and no caller could
  branch on it: a poll loop treated it as neither done nor failed and waited out the whole
  deadline. A job the provider has no record of will never complete, so `unknown_job_status()`
  returns the same shape §33.4 already mandates for a rehydrated job whose provider is gone.
- **Adjustment recorded — the redaction sentinel is `***`, not `[REDACTED]`.** §31.3's example
  shows `[REDACTED]`, but provenance is produced by `settings_manager.redact_settings`, whose
  frozen sentinel is `***` (§22.6). The producer wins. Consequently `validate_egress` has to
  allow a sensitive *key* whose value is nothing but a redaction marker — otherwise §31.2 and
  §31.3 contradict each other, since `resolved_settings_redacted` necessarily keeps the
  original key names.
- **Adjustment recorded — artifact existence needed a staging-aware check.** §34.2 defines
  `PROVIDER_ARTIFACT_MISSING`, but a staged write does not exist at its destination until the
  node succeeds, so a naive check would fail every staged artifact. `ArtifactStager` wraps
  `stage_path` and records destinations; `check_artifacts()` accepts a ref that either exists
  or was staged.
- **`ADAPTER_CACHE_SCHEMA_VERSION` is deliberately not bumped.** No workflow adapter's output
  shape changed in this step — only the error codes on two failure paths, which are never
  cached. Bumping would invalidate every existing entry for no reason, and the step text
  forbids inventing a version change to test the machinery. A test instead proves the
  mechanism the later bumps rely on, through the injectable `adapter_schema_version` parameter
  rather than the shipped constant (acceptance A9).
- **Adjustment recorded — the fixture provider package lives outside the fixture JSON root.**
  §46.3 lists `fixture_provider` in the same table as the recorded boundaries, but it is a
  Python package, not a `<domain>/<provider_id>` JSON triple; keeping it under
  `tests/fixtures/providers/` would make the manifest and the sanitation validator hash and
  scan source files. It is at `tests/fixture_providers/` and is registered by pointing a
  `DomainSpec.providers_base` at that directory, so it never enters the shipped catalog.
- **Deferred as already assigned:** `boundary.invoke()` has no production call site yet — the
  domain steps (13.1–13.4, 14.2, 14.3, 15.2) switch onto it, which is also why the shipped
  manifests stay at `contract_version=1`; the poll loop with jitter and the three-strike limit
  (D31, 14.1); job persistence and rehydration (D33, 14.1); push correlation and duplicate-
  status idempotence (D32, 14.4); per-unit retry (D34, 14.1); and the five
  `providers/contract.py` request/result models (D30).
- Verification passes with 510 backend tests (10 live-provider tests skipped, 161 subtests),
  all 154 frontend tests across 25 files, the Vite production build, and generated-document
  drift checks. Three guards were mutation-checked: reverting `safe_failure_message` to
  `str(exc)`, forcing `is_retryable_failure` to `True`, and disabling progress rate limiting
  each fail their tests. No Vue component and no frontend file changed.

### 11.5 Unified provider API and application startup
Replace the three startup-specific initialization blocks in `app.py:90-95` with hub initialization while
preserving their compatibility functions. Serve one versioned provider catalog plus domain/provider
detail, health, settings-read, settings-write, and option/capability endpoints using the standard
error envelope and loopback/security policy. The current provider API lives in the **editor** blueprint
(`studio/editor/routes.py:230-372`, which re-imports all three registries inside each of its five
handlers) — move it to a provider blueprint and keep the old paths as thin deprecated facades until the
final compatibility gate. Replace the whole-blob `PUT /api/settings/v2` selection write with the
targeted selection endpoint decided in 10.2, routing it through the existing but unused
`settings_manager.set_selected_provider()`.

**Done when:** one API enumerates every healthy, unavailable, deprecated, and broken provider by
domain; settings and health use only registry metadata; old provider endpoints return compatible
answers; startup/shutdown initializes each runtime exactly once; and backend tests cover auth,
redaction, invalid domains/IDs, unavailable providers, and mixed healthy/broken catalogs.

#### Step 11.5 review status — 2026-08-09

- **Complete.** `studio/providers/` is a new top-level blueprint package —
  `routes.py` (thirteen handlers) plus `catalog.py` (catalog assembly and versioning) — and is
  registered in `app.py` beside the other fifteen blueprints. D4 is closed on the API side: the
  five editor handlers that each re-imported three registries and built a literal
  `{tts, storyboard, animator}` dict are gone, and every handler resolves through
  `hub`/`DOMAINS`. `studio/editor/routes.py` shrinks by 189 lines and no longer imports
  `settings_manager` at all; a test asserts the editor blueprint owns zero `/api/providers*`
  rules and no `/api/settings/v2`.
- The startup half of the step was already done by 11.1/11.2 — `app.py:90-95` has called
  `init_providers(app, sock)` since then, and the three `init_<domain>_registry` compatibility
  functions still exist and still work. What 11.5 adds is the *exactly-once* half.
- **Defect found: every catalog reload rebound every runtime.** `_rebind_new_runtimes` iterated
  the whole new snapshot and called `_bind_runtime` on each provider, so a dev reload re-ran
  `register_runtime()` for `gemini_ws` and `grok_automa` — a second claim on an already-claimed
  `@sock.route` path. `ProviderHub` now keeps a `_runtime_bound` ledger keyed on
  `(domain, provider_id)` rather than on the instance, because a reload rebuilds the
  `ProviderInstance` objects; `shutdown()` clears it so a torn-down process can bind again. The
  capability-mismatch warning stays unguarded (it is pure metadata and `add_warning` de-dupes),
  so it survives a reload. Reverting the guard fails two tests.
- **The runtime count had to be taken at the `call_provider_runtime` boundary.** The obvious
  assertion — the provider module's own `bound` list — silently passes a duplicate bind, because
  a reload re-imports `provider.py` under a fresh synthetic module and its module-level state
  resets. The test spies on the hub's seam instead.
- D13 is closed. `PUT /api/providers/<domain>/selection` is the §24.2 write path and is
  `set_selected_provider()`'s first call site since it was written. It validates the domain
  against `DOMAINS`, resolves id-then-alias, answers `409 PROVIDER_EXCLUDED` for a discovered
  but unloadable id and `404 PROVIDER_NOT_FOUND` for an unknown one, stores the **canonical** id
  even when an alias was sent, and returns `{domain, selected, availability, issues}`. Selection
  is non-blocking: a `needs_configuration` provider is written and the issues travel back.
  `PATCH /api/settings/v2` is added for field-level deep merge; `PUT` remains for whole-document
  import and reset.
- The frontend half of D13 is done: `useProviders.selectProvider` no longer does
  `GET /api/settings/v2` → spread → `PUT`. That was a genuine lost-update window plus a second
  round trip (`validateProviderSettings`) purely to learn whether the provider was configured.
  Six Vitest cases cover the targeted write, the absence of any `/api/settings/v2` traffic, the
  alias-to-canonical echo, the non-blocking unconfigured case, the already-selected no-op, and a
  rejected write leaving the store untouched. No Vue component changed — `ProviderSelector`
  still reads `result.needsConfiguration`.
- The catalog is content-versioned, not URL-versioned: `catalog_version` is a 16-character
  SHA-256 of the canonical JSON of the payload, which is what 12.1 caches on. A test proves it
  is stable across identical reads and changes when a provider folder appears.
- New read surface, all from registry metadata and all loopback-only: `GET /api/providers`
  (`{catalog_version, domains}`), `GET /api/providers/<domain>`,
  `GET /api/providers/<domain>/<provider_id>`, `.../capabilities` (manifest only — no provider
  code runs), and `.../health` (probes the stored settings, where `POST .../test` probes a
  candidate patch).
- **Adjustment recorded — the "thin deprecated facade" is a no-op, because the paths did not
  move.** The step text asks to keep the old provider paths as deprecated facades, but the old
  paths *are* the canonical ones (`/api/providers`, `/api/settings/v2`); only the owning module
  changed. Two blueprints cannot register the same rule, so a facade would have had to invent a
  second URL for the same handler. Nothing consumes such a URL, and inventing one would create
  the compatibility surface 16.1 would then have to remove.
- **Adjustment recorded — "deprecated" providers are enumerated as `aliases`.** §20.1 declares
  no `deprecated` manifest field, and §20.3 ignores unknown top-level keys, so a manifest could
  not set one without amending a frozen field table. The deprecated identities are exactly the
  retired legacy wire strings that 11.2 moved into `aliases` — `gemini`, `webhook`, `direct`,
  `grok`, `midjourney`, `kie-ai` — and the catalog already ships them per provider. A test
  asserts each maps to its canonical id and that `GET /api/providers/storyboard/gemini` resolves
  to `gemini_ws`.
- **Adjustment recorded — the provider API became loopback-only.** It was not before: the editor
  blueprint's five handlers had no `is_loopback_remote` check while serving and mutating the
  credential store. This is stricter than the surface it replaces, matching the workflow
  blueprint's policy; a sub-tested case covers all thirteen routes.
- **Adjustment recorded — provider failures now use the §6 envelope.** The old handlers answered
  `{"error": "<string>"}`. Status codes are unchanged (400 unknown domain, 404 unknown provider),
  409 is added for an excluded provider, and the shipped `api` client already parses the envelope
  and falls back for anything else — so the observable change is a *better* message, not a break.
  Codes: `FORBIDDEN`, `INVALID_REQUEST`, `UNKNOWN_DOMAIN`, `PROVIDER_NOT_FOUND`,
  `PROVIDER_EXCLUDED`, `SETTINGS_INVALID`. Per §34.2 the §7 stable list gains nothing.
- **Adjustment recorded — `needsConfiguration` now derives from `availability`, not validation.**
  §21.5 names that conflation as the current bug source. A validation error and "a `requires` key
  is empty after env fallback" are different questions, and the selection response answers the
  second one directly.
- **Adjustment recorded — `PUT /api/settings/v2` is not server-side blocked from carrying a
  selection.** §24.2 says it "must no longer be used to change a selection", but a whole-document
  import legitimately contains one, and rejecting it would break reset/import. The client no
  longer uses it for selection; the server stays permissive.
- **Deferred as already assigned:** the `cache="settings"` invalidation on a selection change
  (§23.4) is 12.2's — today's `_VALUE_CACHE` is keyed by source alone and no source depends on
  settings yet, so there is nothing to invalidate; the option-source endpoint itself and
  `OptionSourceSpec` are 12.2 (D16/D17); the frontend catalog store keyed on `catalog_version` is
  12.1; the legacy `app-config.json` key read-through and deletion are 12.4 and 16.1 (D14).
- Both new guards were mutation-checked: forcing `_bind_runtime`'s already-bound branch off fails
  the exactly-once tests, and short-circuiting `_require_loopback` fails thirteen sub-tests.
- Verification passes with 545 backend tests (10 live-provider tests skipped, 198 subtests), 160
  frontend tests across 26 files, the Vite production build, and the generated-document drift
  check. `app.py` boots, registers all twenty provider/settings rules without collision, and
  logs exactly one runtime initialization for each of `gemini_ws` and `grok_automa`.

---

## Phase 12 — Generic provider UI and generic workflow nodes

### 12.1 Frontend provider catalog store
Add a shared Pinia/composable layer that fetches the unified catalog, caches by catalog version,
groups providers by domain, exposes health/availability/capabilities, and refreshes after provider
dev-reload events. Route all current provider selectors through this store; do not duplicate provider
lists in feature modules or static frontend data.

**Done when:** mocked catalog changes add/remove/relabel a provider everywhere without a frontend code
change; unavailable/deprecated/broken states render consistently; API errors use the standard envelope;
and Vitest covers cache invalidation, domain filtering, selection fallback, and reload behavior.

### 12.2 Metadata-driven selector and settings renderer
Evolve `ProviderSelector.vue`, `ProviderSettingsForm.vue`, and `ProviderSettingsModal.vue` into the
single UI for provider selection and configuration. Render all fields, conditional visibility,
descriptions, validation, secret-write behavior, capability badges, health actions, and provider URLs
from public metadata. Reuse `ConfigField.vue` primitives where possible so workflow and legacy forms
interpret the same settings contract.

Implement the parameterized option-source contract frozen in 10.2: extend `ASYNC_OPTION_SOURCES`,
`studio/workflows/options.py` `_RESOLVERS`, `GET /api/workflow/options/<source>`, and
`useOptionSources.js` so a resolver can receive validated context (domain + selected provider) and so
the shared module-level cache is keyed by source **and** context. Keep the existing module-level assert
and `test_workflow_options.py` allowlist/resolver-parity guards intact. Without this, no dropdown can
depend on the selected provider and 15.2 cannot deliver per-provider voices.

**Done when:** fixture schemas exercise every supported widget and conditional rule; a fixture
option source resolves differently for two providers and its cache invalidates when the selection
changes; unknown sources and unvalidated context are still rejected server-side; secrets are never
echoed; switching providers preserves each provider's unsaved non-secret draft independently; health
and validation feedback name the provider; and no provider ID appears in component control flow.

#### Step 12.2 review status — 2026-08-09

- **Complete.** `ASYNC_OPTION_SOURCES` is now the §23.1 dict of `OptionSourceSpec`
  (`registry.py:29-72`) with ten entries — the three new `*_providers` sources
  (`script`, `scene_blueprint`, `tts`) join the two that existed. Every consumer used
  `set(...)` or `in`, so the module-level parity assert and
  `test_workflow_options.test_resolver_table_matches_allowlist` survive untouched, as the
  contract predicted. A second assert checks every spec's cache policy.
- D16 is closed. `options.py` is rewritten around `OptionContext`: `build_context()` validates
  the query string against the source's own `context` tuple, rejects any other parameter,
  resolves `domain` through `DOMAINS`, normalizes `provider` through id-then-alias to the
  canonical id, checks `node_type` against the registry and `project_id` through
  `sanitize_project_id`, and fills an omitted `domain`/`provider` from the source's scope and
  the §24.1 selection chain — which is what keeps every existing context-free caller working.
  The response carries `{source, context, options, generated_at}`.
- D17 is closed: `OPTION_CONTEXT_INVALID` is added to the §7 list in `contracts.md`, exactly
  the additive change §23.3 authorizes.
- P32 is closed. `_provider_options` reads the domain off the spec, so one resolver serves all
  five `*_providers` sources and a sixth domain is a spec entry with no code. The old function
  branched on `storyboard` vs `animator` and could serve nothing else.
- The cache is the §23.4 replacement: keyed `(source, normalized_context)`, LRU-bounded at 64
  entries **per source**, `static` for process lifetime, `discovery` dropped by
  `hub.reload()` through the dev reloader, `settings` given a 300 s TTL **and** dropped for one
  domain by `PUT /api/providers/<d>/<p>/settings` and `PUT /api/providers/<d>/selection`.
  Failures are never cached, so an unreachable provider is retried rather than remembered as
  empty.
- **Adjustment recorded — `tts_voices` is per-provider from metadata, not from provider code.**
  §23 needs the source to answer differently per provider, but constructing a TTS provider to
  ask it can load an ONNX model, which a dropdown must never pay for. `_provider_voice_options`
  therefore reads the provider's own `settings_schema()` `voice.ui.options` — pure metadata,
  no `create()`, no network — and falls back to the local engine list when a provider declares
  none. Kokoro and Inworld already declare disjoint lists, so the shipped source is per-provider
  today and 15.2 inherits a working mechanism instead of building one. A new TTS provider gets
  its voices into the node dropdown by declaring them, with no edit here (§26).
- **Adjustment recorded — a scoped source rejects a foreign domain.** §23.1 lists `domain` in
  `tts_voices`'s context tuple; left literal, `tts_voices?domain=storyboard` would resolve and
  the client could cache and save the result. An explicit `domain` must now equal the spec's
  scope.
- **Defect found and fixed — save-time validation followed the global selection.** Wiring
  context in immediately broke 17 existing tests: a saved `tts.generate` with no explicit
  `engine` had its `voice` validated against whatever provider was globally selected, so
  switching the selection invalidated saved workflows — precisely what §24.1 rule 2 forbids.
  `config_option_context()` now resolves the node's provider field **including its schema
  default** (`provider_id`, then the legacy `provider`/`engine` of §40.1), and only a node type
  with no provider field at all defers to the selection.
- **Adjustment recorded — 12.2 implements the settings renderer that D18/§22.3 assign to 12.4.**
  The step text explicitly names `ProviderSettingsForm.vue` and "conditional visibility", and
  15.2 depends on `ui.options_source` reaching a real widget. `ProviderSettingsForm.vue` is
  rewritten to render the whole frozen §22.2 vocabulary — including `textarea` — plus
  `ui.show_if`, `ui.options`/`ui.options_source` (source wins), descriptions, per-field issues
  with severity, and required marks taken from `schema.required` rather than from "is a
  password", which the old form got wrong. 12.4 now only has to adopt the component on the
  legacy pages.
- **Adjustment recorded — an absent `ui.type` on a boolean renders a toggle.** §22.2's literal
  fallback is a text input, but a text input can only produce a string and
  `validate_against_schema` rejects that for a `boolean` property, so such a field could never
  hold a legal value. A property that declares options likewise renders as a dropdown without
  spelling `ui.type`.
- **Adjustment recorded — "reuse `ConfigField.vue` primitives" is honored as shared rules, not
  a shared widget.** The two schemas are different shapes (node `config_schema` vs the
  JSON-Schema subset) and ConfigField has no password/slider/toggle widget, so reusing it
  literally would have lost secret handling. Instead the two *rules* are now shared and cannot
  drift: `shared/schema/visibility.js` is the single AND-across-keys/OR-within-list
  implementation behind both `display_options` and `ui.show_if`, and
  `shared/composables/useOptionSources.js` (moved out of the workflow feature) is the single
  option-source client behind both. A test asserts the two spellings give the same answer.
- Secret write behavior is driven by the sentinel itself rather than a local "am I editing
  this" flag: a field holding `"***"` renders as *Saved — hidden* with a **Replace** action,
  and **Keep current** restores the sentinel. The two can therefore never disagree with what
  the server will do with the value, and a parent reset restores the masked display for free.
- Unsaved drafts live in the catalog store keyed by `(domain, provider_id)` and pass through
  `withoutSecrets()`, so switching providers to compare two configurations loses neither and a
  typed credential never outlives the modal. A test asserts a typed secret appears nowhere in
  the stored draft.
- **Defect found and fixed in the 12.1 modal.** Its `watch(() => props.visible)` was
  change-only, but `SettingsPage` guards the modal with `v-if` *and* passes `visible` already
  true — so the watcher never fired and the modal rendered against a null schema. It is now
  `immediate`. The draft watcher also recorded edits under the provider being switched *to*;
  it now takes the previous identity explicitly.
- The selector gained an explicit health probe (still zero I/O at rest, §21.5), capability
  badges, and provider-named status text; the modal gained capability badges, the manifest
  `description`, and `docs_url`/`open_url` links — all from `public_dict()`. Every health and
  validation message now names the provider, because three selectors share one page.
- P47 is closed early: the Settings About row compared the legacy selection key against the
  literals `inworld`/`kokoro`; it reads the catalog label now. A test walks every provider
  component and shared schema helper and fails on any shipped provider id, which is the
  automated form of the step's last acceptance criterion.
- Verification passes with 585 backend tests (10 live-provider tests skipped, 219 subtests),
  226 frontend tests across 31 files, the Vite production build, and generated-document drift
  checks. Two guards were mutation-checked: collapsing the cache key to the bare source and
  disabling the context allowlist each fail their tests.
- **Deferred as already assigned:** converting the five nodes to `provider_id` +
  `provider_options` and retiring the `engine` static list and `display_options.show.provider`
  gating (P26/P27, 12.3); adopting this selector/renderer on the legacy pages and retiring
  `useSettings.DEFAULTS` (P35, 12.4/16.1); live per-provider voice lists (15.2).

### 12.3 Provider-aware generic node configuration
Add a generic provider field/schema primitive keyed only by `provider_domain`. Convert the **five**
provider-backed nodes — `story.generate`, `scenes.blueprint`, `tts.generate`, `storyboard.generate`,
`animator.generate` — to the common persisted pair `provider_id` + `provider_options`; their node types,
ports, and executors remain stable. The inspector composes provider settings dynamically from the
catalog. Remove Grok-, Gemini-, WaveSpeed-, Kokoro-, and other provider-specific fields and
`display_options` from the node registry, moving them into provider settings schemas. Server
validation resolves the selected provider/schema authoritatively and fails open only for explicitly
documented unavailable-provider recovery cases.

`music.select` and `captions.generate` are **not** converted and must be left byte-identical: they are
local, single-implementation services with no provider dimension (owner decision — see the audit
header). Their `mode`/`tone`/`preset` fields are domain configuration, not provider selection, and must
not be mistaken for provider-specific fields during the registry cleanup.

**Bridging rule — this step runs ahead of the domain migrations.** Only `tts`, `storyboard`, and
`animator` have provider packages today; `script` and `scene_blueprint` get theirs in Phase 13.
Converting their nodes to `provider_id` + `provider_options` first would leave two nodes selecting from an
empty catalog. So each un-migrated domain must, in this step, register a single `builtin` provider that
is a thin passthrough to today's concrete service, with a manifest and a settings schema carrying
exactly the fields being removed from the node definition. Phase 13 then splits, renames, or extends
that `builtin` provider behind the interface it already satisfies. A domain's node is never converted
before its domain has at least one registered provider.

**Done when:** the five converted nodes contain no provider IDs or provider-specific settings in their
node definitions; every one of the five domains resolves at least one registered provider and the two
`builtin` passthroughs produce byte-identical artifacts to their pre-conversion services;
`music.select` and `captions.generate` are provably unchanged; each existing saved config migrates to
the new shape through the contracts §41.3 migrations (M1–M3 bump here; M4 uses a non-mutating
fallback); future-version/unavailable-provider workflows remain
safely inspectable; and pytest/Vitest prove provider-specific forms and validation are driven entirely
by catalog metadata.

### 12.4 Adopt the shared provider UI on legacy pages
Replace domain-specific provider dropdowns/settings forms in the TTS, Story/Script, Scene Blueprint,
Storyboard, and Animator legacy surfaces with the shared selector/renderer while
preserving each page's layout, request payload compatibility, defaults, and project hand-offs. Static
lists may remain only for non-provider concepts such as workflow styles, export profiles, caption
presets, and music tones. The Music and Captions pages keep their current forms untouched.

**Done when:** every listed legacy page selects and configures providers from the same catalog as the
workflow inspector; existing defaults and user settings load correctly; legacy requests still pass
their endpoint contract; and adding a fixture provider makes it selectable on both surfaces without
editing either surface.

#### Step 12.4 review status — 2026-08-09

- **Complete.** All five legacy surfaces now read their provider from
  `GET /api/providers` and configure it through the same modal the workflow inspector uses.
  The assembly is one component — `ProviderConfigurator.vue` (selector + modal + form) —
  because copying the Settings page's three-component wiring onto five pages is how five
  surfaces end up with four behaviors. `ProviderSelector.vue` gained a `variant` prop rather
  than a sibling component, so the compact page rows and the Settings row cannot drift.
- §24.3 rule 3 is implemented where it belongs, in the catalog store rather than per page:
  `selectedProvider()` falls back through the retired `app-config.json` key before the domain
  default, and `selectProvider()` mirrors the write back to it. The mirror matters more than
  the read — `usePipeline`, `useProviderTabs`, and `/api/pipeline/preflight` still read those
  keys and are owned by 14.x/16.1, so without it a selection made in the modal and a selection
  made on a page would diverge on the next write. A failed mirror never fails the selection.
- **Adjustment recorded — the catalog ships `legacy_selection_key` per domain.** The alternative
  was a three-entry `domain → key` map in JavaScript, which is the mapping §24.3 exists to
  delete; `DomainSpec` already holds it, and a settings *key name* is browser-safe by the same
  argument that makes `requires` safe (§25). 16.1 removes the field and every reader with it.
- **Adjustment recorded — the legacy wire spelling is `aliases[0]`.** §40.3's output column is
  not carried on the manifest, and `POST /api/storyboard/grab` still compares against it
  (P25). A manifest lists its retired identities in `aliases`, so the first one *is* that
  string; a pytest test asserts this reproduces the frozen table for all seven shipped
  providers, so a manifest that reorders its aliases fails rather than silently changing a
  request. Adding a field to the frozen §20.1 manifest was rejected as the larger change.
- Assets: the four-entry dropdown is gone. Two of its entries (`midjourney`, `meta-ai`) were
  not providers at all, and the `arguments` field they gated was dead — the route compares a
  `ProviderInstance` to the string `"midjourney"`, so it has always sent `""`. The Grok/Kie
  option blocks are now one `ProviderSettingsForm` over the selected provider's schema minus
  its secrets, and the page sends `provider_options` under the provider's own key names. The
  route reads them with the flat `grok_*` keys still winning, so an un-migrated client is
  unaffected — the one backend behavior change is additive.
- **Adjustment recorded — three literals moved into the provider packages they describe.**
  `grok_automa` declares `open_url` (the page the extension drives) and the `image_to_video`
  capability that replaces `provider === 'grok'` around the storyboard hand-off; `kie_ai`
  declares its model dropdown and an `output_format` field that had only ever existed as a page
  widget, defaulted to `png` to preserve today's value. The route half of the animator branches
  stays with 14.3.
- **Defect found and fixed while removing that URL table.** It existed in three places, and the
  third — `PipelinePage.handleRegenerateAssets` — indexed it by `assets.provider.value`, which
  the catalog makes a provider *object*. Left as it was, a regenerate would silently have
  stopped opening any page at all. All three now read `open_url`.
- Storyboard: the two-option `<select>` could not see `wavespeed_direct` at all, and its
  webhook URL, image model, and prompt prefix lived in `localStorage` behind blocks gated on
  provider ids. All three are provider settings now, with a one-time adoption of any value left
  in the old keys — keyed by *settings key*, so whose schema declares a field decides who owns
  it. The run guard is `availability !== available`, which is exactly "a required setting is
  empty" (§21.5) and covers providers this page has never heard of.
- **Adjustment recorded — `storyboard_image_models` is a new option source.** Moving
  `image_model` into `wavespeed_webhook` would have cost the priced model dropdown the page
  fetched itself; §22.4 says a provider's dynamic list belongs in `ui.options_source`, and 12.2
  built the machinery. The allowlist/resolver parity assert and its test are untouched.
- TTS, Story/Script, and Scene Blueprint gained a selector where they had none — the first two
  had no way to change a provider at all, and the TTS subtitle named an engine. Their request
  payloads are unchanged: all three resolve the provider server-side from the selection, which
  is now authoritative for them.
- **Deferred as already assigned:** the per-engine generation and voice-routing branches in
  `useTts.js` / `usePipelineForm.js` / `VoicePicker.vue` (P36–P39, 15.2); the animator and
  storyboard dispatch branches (P13–P16, P24, P25, 14.2/14.3); `useProviderTabs.js` and
  `usePipeline.js`, which still read the legacy keys the mirror now keeps correct (14.4/16.1);
  deleting the three keys from `useSettings.DEFAULTS` (P35, 16.1). A guard test lists the files
  that are now clean and states which two are deliberately absent and why.
- Verification passes with 601 backend tests (10 live-provider tests skipped, 239 subtests),
  266 frontend tests across 36 files, the Vite production build, and the generated-document
  drift check. Three guards were mutation-checked: dropping the legacy read-through, blanking
  `legacy_selection_key`, and disabling the per-run secret filter each fail their tests.

### 12.5 No-node-edit extensibility proof and phase gate
Create a test-only provider package for each execution shape needed by the platform (sync artifact,
sync document, async multi-asset). Discover it normally, expose it through the API/UI, configure it on
an existing generic node, execute it, and inspect its standardized result—without editing
`studio/workflows/registry.py`, any workflow adapter, or any Vue component for that provider.

**Done when:** an automated diff guard/test proves provider addition touches only its provider package
and tests; backend and frontend integration tests complete catalog→settings→node validation→execution;
all legacy and built-in workflow templates still validate; and the full Phase 12 test/build/manual UI
gate passes.

#### Step 12.5 review status — 2026-08-09

- **Complete.** Three test-only packages, one per execution shape, live under
  `tests/fixture_providers/<domain>/<id>/` — `script/fixture_document` (sync document),
  `tts/fixture_artifact` (sync artifact), `storyboard/fixture_async` (async multi-asset).
  They are registered by pointing a `DomainSpec.providers_base` at their folder, the
  mechanism §46.3 already established for `fixture_provider`, so they are found by the
  ordinary discovery scan and validated against their real domain's capability vocabulary
  while never entering the shipped catalog. `tests/test_provider_extensibility.py` drives
  all three through catalog → settings → selection → node validation → execution → §31
  result.
- **Defect found and fixed — 12.3 left the five converted nodes unconfigurable.** That step
  gave them `type: "provider"` and `type: "provider_options"` widgets and nothing rendered
  either: `ConfigField.vue` had no branch, so the inspector drew *"Unsupported field type:
  provider"* for `story.generate`, `tts.generate`, `scenes.blueprint`,
  `storyboard.generate`, and `animator.generate`. 12.5 cannot "configure it on an existing
  generic node" without closing that, so it is closed here. `provider` reuses the existing
  async-select path — a provider list *is* an allowlisted option source, so the change is
  one predicate — and `provider_options` renders the same `ProviderSettingsForm` the
  Settings page and the five legacy pages already use, over the schema of whichever
  provider the *node* selected. `NodeInspector` resolves that from the field declaring the
  `provider` widget, including its schema default, mirroring
  `options.configured_provider()`; a workflow saved before 12.3 therefore shows the options
  of the provider it will really run (§41.3 M4). Secret properties are stripped from the
  node sub-form: a credential there would be persisted into the workflow document, and
  `_validate_provider_options` already refuses it at save time.
- **Defect found and fixed — 12.4's Storyboard model dropdown was dead on arrival.**
  `ProviderSettingsForm` sends `{domain, provider}` to *every* `ui.options_source` it
  renders, because the browser cannot know which sources accept context, but
  `storyboard_image_models` shipped with an empty context tuple — so the request answered
  `OPTION_CONTEXT_INVALID` and the dropdown rendered empty in the shipped app. The tuple is
  widened to `("domain", "provider")` with a `settings` cache policy, and the invariant is
  now mechanical: `test_every_source_a_provider_schema_names_accepts_its_own_context` walks
  every shipped provider's schema and fails on any named source that would be rejected.
  12.4's `test_an_unknown_parameter_is_rejected_rather_than_ignored` was asserting the
  broken behavior and now uses a genuinely unsupported parameter.
- **Adjustment recorded — the diff guard is an invariant, not a `git diff`.** A diff test
  proves one commit; an invariant keeps proving it. Direction 1 walks `studio/`,
  `frontend/src/`, `docs/`, `app.py`, and `config.py` and fails if a fixture provider id
  appears anywhere outside `tests/`. Direction 2 is the backend counterpart of the
  12.2/12.4 frontend guards, which had no backend half: it compares the provider ids found
  in the eighteen §26 surfaces against a **frozen set**, so a new literal fails *and* so
  does a stale entry. Each remaining pair records what it is and who removes it —
  `domains.py` (§19.1) and `config_migrations.py` (§41.3) are the two legitimate homes, the
  rest is 14.2/14.3/16.1 debt. A third test is the substantive one: no provider-id
  *comparison* may appear in any surface except the two visual adapters and `app.py`, which
  are deliberately absent for the same reason `useTts.js` is absent from the 12.4 frontend
  guard.
- **Adjustment recorded — a node names a provider only through its domain default.** The
  literal claim "no provider id in a node definition" is false: `_provider_field`'s
  `default` *is* `DOMAINS[domain].default_provider`. The guard asserts the stronger true
  thing — every provider id in a materialized `config_schema` is that default, read from
  the catalog, and appears nowhere else in any field.
- **Deferred as already assigned — two of the three shapes execute through the runtime, not
  through their node.** `story.generate` dispatches generically (`adapters/story.py:34`),
  so the sync-document fixture runs end to end on a real, unmodified node: merged options,
  request-wins precedence, hidden-field exclusion, a managed relative artifact ref, no
  credential in the written artifact, and `PROVIDER_UNAVAILABLE` rather than a silent
  substitution. `tts.generate` and `storyboard.generate` still call `_step_tts` /
  `_step_storyboard`, which branch on provider id — the branches 15.2 and 14.2 own. Both
  shapes are proved through `boundary.invoke` and the §33 job contract instead, including
  the partial and cancelled paths, with `validate_egress` clean over every envelope.
  Pulling that dispatch forward would have emptied two later steps.
- The uninstalled-provider case is recorded rather than assumed: the `provider` field is a
  hard error (a saved value resolving to nothing has no safe execution), while
  `provider_options` fails open with no schema and the stored value is never rewritten, so
  reinstalling the provider restores the workflow untouched.
- Verification passes with 645 backend tests (10 live-provider tests skipped, 256
  subtests), 280 frontend tests across 37 files, the Vite production build, and the
  generated-document drift check. Four guards were mutation-checked: reverting the option
  context, disabling the `provider_options` widget, leaking a fixture id into
  `studio/providers/catalog.py`, and reintroducing `if selected == "kokoro"` in
  `adapters/tts.py` each fail their tests.
- **Re-verified 2026-08-09 (step gate):** full suite still green at the same counts —
  645 passed / 10 skipped / 256 subtests backend, 280 frontend tests across 37 files,
  `npm run build`, and `python -m studio.workflows.docs --check`. Phase 12 is closed.

---

## Phase 13 — Script, story, and scene-AI providers

### 13.1 Script provider interface and local random-template provider
Introduce the `script` domain contract for providers that produce the existing typed script/story
document. Move the random template catalog and anti-repeat/random selection rules behind a backend
`random_template` provider, preserving the current frontend random-story behavior through a thin API
consumer and retaining existing categories/text. Provider metadata owns its category/language/tone
options; deterministic seeding is available for tests.

**Done when:** the random-story UI and generic Story Generator node can request a template-produced
script from the same provider; current template content and anti-repeat behavior are preserved; the
result validates against the standard script result; and no frontend static provider catalog or
generation algorithm remains.

### 13.2 Current AI story generator as a script provider
Wrap `studio.story.service.generate_story`, its n8n/Gemini webhook behavior, parser, artifact writes,
and diversity history as a registered AI script provider. Move webhook/model/provider-specific fields
into its manifest/settings schema, translating the generic script request into the unchanged service
contract. Keep `studio.story` public functions and routes as compatibility facades during migration.
Claim the 12.3 `builtin` bridge ID as a permanent input alias for this provider; 13.3 upgrades only a
stored `selected_provider: "builtin"` to `"gemini"`, preserving any explicit `random_template`
selection.

**Done when:** fixture-backed AI generation returns the standard script result with the same story
text/sections/artifact/history behavior; provider failures are standardized and retryability is
correct; old `/api/story` callers receive their established envelope; and no workflow adapter imports
the concrete AI story service.

### 13.3 Generic Story Generator dispatch and compatibility migration
Change the `story.generate` adapter and legacy generation controller to resolve the selected `script`
provider through the hub. Map absent/legacy configuration to the historical AI default and map the
random-story action to `random_template`; preserve inherited Project Setup tone/style and current
artifact locations. Provider-specific output is forbidden beyond the standard metadata extension.
Also close the latent defect recorded in 10.1: `adapters/story.py:26` returns a `story` output that
`studio/workflows/registry.py:139` never declares. Per contracts §14.7 the payload is **not** dropped —
`_validate_outputs` only checks declared ports for presence, so `story` survives into `node_outputs`
and its artifact ref is recorded against a port that does not exist — but it is unreachable by any
consumer, because no edge may target an undeclared port and static expression validation rejects it
with `EXPRESSION_OUTPUT_MISSING`. Either declare the port or fold its artifacts into the declared
`script` output, and add the regression test. Replace the hardcoded `"provider": "gemini"` metadata in
`studio/story/service.py:102` with the resolved provider identity.

**Done when:** the same unchanged node runs both random-template and AI providers; legacy saved
workflows, requests, job-history reprocessing, and random-story UI actions still work; cache
fingerprints include provider ID/version and normalized options; and adding another script provider
requires no node/adapter/UI edit.

### 13.4 Scene Blueprint provider migration
Create the `scene_blueprint` provider interface and wrap the current
`studio.build_scene_blueprints`/n8n/OpenRouter path as its first provider. Standardize scene,
image-prompt, narrative-role, chapter, continuity, style, and sound-effect-validation outputs while
preserving `scenes.json`, existing routes, workflow ports, and the current style/tone inheritance.
Move webhook/model settings and health checks into provider metadata. Claim the 12.3 `builtin` bridge
ID as a permanent input alias and upgrade only the matching stored selection to `n8n` when the real
provider lands.

**Done when:** `scenes.blueprint` and the legacy scene-generation page dispatch only through the
registry; current fixture outputs remain schema-compatible; malformed AI responses become safe
provider errors; an alternate fixture provider runs without node edits; and the Phase 13 full
test/build plus mocked end-to-end Script→Scene Blueprint gate passes.

---

## Phase 14 — Storyboard and Animator provider migration

### 14.1 Shared asynchronous media-job service
Build one orchestration layer over the Phase 11 job contract for multi-scene submit, poll/callback,
progress, per-scene results, retry, cancellation, timeout, resume/reconciliation, and terminal
aggregation. It owns managed staging/promotion and execution events; providers own only remote/local
generation mechanics. Adapt the existing Storyboard and Animator job stores/manifests without
changing public job IDs or observable progress behavior.

**Done when:** deterministic tests cover all-success, partial-success, all-failed, delayed callback,
duplicate callback, restart reconciliation, cancellation, timeout, and retry; all-failed can never be
reported as success; and Storyboard/Animator can share the service without domain-specific branches.

### 14.2 Storyboard providers behind their interface
Bring `gemini_ws`, `wavespeed_direct`, and `wavespeed_webhook` fully behind `StoryboardProvider` and
Provider Contract v2. Move all provider-ID branching from `studio/storyboard/routes.py`, workflow
adapters, and WebSocket/runtime setup into provider implementations/capabilities. Normalize
storyboard paths, URLs, thumbnails, watermark handling, and per-scene metadata. Repair the audited
legacy-selection gap: bulk `/api/storyboard/generate` currently ignores its accepted `provider` field,
so normalize legacy `gemini` / `webhook` / `direct` values before generic dispatch while preserving the
field and envelope for old callers.

**Done when:** routes and `storyboard.generate` resolve/execute providers generically; the three
current IDs/defaults/settings and output artifacts remain compatible; unavailable browser-extension
and invalid-key states are isolated health/errors; and contract tests exercise every provider with
mocked transports.

### 14.3 Animator providers behind their interface
Bring `grok_automa` and `kie_ai` fully behind `AnimatorProvider` and Provider Contract v2. Move Kie
options, Grok typing/quality/duration behavior, browser-open/runtime logic, polling, downloads, and all
provider-ID branches from `animation_routes.py:191-211` and workflow adapters into provider packages.
Make the authoritative selected-provider store the fallback when neither a canonical override nor a
legacy request field is present; today the route comment promises that order but
`GrabberStartRequest.provider_id` defaults every such request directly to `grok_automa`.
Close the direct-import bypass at `animator/animation_routes.py:21`, which pulls `generate_image`
straight out of `.providers.kie_ai` without going through the registry. Note that both provider bodies
have never executed (see the Phase 10 audit header), so this step is their first real test.
Normalize video/image paths, thumbnails, durations, and per-scene failure metadata.

**Done when:** routes and `animator.generate` have no provider-ID branches; both current providers
preserve IDs, defaults, job/status APIs, Automa integration, artifacts, and legacy request mappings;
mocked contract tests pass; and a fixture Animator provider executes with no route/node/UI edit.

### 14.4 Extension, callback, and direct-API transport adapters
Extract reusable transport helpers for browser WebSocket/Automa extensions, n8n webhooks, direct HTTP
APIs, and provider callbacks into `providers_common` without coupling them to a domain. Providers opt
in through capabilities/runtime hooks; callback correlation is scoped by domain/provider/job/project,
idempotent, bounded, and redacted. Preserve existing external callback URLs as compatibility facades.

**Done when:** Storyboard and Animator providers use shared transports without sharing business logic;
cross-provider/job callbacks cannot contaminate results; replay/duplicate/oversized/unknown callbacks
are rejected safely; and old extension/Automa flows connect through their existing URLs.

### 14.5 Visual-provider compatibility and live gate
Run fixture-backed full workflow paths for every visual provider, then gated live checks for configured
providers. Compare job envelopes, progress events, `scenes.json` updates, managed artifacts, timeline
assembly, and cache fingerprints before/after migration. Document providers blocked by credentials or
human browser interaction without weakening deterministic gates.

**Done when:** Storyboard-only and Full Video templates complete through the generic dispatch path;
legacy Storyboard/Animator pages work; one configured direct provider completes live where credentials
permit; all compatibility diffs are resolved or explicitly approved; and Phase 14 tests/build/manual
smoke checks are green.

---

## Phase 15 — TTS provider migration

Music and Captions were removed from this phase by owner decision (2026-08-08): both are local,
single-implementation services with no provider dimension — music picks a file from
`resources/sounds/`, captions group words from the alignment output using local presets. They keep
their current nodes, adapters, services, APIs, and legacy pages unchanged. This phase is TTS only,
plus the integration gate that proves music and captions still work alongside the migrated providers.

### 15.1 Bring TTS providers onto Provider Contract v2
Adapt Kokoro and Inworld to the common manifest, settings, invocation, result, error, lifecycle, and
artifact contracts while retaining the domain-specific `TTSProvider` methods. Preserve Kokoro's
process-wide singleton/exclusive execution, voice blending/normalization/pronunciation behavior, and
Inworld cloud options. Replace duplicated metadata and settings paths with the shared registry data.

**Done when:** Kokoro and Inworld pass the generic contract suite plus TTS-specific voice/audio tests;
current provider IDs/settings and audio/metadata files are unchanged; exclusive execution is derived
from provider capability metadata; and secret/error redaction is proven.

### 15.2 Generic TTS dispatch and voice options
Refactor `studio/tts/routes.py` (which today never touches the registry and branches on
`provider == "inworld"` at lines 517, 629, and 902), pipeline services, and
`studio/workflows/adapters/tts.py` to call the selected provider through the registry rather than
branch on `kokoro`/`inworld` or `engine`. Drive voice/model lists, previews, capabilities, defaults, and
provider-specific options from provider metadata/endpoints via the parameterized option sources built
in 12.2. This fixes a live defect: the workflow `voice` dropdown always resolves Kokoro's `VOICES`
through `_tts_voices()` and never reacts to the selected `engine`, so Inworld voices
(`GET /api/tts/voices?provider=inworld`) are unreachable from the canvas. Also reconcile the
`job_meta` blocks, which differ between the Inworld and Kokoro branches today. Keep old `engine`,
`provider`, and TTS route shapes as compatibility inputs.

**Done when:** legacy TTS pages/API and the unchanged `tts.generate` node produce compatible artifacts
through both providers; saved `engine` configs migrate; the voice dropdown lists Inworld voices when
Inworld is selected and Kokoro voices when Kokoro is; both branches emit one reconciled result/metadata
shape; another fixture TTS provider appears and runs without node/UI edits; and mocked plus local
Kokoro tests pass.

### 15.3 Audio/text-output integration gate
Exercise Narration Only and Full Video templates plus the legacy TTS, Timeline, and Export pages
through the generic providers. Verify provider version/options affect cache fingerprints, standard
artifacts still assemble/export, and provider errors remain isolated to their node/run. Prove the
untouched Music and Captions nodes still execute and that their output is still accepted downstream —
they are the regression risk of this phase, not its subject. Run local Kokoro and FFmpeg media
assertions; keep cloud calls mocked unless the live flag is enabled.

**Done when:** old workflows run without edits, generated audio plus unchanged music/captions output is
accepted by existing assembly/export code, no route/adapter branches on a concrete TTS provider ID,
`music.select` and `captions.generate` remain unmodified and green, all deterministic suites and the
production build pass, and a playable fixture export proves end-to-end compatibility.

---

## Phase 16 — Plugin SDK, cleanup, and final gate

### 16.1 Remove concrete-provider knowledge from core code
Audit `app.py`, workflow registry/adapters, pipeline services, routes, shared UI, and generic provider
components for concrete provider IDs, imports, and option fields. Move legitimate mechanics into the
owning provider; retain only documented alias/default compatibility tables at one boundary — the two
legacy maps at `pipeline/services.py:550` and `:644` plus the `"gemini"`/`"grok"` alias branches in
`app.py:253-276` collapse into that single table. Retire the losing provider-selection store decided in
10.2 (`app-config.json` `sts-tts-provider` or `settings/settings.json`) so only one remains. Delete
superseded dispatch code after coverage proves the compatibility facade.

**Done when:** an allowlist-based test/scan finds no concrete provider IDs in generic nodes, generic UI,
workflow adapters, or shared dispatch; core code imports provider interfaces/hub only; compatibility
aliases live in one documented migration module; and all old routes/workflows/settings remain green.

### 16.2 Provider scaffolder and contract-test kit
`python -m studio.shared.providers_common.scaffold <domain> <provider_id>` and
`docs/provider-template/README.md` **already exist** — extend them rather than rebuilding them. Bring the
generator up to Provider Contract v2 (manifest v2 fields, settings schema, capabilities, lifecycle
hooks), make it emit generated contract tests, and widen it from the three hardcoded domains to the
domain catalog from 11.1. Supply reusable pytest suites/fakes for sync document/artifact and async
multi-asset providers; refuse unknown domains, invalid IDs, collisions, and unsafe paths without partial
files.

**Done when:** a new demo provider generated from the CLI is discovered, API-visible, UI-configurable,
and executable on its existing generic node with generated tests passing unchanged; removing the demo
leaves no central registration or node edit; and scaffolding failure is atomic.

### 16.3 Provider author guide and generated reference
Generate a provider reference from the live hub and write a guide covering scaffold→manifest→settings
→implementation→results/errors→artifacts→tests→health→ship. Include domain request/result tables,
capabilities, secret rules, compatibility/versioning, sync/async examples, and the explicit rule that a
provider may not modify nodes or generic UI. Integrate generation with the existing workflow docs
`--check` drift gate.

**Done when:** the provider catalog/reference is generated byte-for-byte from code; a developer can
rebuild the 16.2 demo using only the guide; docs checks fail on manifest/domain contract drift; and
README links the provider author guide and troubleshooting path.

#### Step 16.3 review status — 2026-08-09

- **Complete.** `studio/shared/providers_common/docs.py` generates `docs/providers.md` (live hub
  catalog + domain request/result/capability tables + error-code catalog) and
  `docs/provider-author-guide.md` (scaffold→ship path, extensibility rule, secret rules,
  sync/async examples, troubleshooting).
- Generation is wired into `python -m studio.workflows.docs` / `--check` alongside the workflow
  node docs; standalone `python -m studio.shared.providers_common.docs` remains available.
- README links the author guide, reference, and troubleshooting anchor; `docs/provider-template/`
  points at the generated guide. Drift covered by `tests/test_provider_docs.py`.
- Automated verification: provider + workflow docs suites and scaffold/contract-kit tests pass;
  `python -m studio.workflows.docs --check` is green.

### 16.4 Compatibility, failure-isolation, and security hardening
Build a matrix test covering every old provider ID/alias, saved settings format, node config version,
legacy API request, built-in template, and output artifact. Fuzz malformed manifests, schemas, results,
callbacks, provider exceptions, giant metadata, bad paths, secret values, and concurrent provider
reload/invocation. Verify one provider's import, health, execution, or shutdown failure cannot break
other providers or the Flask process.

**Done when:** compatibility fixtures load/run/migrate without user edits; secrets never appear in API,
SSE, logs, records, archives, or notifications; provider failures are bounded and attributable;
concurrent catalog reads remain consistent during reload; and all security regressions pass.

#### Step 16.4 review status — 2026-08-09

- **Complete.** Compatibility matrix (`tests/test_provider_compat_matrix.py`) covers every
  documented alias (§40.3), legacy selection/settings formats (§42), M1–M3 node migrations
  (+ M4 non-bump), §40.1 request fields, built-in templates, and frozen artifact roots (§44).
- Failure-isolation + security suite (`tests/test_provider_hardening.py`) fuzzes malformed
  manifests/results/callbacks, giant metadata, secret-bearing exceptions, concurrent reload
  reads, and isolation of import/health/create/execute/shutdown failures.
- Hardening: domain-aware selection-alias normalization (script `gemini` stays canonical);
  M1–M3 rewrite wire aliases to canonical ids; settings v2 normalizes stored selections;
  archive packaging re-redacts; notification channel errors and scheduler unhandled-exception
  logs use `sanitize_message`; health `details` and `HealthResult` objects are scrubbed.
- Automated verification: full backend suite green (`1068 passed, 12 skipped`).

### 16.5 Final provider-platform gate
Run the full deterministic backend/frontend/build/doc suite, the generic no-node-edit provider proof,
all built-in templates, legacy page/API smoke tests, and configured live providers. In the running app,
verify catalog-driven selection/settings/health for every domain and inspect execution diagnostics for
success, partial failure, retry, and unavailable provider cases. Record exact results and remaining
external credential/browser limitations.

**Done when:** Script, Scene Blueprint, TTS, Storyboard, and Animator all dispatch only
through registered providers; Music and Captions still run unchanged through their local services;
nodes and UI are provider-agnostic; adding a conforming provider requires
only its provider package/registration and tests; standardized results/errors are enforced; old
workflows/APIs/settings/artifacts remain compatible; docs are current; and every deterministic gate is
green before Phase 17 begins.

#### Step 16.5 review status — 2026-08-09

- **Complete.** Final provider-platform gate is green. The eight-point Definition of Done
  in `proposition-final.md` is machine-checked by `tests/test_provider_platform_gate.py`
  and re-verified by the full deterministic suites.

##### DoD checklist (recorded)

| # | Criterion | Evidence |
|---|---|---|
| 1 | Five AI domains dispatch only through registered providers; Music/Captions stay local | Hub lists exact shipped sets (`script`: gemini/random_template/scaffold_check; `scene_blueprint`: n8n; `tts`: kokoro/inworld; `storyboard`: gemini_ws/wavespeed_*; `animator`: grok_automa/kie_ai). Music/captions adapter blobs still pinned to step-3.2 hashes; neither imports `providers_common`. |
| 2 | Nodes/UI/adapters provider-agnostic (allowlist) | Platform gate + `test_provider_extensibility.ZeroTouchDiffTests` + `test_provider_cleanup`; five provider nodes use `type: provider` + domain default only. |
| 3 | Conforming provider = package + tests only | Fixture ids never leak outside `tests/`; committed `script/scaffold_check` demo is discovered and runs on the unmodified `story.generate` node (16.2). |
| 4 | Standard results/errors enforced | `ProviderError` → adapter bridge; every domain declares request/result models; result egress helper present. Covered deeper by runtime/hardening suites. |
| 5 | Old workflows/APIs/settings/artifacts compatible | All four built-in templates validate + schedule; aliases resolve; full matrix in `test_provider_compat_matrix.py`. |
| 6 | Catalog-driven selection/settings/health | `GET /api/providers` returns all five domains with `catalog_version`; per-provider settings + health 200 for every domain default. Frontend catalog/selector/legacy adoption suites green. |
| 7 | Broken provider degrades only | Missing-provider raises attributable error; scheduler run with forced provider failure finishes `failed`/`partial` (not silent success). Isolation fuzz remains in `test_provider_hardening.py`; success/partial/retry diagnostics in `test_workflow_scheduler.py`. |
| 8 | Docs current + drift-gated | `docs/providers.md` + `docs/provider-author-guide.md` present for all five domains; `python -m studio.workflows.docs --check` → OK. |

##### Automated verification (2026-08-09)

| Gate | Result |
|---|---|
| Backend `venv/Scripts/python.exe -m pytest tests/ -q` | **1088 passed, 12 skipped** (live marker), 470 subtests |
| Frontend `cd frontend && npm run test` | **280 passed** (37 files) |
| Frontend `cd frontend && npm run build` | **OK** → `static/dist/` |
| Docs `venv/Scripts/python.exe -m studio.workflows.docs --check` | **OK** (workflow + provider docs match live sources) |
| Live `tests/test_live_providers.py` without `STS_LIVE` | **10 skipped** (correct opt-in) |

##### Live / external limitations (unchanged; not blocking Phase 17)

| Provider | Status | Notes |
|---|---|---|
| Kokoro TTS (local) | Verified earlier (6.1) | Deterministic path green; keys not required |
| Inworld TTS | Credential present; not re-run live this gate | Cloud spend gated behind `STS_LIVE` |
| Scene blueprint n8n + OpenRouter | Hosted webhook retired; local n8n path previously verified | OpenRouter balance historically negative for paid models |
| WaveSpeed storyboard | Still blocked historically (HTTP 401) | Key present in env; set `STS_LIVE_STORYBOARD=1` after key replacement |
| gemini_ws / grok_automa | Not automatable | Need human-driven browser extension |
| Kie AI animator | Verified earlier (14.5 live) | Key present; re-run with `STS_LIVE=1` spends credits |
| FFmpeg export | Verified earlier | Local only |

Interactive in-app smoke of the Settings + five legacy pages was not re-driven in a browser this
session; catalog API + Vitest legacy/workflow provider adoption cover the same contracts
deterministically. Re-open the running app before Phase 17 UX work if a visual check is desired.

**Phase 16 is gated complete.** Next implementation step is 17.1 (desktop launcher).

---

## Phase 17 — Distribution & assistant

The app stops depending on a terminal and a memory of `python main.py`; a copilot drafts
workflows from prompts.

### 17.1 Desktop launcher
A single entry point that starts the backend, waits for health, opens the app window (browser
or lightweight shell), adds a tray icon with open/restart/quit, and handles port-in-use
gracefully.
**Done when:** double-clicking the launcher on a clean boot yields the running app with no console window, and quit from the tray stops the backend cleanly.

### 17.2 Versioned release build
A build script that produces a versioned, reproducible release folder/installer: frontend
production build, pinned dependencies, version stamp surfaced in the UI, and a changelog entry
gate.
**Done when:** one command emits a versioned artifact from a clean checkout, and the running app displays that version.

### 17.3 Backup & restore of all state
One command/UI action exports all workflows, settings, schedules, and (optionally) projects to
a single backup file; restore brings a fresh install to the same state. Builds on 9.4.
**Done when:** backup → fresh install → restore round-trips the full app state and every workflow validates afterward.

### 17.4 Workflow copilot
Prompt → draft workflow: an assistant panel that sends the registry (declarative node/port
contracts) plus the user's goal to a configured LLM, receives a workflow document, runs
authoritative validation, and only offers valid results for insertion — never silent apply.
**Done when:** a natural-language prompt yields a workflow that passes server validation and appears on the canvas only after explicit user acceptance; invalid generations surface their validation errors instead of applying.

---

## Step count & sequencing summary

| Phase | Steps | Parallelizable? |
|---|---|---|
| 0 — Audit & contracts | 0.1–0.4 (4) | 0.3 can run alongside 0.1/0.2 |
| 1 — Canvas & persistence MVP | 1.1–1.7 (7) | 1.2 alongside 1.1/1.3 |
| 2 — Config & validation | 2.1–2.5 (5) | sequential; 2.5 after 2.1 |
| 3 — Execution | 3.1–3.6 (6) | 3.1 must land alone; 3.3/3.4 parallel after 3.2 |
| 4 — Partial runs & resilience | 4.1–4.4 (4) | 4.3 parallel with 4.2 |
| 5 — Power UX & expressions | 5.1–5.5 (5) | 5.1–5.3 parallelizable |
| 6 — Hardening & production readiness | 6.1–6.6 (6) | 6.2/6.3/6.4 parallelizable; 6.1 first (may reveal new work); 6.5/6.6 last |
| 7 — Triggers & automation | 7.1–7.5 (5) | 7.1 (queue) must land first; 7.2/7.3/7.4 parallel after it |
| 8 — Node developer kit | 8.1–8.4 (4) | 8.2/8.3 parallel after 8.1; 8.4 last |
| 9 — Scale & asset lifecycle | 9.1–9.5 (5) | 9.1 must land alone (scheduler change); 9.3/9.4/9.5 parallelizable |
| 10 — Provider audit & contracts | 10.1–10.4 (4) | sequential contract gate; no production behavior changes |
| 11 — Shared provider platform | 11.1–11.5 (5) | 11.2/11.3 can follow 11.1; 11.4 before 11.5 |
| 12 — Generic provider UI/nodes | 12.1–12.5 (5) | 12.1/12.2 before node conversion; 12.5 is the extensibility gate |
| 13 — Script/story/scene AI | 13.1–13.4 (4) | 13.1/13.2 can parallel; 13.3 joins them; 13.4 independent after Phase 12 |
| 14 — Storyboard & Animator | 14.1–14.5 (5) | async service first; 14.2/14.3 parallel; compatibility gate last |
| 15 — TTS provider migration | 15.1–15.3 (3) | TTS steps sequential; integration gate last |
| 16 — SDK, cleanup & final gate | 16.1–16.5 (5) | cleanup after all migrations; docs/scaffolder can parallel; final gate last |
| 17 — Distribution & assistant | 17.1–17.4 (4) | 17.1/17.2 first; 17.3 builds on 9.4; 17.4 uses provider-driven AI |

86 steps total. Phases 0–9 are the delivered Workflow Builder foundation (51 steps, complete).
Phases 10–16 are the provider-platform migration and become the next work — 31 steps:
audit/contracts (10), shared runtime (11), generic UI and nodes (12), domain migrations (13–15),
then SDK/cleanup/final compatibility gate (16). The platform covers **five** domains: `script`,
`scene_blueprint`, `tts`, `storyboard`, `animator`. Music and Captions are deliberately excluded
(owner decision, 2026-08-08) because they are local single-implementation services with no provider
dimension; they keep their existing nodes and code, and the plan's job is to prove they still work.
Distribution moves to Phase 17 so releases and the Workflow Copilot build on the stable plugin
platform. The provider critical path is **10.1 → 10.2 → 10.3 → 10.4 → 11.1 → 11.3 → 11.4 →
11.5 → 12.1 → 12.2 → 12.3 → 12.5**, after which domain migrations can proceed in parallel before
16.1–16.5. Treat **11.4** (result/error boundary), **12.3** (saved node migration), and **14.1**
(async job reconciliation) with the most care: mistakes there can silently corrupt artifacts,
invalidate caches, or report failed provider work as successful.

Three risks are specific to this codebase and are easy to underestimate:

- **The existing provider interfaces have never run.** Phases 11/14/15 are first-time wiring, not a
  refactor of working code. Budget for the seven `provider.py` bodies being stale or wrong, and capture
  legacy-path fixtures *before* rewiring so there is something real to diff against.
- **12.2 gates 15.2.** Provider-dependent dropdowns are impossible until
  `GET /api/workflow/options/<source>` accepts context. If 12.2 ships without it, 15.2 cannot deliver
  per-provider voices and will either stall or smuggle a provider ID back into the UI.
- **12.3 converts two nodes whose domains have no providers yet.** The `builtin` passthrough rule in
  that step is what keeps the app working between Phase 12 and Phase 13; dropping it strands
  Script and Scene Blueprint on an empty catalog.
- **Music and Captions are out of scope and must stay that way.** Their `mode`/`tone`/`preset` fields
  look like provider selection but are not. An agent doing a thorough job on 12.3 or 16.1 will be
  tempted to "finish" them; every step that touches those two nodes must instead prove they are
  byte-identical.
