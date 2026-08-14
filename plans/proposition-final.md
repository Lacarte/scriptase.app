# Scriptase — Authoritative Specification

Companion to [implementation-plan.md](implementation-plan.md) (the executable phase/step
breakdown) and [contracts.md](contracts.md) (frozen machine contracts). Product reference:
`Scriptase_Architecture_Development_Reference.docx`, cited as §N.

Where this document and the code disagree, resolve in favour of working behaviour and
record the adjustment here.

---

## Objective

Scriptase is a channel-aware, provider-driven, local-first AI video production system. It is
the evolution of ScriptToScene Studio V2 (**V2**, at
`D:\@Workspace\@Development\@Scripts\@Python\ScriptToScene-Studio-V2`) into a product that
is **simple when making one video, powerful when developing a provider, and autonomous when
running a content factory** — without duplicating execution logic for any of the three (§24).

A user creates a Job from a Channel and presses Run. A developer opens any node and tests it
in isolation. An automated Job detects a bad artifact, repairs only the responsible stage,
re-reviews it, and continues. All three use the same node definitions, provider modules,
artifacts, and execution history.

---

## The central architectural decision

> **Nodes are the execution model. Steps are the user experience.**

| Layer | Decision | Reason |
|---|---|---|
| Execution engine | Node-based DAG | Dependency scheduling, partial execution, retries, caching, branches, provider testing |
| Everyday production UI | Step/window | Keeps normal creation simple and understandable |
| Advanced UI | Workflow graph | Custom routing, debugging, branching, provider development |
| Source of truth | Backend node definitions | Prevents the two views from diverging |

**Non-negotiable (§3):** the Production view and the Workflow view operate on the same
workflow, node registry, execution records, artifacts, and provider configuration. They are
two views of one system, not two implementations. **Do not build a second step-based
execution engine.**

The mechanism that enforces this, rather than merely asserting it: the ordered step list is
**projected from the graph on the backend** (step 2.2). A hardcoded step array in the
frontend would silently diverge the first time a branch is added.

---

## Domain vocabulary

| Term | Meaning |
|---|---|
| **Channel** | Reusable identity and production rules for a content brand. Lives *above* Jobs; not a processing node. |
| **Job** | One video-production run using a Channel and a Workflow. An orchestration context, not a media node. |
| **Workflow** | The executable graph describing how a Job is produced. |
| **Node** | One independently executable processing unit with typed inputs and outputs. |
| **Provider** | A swappable implementation used by provider-capable nodes. |
| **Provider instance** | A named, configured binding of a provider type (e.g. "WaveSpeed Main" vs "WaveSpeed Backup"). |
| **Artifact** | A typed, versioned, content-addressed output owned by a Job and usually a Scene. |
| **Review** | Quality analysis producing structured issues. |
| **Repair Router** | Orchestration that sends each issue back to the node responsible for fixing it. |

Default production path: Script → Voice → Timing → Segmentation → Scene Direction → Image →
Video → Review → Compose → Export. Underneath, captions, music, branding, and quality gates
execute in parallel where dependencies allow.

---

## Locked design decisions (§19)

1. One execution engine only; the node-based workflow engine is authoritative.
2. Production steps are a UI projection of the workflow, not separate logic.
3. Channel is a reusable profile above Jobs, not a processing node.
4. Job is an execution context and orchestrator, not a normal media node.
5. Scene Director is the explicit script/segment-to-visual-scene transformation stage.
6. Provider capability is metadata and contract behaviour, not part of the visible node name.
   **`-P` never appears in a stage or node name.**
7. Providers support multiple configured instances and future fallback chains.
8. Correction is Review → structured issue → Repair Router → responsible node, never one
   magical Corrector.
9. Quality gates run as early as possible, so expensive downstream generation never starts
   from a bad input.
10. Every node is independently testable when its required inputs can be supplied.
11. Automatic Jobs require retry and repair budgets and escalation limits.
12. Video nodes must not assume every provider requires an image; routing is capability-based.

**Added for Scriptase, beyond the reference document:**

13. Artifacts are typed, immutable, and versioned. A repair never erases the evidence of
    what it replaced.
14. Scene identity is stable across re-segmentation. Ordinal position is presentation data.
15. Provenance records generation reproducibility (provider instance, seed, request id,
    model revision), because snapshotting configuration is not reproducibility with
    generative providers.
16. Human checkpoints are a durable engine state that releases the worker, not a blocked
    thread.
17. Budget is enforced pre-flight, not reported post-hoc.

---

## Starting conditions (verified in code)

V2 completed 82 steps across its Phases 0–16. The following are facts about the codebase
Scriptase ports from, not assumptions:

- `studio/workflows/` is a ~10,300-line DAG engine with content-addressed caching,
  artifact-integrity re-hashing, staged→promoted artifacts, an SSE resume protocol,
  whitelist-only expressions, and `type_version` migrations. 25 dedicated test modules.
- `studio/shared/providers_common/` is a ~11,300-line provider plugin platform with
  discovery, exclusion-as-data, guarded hot reload, a 16-code error taxonomy with
  **platform-owned** retryability, a versioned result envelope, and a strong secret-redaction
  pipeline. 18 dedicated test modules.
- Every media module already has a thin `(inputs, config, context) -> outputs` adapter.
- **The provider ABC layer is dead code.** `TTSProvider.synthesize`, the storyboard and
  animator `submit`/`poll`, and all seven `get_provider()` factories have zero call sites.
- **Business logic lives inside Flask blueprints** in `timing` (the Whisper aligner) and
  `captions` (caption grouping and presets), and the scene-blueprint service imports three
  functions from its own routes module.
- **A second, complete orchestrator exists** in `studio/pipeline/routes.py` (1,351 lines),
  fully superseded by the workflow engine.
- **Provider selection is stored twice** (`settings/settings.json` and `app-config.json`).
- **Artifacts are not typed.** `artifact_refs: list[str]` is a naming convention. No
  `Artifact` object, no versioning.
- **Scenes are array indices.** No stable identity.
- **There is no cost model**, no pause state, no global concurrency cap, and no startup
  reconciliation of interrupted runs.
- One provider identity does four jobs at once: folder name = manifest id = catalog key =
  settings key = wire value, and the catalog builder rejects duplicates — so multiple named
  instances are impossible without a new identity axis.

---

## Port ledger

The contract for Phase 0. "Lift verbatim" means copy with tests and rename mechanically;
it does not mean rewrite.

### Lift verbatim

| Source | Why |
|---|---|
| `workflows/cache.py` | Content-addressed fingerprints, artifact-integrity re-hashing, cascade invalidation. The strongest component in V2. |
| `workflows/scheduler.py` | `build_graph`, `deterministic_order`, `calculate_scope`, conditional edge activation, the attempt/backoff loop, `ProjectLock`, `ArtifactPromoter`. |
| `workflows/registry.py` | Frozen port-type vocabulary, capabilities, config-schema widgets, JSON node definitions, internal-field stripping. |
| `workflows/validation.py` | Authoritative document validation with structured problems. |
| `workflows/expressions.py` | Parse-only, whitelist-only, ancestry- and scope-checked. |
| `workflows/events.py` | SSE ring buffer, reset snapshot, `Last-Event-ID` resume. |
| `workflows/redaction.py` | Applied at every persistence boundary. Keep the code and the discipline. |
| `workflows/migrations.py`, `config_migrations.py` | Hop-by-hop `type_version` migration; future versions go read-only. |
| `scheduled_runs.py`, `watch_folders.py`, `webhook_triggers.py` | Cursor-advance-before-enqueue and claim-before-enqueue are already correct. |
| `asset_gc.py`, `project_archive.py` | Symlink refusal, re-validation before delete, zip-bomb guards. |
| `shared/providers_common/` (all) | Discovery, hot reload, error taxonomy, invocation, boundary, media jobs, redaction, scaffold, contract tests, docs. |
| `io_utils.py`, `security.py` | Windows-aware atomic write with backup recovery; managed-path joins. |
| `frontend/features/workflow/`, `features/providers/`, `shared/` | Vue Flow canvas, dagre layout, registry-driven inspector, provider catalog store, and 31 Vitest files. |

### Rebuild on the way in

| Subsystem | Problem | Fix |
|---|---|---|
| `timing` | Aligner, validation, and repair heuristics live inside the Flask blueprint; the pipeline step imports from routes. | Extract to `timing/service.py`. |
| `captions` | Caption grouping and presets live in routes behind private names (~282 lines). | Extract to `service.py` and `presets.py`. |
| scene blueprints | Service imports three functions from its own routes module. | Move them into the service layer. |
| `editor/routes.py` | 2,821 lines mixing settings, SFX, discovery, assemble, archive, fonts, overlays, logging, export. | Split into separate blueprints. `VideoProcessor` keeps its boundary. |
| `export` adapter | Emits an absolute path into a port payload, violating the rule the TTS adapter enforces. | Audit every adapter for path leakage. |
| storage listing | Executions, queue, and notifications are listed by scanning and parsing every file. | Indexed storage behind the same interfaces (10.2). |

### Leave behind

`studio/pipeline/routes.py` (duplicate orchestrator) · the 5,819-line legacy step wizard and
per-step pages · the dead provider ABC layer · `app-config.json` as a live store ·
`providers_common/http_client.py` (retries non-idempotent methods; the idempotency-aware
transport wins).

---

## Repository layout

```
SCRIPTASE.app/
├── app.py                     Flask entry, blueprints, provider init
├── config.py                  paths and environment
├── plans/                     proposition-final.md, implementation-plan.md, contracts.md
├── scriptase/
│   ├── engine/                ← V2 studio/workflows (+ adapters/)
│   ├── providers/             ← V2 studio/shared/providers_common + provider routes
│   ├── artifacts/             NEW  Artifact model, content-addressed store, versioning
│   ├── channels/              NEW  ChannelProfile model, store, routes, preset migration
│   ├── jobs/                  NEW  Job model, store, orchestration, stage projection
│   ├── review/                NEW  validators, ReviewIssue, Repair Router, policy
│   ├── modules/
│   │   ├── script/            ← story          image/    ← storyboard
│   │   ├── tts/                                video/    ← animator
│   │   ├── timing/            (service extracted)
│   │   ├── segmenter/         (algorithm relocated)
│   │   ├── scene_director/    ← build_scene_blueprints
│   │   ├── captions/          (service + presets extracted)
│   │   ├── music/
│   │   └── compose/           ← editor (routes split)
│   └── shared/                io_utils, security, validation helpers
├── frontend/src/features/
│   ├── production/            NEW  step/window Production view
│   ├── channels/              NEW  Channel Profile editor
│   ├── workflow/              ← ported Vue Flow builder
│   └── providers/             ← ported catalog and schema-driven forms
├── tests/  bin/  resources/  models/  output/
└── develop/loop-engineering/  the orchestrator that runs implementation-plan.md
```

Package renames are a Phase 0 mechanical pass: `studio`→`scriptase`, `story`→`script`,
`build_scene_blueprints`→`scene_director`, `storyboard`→`image`, `animator`→`video`.
Provider **domain ids** rename with them — domains are data, which is exactly the change the
domain catalogue was designed to absorb. An alias map preserves imported V2 settings. The
`output/` layout stays V2-compatible so the Phase 10 import works.

---

## What must be preserved

- Every provider id, alias, default, and saved settings file that V2 import depends on.
- Node type keys, port ids, and port types — the graph contract must survive the port.
- Saved workflows upgrade through `type_version` migrations and run without manual edits.
- Existing artifact and output paths, so V2 projects import cleanly.
- The registry-driven frontend property: adding a node type means editing the registry or
  dropping in a JSON definition, never editing a Vue component.

---

## Security rules

Non-negotiable, inherited from V2 and extended:

- **Secrets are write-only.** Never echoed by an API, and never present in workflow JSON,
  Job snapshots, execution records, SSE events, logs, errors, archives, notifications, or
  exported templates. Environment fallbacks may be *used* but never *returned*.
- Channel snapshots capture provider **instance references**, never credentials (§4.3).
- Provider metadata sent to the browser is an explicit allowlist — no callables, no absolute
  paths, no resolved credentials.
- No port payload contains an absolute filesystem path; managed relative references only.
- Never trust a browser-supplied filesystem path. Uploads go through managed endpoints with
  type and size validation.
- Workflow and provider API routes stay loopback-only; they describe and mutate the
  credential store.
- Callback correlation is scoped, idempotent, bounded, and redacted.

---

## Definition of done

Scriptase is complete when:

1. A Channel can be created, versioned, and reused, and a Job snapshots it without copying a
   single credential.
2. The Production view and the Workflow view render the same execution from the same records,
   with the step list derived from the graph.
3. Every provider-capable stage dispatches through registered provider **instances**, with
   capability-based candidate selection and policy-driven fallback.
4. Any node can be tested in isolation against artifacts from any Job.
5. Scene Director produces a structured SceneSpec from structured Channel visual direction,
   with no prompt text outside provider packages.
6. Review returns only structured issues; the Repair Router repairs the smallest responsible
   scope and re-reviews.
7. Quality gates catch a bad image before any video generation call is made.
8. An Automatic Job runs end-to-end unattended with bounded retries, repairs, budgets, and
   escalation; an Assisted Job pauses durably at its checkpoints.
9. Artifacts are typed, versioned, and immutable, and scene identity survives
   re-segmentation.
10. A crash mid-run leaves no permanently-running execution, no stale lock, and no orphaned
    staging directory.
11. Adding a provider means creating and registering its package alone — proven by a test
    that fails if any other file changes.
12. All verification suites are green and generated docs show no drift.

---

## Verification

**Bare `python` and `pytest` are not on PATH. Always use the venv interpreter.**

```bash
venv/Scripts/python.exe -m pytest tests/ -q                  # backend, from repo root
cd frontend && npm run test                                  # vitest
cd frontend && npm run build                                 # writes ../static/dist
venv/Scripts/python.exe -m scriptase.engine.docs --check     # node-doc drift gate
venv/Scripts/python.exe -m scriptase.providers.docs --check  # provider-doc drift gate
```

All must be green before any commit. Tests touching real providers stay behind
`@pytest.mark.live` (`STS_LIVE=1`) — the WaveSpeed key returns 401, the hosted n8n webhook is
retired, OpenRouter's balance is negative, and one video provider needs a human driving a
browser.

### End-to-end acceptance

1. Create a Channel from a seeded niche preset; enable a logo; set a structured visual
   pattern.
2. Create a Job from that Channel with Idea → Script, execution mode **Automatic**.
3. Press Run once. The Production view walks Script through Export with no further input.
4. Open the Workflow view mid-run — the same execution, the same node states, live.
5. Open any node and test it in isolation against an artifact from a *previous* Job.
6. Force a bad scene image. Confirm the image gate catches it **before** any video call, the
   Repair Router regenerates only that scene, the prior version is preserved and marked
   superseded, re-review passes, and the Job continues.
7. Re-run the segmenter with different parameters and confirm no open issue or artifact is
   left bound to a scene that no longer exists.
8. Export. Confirm the logo overlay survives 9:16, 16:9, and 1:1 profiles.
9. Grep every persisted record, SSE frame, log, and export for credentials. Zero hits.

---

## Scope guardrails

- Do not build a second step-based execution engine.
- Do not store provider-specific fields in generic node models when a provider schema can
  own them.
- Do not let Review return free-form text; automation depends on structured issues.
- Do not let the Repair Router regenerate broadly; repair the smallest responsible scope.
- Do not regenerate every scene because one scene fails.
- Do not make expensive AI review the only validation layer; deterministic checks run first.
- Do not make automatic repair loops unlimited.
- Do not force every Channel to use the same Workflow.
- **Music and Captions stay out of the provider platform.** They are local,
  single-implementation services with no provider dimension; their mode, tone, and preset
  fields look like provider selection and are not. The requirement on them is no regression,
  not migration.
- Providers own generation mechanics only. Orchestration, staging, promotion, and execution
  events belong to the shared runtime.
- A provider may never modify a node definition, adapter, route, or generic UI component.
