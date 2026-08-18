# Schema — the graph, projected from the engine

Schema draws the workflow the engine holds. It is a **projection**, not a second
execution model, and that is the one rule the whole project hangs off:

> Nodes are the execution model. Steps are the user experience.

Production projects the same graph as an ordered stage list; Schema projects it
as nodes and edges. Neither invents structure.

## Where the picture comes from

| Read | Answers |
|---|---|
| `GET /api/workflow/node-types` | what a node *is* — label, icon, category colour |
| `GET /api/workflows/<id>` | which nodes exist, how they wire, where they were authored |
| `GET /api/workflows/<id>/stages` | which Production stage each node reports to |
| `GET /api/workflow/executions/<id>` | what a run did to each node |
| `GET /api/workflow/executions/<id>/stages` | the same stage labels, for a run |
| `GET /api/workflow/executions/<id>/events` | what is happening right now (SSE) |
| `GET /api/jobs/<id>` | which run the Job is on, and which stage it is in |
| `GET /api/jobs?status=failed` | failed Jobs counted by the topbar badge |

An install with nothing saved falls back to the built-in templates and projects
the body through `POST /api/workflow/stages` — the same projector, not a second
one. A projection failure is survivable: nodes keep their registry category
instead of a stage label, and the canvas still renders.

A **run** is drawn from its `workflow_snapshot`, not from the saved workflow. A
workflow edited since the run started would otherwise animate nodes this
execution never had, and hide ones it did.

**No node list, edge list or stage catalog is authored in this feature.** A
registry key this code has never seen renders anyway, and
`__tests__/schemaPage.test.js` fails the build if a type key or stage key
appears in any source file here. The same file reads `api.js` and permits only
the projector plus step 1.4's explicit Test and Retry writes; Schema cannot
stop, approve, reject, edit, or save a run.

## The running job (step 1.3)

Live status arrives on the same SSE stream Production consumes — one run, two
projections, no polling loop, and no second copy of the status ladder:
`live.js` decides how a status *looks*, while the vocabulary itself stays in
`features/production/stageStatus.js`.

| Look | Engine status |
|---|---|
| dim | `idle`, `stale` |
| glow + percent | `running`, `queued`, `waiting` |
| green | `succeeded` |
| red | `failed`, `invalid` |
| dashed, struck through | `skipped`, `cancelled` |
| scheduled tint | `awaiting_approval` |

Edges *into* an active node flow; edges out of it do not, because nothing has
left it yet. A status this frontend has never heard of draws dim rather than
vanishing, the same way an unknown node type still renders.

**On percent.** The engine records per-node status, not per-node progress, so
there is no honest number for "how far through is this one node". The live
percent is the run's — how much of the graph has settled — which is what the
pill shows and what an active card is reflecting.

`?job=`, `?run=` and `?workflow=` address the view, in that order of
precedence: the Job is what a person is watching, and the other two are how it
is reached.

## Freeze view

Freeze holds **this view** still. The stream stays open, `liveRecords` keeps
moving, and only `records` — what the canvas and the inspector draw — is held.
The badge counts how far behind the view has fallen, and unfreezing shows where
the run actually got to rather than where it was.

Pausing production is the Production row's job, and this feature has no
endpoint that could do it even by mistake.

## Node actions and failures (step 1.4)

The inspector reuses Production's `TestNodePanel`, including registry-defined
input bindings and the provider catalog. With a bound Job, Test posts to
`POST /api/jobs/<id>/test-node`; the resulting execution is exploratory and
does not change the Job's status, stage, artifacts, or production execution.
The selected `provider_instance_id` is one-shot and is never saved on the node.
Without a Job, Test starts the same isolated engine run against the workflow
snapshot on screen.

Retry targets the selected failed node through `run_mode=retry_failed`. Locate
centres and flashes the card. Failed cards carry an inline code/message tooltip,
the detail panel names node, stage, Job, reason and code, and the topbar counts
failed Jobs across the batch. Clicking that badge binds the first failure's
execution and locates its failed node in one action.

## What is cosmetic and what is fixed

`useSchemaCanvas` owns positions and the camera. Dragging a card, auto-aligning,
snapping to the grid, resetting and fitting all produce a new `{id: {x, y}}` map
in component state and issue **no write**. Structure — which nodes exist and how
they connect — is not editable from this view at all.

Navigation matches the prototype: drag the background or two-finger scroll to
pan, Ctrl/pinch-wheel to zoom anchored on the cursor, right-click for the
realign menu.

## Layout

```
api.js                      projection reads plus isolated Test and Retry
graph.js                    pure model + canvas geometry (no Vue)
live.js                     pure run model: looks, percent, inspector (no Vue)
composables/
  useSchemaGraph.js         load registry / workflow / run / projection
  useSchemaCanvas.js        cosmetic positions + camera
  useSchemaLive.js          SSE binding, node records, freeze
components/
  SchemaCanvas.vue          pan, zoom, drag, edges, cards, live states
  SchemaContextMenu.vue     realign menu
  SchemaInspector.vue       inspection plus shared Test and node actions
SchemaPage.vue              topbar, live binding, actions, failure navigation
```

## Still to land

- **1.5** retires the editable canvas, once 1.4 has rescued per-node testing.
