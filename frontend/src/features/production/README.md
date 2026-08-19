# production

The Production Batch view (Phase 2, steps 2.3–2.5).

The page is the prototype's two-column run-sheet: a **config rail**
(Channel → Script source → Execution → Add to Batch) beside a **batch
sheet** (totals, search, channel filter, Run / Stop / Retry / Clear /
Cancel, and the job list). Stages still come from the backend
projection — the rail never invents a pipeline.

It renders the ordered stage list returned by the backend stage-projection
endpoints (step 2.2) and consumes the **same** SSE stream the workflow canvas
uses — including its ring-buffer reset snapshot and `Last-Event-ID` resume.

Stage projection (do not reimplement in the frontend):

| Endpoint | Purpose |
|---|---|
| `GET /api/workflows/<id>/stages` | Project a saved workflow |
| `POST /api/workflow/stages` | Project a draft / template body |
| `GET /api/workflow/executions/<id>/stages` | Snapshot + live per-stage status |

SSE (shared with the canvas — no second stream protocol):

| Endpoint | Purpose |
|---|---|
| `GET /api/workflow/executions/<id>/events` | Sequenced events; `id:` frames + reset snapshot |

Step actions (step 2.4) start runs through the **same** endpoint the canvas uses:

| Endpoint | Purpose |
|---|---|
| `POST /api/workflow/run` | Run / Regenerate / Run From Here |
| `POST /api/jobs/<id>/test-node` | Test Node (step 4.2) — never advances Job |

| Action | Run mode |
|---|---|
| Run | `node_with_deps` |
| Test | `node_isolated` via Test Node panel + input picker |
| Regenerate | `retry_failed` |
| Run From Here | `from_node` |

Test (step 4.2) opens the **Test Node panel** (`components/TestNodePanel.vue`)
wired to the 4.1 InputPicker. When a Job is bound, the panel posts to
`/api/jobs/<id>/test-node` so status, current stage, and the artifact set stay
unchanged. Sample-fed results keep the `from_sample_data` marker.

Step 4.5 keeps failures Job-scoped. The failed row gets a red rail, failed
stage, safe error banner, and Retry / Duplicate / Remove actions. Retry creates
a structured issue and invokes the Repair Router for the responsible node;
Retry Failed does the same independently for every failed Job. A queued Job
also shows a non-blocking advisory when its explicit or confidently detected
script language differs from the frozen Channel language.

Step 13.3: the panel is shared, not owned. The Workflow canvas mounts the same
component from its node context menu ("Test node…"), replacing three run items
that fired blind. Passing a `providerDomain` turns the read-only provider line
into a picker over that domain's catalog instances; the choice leaves as the
one-shot `provider_instance_id` of 13.2 and is never written to the node.

View Input / View Output / Provider / History / Approve are inspect or
checkpoint actions — not new run modes. Approve becomes durable at 2.6.

Review issues and repairs (step 11.4) are read-only surfaces:
`stage.issues` from the projection renders in the detail panel, and the History
pane hosts `components/RepairHistoryPane.vue`, which reads
`GET /api/jobs/<id>/repair-history` for the node each issue was routed to, what
was retried, and every superseded artifact version. Neither surface mutates a
Job or starts a run.

The default full-video spine is Script → Voice → Timing → Segments → Scenes →
Images → Videos → Review → Composer → Export. Side branches (captions, music)
collapse into Composer — adding a parallel caption branch must not add a step.

## The Job row (step 6.2)

The row is the prototype's `.job`: id, channel, title, compact stage line,
status badge, elapsed, and — on completed rows — the two quick destinations.
Expanding it reveals `.job-detail`: the `.stagerail`, the failure banner, the
three-cell detail grid and the timestamps with Retry / Duplicate / Remove.

**Expanding a row is binding that Job.** The rail is the same backend
projection the step list below draws, over the same SSE stream, which is why
only one row is open at a time — a second open row would need a second
projection and a second stream, and the rail would stop being the projection.

Two consequences worth keeping:

- A percentage appears only where the projection supplies one. A running Job
  with no projection to hand gets `.progress.indet`, never a guessed number.
- `.skip-tip` carries a stage's issues or the failure code. It is not rendered
  when there is nothing to say; a tooltip reading "Skipped" repeats what the
  dimmed node already said.

Batch selection (`.job-check` / `.sel-checked`) and the sheet scroller
(`.joblist`) are live. Two prototype row affordances stay unported rather
than faked: `.drag-handle` (queue reordering) and `.job-menu-btn` (a
context menu). The `.st-preparing`, `.st-stopping`, `.st-stopped` and
`.st-draft` spines are absent because `JobStatus` has no such members.

The channel avatar landed with the `ch-*` family in step 6.4: `.job-ch` is now
the prototype's flex row seating a shared `.ch-avatar`, whose colour is derived
from the channel id so a job row and the Channels rail agree.

The quick actions on a completed row are icon plus label, and the label
collapses below 1240px so the row keeps its width, returning at 820px where
`.job-quick` has a line to itself. The `title` carries the destination at
every width, since below 1240px the icon is the whole button.

## Layout

```
api.js                         stage + job + workflow/execution listing + run client
sourceModes.js                 Script-stage modes (§6); provider only when needed
stageStatus.js                 pure aggregation (mirrors backend priorities)
stageActions.js                §18 action → run_mode + request body (mirrors backend)
composables/useProductionStages.js
                               load projection, open SSE, run stage actions
components/JobCreatePanel.vue  Step 0: Channel, source, workflow, execution mode
components/StepDetailPanel.vue §18 action toolbar + inspect panes + script mode
components/TestNodePanel.vue   §9 Test Node panel (input picker + provider
                               picker → node_isolated); shared with the canvas
components/RepairHistoryPane.vue
                               issues + repair history (read-only, step 11.4)
ProductionPage.vue             §3.1 step list + Job create + detail panel host
```

Job API (step 2.5 + 4.2):

| Endpoint | Purpose |
|---|---|
| `GET /api/jobs/defaults` | Source + execution mode catalog |
| `POST /api/jobs` | Create Job (Channel snapshot, no secrets) |
| `POST /api/jobs/<id>/start` | Run through the ported engine |
| `POST /api/jobs/<id>/test-node` | Isolated Test Node; Job progress frozen |
| `GET /api/jobs` / `GET /api/jobs/<id>` | List / load |
| `GET /api/jobs/<id>/repair-history` | Repair sequence for the History pane (11.4) |

Script source modes: Automatic, Topic→Script, Idea→Script, Paste Script,
Manual/Edit. Paste and Manual never require a script provider.

Do not hardcode a step array here, and do not add a second polling mechanism
or a second execution path. Either one silently diverges the two views.
