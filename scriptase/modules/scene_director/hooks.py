"""Hook animation assignment for text scenes.

Moved verbatim out of V2's ``studio/pipeline/services.py`` in step 0.3.
``scriptase.modules.pipeline`` does not exist and never will, so the one helper
``scene_director/service`` needed from it lives here instead.
"""

from loguru import logger


# ── Hook animation tone subgroups (mirrors frontend TONE_HOOK_GROUP) ──
_TONE_HOOK_GROUP = {
    "suspenseful":   ["tension_flicker", "shadow_pulse", "creep_reveal"],
    "dramatic":      ["dramatic_slam", "power_drop", "storm_shake", "force_expand"],
    "epic":          ["movie_title", "epic_rise", "legend_zoom"],
    "comedic":       ["bouncy_pop", "cartoon_slide", "gag_drop"],
    "inspirational": ["uplift_rise", "dawn_glow", "horizon_fade"],
    "educational":   ["teach_type", "chalk_slide", "focus_pop"],
    "horror":        ["dread_shake", "nightmare_glitch", "void_fade"],
    "wholesome":     ["warm_glow", "gentle_wave", "dawn_glow"],
    "romantic":      ["heart_rise", "warm_glow", "gentle_wave"],
    "nostalgic":     ["memory_drift", "echo_blur", "wistful_fade"],
    "melancholic":   ["wistful_fade", "memory_drift", "echo_blur"],
    "meditative":    ["zen_breathe", "gentle_wave", "thought_fade"],
    "philosophical": ["thought_fade", "stoic_reveal", "horizon_fade"],
    "stoic":         ["stoic_reveal", "thought_fade", "force_expand"],
    "motivational":  ["neon_pulse", "rally_slam", "uplift_rise"],
    "urgent":        ["rush_slide", "alarm_flicker", "shadow_pulse"],
    "dark":          ["dark_glitch", "nightmare_glitch", "void_fade"],
    "mysterious":    ["cipher_blur", "creep_reveal", "echo_blur"],
    "cinematic":     ["story_reveal", "movie_title", "epic_rise"],
}
_ALL_HOOKS = ["dramatic_slam", "movie_title", "uplift_rise", "bouncy_pop", "teach_type"]


def _assign_hook_animations(result, story_tone):
    """Assign a random hook animation to each text scene from the tone's subgroup."""
    import random
    scenes = result.get("scenes", [])
    text_scenes = [s for s in scenes if str(s.get("type_of_scene", "")).lower() == "text"]
    if not text_scenes:
        return

    pool = list(_TONE_HOOK_GROUP.get(story_tone, _ALL_HOOKS))
    if not pool:
        pool = list(_ALL_HOOKS)

    random.shuffle(pool)
    for i, scene in enumerate(text_scenes):
        hook = pool[i % len(pool)]
        scene["text_hook_animation"] = hook
        logger.debug("Assigned hook animation '{}' to text scene {}", hook, scene.get("index", i))
