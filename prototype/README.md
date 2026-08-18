# Scriptase — UI/UX Prototype

A single, self-contained HTML file — [`scriptase-prototype.html`](scriptase-prototype.html)
— that is a **clickable UI/UX reference** for the Scriptase front end. Open it directly in
a browser (no server, no build, no npm). Everything is simulated in vanilla JS with dummy
data; there are **no real provider, backend, or filesystem calls**.

Its job is to make the intended experience concrete *before* it is wired to the real
node engine, so the implementation phases in
[`plans/implementation-plan.md`](../plans/implementation-plan.md) have a visual target to
build against. It is a **projection reference, not an engine** — consistent with the one
rule the whole project hangs off:

> **Nodes are the execution model. Steps are the user experience.** One node-based engine
> is authoritative; the Production view (and the Schema view here) is a *projection* of
> that graph, never a second engine.

---

## What's in it

Six top-nav destinations plus one full-screen **Editor** mode, all driven from one shared
in-memory data model (channels, S1 scripts, jobs, providers). The top nav is ordered by the
workflow — **create → run → monitor → output → configure** — with an icon per item:

> **Script · Production · Schema · Library · Channels · Providers**

| View | What it demonstrates |
|---|---|
| **Script** | The Script Studio & Library (the "S1" subsystem): browse/search saved scripts, edit, create (Auto / Paste / Topic→Idea), generate/regenerate **Inworld TTS** with a player, and a **virality checker** with a per-dimension score. Auto/Idea generation **follows the selected channel's script template**; narration processing (remove-silence, speed) is inherited from the channel and **overridable per script**. |
| **Production** | The orchestrator: configure a job (Channel → Script source → Execution), add many to a batch, run a **serial (one-at-a-time) queue** that drains automatically, per-job controls (**Pause/Resume**, Stop, Cancel), status badges, expandable detail with a **stage-rail**, a row **Library** button that deep-links the finished video into the Library view, search/filter, a **48h archive calendar**, and a **language-mismatch advisory**. |
| **Schema** | A **read-only node-graph** of the whole workflow that **animates live** as a job runs — see the [Schema view](#schema-view--the-live-workflow-canvas) section below. |
| **Library** | Gallery of every finished video, searchable, filter by channel, per-item Editor/Export. Uses the **same 48h archive calendar** as Production — recent videos show as cards; older ones pack into a date strip you click to expand (still searchable by name). |
| **Channels** | The source of truth every job inherits. Identity (name/color/platforms/language); **look & voice** (image style, **visual style prompt**, tone, mood, captions, branding, voice); a **script template** (structure brief + editable section outline); **narration processing** (remove-silence + speed); **music folder + tracks**; **thumbnail**; and **logo with a 9-position watermark picker**. Edits propagate live into Production/Script. |
| **Providers** | One provider per capability — Voice=Inworld (API), Video=Grok (extension), Image=Gemini (extension), Scene Director & Virality (n8n/deterministic). Connection status, config, **Test connection**, and a **Simulate request** console showing a per-kind dummy request→response round-trip. |
| **Editor** (full-screen mode) | A faithful visual replica of the ScriptToScene-Studio CapCut-style editor: media tabs, preview with aspect + watermark, properties, and a multi-track timeline. Opened per finished job (or from Library). |

> Note on naming: the UI nav says **Script**, but "S1" is still used internally and in a
> couple of subtitles as the name of the script studio/library subsystem.

### The stage model the prototype assumes

`S1 Script → TTS → Alignment → Segment → Scene Director → Storyboard → Animator → Assembly → Export`,
with three **branch** operations that run alongside: **Script Analyzer** (virality, after
the script exists), **Background Music** (after the script/channel), and **Caption
Generator** (after segmentation). Each branch is anchored to the stage it runs after
(`branchAfter`), so it lights up at the right moment rather than only at the end. Channel
config and Execution mode are resolved at job creation — represented by the `Channel` and
`Execution` entry nodes in the Schema view — and are **not** pipeline stages.

---

## Channels drive generation (inherit-with-override)

A channel is a **format**, not just a look. Everything a job needs is inherited from its
channel, and the two generative stages are shaped by channel settings:

- **Script text** — each channel carries a **script template**: a plain-language *structure
  brief* plus an ordered *section outline* (Hook → Turn → Why → …). When S1 generates a
  script (Auto or Idea→Script), it follows that template — the create flow shows a "Using
  *&lt;channel&gt;*'s template" preview with the section chips. Pasted/existing scripts are
  left as-is.
- **Image prompt** — each channel carries a **visual style prompt**. The per-scene image
  prompt is composed as `<scene subject> + <channel visual style> + <mood> + <aspect>`, so
  the *script* decides **what's** in frame and the *channel* decides **how it looks**. The
  channel editor shows a live example of the composed prompt; the same composition appears in
  the Storyboard node inspector and the Gemini Simulate console.
- **Narration** — voice, plus **remove-silence** and **speed** processing, are channel
  defaults; a single script can override them in S1's narration panel (shown as
  "inherited" until you change it). The active values appear as a compact badge on the
  Schema **TTS** node — they're parameters of the TTS stage, not separate nodes.

This is the same **inherit-with-override** pattern throughout: set the house style once on
the channel; a single job or script can diverge without changing the channel.

---

## Schema view — the live workflow canvas

The Schema view is the clearest demonstration of the "projection, not engine" rule: it is a
**read-only** node-graph that never runs anything itself — it just reflects the state of the
currently-running job.

- **Live animation** — each node shows the running job's state: **pending** (dim),
  **active** (blue glow + live %), **done** (green ✓), **failed** (red ✕), **skipped**
  (dashed + struck-through, e.g. Script/TTS when a job reuses existing narration). Edges
  into the active node animate with a flowing dash. A top-right pill shows the live
  "`Jxxx · Stage · %`" status.
- **Node inspector** — click any node to open a side panel with its **Input**, **Output**,
  and **Error** for the current job (JSON-shaped dummy data), plus status/provider. It stays
  in sync as the job advances.
- **Navigation** — **drag** nodes to reposition; **two-finger trackpad scroll pans**
  (pinch / `Ctrl`+wheel zooms, anchored to the cursor); **right-click** opens a menu to
  realign (Auto-align layout, Snap to grid, Reset positions, Fit & center). A **Freeze view**
  button freezes the *canvas animation* (resume catches up to current state) — it deliberately
  does **not** pause the jobs, because the canvas is a read-only projection. To actually pause
  production, use the job row's **Pause** in the Production view. All read-only navigation —
  positions are cosmetic, structure is fixed.
- **Error surfacing** — when a node fails, the schema shows **which node and why**: the node
  glows red with an inline tooltip, a bottom-right **error panel** lists Node / Stage / Job
  / reason / error-code with **Locate node** and **Retry** actions, and a topbar **"N
  errors"** badge lets you jump to a failed job even while another is running.

## What happens when a job errors

A single failure never stops the batch — it is scoped to the one job. Concretely:

- The job's timer is cleared and its status becomes **`failed`**, recording `failStage`
  (the exact stage that broke), `err` (human reason), and `errCode` (machine code); its
  progress freezes where it died.
- The **serial queue keeps draining** — `pumpQueue()` pulls the next queued job into the
  freed slot immediately.
- It surfaces consistently in every view: the **Production** row (red bar, FAILED badge,
  "Failed · <stage>", Failed counter) and its expanded **error banner + stage-rail**; the
  **Schema** node/inspector/error-panel/badge described above.
- Recovery: **Retry** (re-queues that job), **Retry Failed** (re-queues all failed jobs),
  **Duplicate**, or **Remove**.

> Prototype simplification: **Retry restarts the job from stage 0** and does not resume
> from the failed stage or reuse already-produced artifacts. The real app's **Repair
> Router (Phase 8)** is meant to repair the smallest responsible scope instead — this is the
> main behaviour to upgrade when wiring the real engine.

---

## How this maps to the implementation plan

The prototype does **not** add a phase. It is UI acceptance criteria for phases that
already exist in [`plans/implementation-plan.md`](../plans/implementation-plan.md). When a
plan step lands, the corresponding prototype surface is the look-and-behaviour target.
Format note: plan steps are `### N.M Title` with a `**Done when:**` line — cross-reference
by step id below.

| Prototype surface | Plan phase / steps | Notes for implementation |
|---|---|---|
| Production list, job cards, stage-rail, status badges | **Phase 2 — Production view** (2.1–2.x) | The Production view is the backend-computed **projection** of the node graph. Do not hardcode a step array in the frontend; render from the stage projection the engine emits. |
| Channel config + inheritance into jobs | **Phase 1 — Artifacts, Channel, Job** (1.1 ChannelProfile, 1.3 store/routes) | Channel snapshots capture provider **instance references**, never credentials. |
| Channel **script template** (brief + section outline) → S1 generation | **Phase 1** (channel field) + **S1 / script.generate** | The template is the generator's structure brief. Auto/Idea follow it; paste/existing are untouched. Inherit-with-override. |
| Channel **visual style prompt** → composed image prompt | **Phase 1** (channel field) + **Phase 5 Scene Director** + **Phase 6 Image (Gemini)** | Prompt = `subject (Scene Director) + channel visual style + mood + aspect`. Keep the composition in one place; the channel supplies look, the scene supplies subject. |
| Channel **narration processing** (remove-silence, speed) + per-script override | **Phase 1** (channel field) + **S1 owns TTS** | Applied within the TTS stage — a parameter, not a node. Overridable per script in S1. |
| Providers page (capability → provider, status, config, Test, **Simulate**) | **Phase 3 — Provider instances, capabilities, secret references** | Secrets are write-only: never returned in any response. Loopback-only routes. The prototype's masked-key + "never returned" copy is the required behaviour. |
| Provider **kinds** (API / extension / n8n) & the Simulate console | **Phase 3** + **Phase 15 — Bundled Chromium and the extensions** (15.2 port the four extensions, 15.4 ai-web-auto) | Grok/Gemini are **browser-extension** providers over the automation socket; Inworld is API-key; Scene Director/Virality are n8n webhooks. |
| Scene Director node & naming | **Phase 5 — Scene Director** and **11.5 Rename Scene Blueprint to Scene Director** | The prototype already uses "Scene Director" everywhere; keep the rename consistent. |
| Image vs Video split (Gemini image / Grok video) | **Phase 6 — Image and video split with capability routing** | Storyboard=image (Gemini), Animator=video (Grok); capability is metadata, never in a stage name (`-P` never appears in a node/stage name). |
| Language-mismatch advisory; failed-job error banner; Schema error panel/inspector; Retry / Retry-Failed | **Phase 7 — Review** and **Phase 8 — Repair Router** | Review returns **structured issues only**, never free text. Repair the smallest responsible scope; keep evidence of what was replaced. The prototype's Retry restarts from stage 0 — **Phase 8 should repair the failed node/scope instead**. |
| Execution modes (Queue / Run Now / Scheduled / Auto); unattended drain | **Phase 9 — Automation** | Scheduled/Auto map to trigger + automation config. |
| Schema canvas (read-only node graph, live animation, drag, realign, inspector, errors) | **Phase 12 — Simplify the canvas and make providers usable** (12.1 node visibility, 12.2 Full Video default canvas, 12.3 provider selector on nodes) | The Schema view is the **read-only projection**; the *editable* canvas is Phase 12's authoritative graph. Reuse the node-state → status mapping. |
| Serial one-at-a-time queue; per-job **Pause/Resume**; per-node test with provider override | **Phase 13 — Serial queue and real node testing** (13.1 queue, 13.2 provider override, 13.3 test a node from the canvas) | The prototype's `MAX_CONCURRENT = 1` drain is the intended default. A paused job **holds its slot** (the queue must not advance past it) and resumes from the same stage — model pause as a first-class job state, not a stop+restart. |
| Editor mode + Library gallery + Export panel | **Phase 14 — Video editor and export library** (14.2 timeline editor, 14.3 export library, 14.4 own windows) | The Editor mode mirrors the ported ScriptToScene-Studio editor; Library = the export library. |
| Script virality checker (per-dimension score) & the **Script Analyzer** schema node | **Phase 16 — Script virality analyzer** (16.1 deterministic scoring, 16.2 the `script.analyze` node, 16.3 script-stage panel + Review integration) | The analyzer is an **advisory** branch (deterministic + optional n8n), not a blocking pipeline stage — which is why in the Schema view it runs right after the script exists (via `branchAfter: 'script'`), then completes. |

### Suggested implementation order (front-end wiring against the prototype)

Once the engine phases land, wire the real UI to match the prototype in this order — each
already has a plan home, so this is a checklist, not new scope:

1. **Production view** as the graph projection (P2) — the batch list, cards, and stage-rail.
2. **Channels** (P1) and **Providers** (P3) — the inheritance + provider-instance surfaces.
3. **Serial queue** (P13.1) and execution modes (P9).
4. **Canvas** (P12) — promote the read-only Schema projection into the editable graph;
   reuse the node-state colour/animation mapping.
5. **Editor + Library** (P14) and **Script virality** (P16).
6. **Review / Repair** advisories (P7/P8) surfaced on jobs and on canvas nodes — and upgrade
   Retry to **repair the failed scope** rather than restart from stage 0.

---

## Non-negotiables the prototype already honours (carry them into the real UI)

- **Secrets are write-only** — the Providers page shows masked keys and states the key is
  never returned. Keep that in the real transport.
- **Capability is metadata** — `-P` / provider names never appear in a stage or node name;
  the prototype labels nodes by capability (Storyboard, Animator) with the provider as a
  sub-label only.
- **One engine, projected** — the Schema and Production views read job/stage state; they
  never run their own pipeline. The real app must keep the single authoritative node engine
  and project from it.
- **Structured review, smallest-scope repair** — errors surface as structured, located
  issues (which node, why, error code), not free text; repair targets the failing node.

---

## UX & quality floor

Carry these into the real UI — they're the baseline, not extras:

- **Premium theme** — a "machined control-room" dark theme: tinted-ink elevation layers,
  a blue→violet duotone accent used only on primary/active, layered shadows with a top
  hairline (surfaces read as *lit*), and spring micro-interactions. Cohesive across every
  view. The Editor mode deliberately keeps its own teal identity (it mirrors the real
  ScriptToScene-Studio editor). A **theme-shuffle** button in the top bar re-tints the
  signature accent to a random duotone (right-click to reset); it touches only the accent
  tokens, leaving the neutral ink and status colours (ok/fail/warn) intact so the UI stays
  legible. It's a demo affordance for exploring palettes, not a persisted user setting.
- **Pause a job vs. freeze the canvas** — two distinct controls that are easy to conflate:
  the Production row's **Pause/Resume** genuinely halts a job at its current stage (progress
  held, its queue slot **kept** so nothing jumps ahead) and resumes from the same point; the
  Schema **Freeze view** only stops repainting the diagram. Never let a canvas control halt
  execution — the canvas is a projection.
- **Welcome screen** — an animated first-run overlay (gradient/grid, floating studio icons,
  gradient-text wordmark) with a one-paragraph description of what Scriptase does and an
  **Enter Studio** button. Auto-skipped on deep-links / `?skipwelcome`.
- **Accessibility** — visible `:focus-visible` rings on all controls, `prefers-reduced-motion`
  honored (pulses/flows/spinners disabled), nav `role="tablist"` + `aria-current`,
  `aria-label`s on icon-only buttons, and `aria-live` toasts.
- **Keyboard** — `↑/↓` move through the job list, `Enter` expands, `Space` selects, `E`
  opens the editor, `R` runs the batch, `/` focuses search, `?` opens a shortcuts sheet,
  `Esc` closes. A `?` button in the top bar surfaces the same sheet.
- **Responsive** — below ~820px the top nav collapses to a hamburger and job rows reflow
  (title on line 1, stage/status/actions on line 2). No horizontal overflow on mobile.
- **Undo** — destructive actions (Remove, Clear Completed, Remove selected) show a 5s **Undo**
  toast that restores exact state, rather than blocking behind a confirm dialog.

---

## Running & conventions

- **Open:** double-click `scriptase-prototype.html`, or serve the folder statically.
- **Demo URL hooks** (for screenshots/deep-links; all imply `?skipwelcome`):
  `?view=s1|library|channels|providers|schema`, `?editor=<jobId>`, `?export=<jobId>`,
  `?expand=failed|reuse`, `?script=<id>`, `?channel=<id>`, `?provider=<id>`, `?skipwelcome`.
  Harmless in normal use.
- **All state is in-memory** and resets on reload; uploads (thumbnail/logo) use the
  browser `FileReader` and are not persisted.
- The archive "clock" is pinned to a fixed *now* so the 48h calendar is deterministic.

This file is a **reference artifact**, not shipped code. When the real views exist, the
prototype's role is done — keep it only as long as it's a useful spec.
