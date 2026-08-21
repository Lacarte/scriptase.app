# Scriptase glossary — pipeline & video-production concepts

Plain-language definitions of the terms that come up when designing the
script → video pipeline. Grouped by where they sit in the flow. Terms marked
**[Scriptase]** are how this app names or models the concept; the rest are
general video-production vocabulary worth knowing.

---

## The pipeline, end to end

**Pipeline** — the ordered chain of stages that turns a script into a finished
video: script → TTS → timing → segment → scenes → images → video → compose.
Each stage consumes the previous stage's output.

**Stage** — one step of the pipeline (e.g. "Timing", "Scene Director"). In
Scriptase a stage is a *projection* of the node graph, not its own engine.
**[Scriptase]**

**Node** — a single box in the workflow graph that runs one operation (e.g.
`tts.generate`). Nodes are the real execution model; stages are how the UI
groups them. **[Scriptase]**

**Domain / capability** — a *category* of work (script, tts, image, video, …).
A domain is the "what needs doing." **[Scriptase]**

**Provider** — the concrete *implementation* that does a domain's work (e.g.
Inworld for tts, Grok for video). A domain can have several; you pick one.
**[Scriptase]**

**Instance** — a configured binding of a provider (its saved settings, e.g. a
specific webhook URL or API key). The settings page lists instances, not raw
providers. **[Scriptase]**

**Transport / kind** — *how* a provider is reached: `cloud` (API key),
`extension` (browser extension), `webhook` (n8n), `local` (in-process). Shown
as the badge on each provider card. **[Scriptase]**

**Passerelle / gateway** — a provider that just *forwards* the request to an
external workflow (n8n) and returns its result, instead of doing the work
itself. The "Script Generator" (n8n) provider is a passerelle. **[Scriptase]**

---

## Script & narration

**Script** — the narration text the video is built from. Also called the story.

**Hook** — the opening 1–3 seconds. The single most important part of a short:
if it doesn't grab attention, nothing else matters. Viral structure front-loads
the hook.

**Beat** — a distinct unit of meaning in the script (a sentence or idea). Beats
are what get grouped into scenes.

**Viral structure** — a script template that maximizes retention, e.g.
Hook → Turn → Why → Reframe → Landing. **[Scriptase]** channels carry a script
template with a brief + section outline.

**Concept family** — a bucket of story ideas used to keep successive scripts
*diverse* (so a channel doesn't produce the same story twice). **[Scriptase]**

**TTS (text-to-speech)** — turning the script text into spoken narration audio
(Inworld, in Scriptase).

**Speaking rate** — how fast the voice talks (Inworld `speakingRate`, 0.5–1.5).
A *synthesis* parameter — the audio is generated at that speed, not stretched.
**[Scriptase]** the Channel "narration speed" maps to it.

---

## Timing (the backbone of everything visual)

**Alignment / forced alignment** — finding *when each word is spoken* in the
narration audio → word-level timestamps `{word, begin, end}`. Either the TTS
provider returns them (native word timing) or a forced-aligner (Whisper) derives
them from the audio. **[Scriptase]** the "Timing" stage does this.

**Native word timing** — timestamps the TTS provider itself returns, avoiding a
separate alignment pass. Faster and free. Inworld supports it. **[Scriptase]**

**Word span** — the start/end time range of a scene's words. A scene's
on-screen duration = its word span. This is *the* number the visuals are locked
to.

**On-screen duration** — how long a scene's image/clip is displayed. Derived
from the word span, never hand-set. Short span → short shot.

---

## Segmentation & scenes

**Segmentation** — splitting the aligned script into scene-sized chunks. Cuts
land on *natural speech pauses* (end of sentence, comma, breath), inside a
target duration band. **[Scriptase]** the "Segmenter" stage.

**Scene** — one segment of the script that becomes one visual (image/clip). A
scene has words, a start/end time, and a duration.

**Scene pacing** — how long each scene stays on screen, chosen per Channel as a
preset (Fast ~2.5–4s / Balanced ~3.5–5s / Cinematic ~5–7s) that sets the
segmenter's target band. Balanced ≈ a 5s video-clip model. **[Scriptase]**

**Scene identity** — a stable id for each scene that survives re-segmentation,
so a scene keeps its artifacts/history even if boundaries shift. Ordinal
position is just presentation. **[Scriptase]**

**Target band (target_min / target_max / hard_max)** — the min/preferred/hard
duration limits the segmenter aims for. `hard_max` forces a cut if no natural
pause is found in time. **[Scriptase]**

---

## Visual direction & continuity (the "looks directed" concepts)

**Style prompt / visual direction** — a persistent description of the video's
*look* (lighting, mood, color grade, medium) threaded into every image prompt
so all scenes share an aesthetic. Consistency of *look*. **[Scriptase]** the
Channel's `visual_direction` / `style_prompt`.

**Character bible** — a persistent, reusable description of the *recurring
subjects* — the main character(s) and key settings — injected into every scene's
image prompt so the same person/place looks consistent across shots. Without it,
the image model (which has no memory between scenes) draws a *different* person
each time, and your protagonist "morphs" through the video. Consistency of
*subject*.
  - *Style prompt* keeps the **look** consistent; the *character bible* keeps
    the **who/where** consistent. Different jobs.
  - Only needed when videos have recurring characters/places (narrative
    content). Abstract "one concept image per scene" channels don't need it.
  - Status in Scriptase: **not yet built** (a planned improvement).

**Shot type** — the film-grammar framing of a shot. Varying it across scenes is
what makes a sequence feel *edited* rather than monotonous:
  - **Wide / establishing** — the whole scene/location; sets context, often
    opens a beat.
  - **Medium** — subject from the waist up; the default "someone doing/saying."
  - **Close-up** — a face/object/hand; used for emotion or emphasis.
  - **Insert / detail / cutaway** — a specific object (a clock, a letter);
    adds texture and rhythm.
  - Status in Scriptase: **not explicitly modeled per scene yet** (a planned
    improvement). The app would pick a shot type per beat and put it in the
    image prompt.

**Continuity** — the general principle that visual elements (character, wardrobe,
location, lighting) stay consistent from shot to shot. The character bible +
style prompt are how you enforce it.

**Prompt** — the text instruction sent to an LLM / image model / video model.
In Scriptase the design principle is: **the app authors prompts** (version-
controlled, testable, consistent), **n8n/providers execute** them.

**Negative prompt** — a description of what to *avoid* in an image ("no text, no
watermark, no extra fingers"). **[Scriptase]** carried on visual direction.

---

## Video & motion

**Motion prompt** — the instruction that describes how a still image should
*move* into a clip (camera push-in, pan, parallax, subject motion). A good one
depends on the image content, the scene's duration, and what the next scene is.

**Motion mode** — which motion path a run uses. **[Scriptase]** the video
adapter resolves it per run.

**Fixed clip length** — most image→video models (e.g. Grok) return clips of a
*fixed* duration (often ~5s), not arbitrary lengths. You design *around* this:
size scenes near the clip length, then trim/cut in compose.

**Two-angle coverage** — for a scene longer than one clip, generate *two* clips
(two prompts / two angles of the same beat) and cut between them, like a real
editor covering a moment. Fills long scenes without stretching. *(Planned.)*

**Ken Burns** — a slow pan/zoom over a *still* image to give it gentle motion,
sized to any exact duration. Cheap; good for low-priority scenes or filling odd
durations. Named after the documentary filmmaker. *(Planned.)*

**Trim / cut on the beat** — in compose, shortening each clip to the scene's
exact word-span duration and cutting at the pause, so the visual changes when
the narration does. The model gives 5s; you use 4.3s and cut.

---

## Compose & finishing

**Compose / assembly** — stitching the clips together with narration, music, and
captions into the final video. **[Scriptase]** the "Assemble" / "Compose" stage.

**Music bed** — the background track under the narration. **[Scriptase]** a
Channel can use a random bed per job or a fixed one.

**Ducking** — automatically lowering the music volume while the voice is
speaking, so narration stays clear. **[Scriptase]** a Channel audio setting.

**Loudness normalization (LUFS)** — adjusting audio to a consistent perceived
loudness (so one video isn't quieter than the next). **[Scriptase]** run on TTS
output and configurable per Channel.

**Captions** — on-screen text of the narration, timed to the alignment. A local
service in Scriptase (preset/position), not a provider domain. **[Scriptase]**

**Aspect ratio** — the frame shape: 9:16 (vertical Shorts/TikTok/Reels), 16:9
(landscape), 1:1 (square). **[Scriptase]** a Channel export default.

**Export profile** — the render preset (resolution, fps, codec) for the final
video. **[Scriptase]**

---

## Quality & scoring

**Virality score** — a 0–100 estimate of how likely a script is to perform,
with a per-dimension breakdown. **[Scriptase]** the "Virality Scorer" (offline,
deterministic) can score the *script* before you spend on images/video.

**Pre-score gate** — running the virality score *before* expensive stages so a
weak script is caught cheaply. *(A design decision: warn vs. stop.)*

---

## Channels, jobs & artifacts

**Channel** — a reusable content brand: identity, style, voice, pacing, and
production rules. Lives *above* jobs; never a processing node. **[Scriptase]**

**Job** — one production run of a Channel through a workflow, from a source
(pasted script, topic, idea…). **[Scriptase]**

**Source mode** — where a job's script comes from: `paste`, `topic`, `idea`,
`automatic`, `manual`. **[Scriptase]**

**Execution mode** — how a job runs: `manual` (pauses at approval gates),
`assisted`, `automatic`. **[Scriptase]**

**Approval gate** — a checkpoint where a job pauses for you to approve before
spending money on the next stage (e.g. approve the script before TTS).
**[Scriptase]**

**Artifact** — a typed, immutable, versioned output of a stage (the audio file,
the scenes doc, an image, a clip). A repair never erases what it replaced.
**[Scriptase]**

**Repair** — targeted recovery of a *failed* scope (one scene, not the whole
video), bounded so it never loops forever. **[Scriptase]**

**Provenance** — the record of *which provider/instance/settings* produced an
artifact, kept for auditing and cost. Never holds credentials. **[Scriptase]**

---

## Providers you have today

| Domain | Provider (label) | id | Transport | What it does |
|---|---|---|---|---|
| Script | Story Generator | `script_n8n` | n8n | app builds the prompt, webhook relays to LLM |
| Script | Script Generator | `n8n` | n8n | passerelle: sends raw fields, n8n builds the prompt |
| Scene Director | Scene Director | `n8n` | n8n | plans scenes / image prompts via n8n |
| Text to Speech | Voice Generator | `inworld` | cloud | narration audio (Inworld) |
| Image | Image Generator | `gemini_ws` | extension | scene images (Gemini) |
| Video | Video Generator | `grok_automa` | extension | image→video clips (Grok) |
| Virality | Virality Scorer | `deterministic` | local | offline script score |
