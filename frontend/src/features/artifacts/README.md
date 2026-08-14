# artifacts

Artifact library and input picker (step 4.1 / product §9.1).

| Surface | Role |
|---|---|
| `api.js` | List / get / upload / resolve-inputs against `/api/artifacts` |
| `components/InputPicker.vue` | Per-port source chooser for standalone / Test runs |

## Input sources

A required node port can be supplied from:

| Source | Binding shape |
|---|---|
| Current Job | `{ source: "current_job", job_id?, kind?, artifact_id?, scene_id? }` |
| Previous Job | `{ source: "job", job_id, kind?, artifact_id?, scene_id? }` |
| Artifact library | `{ source: "library", artifact_id }` |
| Managed upload | `{ source: "upload", artifact_id }` after `POST /api/artifacts/upload` |
| Manual value | `{ source: "manual", value }` |
| Sample stub | `{ source: "sample", port_type }` |
| Run dependencies | `{ source: "run_deps" }` — parent switches to `node_with_deps` |

Resolved overrides are sent on `POST /api/workflow/run` as `input_bindings`
(or pre-resolved `input_overrides`). Source artifact ids land on the
execution record as `nodes.<id>.source_artifact_ids`.

The Test Node panel (step 4.2, `features/production/components/TestNodePanel.vue`)
consumes this package: library listing, managed upload, and per-port bindings
for isolated `node_isolated` runs.
