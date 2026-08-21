"""Lab #1 — the Script Prompt lab.

Tunes the prompt that writes narration scripts (scriptase.modules.script.prompts)
and measures each variant with the offline Virality Scorer. This module is the
reference implementation of a lab: a metadata block, the variant knobs, the real
engine defaults shown pre-filled, and the two engine hooks.
"""

from __future__ import annotations

from scriptase.modules.lab.experiment import build_prompt, run_experiment
from scriptase.modules.lab.registry import LabDescriptor, VariantField, register
from scriptase.modules.script.prompts import _ANGLE_STARTERS


# The built-in control's fields, shown PRE-FILLED with the engine's real
# defaults so a user can see and clone them. Empty `angle_pool` in a *stored*
# variant means "use the built-in pool"; here we surface that pool so it is
# visible rather than blank.
_DEFAULT_VARIANT = {
    "angle_pool": list(_ANGLE_STARTERS),
    "extra_directives": [],
    "tone_override": "",
    "language_level": "",
    "temperature": None,
    "word_target_ratio": 1.0,
}


SCRIPT_PROMPT_LAB = LabDescriptor(
    id="script_prompt",
    name="Script Prompt Lab",
    description="Tune and A/B the prompt that writes your narration scripts.",
    purpose=(
        "The script prompt decides the quality, structure, and variety of every "
        "video's narration. This lab makes that prompt tunable and measurable "
        "instead of frozen in code — so you can improve it deliberately."
    ),
    how_to=(
        "1) In Variants, clone the built-in control and change one knob (e.g. "
        "restrict the angle pool to question-hooks, or add a directive). "
        "2) In Test, pick a Channel, a provider, and your variant, then Run — it "
        "generates a real script and scores it. 3) Run the control too and "
        "compare side by side. 4) Watch the Performance leaderboard to see which "
        "variant averages the best score, then keep the winner."
    ),
    measures=(
        "The Virality Score (0–100) and its per-dimension breakdown (hook, "
        "pacing, opening line, …) from the offline, deterministic Virality "
        "Scorer — so a prompt change is measurable immediately, before any real "
        "view data exists."
    ),
    domain="script",
    provider_domain="script",
    variant_fields=(
        VariantField(
            "angle_pool", "Angle pool", "list",
            help="One opening angle per line. Empty uses the built-in pool of 15.",
            default=[],
        ),
        VariantField(
            "extra_directives", "Extra directives", "list",
            help="Extra instruction lines appended to the prompt, one per line.",
            default=[],
        ),
        VariantField("tone_override", "Tone override", "text",
                     help="Force a narration tone. Empty keeps the channel's tone.",
                     default=""),
        VariantField(
            "language_level", "Language level", "select",
            options=("", "beginner", "intermediate", "advanced", "native"),
            help="Vocabulary complexity. Empty uses the default.", default="",
        ),
        VariantField("temperature", "Temperature", "number",
                     help="LLM sampling temperature (0–2). Empty uses the provider default.",
                     default=None, min=0, max=2, step=0.1),
        VariantField("word_target_ratio", "Word target ×", "number",
                     help="Scale the duration-derived word target (0.5–2).",
                     default=1.0, min=0.5, max=2, step=0.05),
    ),
    default_variant=_DEFAULT_VARIANT,
    build_prompt=build_prompt,
    run_experiment=run_experiment,
)

register(SCRIPT_PROMPT_LAB)

__all__ = ["SCRIPT_PROMPT_LAB"]
