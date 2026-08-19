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

| Class | Look | Engine status |
|---|---|---|
| `s-idle` | dim | — (no run is being watched) |
| `s-pending` | dimmer | `idle`, `stale` |
| `s-active` | glow + percent | `running`, `queued`, `waiting` |
| `s-done` | green | `succeeded` |
| `s-failed` | red | `failed`, `invalid` |
| `s-skip` | dashed, struck through | `skipped`, `cancelled` |
| `s-blocked` | scheduled tint | `awaiting_approval` |

`s-skip` is the prototype's spelling of the engine's `skipped`; `stateClass`
translates rather than renaming the engine's vocabulary to suit a stylesheet.
`s-blocked` has no prototype counterpart — the prototype has no approval gate —
so it keeps its own token instead of being flattened onto a state that means
something else. A status this frontend has never heard of draws dim rather than
vanishing, the same way an unknown node type still renders.

Edges are coloured by **both** ends: `e-done` once work has crossed, `e-active`
while it is crossing, `e-fail` if either end failed. Only `e-active` animates,
and it is narrower than "any edge into an active node" — an edge whose source
has produced nothing yet is carrying nothing, so animating it would be a lie.

**On percent.** The engine records per-node status, not per-node progress, so
there is no honest number for "how far through is this one node". The live
percent is the run's — how much of the graph has settled — which is what the
pill shows and what an active card is reflecting.

`?job=`, `?run=` and `?workflow=` address the view, in that order of
precedence: the Job is what a person is watching, and the other two are how it
is reached.

## Freeze view

Freeze holds **this view** still. The stream stays open, `liveRecords` and
`liveExecutionStatus` keep moving, and only `records` / `executionStatus` —
what the canvas, inspector and pill draw — are held. The badge counts how far
behind the view has fallen, and unfreezing shows where the run actually got to
rather than where it was.

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

## Prototype fidelity (step 6.6)

The `sch-*` family is ported: `sch-topbar` with its `sch-live` pill and
`sch-pause`, the `sch-canvas` / `sch-world` / `sch-edges` / `sch-nodes` stack,
cards by `role-*` with the `s-*` treatments and their `sch-state` corner pill,
`sch-tags`, the `sch-node-err` tooltip, the `sch-legend`, the `sch-err` panel
and the `sch-inspect` shell with its `si-*` set.

Two things the prototype does are done differently here, both for the same
reason — it hardcodes one graph and this page draws whatever the backend
returns:

- **Role** is derived, not authored. A node the projection claims is
  `role-stage`; one it does not is `role-flow`; one whose registry definition
  declares a `conditional` output is `role-branch`. A list of branching type
  names here would be exactly the hardcoded node knowledge this feature bans.
- **The narration tags** read the resolved `narration_processing` the engine
  stamped on the snapshot, so the trim glyph and the speed chip say what the
  run will actually do rather than what a fixture said.

And three parts of the family are excluded rather than faked:

- **`sch-live.paused`** is the prototype's *job* pause. Nothing on this page can
  pause a job, so the tone is used for `awaiting_approval` — waiting rather than
  working — which is the only thing the app has that means it.
- **The prototype's per-node `accent`, `icon`, `x`/`y` and `sub`** are its own
  fixture. Colour comes from the registry's category, the glyph from its `icon`,
  the position from the workflow document, the subtitle from the projection.
- **`si-sec pre` colouring** is applied from tokens rendered as elements, never
  by assigning to `innerHTML` the way the prototype does. A summary is engine
  output, and engine output must not reach `v-html`.

The topbar also carries three controls the prototype has no need for, because it
draws one fixed graph: the workflow picker, the run picker and the `sch-meta`
counts. They reuse the shared vocabulary rather than inventing one.

Opened with no `?job=` / `?run=` / `?workflow=`, Schema follows the batch the
way the prototype's `schemaFocusJob` does: a live Job, else the first failure,
else the most recent completed. Freeze view is always on the bar — it never
pauses production.

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
