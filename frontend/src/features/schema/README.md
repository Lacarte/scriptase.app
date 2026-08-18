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

An install with nothing saved falls back to the built-in templates and projects
the body through `POST /api/workflow/stages` — the same projector, not a second
one. A projection failure is survivable: nodes keep their registry category
instead of a stage label, and the canvas still renders.

**No node list, edge list or stage catalog is authored in this feature.** A
registry key this code has never seen renders anyway, and
`__tests__/schemaPage.test.js` fails the build if a type key or stage key
appears in any source file here.

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
api.js                      the three reads, and nothing that writes
graph.js                    pure model + canvas geometry (no Vue)
composables/
  useSchemaGraph.js         load registry / workflow / projection
  useSchemaCanvas.js        cosmetic positions + camera
components/
  SchemaCanvas.vue          pan, zoom, drag, edges, cards
  SchemaContextMenu.vue     realign menu
SchemaPage.vue              topbar, workflow picker, banners
```

## Still to land

- **1.3** live job animation and the node inspector. Freeze view must stop the
  canvas repainting and never pause execution — pausing production is the
  Production row's job.
- **1.4** node actions in the inspector, including Test with a one-shot
  provider-instance override.
- **1.5** retires the editable canvas, once 1.4 has rescued per-node testing.
