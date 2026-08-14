# Workflow canvas performance

Step 9.5 uses a deterministic 150-node workflow at
`frontend/src/features/workflow/fixtures/large-workflow.json`. Regenerate it with:

```text
cd frontend
npm run fixture:large-workflow
```

The generator is the source of truth; the frontend regression test fails if the checked-in JSON
drifts from it. The fixture uses valid Sample Input nodes on a 15-by-10 grid and is intended for
both automated interaction tests and manual browser profiling through the normal Import JSON
action.

## Performance controls

- Canvas element projection preserves object identity for every unchanged node. Selecting or
  moving one node therefore gives Vue Flow one changed object instead of 150 replacements.
- Node-card subtrees use Vue memoization keyed by every visible card state.
- At 100 nodes, Vue Flow's `onlyRenderVisibleElements` mode activates, keeping offscreen node and
  edge DOM out of pan/zoom rendering work.
- Positions enter the persisted workflow only on drag-stop. Draft writes retain the existing
  trailing 1,000 ms debounce, and viewport persistence runs only at pan/zoom end.

## Recorded measurement

On 2026-08-05, Node 24.14.0 on Windows ran the repeatable canvas-projection benchmark three
times. Each run covered the initial 150-node load, 600 selection/pan-equivalent projections, and
120 single-node drag updates (721 measured updates total). Against a 16.67 ms frame budget, all
three runs reported zero over-budget updates:

| Run | median | p95 | max | over 16.67 ms |
| --- | ---: | ---: | ---: | ---: |
| 1 | 0.034 ms | 0.090 ms | 0.812 ms | 0 |
| 2 | 0.036 ms | 0.090 ms | 0.810 ms | 0 |
| 3 | 0.033 ms | 0.086 ms | 0.756 ms | 0 |

Re-run the gate with `npm run benchmark:large-canvas`. This measurement isolates the JavaScript
projection work controlled by this code; browser paint/compositing depends on the machine and is
kept bounded by viewport culling. For a visual spot check, import the fixture, record the browser
Performance panel while panning across the grid and dragging a node, and confirm there are no
long animation frames attributable to scripting.

The automated interaction regression mounts the full Workflow page with the fixture and verifies
all 150 nodes load, large-canvas culling is enabled, pan state is retained without dirtying the
document, drag state is persisted, and local draft serialization waits for the debounce boundary.
