# Scriptase production pipeline — design & plan

Working design for the script → video pipeline, merging the two drafts,
reconciled against what the codebase already does, with the gaps and
improvements called out. **Status tags** mean:

- ✅ **exists** — already implemented in the pipeline
- 🟡 **partial** — exists but incomplete for this design
- 🔴 **missing** — not built yet
- ❓ **decision** — needs your input (see the Open Questions at the end)

The one principle everything hangs off:

> **The app owns *what to say and its structure* (prompts, continuity, timing,
> pacing — version-controlled, testable, consistent). n8n owns *executing the
> call* (LLM/image/video invocation, retries, chaining, research).**

---

## The merged pipeline

```
STAGE 1 — SCRIPT                                                   [domain: script]
  app builds the viral-structure prompt  →  n8n calls the LLM  →  script text
  ✅ script domain, both providers use the n8n webhook transport (N8N badge);
     they differ by WHERE the prompt is authored:
       • "Story Generator"  — the APP builds the prompt in prompts.py and the
         n8n webhook just relays it to the LLM (internal id `gemini`, kept as a
         frozen migration anchor; the name is never user-facing)
       • "Script Generator" — the passerelle sends RAW fields and the n8n
         workflow builds the prompt itself (internal id `n8n`)
  🟡 which one is the default is the prompt-ownership decision (❓Q1)

        ↓

TIMING — TTS + ALIGN                                              [domain: tts, module: timing]
  narration audio (Inworld)  →  word-level timestamps
  ✅ TTS (Inworld) + timing.align (native word timings OR Whisper fallback)
  → this is where per-scene on-screen duration comes from. NEVER skipped.
  🐛 FIXED this session: dispatch.synthesize NameError blocked first-time TTS.

        ↓

SEGMENT — SPLIT INTO SCENES                                       [module: segmenter, scenes]
  group words into ~5s scenes at natural speech pauses; stamp stable scene ids
  ✅ segmenter (natural-pause cutting within a duration band)
  ✅ stable scene identity (scene_id persists across re-segmentation)
  ✅ Scene pacing preset (Fast/Balanced/Cinematic) — Channel setting → band
     • Balanced = 3.5–5s, targets one scene per ~5s video clip

        ↓

STAGE 2 — SCENE DIRECTOR → IMAGE                                  [domain: scene_director, image]
  per-scene prompt (continuity + shot type)  →  n8n plans scenes / image prompts
  per-scene image prompt  →  image provider (Gemini ext)  →  image
  ✅ scene_director domain (n8n "Scene Director") + image domain (Gemini)
  🟡 style_prompt / visual_direction threads through; a full CHARACTER BIBLE
     (same person/place consistent across shots) is NOT threaded (🔴, decision ❓Q3)
  🔴 explicit per-scene shot type (wide/close/insert) not modeled

        ↓

STAGE 3 — VIDEO                                                   [domain: video]
  per scene, the app PICKS a fill strategy from duration + priority:
    • motion clip        (default)
    • two-angle coverage (long scenes > clip length)         🔴 not built
    • still + Ken Burns  (budget / low-priority scenes)      🔴 not built
  app builds the motion prompt (from image + NEXT scene + timing)
    →  n8n returns motion prompt  →  video provider (Grok, ~5s clips)  →  clip(s)
  ✅ video domain (Grok) + motion_mode resolution + duration reaches the request
  🟡 motion prompt does not yet use image + next-scene + exact duration together
  🔴 the fixed 5s clip length is not yet reconciled per-scene (trim/loop/cut)

        ↓

STAGE 4 — COMPOSE                                                 [module: compose]
  trim each clip to the scene's EXACT word-span duration, cut on the beat,
  layer narration + music (random bed) + captions
  ✅ compose stage exists; music (random bed) + captions wired
  🟡 "trim each clip to exact duration + cut on beat" — verify it uses the
     per-scene alignment span, not a fixed cut (decision ❓Q4)

        ↓
                         FINAL VIDEO
```

### Optional quality gate (recommended, cheap)

```
VIRAL PRE-SCORE  [domain: viral]  ✅ exists (Virality Scorer)
  score the SCRIPT (0–100) BEFORE spending on images/video.
  🟡 wired as a node; confirm it can gate/branch the run (decision ❓Q5)
```

---

## Why the timing drives everything (the 5s-clip answer)

You never hand-set scene length. It is **derived**:

1. script → **TTS** → narration audio (real duration, e.g. 47.3s)
2. **alignment** → word-level `{word, begin, end}` timestamps
3. **segment** → group words into scenes at natural pauses, inside the pacing
   band → each scene has an exact `start`/`end`/`duration`
4. a scene that needs 4.5s of visual gets a ~5s clip, **trimmed to 4.5s** and
   cut on the boundary in compose

**The 5s cap is a segmentation setting, not a video problem.** Set the pacing
band ≈ the model's clip length (Balanced 3.5–5s ↔ 5s clips) and each scene maps
1:1 to a clip at native length. Vary within the band (natural pauses already do
this) so cuts don't feel metronomic.

For scenes that won't fit one clip:
- **> clip length** → two-angle coverage (two prompts, cut between) 🔴
- **budget/low-priority** → still + Ken Burns pan sized to duration 🔴
- **the hook (first ~2s)** → always a motion clip, strongest move 🔴

---

## What's genuinely missing (priority order)

1. 🔴 **Reconcile 5s clips per scene** (trim/loop/two-angle/Ken-Burns). Without
   it, clip length and scene length drift → slideshow feel. *Highest impact.*
2. 🔴 **Character/continuity bible** threaded into every image prompt. Without
   it, the same character looks different every shot. *Second highest.*
3. 🟡 **Motion prompt uses image + next-scene + exact duration.** Today it's
   generic. Duration → motion intensity (short = punchy, long = slow).
4. 🟡 **Confirm compose trims to the exact word-span** and cuts on the beat.
5. 🟡 **Decide the n8n prompt-ownership split** (Q1) — the biggest architectural
   choice; everything downstream inherits from it.
6. 🔴 **Shot-type per scene** (wide/close/insert) for visual variety.
7. 🟡 **Viral pre-score as a real gate**, not just a node that scores.

---

## Open questions (need your answers)

**Q1 — n8n prompt ownership.** For Stage 1 (and 2/3), does the APP build the
prompt and n8n just execute the LLM call (recommended: version-controlled,
testable, consistent), or does N8N build the prompt from raw fields (flexible,
but prompts leave git and continuity is harder)? My recommendation: app builds,
n8n executes — make the gemini "Story Generator" model the default.

**Q2 — one webhook or three?** Script, Scene, and Video n8n providers currently
all default to `N8N_STORY_WEBHOOK_URL`. Do you want three separate n8n workflows
(one per stage, cleaner) or one workflow that branches on stage?

**Q3 — character bible.** Do your videos have recurring characters/places that
must look consistent across shots (needs a bible), or is each scene visually
independent (no bible needed)?

**Q4 — clip vs scene length.** When a scene is 4.5s and the model gives a 5s
clip, do you want: trim to 4.5s (recommended), or hold/loop, or speed-adjust?
And for scenes LONGER than one clip — two-angle coverage, or a longer single
clip if the model supports it?

**Q5 — viral gate.** Should a low viral score STOP the run (save money) or just
warn and continue?

**Q6 — target video length / platform.** What's the typical final length
(e.g. 30s / 60s Shorts) and platform (YT Shorts / TikTok / IG)? This sets the
default pacing band and aspect ratio.

**Q7 — motion everywhere?** Do you want a video clip on every scene, or is a mix
of motion clips + still-with-Ken-Burns acceptable (cheaper, and often *better* —
constant motion is tiring to watch)?
