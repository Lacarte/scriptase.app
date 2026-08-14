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

The default full-video spine is Script → Voice → Timing → Segments → Scenes →
Images → Videos → Review → Composer → Export. Side branches (captions, music)
collapse into Composer — adding a parallel caption branch must not add a step.

Do not hardcode a step array here, and do not add a second polling mechanism.
Either one silently diverges the two views the first time a branch is added.
