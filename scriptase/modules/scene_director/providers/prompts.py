"""Prompt builders for structured scene generation."""

from __future__ import annotations

import json

from scriptase.modules.scene_director.sfx_validator import (
    SFX_BUDGET_MAX,
    SFX_BUDGET_MAX_SHORT,
    SFX_BUDGET_MIN,
    SFX_BUDGET_MIN_SHORT,
    SFX_SHORT_THRESHOLD_SECONDS,
    load_sfx_vocabulary,
)


SHOT_TYPES = (
    "extreme-close-up | close-up | medium | wide | POV | bird's-eye | "
    "low-angle | high-angle | over-shoulder | centered-symmetrical"
)


def _json_block(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=True)


def _build_header(chapter_context: str = "") -> str:
    parts = [
        "You are a visual scene planner and prompt writer for short-form viral video.",
        "",
        "## INPUT",
        "You receive JSON with:",
        "- script: full spoken transcript",
        "- style: style id",
        "- segments: array of speech segments, each with index and words",
        "- style_spec: structured visual template constraints",
        "- visual_bible: project-level continuity contract",
        "- scene_blueprints: per-segment targets for role, type, shot, and continuity",
    ]
    if chapter_context:
        parts.extend(["", chapter_context.strip()])
    return "\n".join(parts)


def _build_sfx_section() -> str:
    """Render the SFX vocabulary + budget rules block for the LLM prompt.

    Reads the live vocabulary file so adding or removing a hint in
    resources/sfx-vocabulary.json automatically updates the prompt without
    any code change. The budget numbers come from the validator constants
    so the prompt and the enforcement layer can never drift apart.
    """
    vocab = load_sfx_vocabulary()
    hints = vocab.get("hints") or {}
    if not hints:
        return ""

    # Render each hint as a compact one-line entry: id + label + description.
    # The LLM uses the description to decide WHEN to pick this hint, the id
    # to write into the sfx_hint field. Labels are informational only (the
    # editor uses them on the timeline track row).
    hint_lines = []
    for hint_id, entry in hints.items():
        label = entry.get("label", "")
        description = entry.get("description", "").strip()
        # Strip the "Files for this hint live in..." trailing sentences from
        # the description — they're for the human curator, not the LLM.
        description = description.split(" Files for this hint live in")[0].rstrip(". ") + "."
        hint_lines.append(f"- `{hint_id}` ({label}): {description}")

    hints_block = "\n".join(hint_lines)

    return f"""
## SFX HINTS (optional `sfx_hint` field)

You may optionally tag scenes with an `sfx_hint` field that requests a
specific sound effect at that scene's position on the timeline. The renderer
will pick a real sound file matching the hint and place it on the timeline
with proper volume, ducking, and timing.

### Available hints (closed list — pick from these or `null`)

{hints_block}

### SFX BUDGET (HARD RULES)

- TOTAL BUDGET per video: {SFX_BUDGET_MIN}-{SFX_BUDGET_MAX} hints maximum.
  For videos under {SFX_SHORT_THRESHOLD_SECONDS} seconds: {SFX_BUDGET_MIN_SHORT}-{SFX_BUDGET_MAX_SHORT} hints.
- Most scenes (60-80%) MUST have `sfx_hint: null`. SFX is punctuation, not wallpaper.
- `bass_drop_impact` may appear AT MOST ONCE per video, on the FINAL CLIMAX scene only.
- `tension_riser` may appear AT MOST ONCE per video, on the scene IMMEDIATELY BEFORE the climax.
- Two consecutive scenes may NOT both have hints UNLESS the pattern is exactly
  `tension_riser` followed by `bass_drop_impact` / `cinematic_hit` / `glass_shatter` / `gunshot_punctuation`.
  This riser -> impact pair is the only legal back-to-back stack.
- `text_appear`, `text_disappear`, `text_emphasis` may ONLY be used on text-type scenes
  (`type_of_scene: "text"`). Never on image or video scenes.
- `cartoon_pop` and `crowd_laugh` are FORBIDDEN unless the visual style is comedic.
  For dramatic, philosophical, suspenseful, or contemplative content: never use them.
- Looping textures (`heartbeat_pulse`, `clock_tick`, `viscous_liquid`, `keyboard_typing`,
  `rain_ambience`, `nature_ambience`, `thinking_pad`) work best on short scenes (≤4s).
  Do not place a texture on a long scene — it becomes background wallpaper and the ear stops hearing it.

### WHEN TO ADD A HINT (criteria)

A scene gets an `sfx_hint` if and only if AT LEAST ONE of these is true:

1. The script LITERALLY names an event a sound represents — a phone call, a gunshot,
   glass breaking, a clock ticking, applause. Use the matching hint.
2. The scene marks a STRUCTURAL PIVOT - hook to build, build to climax, climax to CTA.
   Use a transition or impact hint.
3. The scene is the SINGLE DOMINANT EMOTIONAL BEAT of the story — the betrayal, the
   revelation, the realization. Use the strongest fitting impact hint.

If a scene doesn't pass any of these tests, leave `sfx_hint: null`. SFX without
a specific reason is decoration and decoration is what makes videos feel cluttered.

### IDEAL ALLOCATION (mental model)

For a typical 60-second video, the {SFX_BUDGET_MAX}-hint allocation looks like:
- 1 hit on the HOOK (a bright accent, magic_shimmer or text_appear)
- 1 hit on a BUILD escalation (a subtle marker, whoosh_transition or glitch_distort)
- 1 lead-in RISER on the scene before the climax (`tension_riser`)
- 1 IMPACT on the climax scene itself (`bass_drop_impact` or `cinematic_hit`)

For a 30-second video drop the build-escalation hit and use {SFX_BUDGET_MAX_SHORT} hints total.

### THE NUCLEAR RULE

Never exceed {SFX_BUDGET_MAX} hints. If you find yourself wanting a 5th hint, REMOVE one of
the existing hints instead. Restraint produces better videos than abundance.
"""


def _build_scene_contract(include_analysis: bool) -> str:
    analysis_section = ""
    if include_analysis:
        analysis_section = """
## STEP 1: ANALYZE
Read the full script first.
Return an "analysis" object that sharpens the story's meaning while staying inside the provided VISUAL BIBLE.

Rules:
- Preserve the visual bible as the source of truth for continuity.
- You may improve wording, but do not replace the world anchor, palette guardrails, anchor subject, or camera grammar.
- The returned analysis must include:
  - core_theme
  - mood
  - environment
  - color_palette
  - tone
  - visual_style
  - visual_bible
"""
    return f"""{analysis_section}
## STEP 2: WRITE SCENES

Every scene must serve the script's meaning, not literally illustrate words.
The viewer hears the transcript while seeing the image. The image should deepen meaning, not duplicate the narration.

## RULE HIERARCHY
1. Segment contract
2. Visual bible continuity
3. Scene blueprint compliance
4. Style spec constraints
5. Creative enrichment

## SEGMENT CONTRACT
- Return exactly ONE scene for every input segment.
- Match each input index exactly.
- Do NOT merge, split, reorder, omit, or add segments.

## CONTINUITY RULES
- All scenes belong to one coherent visual world.
- Keep the anchor subject or anchor motifs visible across the sequence.
- Stay inside the palette guardrails and lighting baseline unless the script clearly demands a contrast moment.
- If you change environment, it must still feel part of the same world anchor.

## BLUEPRINT RULES
- Each scene blueprint tells you the target narrative role, preferred scene type, target shot type, camera move, and continuity priority.
- Follow the blueprint unless the segment would become nonsensical.
- Prefer exact blueprint role/type/shot matches.
- If a blueprint marks anchor_required=true, include the anchor subject or one of the anchor motifs.
- For video scenes with a camera_move field, incorporate that exact camera direction into the image_prompt as the primary camera motion cue.

## Scene object keys (output ONLY these — no extra fields)
- index: integer (match input index exactly)
- title: string (2-6 words)
- narrative_role: "hook" | "buildup" | "peak" | "transition" | "text_accent" | "cta"
- type_of_scene: "image" | "video" | "text"
- image_prompt: scene description
- text_content: string or null
- sfx_hint: string or null (see SFX HINTS section below for the closed list of legal values and budget rules)

## TYPE RULES
- First and last scenes must NOT be text.
- Default to the blueprint's preferred scene type.
- Text scenes use the hardest-hitting line only.

## IMAGE PROMPT RULES

VIDEO:
- Must feel like a living moment with motion — never a static pose.
- Format: [shot type], [subject + action], [setting], [lighting], [mood], [camera move], [1-2 ambient motion cues]
- Use the blueprint's camera_move as the primary camera direction (e.g. "slow push-in zoom", "180° orbit").
- Add at least ONE ambient motion cue from: body (gesturing, walking, turning),
  environment (wind, rain, flickering lights), atmosphere (smoke drifting, dust particles, shadows shifting).
- If no obvious action exists, use subtle ambient motion (swaying fabric, breathing, light flicker).

IMAGE:
- One frozen photographic moment.
- No motion verbs.
- Format: [shot type], [subject + details], [setting], [lighting], [mood]

TEXT:
- Use a blurred or abstract background from the same world anchor.
- Do NOT include text inside the prompt itself.

ALL TYPES:
- Valid shot types: {SHOT_TYPES}
- Start each image_prompt with the shot type.
- No two consecutive scenes may use the same shot type.
- Never mention aspect ratio or resolution.
- Weave style cues naturally into the description (lighting, texture, mood).
- NEVER append raw style labels or tag lists at the end of a prompt (e.g. "Noir, Mystery, High contrast").
  Instead, embed the style through concrete visual details throughout the description.

{_build_sfx_section()}

## OUTPUT
Return ONLY valid JSON. No markdown. No code fences. No commentary. ENGLISH ONLY.
"""


def build_scene_system_prompt(
    style_spec: dict,
    visual_bible: dict,
    scene_blueprints: list[dict],
    *,
    plan_summary: dict | None = None,
    custom_style_notes: str = "",
    continuation_state: dict | None = None,
    chapter_context: str = "",
) -> str:
    """Build the prompt used for single-call generation and chapter 1."""
    sections = [
        _build_header(chapter_context),
        "",
        "## STYLE SPECIFICATION",
        _json_block(style_spec),
        "",
        "## VISUAL BIBLE",
        _json_block(visual_bible),
    ]
    if plan_summary:
        sections.extend(["", "## GLOBAL PLAN SUMMARY", _json_block(plan_summary)])
    sections.extend(["", "## SCENE BLUEPRINTS", _json_block(scene_blueprints)])
    if continuation_state:
        sections.extend(["", "## CONTINUITY STATE", _json_block(continuation_state)])
    if custom_style_notes:
        sections.extend(["", "## CUSTOM STYLE NOTES", custom_style_notes.strip()])
    sections.extend([
        "",
        _build_scene_contract(include_analysis=True),
        "",
        """{
  "analysis": {
    "core_theme": "...",
    "mood": "...",
    "environment": "...",
    "color_palette": ["..."],
    "tone": "...",
    "visual_style": "...",
    "visual_bible": { "...": "..." }
  },
  "scenes": [
    {
      "index": 0,
      "title": "...",
      "narrative_role": "hook",
      "type_of_scene": "image",
      "image_prompt": "...",
      "text_content": null,
      "sfx_hint": "magic_shimmer"
    }
  ]
}""",
    ])
    return "\n".join(sections)


def build_scene_continuation_prompt(
    precomputed_analysis: dict,
    style_spec: dict,
    visual_bible: dict,
    scene_blueprints: list[dict],
    *,
    plan_summary: dict | None = None,
    custom_style_notes: str = "",
    continuation_state: dict | None = None,
    chapter_context: str = "",
) -> str:
    """Build the prompt used for later chapter/chunk requests."""
    analysis = dict(precomputed_analysis or {})
    analysis.setdefault("visual_bible", visual_bible)

    sections = [
        _build_header(chapter_context),
        "",
        "## PRE-COMPUTED ANALYSIS",
        "Return this analysis UNCHANGED under the `analysis` key.",
        _json_block(analysis),
        "",
        "## STYLE SPECIFICATION",
        _json_block(style_spec),
        "",
        "## VISUAL BIBLE",
        _json_block(visual_bible),
    ]
    if plan_summary:
        sections.extend(["", "## GLOBAL PLAN SUMMARY", _json_block(plan_summary)])
    sections.extend(["", "## SCENE BLUEPRINTS", _json_block(scene_blueprints)])
    if continuation_state:
        sections.extend(["", "## CONTINUITY STATE", _json_block(continuation_state)])
    if custom_style_notes:
        sections.extend(["", "## CUSTOM STYLE NOTES", custom_style_notes.strip()])
    sections.extend([
        "",
        _build_scene_contract(include_analysis=False),
        "",
        '{"analysis": {copy the pre-computed analysis exactly}, "scenes": [...]}',
    ])
    return "\n".join(sections)


SCENE_GENERATOR_PROMPT = (
    "Structured scene prompt builder module. "
    "Use build_scene_system_prompt() or build_scene_continuation_prompt()."
)
