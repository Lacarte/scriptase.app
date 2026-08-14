# Workflow Builder — User Guide

The workflow builder is the default surface of ScriptToScene Studio: a node
canvas where you assemble, validate, and run video-production pipelines. Every
node wraps a real pipeline step (TTS, alignment, segmentation, scene AI, asset
generation, captions, music, assembly, export) and writes the same artifacts as
the legacy step pages.

Companion reference: [workflow-nodes.md](workflow-nodes.md) — every node's
ports, configuration fields, defaults, and capabilities, generated directly
from the backend registry (`python -m scriptase.engine.docs`).

## Before you begin

Complete the repository [prerequisites and installation](../README.md#prerequisites)
once before following this guide. For day-to-day development, run
`start-dev.bat`; for the production build, run `start-prod.bat`. The Full Video
template invokes the configured scene, storyboard, and animator providers, so
configure their URLs or credentials in **Settings** (and `.env` where
applicable) before the first real run.

---

## 1. Quick start — run the Full Video template

1. Start the app (`start-dev.bat`) and open it in the browser. You land on the
   workflow builder (`#/workflow`) automatically.
2. In the toolbar, open the **Template…** dropdown and pick **Full Video**.
   A fully connected pipeline appears: Manual Trigger → Project Setup +
   Script Input → Text to Speech → Timing → Segmenter →
   Scene Blueprint → Storyboard → Animator → (with Captions and Background
   Music) → Assemble Project → Timeline Project → Video Export →
   Workflow Output.
3. Click the **Script Input** node. In the right inspector, paste your
   narration script into the **Script** field (this is the only required field
   the template leaves blank).
4. Optionally click **Project Setup** and choose tone, visual style, aspect
   ratio, and branding (enable **Show logo on video** to upload a logo that is
   watermarked onto every export).
5. Click **Validate** in the toolbar. You should see "Workflow is valid".
6. Click **Save**, give the workflow a name. Saving enables run history.
7. Leave the run-mode dropdown on **Full workflow** and click **▶ Run**.
   Nodes light up as they execute (blue = running, green = succeeded,
   red = failed); edges animate while data flows.
8. When the run finishes, the bottom panel shows every node's status and
   duration. Click **Open in Timeline Editor** to fine-tune the assembled
   project, or click the **Video Export** node in the timeline pane to see the
   rendered file's path under `output/exports/<project_id>/`.

Other built-in templates: **Narration Only** (script → audio),
**Storyboard Only** (script → reference images), and **Re-export Existing
Project** (existing timeline project → new export).

---

## 2. The workspace

| Region | Purpose |
|---|---|
| Left panel | Node library: search box ("Search nodes…"), a **Recently used** section, and all nodes grouped by colored category. Drag a node onto the canvas to add it. |
| Canvas | The graph itself: nodes, typed connections, sticky notes, minimap, zoom controls, 20 px snap grid. |
| Right panel | Inspector for the selected node: name, enable/disable, configuration form, error policy, and the **Workflow variables** editor. |
| Bottom panel | "Runs & diagnostics": run history, node timeline, and per-node deep inspection. |
| Toolbar | File actions (New / Open… / Template… / Save / More), Undo/Redo, Validate, run controls, Tidy / Fit / Auto-stubs, and the legacy **Pipeline** link. |

### Canvas basics

- **Connect nodes** by dragging from an output handle to an input handle.
  Connections are typed: a port only accepts a connection of the **same**
  type (see the port tables in [workflow-nodes.md](workflow-nodes.md)).
  Incompatible targets are rejected with a plain-language toast; compatible
  handles highlight while you drag.
- **Drop a connection on empty canvas** to open the "Insert compatible node"
  palette — pick a node and it is inserted and connected in one step.
- **Right-click** a node, edge, note, or the empty canvas for context menus:
  Copy, Duplicate, Enable/Disable, Replace with…, run actions, Attach sample
  inputs / Attach result viewer, Delete; edges offer Disconnect; the canvas
  offers Paste here, Add note, and Auto arrange.
- **Tidy** auto-arranges the graph left-to-right; **Fit** frames everything.
- **Sticky notes** annotate the canvas and never execute.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+Z / Ctrl+Shift+Z | Undo / Redo (every canvas operation is undoable) |
| Ctrl+C / Ctrl+V | Copy / paste selected nodes (works across workflows) |
| Ctrl+D | Duplicate selection |
| Delete | Remove selected nodes / edges / notes |
| Ctrl+Click | Add or remove a node from the multi-selection |

---

## 3. Configuring nodes

Select a node to edit it in the inspector. Forms are generated from each
node's schema — text, numbers, toggles, dropdowns, JSON editors, and the
logo's media-asset picker (upload new or pick an existing image; raw file
paths are never accepted).

- **Conditional fields** appear only when relevant (e.g. the logo position
  controls only show once **Show logo on video** is enabled; Grok-specific
  animator options only show for that provider).
- **Live option lists** (voices, tones, style templates, providers, export
  profiles, caption presets) are fetched from the backend, so they always
  match what the server accepts.
- **Project settings inheritance:** nodes with a `settings` input inherit
  tone/style/aspect-ratio defaults from **Project Setup**; a value set
  directly on the node always wins over the inherited one.
- **Error policy:** where a node supports it, choose what a failure does —
  stop the run, retry with backoff, continue through the explicit `error`
  control output, or skip when optional.
- **Expressions:** any config field can be mapped from an upstream output via
  the "Map from upstream output…" picker, which writes an expression such as
  `{{ nodes.<id>.outputs.<port> }}`. `{{ workflow.project_id }}` and
  `{{ variables.<name> }}` are also available; variables are edited as JSON in
  the inspector's **Workflow variables** section. Expressions are whole-value
  only (no interpolation or code) and may reference only upstream nodes.

### Validation

Invalid nodes show a badge with the number of issues (hover to read them).
The **Validate** toolbar button asks the server for an authoritative check and
reports problems and warnings. The same validation runs on save, and a save is
blocked — with the reason shown in the toolbar — while any JSON field holds
unparseable text.

---

## 4. Sample-data stubs (test nodes in isolation)

You do not need a full pipeline to try a node:

- With **Auto-stubs** enabled in the toolbar (default), dropping a node with
  unconnected required inputs automatically spawns one dashed **Sample Input**
  stub per required input, pre-filled with a realistic fixture payload, plus a
  **Result Viewer** on the node's main output.
- Edit a stub's payload in the inspector; payloads are validated against the
  port type.
- Connecting a real edge to a stubbed input removes the stub (Ctrl+Z brings
  it back).
- Add stubs manually from the **Testing** library category or via the node
  context menu ("Attach sample inputs" / "Attach result viewer").
- Run the node with the **Node in isolation** run mode: Sample Inputs return
  their payloads instantly and every downstream result is marked **sample** in
  the timeline and run record, so test data can never be mistaken for real
  output.
- **Pinning:** enable **Pin edited result** on a Result Viewer to freeze its
  payload. The pinned value feeds downstream nodes (shown as a "pinned" badge)
  until unpinned — useful for iterating on late pipeline stages without
  re-running expensive upstream nodes.

### Testing one node — the short path

1. Right-click the node → **Run node in isolation**.
2. If it has required inputs but no stubs yet, attach them first from the same
   menu, or drop the node on empty canvas with Auto-stubs on.
3. Read the output in its Result Viewer, or open the bottom panel for the full
   JSON, duration, logs, and errors.

Three modes each run "one node", and they are not interchangeable:

| You want to | Use | What it costs |
|---|---|---|
| Check this node's own logic | **Node in isolation** | Only this node runs; inputs come from stubs. |
| Check it against real upstream data | **Node + dependencies** | Every upstream node runs, or is served from cache. |
| Re-run everything affected by a change here | **From node downstream** | This node and all its descendants. |

**Isolation ignores real upstream nodes deliberately.** It will not fall back to
a connected predecessor's output: a required input with no Sample Input attached
fails validation rather than running on invented data. Attach a stub, or switch
to **Node + dependencies** when you want the real upstream result.

---

## 5. Running workflows

Pick a mode in the run dropdown (or use the node context menu), then **▶ Run**:

| Mode | Runs |
|---|---|
| Full workflow | Every enabled node. |
| Node + dependencies | The selected node and everything it depends on. |
| Node in isolation | Only the selected node, fed by its Sample Input stubs. |
| Selected + dependencies | All selected nodes plus their dependencies. |
| From node downstream | The selected node and everything after it. |
| Retry failed node | Re-runs one failed node, keeping all other results. |
| Retry failed + downstream | The failed node plus its descendants. |

While running:

- Node colors show status: gray = idle/queued, blue = running,
  purple = waiting, green = succeeded, red = failed, amber = cancelled,
  slate = skipped, orange = stale.
- **■ Stop** cancels cooperatively; a cancelled run never reports success.
- Progress streams live; dropped connections reconnect automatically and
  replay the events they missed, and finished runs are always available in
  run history.

### Caching and staleness

Successful node results are cached by a fingerprint of the node's type,
configuration, and upstream artifacts. Re-running an unchanged workflow
re-executes nothing; changing one node marks it and its descendants **stale**
(orange) and re-executes exactly that subgraph. Renaming or moving nodes never
invalidates the cache. Each run records the cache hit/miss decision and reason
per node — visible in the bottom panel.

### Diagnosing a run

The bottom panel ("Runs & diagnostics") has three panes:

1. **Run history** — every persisted run for the saved workflow, newest first,
   with status, mode, and duration. Click one to inspect it.
2. **Node timeline** — per-node status, duration bars, attempt counts, and
   **sample** markers.
3. **Detail** — click a finished node to see its cache decision, resolved
   inputs, outputs, artifact references, structured errors with recovery
   suggestions, per-attempt errors, and logs. Failed nodes offer **Retry
   failed** and **Retry + downstream** buttons that preserve all successful
   work.

When a run produces an editor project, **Open in Timeline Editor** jumps to it
with the project preloaded.

---

## 6. Saving, drafts, and portability

- **Save / Save as… / Duplicate workflow** live in the toolbar; the yellow
  **Unsaved** badge shows dirty state.
- **Draft autosave:** edits are snapshotted to the browser about once a second.
  If the tab closes or crashes mid-edit, reopening the page offers to recover
  the draft. Explicit save clears the dirty state; leaving with unsaved
  changes asks for confirmation (the draft is kept either way).
- **Import JSON… / Export JSON** exchange workflow files with other machines;
  imports are validated (size, schema, node types) before anything is saved.
- Deleting a workflow moves it to `output/TRASH/workflows/` rather than
  erasing it.

---

## 7. Automated triggers

Saved workflows can enqueue full runs without clicking Run. Open the toolbar's
**Trigger** group to configure any of these sources, then save the workflow:

- **Schedule** uses five-field UTC cron expressions. Each schedule can be
  disabled independently; after the app was closed, only the latest missed
  fire is caught up.
- **Folder** watches matching UTF-8 text files, waits until each file is stable,
  maps its content to Script Input or another text/script input, and moves the
  claimed file into `processed/`.
- **Webhook** creates a private loopback URL and maps dotted JSON payload paths
  (for example `story.text`) to declared typed input ports. Required fields and
  port-specific values are validated before a run enters the queue. The endpoint
  accepts at most 64 KiB, rejects non-loopback clients, and is disabled whenever
  the server is bound to a non-loopback address. **Regenerate** immediately
  invalidates the previous URL; tokens are stored separately and never included
  in workflow exports or execution snapshots.

All trigger sources use the Runs & diagnostics queue. Runs for the same project
execute one at a time, pending runs can be cancelled, and different projects do
not block each other.

---

## 8. Legacy pages

The step-by-step dashboard remains available: toolbar → **Pipeline**, or the
sidebar's "Legacy Pipeline Dashboard". Each legacy page links back to the
workflow builder. Both surfaces operate on the same projects and artifacts
under `output/`, so you can mix them freely — e.g. run the workflow, then
polish in the Timeline Editor, then re-export from either surface.

---

## 9. Where things live

| What | Where |
|---|---|
| Saved workflows | `output/workflows/<wf_id>.json` |
| Run records | `output/workflows/executions/` |
| Webhook tokens | `output/workflows/hook-tokens/` (private runtime state) |
| Project artifacts | `output/<step>/<project_id>/` |
| Final exports | `output/exports/<project_id>/` |
| Branding / logos | `output/branding/` |
| Node reference | [docs/workflow-nodes.md](workflow-nodes.md) (generated — do not edit) |
