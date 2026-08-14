# Scriptase — Machine Contracts

Frozen schemas, API shapes, and error codes. Reviewers check implementations against this
file; the orchestrator's review prompts cite it by name.

> **Status: SEED.** Written at step 0.1 so Phase 0 has something to work against.
> **Step 0.4 freezes it** by (a) adapting V2's `contracts.md` sections for node, port,
> execution-record, API, and error contracts under the new import paths, and (b) confirming
> the Scriptase-specific schemas below against the ported code. Nothing here is authoritative
> until 0.4 lands. Where this file and working code disagree after 0.4, the code wins and
> this file is corrected in the same commit.

Conventions: field names are snake_case; timestamps are ISO-8601 UTC strings; ids are opaque
strings with a documented prefix; every persisted document carries `schema_version`;
forward-only migrations, never destructive rewrites.

---

## 1. Inherited from V2 — adapted at 0.4

These are ported wholesale and must not drift during Phase 0. The authoritative source until
0.4 rewrites them here is
`D:\@Workspace\@Development\@Scripts\@Python\ScriptToScene-Studio-V2\_dev\loop-engineering\phases-plans\contracts.md`.

| Contract | Rule that must survive the port |
|---|---|
| Node definition | Ports, `config_schema`, capabilities, `type_version`, and a dotted `module:function` executor string. The backend registry is authoritative; the frontend renders from it. |
| Port types | The frozen port-type vocabulary. Renaming or adding a type is a contract change. |
| Adapter | `(inputs, config, context) -> dict[port_id, payload]`. Explicit node config beats inherited settings; an empty string is not explicit. |
| Execution record | Per-node status, attempts, duration, fingerprint, cache reason, bounded input/output summaries, artifact references, logs, structured errors. Payload bodies are never persisted, only summaries. |
| Error envelope | `{"error": {"code", "message", "details?"}}` on every API surface. |
| Provider result envelope | Typed content plus provider/domain/version, artifact refs, metadata, warnings, provenance. |
| `ProviderError` | Stable code, safe message, retryable flag, redacted details. **Retryability is owned by the platform, not the provider.** |
| Cache fingerprint | Node type, type version, configuration, inputs, upstream artifact fingerprints, adapter cache schema version. Artifact integrity is re-verified on lookup. |
| Redaction | Applied to execution records, queue records, SSE events, workflow documents, notifications, archives, and logs. |

---

## 2. Provenance — extended at 0.4

Extends the ported provenance block. **Added now, before anything is recorded**, because it
cannot be retrofitted onto past runs and because §12.1-style repair instructions ("preserve
character and composition, change lighting to sunrise") require pinning a seed and varying
one axis.

```
Provenance
- provider_type            # e.g. "wavespeed_direct"
- provider_instance_id     # which configured instance actually ran
- provider_version
- model_revision           # provider-reported model/version string, if any
- seed                     # generation seed, when the provider exposes one
- request_id               # provider-side correlation id, when available
- selection_reason         # "default" | "channel" | "node_override" | "fallback_after:<instance_id>"
- duration_ms
- cache_hit
- cost                     # {amount, currency, unit_count, unit} when reportable
```

**Per-unit rule (blocking for step 8.3):** a fallback run produces units from different
provider instances. Provenance is recorded **per unit**, not once per result. Decide and
freeze this shape before writing fallback execution.

---

## 3. Artifact

Replaces V2's `artifact_refs: list[str]` convention, which is a naming convention rather
than a type. Frozen at 0.4, implemented at 1.2.

```
Artifact
- id                       # "art_XXXXXX"
- schema_version
- job_id
- scene_id                 # nullable; set for per-scene media
- kind                     # script | audio | alignment | segments | scene_spec |
                           # image | video | captions | music | timeline | export
- version                  # 1-based, monotonic per (job_id, scene_id, kind)
- content_hash             # sha256 of the file or canonical JSON
- path                     # relative, managed, forward-slash, under output/
- size_bytes
- mime
- provenance_ref           # -> the Provenance record that produced it
- created_at
- superseded_by            # nullable artifact id
- from_sample_data         # bool; stub-derived output is never mistaken for real output
```

Rules:

- **Immutable and additive.** A repair creates version N+1 and sets `superseded_by` on
  version N. It never overwrites or deletes.
- The existing staging/promotion flow still owns writing files; the Artifact records what it
  produced.
- `path` is always relative to the managed output root. **An absolute path in an artifact
  record or a port payload is a contract violation.**
- Cache artifact-integrity re-hashing continues to operate on `path` and `content_hash`.

---

## 4. Scene identity

Frozen at 0.4, implemented at 1.6. Scenes in V2 are array indices; the review and repair
design is per-scene, and §12.2 allows an issue to route back to Segmenter — which shifts
every index.

```
Scene
- id                       # "scn_XXXXXX" — stable across re-segmentation
- job_id
- ordinal                  # presentation order only; NOT identity
- start / end / duration
- segment_words
- superseded_by            # nullable; set when re-segmentation replaces this scene
```

**Re-segmentation rule.** When the segmenter reruns, each resulting scene either:

1. **rebinds** to an existing scene id when its span is materially unchanged (artifacts and
   open issues carry over), or
2. **supersedes** one or more prior scenes (prior artifacts are marked superseded; open
   issues bound to them are re-targeted to the successor), or
3. is **new** (no inherited artifacts or issues).

No open issue or artifact may remain bound to a scene id that no longer resolves. This is
test-enforced.

---

## 5. ChannelProfile

Per §15.1. Frozen at 0.4, implemented at 1.1.

```
ChannelProfile
- id / name / version / schema_version
- branding          { logo_asset_id, enabled, position, size, opacity, margin }
- content           { niche, language, audience, script_style, tone, mood,
                      hook_style, cta_style, duration_target }
- visual_direction  { style, pattern, palette, lighting, camera, character_style,
                      continuity, negative_prompt, references[] }
- audio_defaults    { tts_provider_instance_id, voice, speed, music_profile,
                      loudness, ducking }
- captions          { preset, position, font_treatment, animation }
- provider_defaults { script, tts, scene_director, image, video, review }   # instance ids
- fallback_policies { <stage>: { primary, fallbacks[] } }                   # instance ids
- review_policy     { thresholds, max_repairs, escalation, human_checkpoints[] }
- budget            { max_generations, max_cost, currency }
- export_defaults   { aspect_ratio, resolution, fps, profile }
- default_workflow_id
```

`visual_direction.pattern` is **structured**, never free text (§4.2):

```
pattern: [ { narrative_role: "hook",           shot: "extreme close-up" },
           { narrative_role: "explanation",    shot: "medium cinematic" },
           { narrative_role: "emotional_beat", shot: "wide environmental" },
           { narrative_role: "ending",         shot: "symbolic visual" } ]
```

`provider_defaults` and `fallback_policies` hold **provider instance ids**. A Channel may
override safe non-secret generation defaults (model, aspect ratio, prompt suffix, voice). It
never holds credentials.

---

## 6. Job

Per §15.2. Frozen at 0.4, implemented at 1.4.

```
Job
- id / schema_version
- channel_id
- channel_snapshot         # non-secret channel config + provider INSTANCE REFERENCES
- workflow_id / workflow_version
- execution_mode           # manual | assisted | automatic
- source                   { mode, topic, idea, pasted_script, references[] }
- status                   # queued | running | awaiting_approval | paused |
                           # completed | failed | cancelled
- current_stage
- artifacts[]              # artifact ids
- scenes[]                 # scene ids
- issues[]                 # review issue ids
- repair_history[]
- budget_spent             { generations, cost }
- execution_id
- created_at / started_at / completed_at
```

Rules:

- The snapshot captures non-secret configuration and provider **instance references** only.
  Secrets resolve from the instance at runtime and never enter a Job (§4.3, §21).
- Job status **derives** from the execution record so the two cannot disagree.
- A Job is an orchestration object, not a node. It never appears in the node registry.

---

## 7. ProviderInstance

Per §15.3, extended for the type/instance split. Frozen at 0.4, implemented at 3.1.

```
ProviderInstance
- instance_id              # NEW axis; unique within a domain
- provider_type            # the discovered package id (folder/manifest id)
- domain
- display_name
- enabled
- settings                 # non-secret; secrets held as {"$secret": "<ref>"}
- limits                   { rate, quota, max_concurrency }
- capabilities[]           # from the type manifest
- availability             # available | needs_configuration | degraded
- health_state / last_health_check
```

Settings store shape:

```
domains: { <domain>: { selected_instance_id, instances: {
             <instance_id>: { type, label, settings } } } }
```

Rules:

- Provider **type** is discovered from the filesystem; provider **instance** is user-created
  configuration. Two instances of one type are independent in settings, availability, and
  health.
- Construction is memoized per `(type, instance_id)`; the exclusivity lock keys on the same
  pair.
- `manifest.environment` env-fallback is per **type** and therefore ambiguous once instances
  exist — it applies to the default instance only.
- **No credential is ever stored inline.** Secrets are references resolved at call time.

---

## 8. SceneSpec

Per §11. Frozen at 0.4, implemented at 5.1. Carried on the stable scene id from §4 above.

```
SceneSpec
- scene_id
- narration
- visual_description
- image_prompt
- motion_prompt
- camera
- lighting
- mood
- continuity               # e.g. "same protagonist and wardrobe as previous scene"
- narrative_role           # hook | buildup | explanation | emotional_beat | peak |
                           # transition | cta | ending
- overlay_hints / sfx_hints
```

The Image and Video adapters consume `SceneSpec`, not loose dicts. **No prompt text lives
outside a provider package** — the Scene Director composes from Channel visual direction and
the provider owns wording.

---

## 9. ReviewIssue

Per §15.4. Frozen at 0.4, implemented at 7.2.

```
ReviewIssue
- id / schema_version
- job_id
- scene_id                 # nullable
- target_node_id
- target_artifact_id
- issue_type               # visual_mismatch | continuity_break | motion_defect |
                           # audio_defect | timing_drift | segmentation_defect |
                           # script_defect | technical_defect | policy_violation
- severity                 # low | medium | high | critical
- confidence               # 0.0–1.0
- reason                   # human-readable, safe, bounded
- suggested_action         # regenerate | re-prompt | adjust | escalate | accept
- repair_instruction       # what to preserve and what to change
- attempt_count
- status                   # open | repairing | resolved | escalated | accepted
- created_at / resolved_at
```

**Free-form text is not an acceptable review output.** A reviewer that cannot produce a
structured issue fails; automation depends on structure.

Routing table (§12.2) — table-driven, not scattered conditionals:

| Detected problem | Routes to |
|---|---|
| Script too long, wrong tone, weak hook | Script |
| Pronunciation or voice problem | TTS |
| Words do not align with audio | Timing |
| Poor or overlong scene boundaries | Segmenter |
| Visual concept does not represent narration | Scene Director |
| Wrong character, object, or style in a still | Image Generator |
| Motion deformation, instability, poor animation | Video Generator |
| Caption outside safe area, branding missing | Composer |
| Render corruption, codec failure | Export |

---

## 10. Stage projection

Frozen at 0.4, implemented at 2.2. The mechanism that keeps the Production and Workflow
views from diverging.

```
StageProjection
- stages[]  { key, label, ordinal, node_ids[], status, provider_capable,
              active_provider_instance_id?, artifacts[], issues[] }
```

Rules:

- The projection is **computed from the graph on the backend**. A hardcoded step array in
  the frontend is a contract violation.
- Side branches (captions, music, branding, validators) collapse into the stage where they
  merge. Adding a parallel branch changes the graph without adding a step.
- Stage status derives from its member nodes' execution records. There is no separate
  status store.
- Step actions map onto existing run modes only. **No new execution path may be introduced
  for the Production view.**

---

## 11. Approval checkpoints

Frozen at 0.4, implemented at 2.6. §8 Assisted mode and the §18 Approve action.

```
ApprovalCheckpoint
- job_id / execution_id / node_id / stage_key
- reason                   # script_approval | critical_issue | budget_ceiling | policy
- created_at / expires_at  # nullable
- status                   # awaiting | approved | rejected | expired
- decided_by / decided_at
```

Rules:

- `awaiting_approval` **releases the worker thread** and persists the resume point. Blocking
  a pool thread on human input is a contract violation.
- The state survives a process restart and resumes from exactly where it paused.
- Manual mode approves explicitly; Automatic mode pauses only on configured unrecoverable
  conditions.

---

## 12. Budget and admission control

Frozen at 0.4, implemented at 3.5 (enforcement) and 9.3 (accounting).

- Budget is checked **pre-flight**: work that would exceed a Channel's or Job's ceiling is
  refused before the provider is called. Post-hoc reporting is not enforcement.
- A single bounded global work pool replaces per-project drain threads, preserving
  per-project FIFO ordering.
- Repair budgets (§12.5) are enforced through the same path: maximum attempts per issue,
  maximum generations and cost per Job, escalation on repeated failure, and configured safe
  degradation.

---

## 13. Error codes

The ported workflow and provider error catalogues carry over unchanged and are restated here
at 0.4. New Scriptase codes:

| Code | Meaning | Retryable |
|---|---|---|
| `CHANNEL_NOT_FOUND` | Referenced channel id does not resolve | no |
| `CHANNEL_INVALID` | Channel document failed schema validation | no |
| `JOB_NOT_FOUND` | Referenced job id does not resolve | no |
| `JOB_TERMINAL` | Operation invalid for a completed/failed/cancelled job | no |
| `ARTIFACT_NOT_FOUND` | Artifact id does not resolve | no |
| `ARTIFACT_SUPERSEDED` | Operation targeted a superseded artifact version | no |
| `SCENE_NOT_FOUND` | Scene id does not resolve after re-segmentation | no |
| `PROVIDER_INSTANCE_NOT_FOUND` | Instance id does not resolve in its domain | no |
| `BUDGET_EXCEEDED` | Pre-flight check refused the work | no |
| `APPROVAL_REQUIRED` | Execution paused awaiting a human checkpoint | n/a |
| `REPAIR_LIMIT_REACHED` | Issue exhausted its repair budget; escalated | no |

---

## 14. Open questions for step 0.4

1. Artifact store layout — keep V2's per-module output directories (required for V2 import
   compatibility) while adding the artifact index, or introduce a content-addressed blob
   directory alongside them?
2. Scene rebinding threshold — what span overlap counts as "materially unchanged" in §4's
   re-segmentation rule?
3. Whether `Job.status` needs `paused` as distinct from `awaiting_approval`, or whether one
   state with a reason field is sufficient.
4. Whether cost is normalised to a single currency at record time or at report time.
5. Which V2 error codes are renamed by the domain rename pass and therefore need aliases in
   the single documented migration module.
