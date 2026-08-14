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
| `POST /api/workflow/run` | Run / Test / Regenerate / Run From Here |

| Action | Run mode |
|---|---|
| Run | `node_with_deps` |
| Test | `node_isolated` |
| Regenerate | `retry_failed` |
| Run From Here | `from_node` |

View Input / View Output / Provider / History / Approve are inspect or
checkpoint actions — not new run modes. Approve becomes durable at 2.6.

The default full-video spine is Script → Voice → Timing → Segments → Scenes →
Images → Videos → Review → Composer → Export. Side branches (captions, music)
collapse into Composer — adding a parallel caption branch must not add a step.

## Layout

```
api.js                         stage + workflow/execution listing + run client
stageStatus.js                 pure aggregation (mirrors backend priorities)
stageActions.js                §18 action → run_mode + request body (mirrors backend)
composables/useProductionStages.js
                               load projection, open SSE, run stage actions
components/StepDetailPanel.vue §18 action toolbar + inspect panes
ProductionPage.vue             §3.1 step list + detail panel host
```

Do not hardcode a step array here, and do not add a second polling mechanism
or a second execution path. Either one silently diverges the two views.
Job creation and Script stage modes land in 2.5.
