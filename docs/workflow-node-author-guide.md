<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Regenerate with: python -m scriptase.engine.docs
     Sources: plans/contracts.md and scriptase/engine/registry.py -->

# Workflow Node Author Guide

This is the complete path for adding a backend workflow node: **scaffold → schema → adapter → test → ship**. Run commands from the repository root with Python 3.10 or newer. The generated files are source-controlled; a normal application restart discovers them, while development hot reload discovers saved changes when `STS_WORKFLOW_DEV_RELOAD=1`.

The tables under [Registry-generated contracts](#registry-generated-contracts) come from the same registry served to the palette. The connection prose comes verbatim from the normative [`contracts.md`](../plans/contracts.md) section 1.1. Regenerate this guide after any registry or contract change:

```powershell
python -m scriptase.engine.docs
python -m scriptase.engine.docs --check
```

## 1. Scaffold

Choose a stable lowercase dotted key. It is persisted in workflows, so do not rename it after shipping. Declare data ports on the command line; the scaffolder adds optional `trigger:control` and `control:control` ports itself. `control` is reserved and cannot be passed to `--input` or `--output`.

The step 8.1 demo is reproducible with:

```powershell
python -m scriptase.engine.scaffold scaffold_check.echo `
  --input source:generic_json `
  --output result:generic_json `
  --category testing `
  --display-name "Scaffold Check Echo" `
  --description "Echo a JSON value for node-author verification."
```

This creates exactly three files:

- `scriptase/engine/node_definitions/scaffold_check.echo.json` — registry metadata and configuration schema.
- `scriptase/engine/adapters/generated/scaffold_check_echo.py` — executable adapter.
- `tests/test_workflow_node_scaffold_check_echo.py` — passing registry and execution smoke tests.

The command refuses an existing registry key, an existing target file, malformed IDs, duplicate/reserved port IDs, and types outside the generated table below. Use `python -m scriptase.engine.scaffold --help` for all options.

## 2. Define the schema

Edit the generated JSON definition. Keep port IDs stable and make each input's `required` and `multiple` flags intentional. Outputs may fan out; `multiple: true` on an input permits more than one incoming edge. Do not use `dynamic` for authored nodes—it is reserved for the built-in stubs and Workflow Output.

Configuration fields render directly in the inspector. Supported widgets are `string`, `textarea`, `number`, `boolean`, `options`, `json`, and `media_asset`. Every field needs `name`, `label`, `type`, and `default`. Useful optional constraints are `required`, `min`, `max`, `integer`, `min_length`, `max_length`, `pattern`, `options`, `options_source`, `accept`, and `display_options`. Use only an existing allowlisted `options_source`; registry tests enforce this.

Capabilities describe scheduler behavior: set `retry` only for safe repeatable attempts, `cancel` only when the adapter cooperatively observes cancellation, and `cacheable: false` when executing the node is itself the intended side effect. The registry supplies error/skip outputs for ordinary control-producing nodes.

When a released schema changes, increment `type_version` and add every sequential migration as a `module:function` entry under `migrations` (for example, key `"1"` upgrades configuration from 1 to 2). A migration accepts and returns a configuration object and must not mutate files or external state.

## 3. Implement the adapter

Adapters have one boundary: `execute(inputs, config, context) -> outputs`. `inputs` and `config` are resolved mappings. `context` is an `AdapterContext` (mapping-compatible in tests) with project/execution/node IDs, progress and stop callbacks, existing-project authorization, and optional staged-artifact support.

Use helpers from `scriptase.engine.adapters.common`: `outputs(...)` adds the control token, `AdapterError` reports a stable code and safe message, `project_id(...)` resolves a strict project ID, `inherited_config(...)` applies explicit-over-inherited settings, and `with_artifacts(...)` emits managed relative artifact refs. Call importable Python services directly—never call this application's Flask routes over HTTP. Use `safe_json_read`, `safe_json_write`, `safe_join`, and configured directory constants for filesystem work.

The committed demo turns the scaffold placeholder into a real deterministic echo: it returns `source` when connected and otherwise the configured `value`. Its generated smoke test therefore continues to pass without modification.

Adapter checklist:

- Return only declared output port IDs; omit an inactive conditional branch instead of returning `null`.
- Raise `AdapterError(code, message, details=...)` for expected failures; never include secrets in details.
- Keep output payloads JSON-serializable. Put large/file-backed results under managed output roots and include `artifact_refs`.
- Stage newly created artifacts through `context.stage_artifact` when atomic publication matters.
- Report meaningful progress through `context.progress` and check `context.stop_requested` only if `cancel` is advertised.
- Keep provider IDs canonical and obtain providers through their registries rather than importing synthetic modules.

## 4. Test

Run the generated smoke test first, then add behavior tests beside it for defaults, every output branch, validation failures, structured errors, cancellation/retry claims, and artifact containment as applicable.

```powershell
python -m pytest tests/test_workflow_node_scaffold_check_echo.py -q
python -m pytest tests/test_workflow_scaffold.py tests/test_workflow_registry.py tests/test_workflow_docs.py -q
python -m scriptase.engine.docs --check
```

For a provider or filesystem node, also test with deterministic fixtures from `scriptase/engine/fixtures/`; normal tests must not require live providers. Before shipping, run the complete relevant backend suite and the frontend workflow tests if registry presentation changed.

## 5. Ship

Regenerate and commit both documentation files. Restart the app (or confirm a successful dev-reload event), verify the node appears in the intended palette category, configure it, connect only exact-type ports, validate the graph, and execute it. Review the execution record for output summaries, redaction, cache behavior, and managed artifact references. Commit the definition, adapter, tests, generated docs, and any migration module together.

## Registry-generated contracts

Registry version **4**.

### Allowed port types

| Port type | CLI data port? |
|---|---|
| `control` | no — reserved for execution order |
| `text` | yes |
| `script` | yes |
| `project_id` | yes |
| `project_settings` | yes |
| `audio_file` | yes |
| `tts_metadata` | yes |
| `alignment` | yes |
| `segments` | yes |
| `scenes` | yes |
| `image_prompts` | yes |
| `storyboard_images` | yes |
| `animation_assets` | yes |
| `captions` | yes |
| `music_track` | yes |
| `editor_project` | yes |
| `export_profile` | yes |
| `video_file` | yes |
| `generic_json` | yes |

### Frozen connection rules

Adapted from V2 at step 0.2, ahead of the rest of section 1, because the generated node
author guide reads this prose verbatim and the doc-drift gate depends on it. The type
inventory is deliberately stated here as prose only — `scriptase/engine/registry.py` is the
executable source of truth for the list itself.

Compatibility rule: **exact type match only.** No wildcard: `generic_json` connects only to `generic_json`. `stub.input`/`stub.output` resolve their dynamic type from configuration at validation time and then obey exact-match. Additional rules: no in→in / out→out; single-value inputs reject a second edge; DAG only (cycle rejection); control edges distinct from data edges. Every payload that references files carries `{artifact_refs: [relpaths]}` alongside inline JSON; integrity check = existence + nonzero size.

Data edges establish both a dependency and a typed value. Control edges establish only a
dependency and never satisfy a required data input. A node with a connected `trigger` waits
for that control predecessor as well as all required data. An unconnected optional `trigger`
does not block a node. A node emits `control` only after successful completion; skipped,
failed, and cancelled propagation is handled explicitly by scheduler policy rather than by
fabricating a success token. These rules make Manual Trigger useful without making it
mandatory for partial or isolated execution.

### Current node port matrix

`?` marks an optional input and `*` marks a multiple-connection input.

| Node type | Inputs | Outputs |
|---|---|---|
| `trigger.manual` | — | `control:control` |
| `project.setup` | `trigger:control?` | `control:control`, `settings:project_settings`, `error:control` |
| `script.input` | `trigger:control?` | `control:control`, `script:script`, `error:control` |
| `story.generate` | `trigger:control?`, `settings:project_settings?` | `control:control`, `script:script`, `story:generic_json`, `error:control` |
| `project.existing` | `trigger:control?` | `control:control`, `project_id:project_id`, `project:editor_project`, `error:control` |
| `tts.generate` | `trigger:control?`, `script:script`, `settings:project_settings?` | `control:control`, `audio:audio_file`, `metadata:tts_metadata`, `error:control` |
| `timing.align` | `trigger:control?`, `audio:audio_file`, `script:script` | `control:control`, `alignment:alignment`, `error:control` |
| `segment.run` | `trigger:control?`, `alignment:alignment` | `control:control`, `segments:segments`, `error:control` |
| `scenes.blueprint` | `trigger:control?`, `segments:segments`, `script:script`, `settings:project_settings?` | `control:control`, `scenes:scenes`, `image_prompts:image_prompts`, `error:control` |
| `storyboard.generate` | `trigger:control?`, `scenes:scenes`, `settings:project_settings?` | `control:control`, `images:storyboard_images`, `error:control` |
| `animator.generate` | `trigger:control?`, `scenes:scenes`, `storyboard:storyboard_images?`, `settings:project_settings?` | `control:control`, `assets:animation_assets`, `error:control` |
| `captions.generate` | `trigger:control?`, `alignment:alignment` | `control:control`, `captions:captions`, `error:control` |
| `music.select` | `trigger:control?`, `settings:project_settings?`, `project_id:project_id?` | `control:control`, `track:music_track`, `error:control` |
| `assemble.project` | `trigger:control?`, `assets:animation_assets`, `metadata:tts_metadata`, `scenes:scenes`, `captions:captions?`, `music:music_track?`, `settings:project_settings?` | `control:control`, `project:editor_project`, `error:control` |
| `timeline.project` | `trigger:control?`, `project:editor_project` | `control:control`, `project:editor_project`, `project_id:project_id`, `error:control` |
| `export.video` | `trigger:control?`, `project:editor_project`, `settings:project_settings?` | `control:control`, `video:video_file`, `error:control` |
| `utility.set_value` | `trigger:control?`, `value:generic_json?` | `control:control`, `value:generic_json`, `error:control` |
| `utility.condition` | `trigger:control?`, `value:generic_json` | `true:generic_json`, `false:generic_json` |
| `utility.merge` | `values:generic_json*` | `control:control`, `value:generic_json`, `error:control` |
| `utility.wait` | `trigger:control?`, `value:generic_json?` | `control:control`, `value:generic_json`, `error:control` |
| `workflow.output` | `trigger:control?`, `value:dynamic` | — |
| `stub.input` | — | `value:dynamic` |
| `stub.output` | `value:dynamic` | `value:dynamic` |
| `scaffold_check.echo` | `trigger:control?`, `source:generic_json?` | `control:control`, `result:generic_json`, `error:control` |
