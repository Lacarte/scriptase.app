<!-- GENERATED FILE — DO NOT EDIT BY HAND.
     Regenerate with: python -m scriptase.engine.docs
     Source of truth: scriptase/engine/registry.py -->

# Workflow Node Reference

Registry version **5** — 26 node types across 9 categories.

Connections require the source and target port to have the **same** type; there are no implicit conversions. `control` ports carry execution order only and never data. Dynamic ports (`stub.input`, `stub.output`, `workflow.output`) take the type chosen in the node's `port_type` setting.

## Port types

| Type |
|---|
| `control` |
| `text` |
| `script` |
| `project_id` |
| `project_settings` |
| `audio_file` |
| `tts_metadata` |
| `alignment` |
| `segments` |
| `scenes` |
| `image_prompts` |
| `storyboard_images` |
| `animation_assets` |
| `captions` |
| `music_track` |
| `editor_project` |
| `export_profile` |
| `video_file` |
| `generic_json` |

## Categories

| Category | Label | Color |
|---|---|---|
| `input` | Input | `#4ECDC4` |
| `audio` | Audio | `#A78BFA` |
| `timing` | Timing | `#60A5FA` |
| `ai` | AI | `#F472B6` |
| `assets` | Assets | `#FBBF24` |
| `video` | Video | `#34D399` |
| `output` | Output | `#F87171` |
| `utility` | Utility | `#9CA3AF` |
| `testing` | Testing | `#78716C` |

## Input nodes

### Execution (`trigger.manual`)

Emits one control token when the run starts.

- **Type version:** 1
- **Capabilities:** no retry, cancel, error output, skip-optional

**Inputs:** none

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |

**Configuration:** none

### Channel (`project.setup`)

Project identity, branding, and creative defaults shared by downstream nodes.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `settings` | `project_settings` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `project_name` | Project name | `string` | `""` | no | max length 120 |
| `channel_name` | Channel name | `string` | `""` | no | max length 120 |
| `logo_enabled` | Show logo on video | `boolean` | `false` | no | — |
| `logo` | Logo image | `media_asset` | — | no | file types `png`, `jpg`, `jpeg`, `webp`; shown when `logo_enabled` is `true` |
| `logo_position` | Logo position | `options` | `"top_right"` | no | one of `top_left`, `top_right`, `bottom_left`, `bottom_right`, `center`; shown when `logo_enabled` is `true` |
| `logo_size` | Logo size (% of width) | `number` | `10` | no | range 2–40; shown when `logo_enabled` is `true` |
| `logo_opacity` | Logo opacity | `number` | `0.9` | no | range 0.05–1.0; shown when `logo_enabled` is `true` |
| `logo_margin` | Logo margin (px) | `number` | `32` | no | range 0–200; shown when `logo_enabled` is `true` |
| `tone` | Story tone | `options` | `""` | no | options from `story_tones` |
| `style` | Visual style | `options` | `"cinematic"` | no | options from `style_templates` |
| `aspect_ratio` | Aspect ratio | `options` | `"9:16"` | no | one of `9:16`, `16:9`, `1:1` |

### Script Input (`script.input`)

The narration script that drives the production.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `script` | `script` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `text` | Script | `textarea` | `""` | yes | min length 1; max length 10000 |

### Existing Project (`project.existing`)

Select an existing project (WIP preferred over initial) without rewriting it.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `project_id` | `project_id` | — |
| `project` | `editor_project` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `project_id` | Project ID | `string` | `""` | yes | pattern `^p[pm]_[A-Za-z0-9]{6}$` |

## Audio nodes

### Text to Speech (`tts.generate`)

Generate narration audio from the script.

- **Type version:** 3
- **Capabilities:** supports retry, error output, skip-optional; no cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `script` | `script` | required |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `audio` | `audio_file` | — |
| `metadata` | `tts_metadata` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `provider_id` | Provider | `provider` | `"inworld"` | yes | options from `tts_providers` |
| `voice` | Voice | `options` | `"Ashley"` | no | options from `tts_voices` |
| `speed` | Speed | `number` | `1.0` | no | range 0.5–2.0 |
| `provider_options` | Provider options | `provider_options` | `{}` | no | — |

### Background Music (`music.select`)

Pick a background track by tone, at random, or explicitly.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `settings` | `project_settings` | optional |
| `project_id` | `project_id` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `track` | `music_track` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `mode` | Selection mode | `options` | `"tone"` | no | one of `tone`, `random`, `specific` |
| `story_tone` | Story tone | `options` | `""` | no | options from `story_tones`; shown when `mode` is `"tone"` |
| `track_ref` | Track | `string` | `""` | no | shown when `mode` is `"specific"` |
| `volume` | Volume | `number` | `0.15` | no | range 0.0–1.0 |
| `fade_in` | Fade in (s) | `number` | `2.0` | no | range 0.0–10.0 |
| `fade_out` | Fade out (s) | `number` | `3.0` | no | range 0.0–10.0 |
| `loop` | Loop | `boolean` | `true` | no | — |
| `ducking_enabled` | Duck under voice | `boolean` | `true` | no | — |
| `ducking_level` | Ducking level | `number` | `0.2` | no | range 0.0–1.0 |

## Timing nodes

### Timing (`timing.align`)

Word-level timestamps for the narration. AUTO uses native TTS timings when the provider advertises them; otherwise force-aligns with stable-whisper. Downstream always sees one alignment schema.

- **Type version:** 1
- **Capabilities:** supports retry, error output, skip-optional; no cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `audio` | `audio_file` | required |
| `script` | `script` | required |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `alignment` | `alignment` | — |
| `error` | `control` | — |

**Configuration:** none

### Segmenter (`segment.run`)

Split the alignment into scene-sized segments.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `alignment` | `alignment` | required |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `segments` | `segments` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `segment_config` | Segmenter overrides | `json` | `{}` | no | — |

## AI nodes

### Story Generator (`story.generate`)

Generate a structured narration script with the selected script provider.

- **Type version:** 1
- **Capabilities:** supports retry, error output, skip-optional; no cancel
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `script` | `script` | — |
| `story` | `generic_json` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `provider_id` | Provider | `provider` | `"script_n8n"` | yes | options from `script_providers` |
| `preset_style` | Visual style | `options` | `"cinematic"` | no | options from `style_templates` |
| `story_category` | Story category | `string` | `"motivation"` | yes | max length 80 |
| `duration` | Target duration (seconds) | `number` | `45` | no | range 15–180; integer |
| `language` | Language | `options` | `"english"` | no | one of `english`, `french`, `spanish` |
| `language_level` | Language level | `options` | `""` | no | one of ``, `beginner`, `intermediate`, `advanced`, `native` |
| `story_tone` | Story tone | `options` | `""` | no | options from `story_tones` |
| `idea` | Idea or prompt | `textarea` | `""` | no | max length 4000 |
| `webhook_url` | Webhook URL | `string` | `""` | no | max length 2048 |
| `provider_options` | Provider options | `provider_options` | `{}` | no | — |

### Scene Director (`scenes.blueprint`)

Directs each segment into a scene: visual direction, scene description, and image prompt.

- **Type version:** 1
- **Capabilities:** supports retry, error output, skip-optional; no cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `segments` | `segments` | required |
| `script` | `script` | required |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `scenes` | `scenes` | — |
| `image_prompts` | `image_prompts` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `provider_id` | Provider | `provider` | `"n8n"` | yes | options from `scene_director_providers` |
| `webhook_url` | Webhook URL | `string` | `""` | no | — |
| `style` | Visual style | `options` | `"cinematic"` | no | options from `style_templates` |
| `style_prompt` | Custom style notes | `textarea` | `""` | no | — |
| `story_tone` | Story tone | `options` | `""` | no | options from `story_tones` |
| `provider_options` | Provider options | `provider_options` | `{}` | no | — |

### Review (`review.run`)

Quality review of the generated stills and clips. Deterministic technical validators always run; the selected review provider adds semantic findings when enabled. Emits structured issues only.

- **Type version:** 1
- **Capabilities:** supports retry, error output, skip-optional; no cancel
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `images` | `storyboard_images` | optional |
| `assets` | `animation_assets` | optional |
| `scenes` | `scenes` | optional |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `issues` | `generic_json` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `provider_id` | Provider | `provider` | — | yes | options from `review_providers`; shown when `semantic` is `true` |
| `subject` | Review subject | `options` | `"auto"` | no | one of `auto`, `images`, `videos` |
| `semantic` | Run semantic review | `boolean` | `false` | no | — |
| `aspect_ratio` | Expected aspect ratio | `options` | `"9:16"` | no | one of `9:16`, `16:9`, `1:1` |
| `require_audio` | Clips must carry audio | `boolean` | `false` | no | hidden when `subject` is `"images"` |
| `fail_on_blocking` | Fail this node on blocking issues | `boolean` | `false` | no | — |
| `provider_options` | Provider options | `provider_options` | `{}` | no | — |

### Script Analyzer (`script.analyze`)

Score the script for virality before an expensive stage runs. The default provider is offline, deterministic, and free; it reports a 0-100 score with a per-dimension breakdown and never blocks the run.

- **Type version:** 1
- **Capabilities:** supports retry, error output, skip-optional; no cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `script` | `script` | required |
| `story` | `generic_json` | optional |
| `scenes` | `scenes` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `score` | `generic_json` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `provider_id` | Provider | `provider` | `"deterministic"` | yes | options from `viral_providers` |
| `target_duration` | Target duration (seconds) | `number` | `0` | no | range 0–600; integer |
| `provider_options` | Provider options | `provider_options` | `{}` | no | — |

## Assets nodes

### Storyboard (`storyboard.generate`)

Reference images per scene (never timeline media — see contracts D4).

- **Type version:** 3
- **Capabilities:** supports retry, error output, skip-optional; no cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `scenes` | `scenes` | required |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `images` | `storyboard_images` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `provider_id` | Provider | `provider` | `"gemini_ws"` | yes | options from `image_providers` |
| `aspect_ratio` | Aspect ratio | `options` | `"9:16"` | no | one of `9:16`, `16:9`, `1:1` |
| `style` | Visual style | `options` | `"cinematic"` | no | options from `style_templates` |
| `image_model` | Image model | `string` | `""` | no | — |
| `provider_options` | Provider options | `provider_options` | `{}` | no | — |

### Animator (`animator.generate`)

Timeline media (video/image) per scene via the asset grabber.

- **Type version:** 3
- **Capabilities:** supports retry, error output, skip-optional; no cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `scenes` | `scenes` | required |
| `storyboard` | `storyboard_images` | optional |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `assets` | `animation_assets` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `provider_id` | Provider | `provider` | `"grok_automa"` | yes | options from `video_providers` |
| `aspect_ratio` | Aspect ratio | `options` | `"9:16"` | no | one of `9:16`, `16:9`, `1:1` |
| `arguments` | Extra arguments | `string` | `""` | no | — |
| `skip_quality_gate` | Skip the image quality gate | `boolean` | `false` | no | — |
| `image_gate_max_repairs` | Image gate repair attempts | `number` | `1` | no | range 0–5; integer; hidden when `skip_quality_gate` is `true` |
| `image_gate_semantic` | Add semantic review to the image gate | `boolean` | `false` | no | hidden when `skip_quality_gate` is `true` |
| `provider_options` | Provider options | `provider_options` | `{}` | no | — |

## Video nodes

### Caption Generator (`captions.generate`)

Word-level captions grouped from the alignment.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `alignment` | `alignment` | required |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `captions` | `captions` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `preset_id` | Caption preset | `options` | `"bold_popup"` | no | options from `caption_presets` |
| `words_per_group` | Words per caption | `number` | `3` | no | range 1–10 |
| `enabled` | Enabled | `boolean` | `true` | no | — |

### Assemble Project (`assemble.project`)

Merge audio, scenes, and assets into an editor project.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `assets` | `animation_assets` | required |
| `metadata` | `tts_metadata` | required |
| `scenes` | `scenes` | required |
| `captions` | `captions` | optional |
| `music` | `music_track` | optional |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `project` | `editor_project` | — |
| `error` | `control` | — |

**Configuration:** none

## Output nodes

### Timeline Project (`timeline.project`)

Persist the assembled project for the timeline editor.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `project` | `editor_project` | required |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `project` | `editor_project` | — |
| `project_id` | `project_id` | — |
| `error` | `control` | — |

**Configuration:** none

### Video Export (`export.video`)

Render the final video with FFmpeg.

- **Type version:** 1
- **Capabilities:** supports retry, cancel, error output, skip-optional

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `project` | `editor_project` | required |
| `settings` | `project_settings` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `video` | `video_file` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `profile` | Export profile | `options` | `"yt_shorts"` | no | options from `export_profiles` |
| `captions` | Bake captions | `boolean` | `true` | no | — |
| `grain` | Grain overlay | `boolean` | `false` | no | — |

## Utility nodes

### Set Value (`utility.set_value`)

Emit a configured JSON value, optionally sequenced by an incoming value.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `value` | `generic_json` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `value` | `generic_json` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `value` | Value | `json` | — | no | — |

### Condition (`utility.condition`)

Route one JSON value to exactly one of two explicit branches.

- **Type version:** 1
- **Capabilities:** no retry, cancel, error output, skip-optional
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `value` | `generic_json` | required |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `true` | `generic_json` | conditional branch |
| `false` | `generic_json` | conditional branch |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `operator` | Operator | `options` | `"truthy"` | no | one of `truthy`, `falsy`, `equals`, `not_equals`, `contains` |
| `compare_to` | Compare to | `json` | — | no | shown when `operator` is `"equals"` or `"not_equals"` or `"contains"` |

### Merge (`utility.merge`)

Join active branch values after all connected branches resolve.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `values` | `generic_json` | required, multiple connections |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `value` | `generic_json` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `mode` | Merge mode | `options` | `"array"` | no | one of `array`, `first`, `object` |

### Wait (`utility.wait`)

Delay a branch and pass its JSON value through unchanged.

- **Type version:** 1
- **Capabilities:** supports cancel, error output, skip-optional; no retry, cacheable
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `value` | `generic_json` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `value` | `generic_json` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `delay_ms` | Delay (milliseconds) | `number` | `1000` | no | range 0–300000; integer |

### Workflow Output (`workflow.output`)

Record a value as a result of this workflow.

- **Type version:** 1
- **Capabilities:** no retry, cancel, error output, skip-optional

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `value` | `dynamic` | required |

**Outputs:** none

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `port_type` | Value type | `options` | `"generic_json"` | yes | one of `text`, `script`, `project_id`, `project_settings`, `audio_file`, `tts_metadata`, `alignment`, `segments`, `scenes`, `image_prompts`, `storyboard_images`, `animation_assets`, `captions`, `music_track`, `editor_project`, `export_profile`, `video_file`, `generic_json` |
| `label` | Label | `string` | `""` | no | max length 120 |

## Testing nodes

### Sample Input (`stub.input`)

Editable sample data feeding an unconnected input (testing).

- **Type version:** 1
- **Capabilities:** no retry, cancel, error output, skip-optional
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs:** none

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `value` | `dynamic` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `port_type` | Data type | `options` | `"generic_json"` | yes | one of `text`, `script`, `project_id`, `project_settings`, `audio_file`, `tts_metadata`, `alignment`, `segments`, `scenes`, `image_prompts`, `storyboard_images`, `animation_assets`, `captions`, `music_track`, `editor_project`, `export_profile`, `video_file`, `generic_json` |
| `payload` | Sample payload | `json` | `{}` | no | — |

### Result Viewer (`stub.output`)

Captures a node's output for inspection (testing; pinning in Phase 4).

- **Type version:** 1
- **Capabilities:** no retry, cancel, error output, skip-optional
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `value` | `dynamic` | required |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `value` | `dynamic` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `port_type` | Data type | `options` | `"generic_json"` | yes | one of `text`, `script`, `project_id`, `project_settings`, `audio_file`, `tts_metadata`, `alignment`, `segments`, `scenes`, `image_prompts`, `storyboard_images`, `animation_assets`, `captions`, `music_track`, `editor_project`, `export_profile`, `video_file`, `generic_json` |
| `pinned` | Pin edited result | `boolean` | `false` | no | — |
| `payload` | Pinned payload | `json` | `{}` | no | shown when `pinned` is `true` |

### Scaffold Check Echo (`scaffold_check.echo`)

Echo a JSON value for node-author verification.

- **Type version:** 1
- **Capabilities:** supports error output, skip-optional; no retry, cancel
- **Palette:** hidden by default — enable *Show all nodes* in the node library. Executes normally wherever it is already used.

**Inputs**

| Port | Type | Notes |
|---|---|---|
| `trigger` | `control` | optional |
| `source` | `generic_json` | optional |

**Outputs**

| Port | Type | Notes |
|---|---|---|
| `control` | `control` | — |
| `result` | `generic_json` | — |
| `error` | `control` | — |

**Configuration**

| Field | Label | Widget | Default | Required | Constraints |
|---|---|---|---|---|---|
| `value` | Fallback value | `json` | `{}` | no | — |

## Built-in templates

| Template | Name | Nodes | Description |
|---|---|---|---|
| `full_video` | Full Video | `trigger.manual`, `project.setup`, `script.input`, `script.analyze`, `tts.generate`, `timing.align`, `segment.run`, `scenes.blueprint`, `storyboard.generate`, `animator.generate`, `captions.generate`, `music.select`, `assemble.project`, `timeline.project`, `export.video`, `workflow.output` | Complete ScriptToScene production workflow |
| `narration_only` | Narration Only | `trigger.manual`, `script.input`, `tts.generate`, `workflow.output` | Turn a script into narration audio |
| `storyboard_only` | Storyboard Only | `trigger.manual`, `script.input`, `tts.generate`, `timing.align`, `segment.run`, `scenes.blueprint`, `storyboard.generate`, `workflow.output` | Generate storyboard images from a script |
| `reexport_existing_project` | Re-export Existing Project | `trigger.manual`, `project.existing`, `export.video`, `workflow.output` | Render a new export from an existing timeline project |
