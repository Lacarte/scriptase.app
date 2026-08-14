# production

The step/window Production view (Phase 2, steps 2.3–2.5).

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

View Input / View Output / Provider / History / Approve are inspect or
checkpoint actions — not new run modes. Approve becomes durable at 2.6.

The default full-video spine is Script → Voice → Timing → Segments → Scenes →
Images → Videos → Review → Composer → Export. Side branches (captions, music)
collapse into Composer — adding a parallel caption branch must not add a step.

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
components/TestNodePanel.vue   §9 Test Node panel (input picker → node_isolated)
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

Script source modes: Automatic, Topic→Script, Idea→Script, Paste Script,
Manual/Edit. Paste and Manual never require a script provider.

Do not hardcode a step array here, and do not add a second polling mechanism
or a second execution path. Either one silently diverges the two views.
