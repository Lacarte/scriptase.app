# Scriptase — Implementation Plan

Executable plan for the loop-engineering orchestrator. Authoritative spec:
[proposition-final.md](proposition-final.md). Frozen machine contracts:
[contracts.md](contracts.md). Visual and behavioural target:
[`../prototype/scriptase-prototype.html`](../prototype/scriptase-prototype.html) and its
README.

**Format is load-bearing.** `loop_engineering.py` parses `## Phase N — Title`,
`### N.M Title`, and a literal `**Done when:**` line per step, and detects progress from
commit subjects containing `step N.M`. Do not reformat headings.

**Core principle:** nodes are the execution model, steps are the user experience. One
node-based engine is authoritative; Production and Schema are projections of that same
graph, never a second engine.

**What came before.** Phases 0–16 of the previous plan are delivered in full — 70 steps
building the ported DAG engine, the provider platform with named instances, Channels, Jobs,
Scene Director, the Review and Repair correction loop, automation, the timeline editor,
bundled Chromium with its extensions, and the virality analyzer. That plan is archived at
[archive/implementation-plan-v1-delivered.md](archive/implementation-plan-v1-delivered.md)
and the contracts it froze remain authoritative. **This plan starts fresh at Phase 0** and
rebuilds the front end against the prototype.

**Step ids restart.** The repository already contains commits reading `step 0.1` through
`step 16.3` from the delivered plan. Progress detection is therefore scoped to the plan
epoch recorded in `runtime/state.json` — commits before it are ignored, so the reused ids
cannot mark this plan complete before it begins.

---

## Phase 0 — Adopt the prototype design system

`prototype/scriptase-prototype.html` is the visual and behavioural target. It defines a
complete "machined control-room" system — tinted ink elevation layers, a blue→violet duotone
accent used only on primary and active states, layered shadows with a top hairline so
surfaces read as lit, and spring easing. The app currently uses an unrelated token set
(`--bg-dark`, `--accent-primary`, …). Swap it wholesale: a half-themed app looks broken.

### 0.1 Port the token set and primitives

Replace `frontend/src/styles/theme.css` with the prototype's `:root` block — the ink scale
(`--bg`, `--bg-2`, `--panel`, `--panel-2`, `--raise`, `--line`, `--line-soft`, text ramp),
the duotone accent pair and `--accent-grad`, status colours (`--run`, `--ok`, `--fail`,
`--warn`, `--queue`, `--sched`) with their dim partners, `--panel-grad` and `--panel-grad2`,
`--hairline-top`, the three radii, `--shadow` / `--shadow-sm` / `--glow`, `--ease-spring`,
and the three font stacks. Keep the current names as deprecated aliases mapped onto the new
values so nothing goes unstyled mid-phase.

**Done when:** every prototype token exists in the theme, the production build succeeds, and no view renders with an unresolved custom property.

### 0.2 Restyle the shipped views onto the new system

Bring Production, Channels, Providers and the export library onto the new primitives: raised
panels use the panel gradient plus the top hairline, the duotone accent appears only on
primary and active states, and status badges use the status ramp. The Editor keeps its own
teal identity deliberately — it mirrors the ported ScriptToScene editor and is excluded from
this sweep.

**Done when:** no component references a deprecated alias, the four views match the prototype visually, and the Editor retains its distinct teal theme.

### 0.3 The UX floor

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

## Phase 1 — Information architecture and the Schema view

The prototype's nav is Script, Production, Schema, Library, Channels, Providers — ordered
create, run, monitor, output, configure. Schema is a read-only projection of the running job;
it never executes anything, which is the one rule the whole project hangs off.

### 1.1 The six-destination nav and routes

Rename the exports route to `/library`, add `/script` and `/schema`, promote provider
settings to a top-level `/providers`, and render the nav in the prototype's order with an
icon per item. Keep redirects from every previous path so existing links and the editor's
deep links survive.

**Done when:** all six destinations route correctly, the nav matches the prototype's order and labels, and every previous route redirects rather than returning a 404.

### 1.2 The Schema graph, projected from the engine

A read-only canvas rendering the workflow as nodes and edges on a virtual grid. Structure
comes from the backend node registry and the stage projection, never a hardcoded array in the
frontend. Drag to reposition and right-click to realign (auto-layout, snap to grid, reset,
fit and centre); two-finger scroll pans and pinch or Ctrl+wheel zooms anchored to the cursor.
Positions are cosmetic; structure is fixed.

**Done when:** the graph renders from the registry, all navigation and realign actions work, and no frontend file contains a hardcoded node or edge list.

### 1.3 Live animation and the node inspector

Each node reflects the running job: pending dim, active with a glow and live percent, done
green, failed red, and skipped dashed and struck through. Edges into the active node animate
with a flowing dash, and a pill shows job, stage and percent. Clicking a node opens a panel
with its input, output and error for the current job plus status and resolved provider.
Freeze view stops the canvas repainting and must never pause execution — pausing production
is the Production row's job.

**Done when:** a running job animates the graph live, the inspector stays in sync as stages advance, and Freeze view demonstrably leaves the job running.

### 1.4 Node actions in the inspector, including test with a provider override

Retiring the editable canvas would otherwise delete step 13.3's capability, so it moves here.
The inspector carries a Test action with input bindings and a one-shot provider-instance
override, reusing the existing test panel and the `provider_instance_id` parameter from 13.2.
Failures surface as the prototype specifies: the node glows red with an inline tooltip, a
panel lists node, stage, job, reason and error code with Locate node and Retry, and a topbar
badge counts errors across jobs.

**Done when:** any node can be tested from the inspector against a chosen instance without advancing the bound Job, and a failed node is locatable from the topbar badge in one click.

### 1.5 Retire the editable canvas

With Schema carrying projection, inspection and per-node testing, remove the editable canvas
route from the UI. The engine stays authoritative and workflows remain editable through the
API and templates, so this removes a surface rather than a capability. Delete the route and
its nav entry; leave the node registry, templates and every backend contract untouched.

**Done when:** the editable canvas route is gone, the Full Video template still loads and runs, and the backend workflow API and its tests are unchanged.

---

## Phase 2 — Channel becomes the format, not just the look

The prototype's inherit-with-override pattern: set the house style once on the Channel, and
let a single script or job diverge without changing it. Four field groups, each shipping its
`type_version` migration in the same step.

### 2.1 Script template

Add a script template to the Channel: a plain-language structure brief plus an ordered
section outline such as Hook, Turn, Why, Reframe, Landing. Seed every starter Channel with a
sensible template and ship a default for Channels that lack one.

**Done when:** a Channel round-trips its brief and ordered sections, existing Channels migrate to the default template, and the editor renders the sections as reorderable chips.

### 2.2 Visual style prompt and prompt composition

Add a visual style prompt to the Channel's visual direction. The per-scene image prompt
composes as scene subject plus channel visual style plus mood plus aspect — the script
decides what is in frame, the Channel decides how it looks. Compose in exactly one place,
consumed by both Scene Director and the image provider, and show a live example of the
composed prompt in the Channel editor.

**Done when:** two Channels produce visibly different composed prompts from the same scene subject, and the composition lives in a single module with no duplicated string building.

### 2.3 Narration processing

Add remove-silence and speed to the Channel's audio defaults, applied within the TTS stage as
parameters rather than as separate nodes. A script may override them, and the UI shows
"inherited" until changed. The active values appear as a compact badge on the Schema TTS
node.

**Done when:** a Channel's narration settings reach TTS, a per-script override wins over them, and the Schema TTS badge reflects whichever is active.

### 2.4 Music library, thumbnail and the watermark picker

Add a music folder with its track list, a channel thumbnail, and a logo with a nine-position
watermark picker. Uploads go through the existing managed-asset endpoint with type and size
validation — never a browser-supplied filesystem path.

**Done when:** a Channel stores a track list, thumbnail and positioned logo, and the export applies the watermark at the chosen position across 9:16, 16:9 and 1:1.

---

## Phase 3 — The Script studio

A new subsystem in which scripts are first-class artifacts owning their text and their
narration, so a Job built from one skips Script and TTS entirely.

### 3.1 Script model and store

Persist a script with id, title, body, channel, origin (auto, paste, idea or manual), created
date, word count, estimated duration, and a narration block carrying state (none, generating,
ready), voice, duration and an audio artifact reference. Reuse the artifact store from step
1.2 for the audio rather than introducing a second one.

**Done when:** a script round-trips through create, read, update, delete and list, and its narration audio resolves through the artifact store.

### 3.2 The studio surface

Browse and search the library, open and edit a script, and create one by Auto, Paste or
Topic to Idea. Auto and Idea follow the selected Channel's template from 2.1 and show a
preview naming the template with its section chips; pasted and hand-written scripts are left
untouched.

**Done when:** all three create modes work, generated scripts visibly follow the Channel's section outline, and Paste requires no script provider at all.

### 3.3 Narration in the studio

Generate and regenerate narration for a script with an inline player, a voice picker
defaulting to the Channel's voice, and per-script overrides of remove-silence and speed shown
as inherited until changed.

**Done when:** a script gains playable narration, regenerating supersedes the previous audio without erasing it, and an overridden value is visibly distinct from an inherited one.

### 3.4 The virality panel

Surface the Phase 16 deterministic scorer per script as an overall gauge plus the
per-dimension breakdown, run on demand and cached. Advisory only — it never blocks saving a
script.

**Done when:** scoring a script shows an overall grade with per-dimension detail, re-scoring identical text returns an identical result, and no cloud provider is required.

---

## Phase 4 — Production as a batch orchestrator

### 4.1 Batch job creation

Configure a job as Channel, then script source, then execution mode, and add many to a batch
before running. The script source accepts an existing studio script, and the flow supports
selecting several scripts to create one job each.

**Done when:** five selected scripts become five queued jobs in one flow, each carrying its own channel snapshot.

### 4.2 Serial drain with a first-class pause

The queue drains one job at a time, which step 13.1 already defaults to. Add Pause and Resume
as a real job state: a paused job holds its queue slot so nothing advances past it, and
resumes from the same stage rather than restarting. Model pause in the engine, not as a
stop-then-recreate.

**Done when:** pausing the running job stops the queue advancing, resuming continues from the same stage with prior artifacts intact, and a paused job survives a process restart.

### 4.3 Jobs reuse a script's narration

When a job's source is a studio script with ready narration, Script and TTS are skipped: the
stage projection reports them as skipped for that job, and Schema renders them dashed and
struck through. The audio comes from the script's artifact instead of being regenerated.

**Done when:** a job built from a narrated script runs without invoking any script or TTS provider, and both stages report as skipped in Production and Schema.

### 4.4 The forty-eight hour archive calendar

Recent jobs show as full rows or cards; anything older packs into a date strip that expands
on click and remains searchable by name. One component serves both Production and the
Library.

**Done when:** a single component drives both views, older items collapse into the date strip, and search finds a collapsed item without expanding it first.

### 4.5 Failure handling and advisories

A failure is scoped to one job and never stops the batch — the queue keeps draining. The row
shows a red bar, a failed badge, the failing stage, and an error banner with the stage rail.
Offer Retry, Retry Failed, Duplicate and Remove. Retry must invoke the Phase 8 Repair Router
to repair the smallest responsible scope, not restart from stage zero as the prototype
simplifies. Add the language-mismatch advisory when a script's language differs from its
Channel's.

**Done when:** one job failing leaves the rest draining, Retry repairs the failed scope rather than restarting, and a language mismatch warns before the job runs.

---

## Phase 5 — Library and Providers

### 5.1 The Library gallery

Every finished video as a searchable gallery, filterable by channel, with per-item Editor and
Export actions, reusing the calendar from 4.4. A Library button on a finished Production row
deep-links to that video.

**Done when:** a finished job deep-links from Production into the Library, and filtering by channel and searching by name both work.

### 5.2 Providers page with a simulate console

One provider per capability with connection status, configuration, Test connection, and a
Simulate request console showing a per-kind dummy request and response round-trip for API,
extension and n8n providers. Keys stay masked and are never returned by any response.

**Done when:** each provider kind simulates a round-trip without touching a real endpoint, and a redaction test proves no response carries a credential.

### 5.3 Restrict the catalogue to the prototype's provider set

The prototype ships exactly one provider per capability: **Inworld** for voice (API key),
**Grok** for video and **Gemini** for image (both browser-extension transports), **n8n** for
Scene Director, and the **deterministic** scorer for virality. Everything else the port
carried over — Kokoro, both WaveSpeed image providers, Kie for video, and the random-template
script provider — is removed from the user-facing catalogue so a Channel cannot be configured
against a provider the product does not support.

Removal means unregistering from the domain catalogue, not deleting the platform's test
fixtures: the `scaffold_check` packages exist to prove the scaffolder and the
no-node-edit extensibility gate still work, and the contract-test fixtures under
`tests/fixture_providers/` must keep loading. Migrate any Channel or settings document
pointing at a retired provider onto its capability's remaining one, in the same step.

Note the consequence, which is deliberate: **Kokoro was the only credential-free path**, so
after this step narration requires a working Inworld key and there is no offline TTS.

**Done when:** the catalogue exposes exactly the five prototype providers, a Channel referencing a retired provider migrates without manual editing, and the provider extensibility and scaffolder tests stay green.

---

## Phase 6 — Prototype fidelity pass

Phase 0 ported the prototype's `:root` tokens and restyled the shipped views onto
them. It did not port the component styling: the prototype carries **1,101 class
rules** across `prototype/scriptase-prototype.html`, and the app re-invented that
layer instead of reproducing it. The result reads as a different product wearing
the same palette — same colours, different spacing, structure and density.

### The method — brain and skin

Steps 6.1–6.8 ported CSS onto markup the app had already invented, and it did not
converge. Every mismatch found by eye was **structural, not stylistic**: the
archive strip was built as `archive-day-*` rather than `cal-*`, the topbar tail
was simply absent, the node icon is a rounded square because the app wrote its
own element. No amount of restyling reaches a different DOM.

So the direction flips. **Lift the prototype's templates and CSS into Vue, and
mount them on the composables that already exist.** Markup and CSS first, binding
second. Fidelity then holds by construction — the classes match because they are
the same elements — instead of being chased screenshot by screenshot.

What each side owns is not negotiable:

| Keep — the brain (this repo) | Take — the skin (the prototype) |
|---|---|
| `useProductionStages`, the job APIs, SSE | rail and batch-sheet markup |
| the Schema graph, live layer and inspector | `sch-*` topbar, canvas chrome, legend |
| Channel, provider and script clients | their rails and cards |
| contracts, tests, the fidelity gate | tokens, motion, empty states |

Four rules bind every remaining step:

1. **No second frontend.** The Vue app and the Flask backend stay. The prototype
   is a template source, never a starting point.
2. **One view at a time**, markup and CSS first, then bind the composables that
   already serve that view.
3. **Tuck the surfaces that fight the layout.** The workflow and run pickers,
   cost panels and step detail are power-user chrome the prototype was drawn
   without; they are hidden or moved, not left to break the composition.
4. **Never port prototype JS that *runs* anything — only what *shows* it.** Its
   `pumpQueue()`, its hardcoded `STAGES` and its retry-from-zero are precisely
   the second execution engine this project forbids. They are a drawing of an
   engine, not one.

Rule 4 is the one that carries real risk. The prototype makes **zero network
calls** — 43 top-level data literals, 178 `getElementById`, 65 `innerHTML`
assignments and no `fetch`. Everything it appears to do is mimed. Porting any of
that behaviour would reintroduce the hardcoded step array the whole architecture
exists to prevent.

The Editor stays outside all of this: it keeps its own teal identity (`ed-*`, 103
rules), mirroring the ported ScriptToScene editor.

The gate in step 6.8 measures progress. It carries a ledger of every prototype
class the app does not have, split into BEHAVIOUR (the app deliberately lacks it)
and UNPORTED (debt), and it asserts the unported count — so a step cannot be
called done while its classes are still excused.

### 6.1 Shared primitives

Port the cross-cutting families every view depends on: `topnav`, `btn`, `badge`,
`seg`, `stat`, `toast`, `welcome`, and the `si-*` status-indicator set — roughly
135 rules. These come first because every later step composes them, and because
divergence here is what makes the whole app read as off.

**Done when:** every shared class in the prototype resolves in the app with matching declarations, and the six nav destinations render with the prototype's spacing, weight and active treatment.

### 6.2 Production

Port `job-*` (65 rules) and `srstage-*` (18) — the job row, its expanded detail,
the stage rail, status bars and counters. The row must keep its backend-projected
stage list; only presentation changes.

**Done when:** a job row, its expanded detail and the stage rail match the prototype's layout and density, and the stage list still comes from the backend projection.

### 6.3 Script studio

Port `s1-*` (151 rules) — the largest family. The library rail, script editor,
create flow with its template preview chips, the narration panel with its player,
and the virality gauge with per-dimension bars.

Verified gap before starting: **none of the 57 `s1-*` classes exist in the app**,
and the library **filter chips are missing entirely** — the prototype's
`ALL · n` / `TTS READY · n` / `SCRIPT ONLY · n` (`s1-fchip`) have no counterpart,
so the library cannot be filtered by narration state. That is a functional gap,
not a styling one: build the control, do not just style a missing element. The
narration panel and virality panel do exist in code but are unreachable: they
render only when a script is selected, and the library is empty. Two further
gaps confirmed by reading the template rather than grepping for keywords — the
header-level **Check Virality** button does not exist anywhere in `frontend/src`,
and the virality action is labelled **Analyze script** and shown only in the
not-yet-run state. Port the labels and placement, not just the styling.

**Done when:** the studio's three columns, filter chips, template chips, narration panel and virality gauge match the prototype, filtering by narration state works, and the channel template preview still reads from the selected Channel.

### 6.4 Channels

Port `ch-*` (128 rules) — the channel list and the editor's field groups:
identity, look and voice, script template with its section outline, narration
processing, music, thumbnail, and the nine-position watermark picker.

**Done when:** the Channels list and editor match the prototype, including the 3x3 watermark picker, and every field still round-trips through the Channel API.

### 6.5 Providers

Port `pv-*` (97 rules) — the capability rail, the provider detail header with its
connection state, the capability chip set, and the simulate console's
request/response panes.

**Done when:** the Providers page matches the prototype, and the simulate console still contacts no real endpoint while keeping secrets masked.

### 6.6 Schema

Port `sch-*` (91 rules) — node cards by role, the status treatments (pending,
active, done, failed, skipped), animated edges, the status pill, the node
inspector and the error panel.

**Done when:** node states and edge animation match the prototype, and the graph still renders from the registry with no hardcoded node list.

### 6.7 Library

Port `lib-*` (32) and `exp-*` (39) — the gallery cards with hover preview, the
detail and pipeline-timing panels, the search and filter row, and the stats bar.

**Done when:** the Library gallery matches the prototype, and the 48-hour calendar it shares with Production still collapses older items.

### 6.8 Fidelity gate

A test that fails when the app drifts from the prototype: extract the class
families from `prototype/scriptase-prototype.html` and assert every one the app
claims to implement is present. Cheap to run, and it turns "looks different" from
a judgement call into a check.

**Done when:** the gate passes, and deleting a ported rule from the app makes it fail.

### 6.9 Production rail and batch sheet

*Delivered.* The first step done by the method above: the prototype's two-column
run-sheet lifted whole — config rail (Channel → Script source → Execution → Add
to Batch) beside a batch sheet carrying totals, search, the channel filter, the
Run / Stop / Retry / Clear / Cancel controls and the job list — mounted on the
existing job APIs and `useProductionStages`. Three families left the ledger:
`rail-*` with its inheritance chips and step numbers, the finder row, and batch
selection. Unported debt fell 59 → 35.

**Done when:** the Production page is the prototype's run-sheet, stages still come from the backend projection, and the gate's unported count is 35.

### 6.10 Strip the chrome that fights the skin

Rule 3, applied to what is left over. The prototype was drawn without a workflow
picker, a run picker, a second stage list beneath the batch, or the advisory
banners the app grew — and those are what make a ported view still read wrong.

Remove the workflow and run `<select>`s from the Schema topbar and the Workflow
field from the job rail, with the state and fetches that exist only to feed them.
The graph resolves its workflow without a picker and follows the newest running
job; `?job=`, `?run=` and `?workflow=` stay as the way a specific run is
addressed. Nothing here may hardcode a workflow id to compensate.

Then audit the remaining views for the same shape of leftover: panels stacked
where the prototype has one composition.

**Done when:** the Schema topbar carries only what the prototype's `.sch-topbar` carries, no workflow id is hardcoded anywhere in the frontend, and route-query addressing still reaches a specific run.

### 6.11 Script studio (S1) — template-first

The first view built the new way from the start. Lift the prototype's `s1-*`
markup — the library rail, the document header and title input, the create flow
with its template preview chips, the narration panel with its transport, and the
virality gauge — then bind the script clients and Channel template preview that
already exist.

The narration player family (`play-btn`, `played`, `track`, `tick`, `wave`,
`audio`, `caption`, `subtitle`) leaves the ledger here. Its transport controls a
real audio element over a real narration artifact; nothing about playback may be
mimed the way the prototype mimes it.

**Done when:** the studio matches the prototype's three columns and its narration panel plays a real artifact, the template preview still reads from the selected Channel, and the gate's unported count drops by eight.

### 6.12 Channels — template-first

Same method. Lift the `ch-*` editor: identity, look and voice, script template
with its section outline, narration processing, music, thumbnail, and the
nine-position watermark picker. Bind the Channel API that already serves them.

The media families (`r-16-9`, `r-1-1`, `wm`, `thumb`) leave the ledger here —
aspect ratio and watermark are Channel fields, so they bind rather than being
drawn. `ch-sw`/`ch-swatches` and the platform chips stay excused: `ChannelProfile`
has no `color` and no `platforms`.

**Done when:** the Channels editor matches the prototype including the 3×3 watermark picker, every field round-trips through the Channel API, and the gate's unported count drops by four.

### 6.13 Shared chrome — calendar, modal, shortcuts sheet

The three families that belong to no single view. The archive calendar is the
clearest case of the old method's failure: the app built `archive-day-*` instead
of porting `cal-*`, so it has never been restylable. Lift `cal-cells` / `cal-cell`
with its `open` state and the `cal-wd` / `cal-day` / `cal-mo` / `cal-count` /
`cal-dot` internals onto `shared/components/ArchiveCalendar.vue`, which both
Production and the Library render. Then the modal and shortcuts-sheet chrome:
`modal`, `modal-head`, `modal-foot`, `keys-modal`, `keys-grid`, `kbd`, `krow`.

**Done when:** the 48-hour strip is the prototype's, both views still collapse older items, the shortcuts sheet matches, and the gate's unported count drops by fourteen.

### 6.14 Run states and the language banner — ledger to zero

The tail. `st-draft`, `st-preparing`, `st-stopping`, `st-stopped`, `is-live` and
`scenetag` must map onto the Job statuses the backend actually emits — `queued`,
`running`, `paused`, `awaiting_approval`, `completed`, `failed`, `cancelled` —
rather than introducing a seventh vocabulary in the frontend. Where a prototype
state has no backend equivalent, its ledger entry moves from UNPORTED to
BEHAVIOUR with the reason, which is an honest outcome and not a failure. Then
`lang-banner` with `lang-badge` and `lang-actions`, and `drag-over`.

**Done when:** every prototype run state either renders from a real Job status or is recorded as behaviour with its reason, and the gate's unported count reaches zero.

---

## Phase 7 — Functional gaps surfaced by the fidelity pass

Phase 6 is presentational by definition. Where comparing against the prototype
reveals a control that was never built rather than built differently, it belongs
here — styling an absent element would hide the problem.

### 7.1 Restore a script provider so Auto and Idea work

Step 5.3 set the `script` domain's catalogue to the empty set, because the
prototype's Providers page lists one provider per capability and names none for
script. The consequence was not thought through: **two of the studio's three
create modes are dead.** Auto and Topic → Idea both need a script provider, so
only Paste functions, and the studio cannot originate a script at all — it can
only ingest text written elsewhere.

Decide where script generation belongs and wire it: either the n8n instance that
already serves Scene Director also serves `script`, or the domain gets its own
catalogue entry. Whichever is chosen, Paste and Manual must keep working with no
provider configured, per the reference document's §6.

**Done when:** Auto and Topic → Idea both produce a script end to end, Paste still needs no provider, and the Providers page shows whatever now serves the script capability.

---

## Step count and sequencing

| Phase | Steps | Notes |
|---|---|---|
| 0 — Prototype design system | 0.1–0.3 (3) | 0.1 first; 0.2 depends on it. |
| 1 — IA and the Schema view | 1.1–1.5 (5) | **1.4 before 1.5** — it rescues per-node testing before the canvas goes. |
| 2 — Channel as format | 2.1–2.4 (4) | Each ships its own `type_version` migration. 2.1 gates 3.2. |
| 3 — Script studio | 3.1–3.4 (4) | 3.1 before the rest; needs 2.1 and 2.3. |
| 4 — Batch orchestrator | 4.1–4.5 (5) | 4.2 and 4.3 are engine changes. 4.3 needs 3.1. |
| 5 — Library and Providers | 5.1–5.3 (3) | 5.1 reuses 4.4's calendar. 5.3 retires non-prototype providers. |
| **6 — Prototype fidelity pass** | 6.1–6.8 (8) | **6.1 first** — every later step composes the shared primitives. |
| **7 — Functional gaps** | 7.1 (1) | Surfaced by Phase 6; 7.1 unblocks two of the studio's three create modes. |

**33 steps across 8 phases.** Phases 0–5 are delivered; Phase 6 is the fidelity pass and Phase 7 collects the functional gaps it surfaces.

Critical path: **0.1 → 1.1 → 1.2 → 1.3 → 1.4 → 1.5**, then
**2.1 → 2.3 → 3.1 → 3.2 → 3.3 → 4.1 → 4.2 → 4.3**. Phase 5 is independent of that chain
once 4.4 exists.

Treat these three with the most care:

- **1.5** (retire the editable canvas) — only safe after 1.4 moves per-node testing with a
  provider override into the Schema inspector. Landing 1.5 first deletes a capability.
- **4.2** (pause as a first-class job state) — an engine change. A paused job holds its
  queue slot and resumes from the same stage; modelling it as stop-then-recreate loses
  artifacts and lets the queue jump ahead.
- **4.3** (skipped stages) — the stage projection must report Script and TTS as skipped when
  a job reuses a script's narration, or Production and Schema will disagree with the engine.

Three constraints carried forward from the delivered plan:

- **`type_version` migrations are unforgiving.** The runner refuses to skip a hop and marks
  future-version documents read-only. Every node or channel schema change in Phases 1–2
  ships its migration in the same step.
- **The prototype simplifies two behaviours the real app must not.** Its Retry restarts from
  stage 0 where 4.5 must invoke the Repair Router on the smallest responsible scope, and its
  Freeze view must never be able to pause execution — the canvas is a projection.
- **Secrets stay write-only.** Never returned by an API, and never present in a Job
  snapshot, execution record, SSE event, log, export, or the Providers simulate console.
