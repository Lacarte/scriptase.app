# Future labs — ranked candidates

A scan of the codebase for places with tunable prompt/config logic buried in
code that shapes output quality, and would benefit from their own
variant + experiment lab (like the shipped **Script Prompt Lab**).

The pattern: a **variant** is a data bundle of knobs overriding in-code logic; an
**experiment** generates + scores; a **leaderboard** ranks variants. The hard
constraint: the offline **Virality Scorer** (`scriptase/modules/viral/`) scores
*scripts only*. Any non-script domain needs its own automated measure, or is
blocked on real performance data (views/retention).

Each candidate maps to real code (file:line). Ranked by value = impact ×
feasibility.

---

## Tier A — do first (measurable with the existing scorer, low effort)

These are **extensions of the current Script Prompt lab**, reusing the Virality
Scorer — the fastest wins, not new labs.

### A1. Topic banks / narrative lenses (highest ROI)
- **Where:** `scriptase/modules/script/prompts.py` — `_CATEGORY_TOPIC_BANKS`
  (:24), `_NICHE_TOPIC_BANKS` (:223), `_STYLE_TOPIC_BANKS` (:422),
  `_NARRATIVE_LENSES` (:447), `_RUT_WARNINGS` (:515). (`_ANGLE_STARTERS` is
  *already* a variant knob.)
- **What varies:** the topic strings, lenses, and rut-warnings a variant may
  override — a huge surface of curated strings that shape the script.
- **Measures:** the script Virality Score (already the lab's measure).
- **Effort:** low — same functions the lab already calls (`build_story_user_prompt`,
  `_build_topic_coverage_block`); just thread more override params.

### A2. Story-tone description text
- **Where:** `scriptase/channels/presets.py:1188` `STORY_TONES`; consumed at
  `script/prompts.py:551-555`. The lab already selects a tone (`tone_override`);
  this would let a variant edit the tone's *description text*.
- **Measures:** script Virality Score. **Effort:** low.

---

## Tier B — high value, medium effort (needs a new but buildable measure)

### B1. Scene Director / Image-Prompt Lab (biggest new lab)
- **Where:** `scene_director/providers/prompts.py` — `build_scene_system_prompt`
  (:234), `IMAGE PROMPT RULES` (:199), `SHOT_TYPES` (:17); `planner.py` —
  `CAMERA_GRAMMAR` (:20), `VIDEO_CAMERA_MOVES` (:29), role/peak allocation
  (`_choose_peak_index` :90); `style_compiler.py` — `DEFAULT_NEGATIVE_RULES`
  (:25), `compile_style_prompt` (:181).
- **What varies:** shot-type pools per role, camera-move phrasings, the
  image-prompt format templates, text-scene ratio, SFX budget, per-style
  negative rules.
- **Measures:** **the Virality Scorer does not apply.** But `summarize_blueprints()`
  (`planner.py:314`) already computes a free **structural** metric — shot
  variety, role distribution, anchor ratio — a lab could optimize *today*. True
  visual quality needs a render + vision-model/human judge (deferred).
- **Effort:** medium — the prompt logic is well isolated and already
  parameterized by `style_spec`/`visual_bible`/`blueprints` dicts, but a new
  structural scorer must be wired.
- **Note:** the **video / motion prompt** (Candidate: `VIDEO_CAMERA_MOVES` +
  the `VIDEO:` prompt rules) is a *subset* of this lab, not standalone —
  `video/generation.py:90` sends `scene.prompt` straight through.

---

## Tier C — low effort to parameterize, but weak/structural measure only

### C1. Segmenter / scene-pacing
- **Where:** `segmenter/service.py:119-129` (`target_min/max`, `hard_max`,
  `break_weights`, `max_silence`, rebind thresholds); band logic in
  `segmenter/algorithm.py`.
- **What varies:** the pacing band + break weights + silence handling. *(The
  Channel "Scene pacing" preset already exposes the band; a lab would let you
  measure it.)*
- **Measures:** only **structural** stats (segment-count-in-band, mean duration
  vs target, filler ratio) — no aesthetic/outcome scorer.
- **Effort:** low (config is already a plain dict), but limited payoff.

### C2. Niche-preset bundles
- **Where:** `channels/presets.py:187` `_DEFAULTS` (~100 presets).
- **Measures:** the existing scorer (presets resolve into script inputs), but
  **largely redundant** with the current Channel-driven lab.

---

## Shipped since this scan

- **LLM virality judge** (`viral` domain, provider `llm_judge`) — a *semantic*
  second opinion beside the deterministic scorer. An n8n/OpenRouter webhook
  (`scriptase-virality-llm.json`) has an LLM rate the same six frozen dimensions;
  the provider folds the reply into the frozen `ViralScore`, so the two scores
  are directly comparable. Surfaced in the Lab as **Structural | LLM** side by
  side. This does **not** close D1 below — it's a second opinion, not a
  data-calibrated scorer — but it gives a non-heuristic cross-check for free.

## Tier D — blocked on lacking an automated measure (human A/B or real analytics)

### D1. Virality Scorer config (meta-lab)
- **Where:** `viral/models.py` `DIMENSION_WEIGHTS` (:35), `SCORE_BANDS` (:47);
  `viral/scoring.py` thresholds (`SECTION_SHARE_BANDS` :28, `RHYTHM_IDEAL` :41,
  `LOOP_DENSITY_TARGET` :46, …); `viral/archetypes.py` detectors.
- **What varies:** the six dimension weights and every numeric threshold — a
  "scorer variant" is a competing config.
- **Measures:** correlation to **real** view/retention on published videos —
  **no automated ground truth exists.** High value once analytics exist; the
  `SCORER_VERSION` field already anticipates versioned scorer changes.
- **Effort:** low to build (exceptionally isolated pure functions), blocked on data.

### D2. Voice / narration selection
- **Where:** `channels/presets.py` `INWORLD_VOICE_MAP` (:55), `resolve_inworld_voice`
  (:173); TTS breathing `tts/normalize.py:210`.
- **Measures:** audio-perceptual — **no offline measure** (needs listening or
  real retention).

### D3. Music & SFX tone-mapping
- **Where:** `music/selector.py` `TONE_MUSIC_MAP` (:22), `TONE_SFX_MAP` (:35),
  mix constants (:183-192).
- **Measures:** perceptual — **none offline.**

### D4. Caption presets
- **Where:** `captions/presets.py` `CAPTION_PRESETS` (:55).
- **Measures:** visual, depends on the rendered frame — **none offline.**

---

## Recommendation

1. **Unlock the topic banks / lenses / tone text as variant knobs (A1, A2)** —
   biggest improvement per effort, and they already flow through the scoreable
   script path. These extend the existing lab; no new measure needed.
2. **Build the Scene Director / Image-Prompt Lab (B1)** next — the most
   impactful *new* domain — starting with the free structural measure
   (`summarize_blueprints`), deferring true visual quality to a render+judge.
3. Everything downstream of the script (voice, music, captions, scorer-tuning)
   is **blocked on a non-script measure** — a vision/audio judge or real
   analytics. Do these once that measurement source exists.
