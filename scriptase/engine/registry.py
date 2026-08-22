"""Authoritative node-type registry for the workflow builder.

Single source of truth (contracts.md §2-§3): port IDs, port types, config
schemas, defaults, and capabilities for every node type. The frontend
consumes the presentation-safe form served by GET /api/workflow/node-types;
the execution engine (Phase 3) dispatches through the internal ``executor``
field, which is never serialized.
"""

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

from scriptase.providers.domains import DOMAINS

# 4 adds the `provider` / `provider_options` config widgets (step 12.3).
# 5 adds the presentation-only `hidden` flag (step 12.1).
REGISTRY_VERSION = 5

# contracts.md §3 — frozen v1 port vocabulary.
PORT_TYPES = [
    "control", "text", "script", "project_id", "project_settings",
    "audio_file", "tts_metadata", "alignment", "segments", "scenes",
    "image_prompts", "storyboard_images", "animation_assets", "captions",
    "music_track", "editor_project", "export_profile", "video_file",
    "generic_json",
]

# Data types a dynamic port (workflow.output, stub.*) may resolve to.
DYNAMIC_PORT_TYPES = [t for t in PORT_TYPES if t != "control"]

@dataclass(frozen=True)
class OptionSourceSpec:
    """One allowlisted async option source (contracts.md §23.1).

    ``context`` is the allowlist of query parameters the source accepts; any
    other parameter is rejected rather than ignored, because silently dropping a
    misspelling resolves options for the wrong provider. ``cache`` picks the
    invalidation policy in ``options.py``. ``domain`` scopes the source to one
    provider domain: it is the default for an omitted ``domain`` parameter, and
    it is what lets one resolver serve all five ``*_providers`` sources.
    """

    context: tuple[str, ...] = ()
    cache: str = "static"
    domain: str | None = None


# Cache policies (contracts.md §23.4): process lifetime, invalidated on provider
# discovery and dev reload, or TTL plus explicit invalidation on a settings or
# selection write.
CACHE_POLICIES = frozenset({"static", "discovery", "settings"})

# contracts.md §11/§23.1 — backend-approved async option sources. `caption_presets`
# reconciles §2 (captions.generate: "approved preset id") with the allowlist.
ASYNC_OPTION_SOURCES = {
    # Step 3.2: `instance` lets a voice list follow the selected binding when
    # two instances of one type hold different credentials / catalogs.
    "tts_voices": OptionSourceSpec(
        context=("domain", "provider", "instance"), cache="settings", domain="tts"
    ),
    # Instance lists change on settings writes (create/select instance), so
    # these use the settings cache policy rather than discovery alone.
    "script_providers": OptionSourceSpec(cache="settings", domain="script"),
    "scene_director_providers": OptionSourceSpec(
        cache="settings", domain="scene_director"
    ),
    "tts_providers": OptionSourceSpec(cache="settings", domain="tts"),
    "image_providers": OptionSourceSpec(cache="settings", domain="image"),
    "video_providers": OptionSourceSpec(cache="settings", domain="video"),
    # Step 11.1: the sixth domain finally gets a node. Adding it is exactly what
    # P32 promised — one spec entry plus one `_RESOLVERS` line, no new resolver
    # and no frontend edit.
    "review_providers": OptionSourceSpec(cache="settings", domain="review"),
    # Step 16.2: the seventh domain, and the second time that promise held —
    # one spec entry plus one `_RESOLVERS` line.
    "viral_providers": OptionSourceSpec(cache="settings", domain="viral"),
    # Read by an image provider's own `image_model` setting (§22.4). The
    # Storyboard page used to fetch this list itself and render a bespoke
    # `<select>` beside its webhook fields; step 12.4 moved the field into the
    # provider that consumes it, and this is how the option list follows.
    #
    # A source named by a provider's own `ui.options_source` is always resolved
    # *for that provider instance*, so it must accept `domain`, `provider`, and
    # `instance` — the settings renderer has no way to know which sources want
    # them and sends all three to every one.
    "image_models": OptionSourceSpec(
        context=("domain", "provider", "instance"), cache="settings", domain="image"
    ),
    "story_tones": OptionSourceSpec(),
    "style_templates": OptionSourceSpec(),
    "export_profiles": OptionSourceSpec(),
    "caption_presets": OptionSourceSpec(),
}

assert all(spec.cache in CACHE_POLICIES for spec in ASYNC_OPTION_SOURCES.values()), (
    "unknown option-source cache policy"
)

CATEGORIES = {
    "input":   {"label": "Input",   "color": "#4ECDC4"},
    "audio":   {"label": "Audio",   "color": "#A78BFA"},
    "timing":  {"label": "Timing",  "color": "#60A5FA"},
    "ai":      {"label": "AI",      "color": "#F472B6"},
    "assets":  {"label": "Assets",  "color": "#FBBF24"},
    "video":   {"label": "Video",   "color": "#34D399"},
    "output":  {"label": "Output",  "color": "#F87171"},
    "utility": {"label": "Utility", "color": "#9CA3AF"},
    "testing": {"label": "Testing", "color": "#78716C"},
}

_ASPECT_RATIOS = ["9:16", "16:9", "1:1"]


def _quality_gate_fields():
    """The early-quality-gate keys the gate has always read (step 11.1).

    `enforce_image_gate_for_video` has read all three off the node
    configuration since step 7.4 (`review/gates.py:712, 751, 757`) while no node
    declared them. Because save-time validation rejects an undeclared key
    (`validation.py:325-327`), setting one was impossible and the gate ran on
    its hardcoded fallbacks forever. Declaring them is the whole fix — the
    reading code is untouched.

    These are additive optional keys with defaults, which contracts §41.2
    states explicitly does **not** bump `type_version`: nothing is renamed,
    removed, or re-typed, so every saved workflow keeps loading and its
    configuration fingerprint (and therefore its cache) stays valid. A bump
    would demand a migration whose only job is to write the defaults.
    """
    return [
        {"name": "skip_quality_gate", "label": "Skip the image quality gate",
         "type": "boolean", "default": False,
         "description": (
             "Animate without checking the source stills first. The gate is what "
             "stops an expensive generation starting from a broken image."
         )},
        {"name": "image_gate_max_repairs", "label": "Image gate repair attempts",
         "type": "number", "default": 1, "min": 0, "max": 5, "step": 1, "integer": True,
         "description": "How many times a failing still may be regenerated before the gate blocks.",
         "display_options": {"hide": {"skip_quality_gate": [True]}}},
        {"name": "image_gate_semantic", "label": "Add semantic review to the image gate",
         "type": "boolean", "default": False,
         "description": (
             "Run the semantic reviewer alongside the always-on technical "
             "validators. Slower, and it may cost a provider call."
         ),
         "display_options": {"hide": {"skip_quality_gate": [True]}}},
    ]


def _in(port_id, port_type, *, required=False):
    return {"id": port_id, "type": port_type, "required": required, "multiple": False}


def _out(port_id, port_type):
    return {"id": port_id, "type": port_type}


_TRIGGER_IN = _in("trigger", "control")
_CONTROL_OUT = _out("control", "control")


# ---------------------------------------------------------------------------
# The generic provider primitive (step 12.3)
# ---------------------------------------------------------------------------

# Two config widgets that a node parameterizes with nothing but a domain id.
# `provider` selects one registered provider of `provider_domain`;
# `provider_options` is that provider's per-run settings patch, validated
# against whichever provider is selected (contracts.md §22, §40.2 O1).
PROVIDER_FIELD = "provider_id"
PROVIDER_OPTIONS_FIELD = "provider_options"
PROVIDER_WIDGETS = frozenset({"provider", "provider_options"})


def _provider_field(domain):
    """The one provider-selection field, generated from a domain id alone.

    Every provider-specific thing about it — the option list, the default —
    comes from the domain catalog and the live registry, so no provider id is
    written into a node definition and adding a provider needs no edit here
    (contracts.md §26).
    """
    return {
        "name": PROVIDER_FIELD,
        "label": "Provider",
        "type": "provider",
        "provider_domain": domain,
        "options_source": f"{domain}_providers",
        "default": DOMAINS[domain].default_provider,
        "required": True,
    }


def _provider_options_field(domain):
    """Per-run overrides for the selected provider's own settings."""
    return {
        "name": PROVIDER_OPTIONS_FIELD,
        "label": "Provider options",
        "type": "provider_options",
        "provider_domain": domain,
        "default": {},
        "description": (
            "Overrides applied on top of this provider's saved settings for "
            "this node only. Credentials belong in provider settings."
        ),
    }


# ---------------------------------------------------------------------------
# Node catalog — port IDs frozen per contracts.md §3.1.
# ---------------------------------------------------------------------------

# `hidden` (step 12.1) is presentation only: it keeps a node out of the palette
# by default and nothing else. Hidden nodes stay registered, validated, saved,
# and executable, so a workflow that already uses one keeps loading and running.
# It defaults to False and is normalized onto every definition in
# `reload_generated_node_types`, so the served payload always states visibility
# explicitly rather than leaving the client to infer it from the category.

_NODE_TYPES = {
    "trigger.manual": {
        "type_version": 1,
        "display_name": "Execution",
        "description": "Emits one control token when the run starts.",
        "category": "input",
        "icon": "play",
        "schema": {"sub": "Job trigger", "glyph": "▶", "accent": "#3fb68b", "role": "flow"},
        "inputs": [],
        "outputs": [_CONTROL_OUT],
        "config_schema": [],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.control:manual_trigger",
    },
    "project.setup": {
        "type_version": 1,
        "display_name": "Channel",
        "description": "Project identity, branding, and creative defaults shared by downstream nodes.",
        "category": "input",
        "icon": "briefcase",
        "schema": {"sub": "Inherited config", "glyph": "◆", "accent": "#5b8cff", "role": "flow"},
        "inputs": [_TRIGGER_IN],
        "outputs": [_CONTROL_OUT, _out("settings", "project_settings")],
        "config_schema": [
            {"name": "project_name", "label": "Project name", "type": "string", "default": "", "max_length": 120},
            {"name": "channel_name", "label": "Channel name", "type": "string", "default": "", "max_length": 120},
            {"name": "logo_enabled", "label": "Show logo on video", "type": "boolean", "default": False},
            {"name": "logo", "label": "Logo image", "type": "media_asset",
             "accept": ["png", "jpg", "jpeg", "webp"], "default": None,
             "display_options": {"show": {"logo_enabled": [True]}}},
            {"name": "logo_position", "label": "Logo position", "type": "options", "default": "top_right",
             "options": ["top_left", "top_right", "bottom_left", "bottom_right", "center"],
             "display_options": {"show": {"logo_enabled": [True]}}},
            {"name": "logo_size", "label": "Logo size (% of width)", "type": "number",
             "default": 10, "min": 2, "max": 40, "step": 1,
             "display_options": {"show": {"logo_enabled": [True]}}},
            {"name": "logo_opacity", "label": "Logo opacity", "type": "number",
             "default": 0.9, "min": 0.05, "max": 1.0, "step": 0.05,
             "display_options": {"show": {"logo_enabled": [True]}}},
            {"name": "logo_margin", "label": "Logo margin (px)", "type": "number",
             "default": 32, "min": 0, "max": 200, "step": 1,
             "display_options": {"show": {"logo_enabled": [True]}}},
            {"name": "tone", "label": "Story tone", "type": "options",
             "options_source": "story_tones", "default": ""},
            {"name": "style", "label": "Visual style", "type": "options",
             "options_source": "style_templates", "default": "cinematic"},
            {"name": "aspect_ratio", "label": "Aspect ratio", "type": "options",
             "options": _ASPECT_RATIOS, "default": "9:16"},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.project:setup",
    },
    "script.input": {
        "type_version": 1,
        "display_name": "Script Input",
        "description": "The narration script that drives the production.",
        "category": "input",
        "icon": "file-text",
        "inputs": [_TRIGGER_IN],
        "outputs": [_CONTROL_OUT, _out("script", "script")],
        "config_schema": [
            {"name": "text", "label": "Script", "type": "textarea", "default": "",
             "required": True, "min_length": 1, "max_length": 10000},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.project:script_input",
    },
    "story.generate": {
        "type_version": 1,
        "display_name": "Story Generator",
        "description": "Generate a structured narration script with the selected script provider.",
        "category": "ai",
        "icon": "sparkles",
        # An alternative to Script Input rather than a Full Video stage.
        "hidden": True,
        "inputs": [_TRIGGER_IN, _in("settings", "project_settings")],
        # `script` carries the narration text for TTS/scenes edges. `story`
        # (step 13.3) is the full document + managed artifact ref that the
        # adapter always emitted but the registry never declared (contracts
        # §14.7) — declare it so edges/expressions can target it.
        "outputs": [
            _CONTROL_OUT,
            _out("script", "script"),
            _out("story", "generic_json"),
        ],
        "config_schema": [
            # M4 (contracts.md §41.3): a new optional key with a default, so no
            # `type_version` bump — a saved config that predates it keeps
            # running the bridge provider without being rewritten.
            _provider_field("script"),
            {"name": "preset_style", "label": "Visual style", "type": "options",
             "options_source": "style_templates", "default": "cinematic"},
            {"name": "story_category", "label": "Story category", "type": "string",
             "default": "motivation", "required": True, "max_length": 80},
            {"name": "duration", "label": "Target duration (seconds)", "type": "number",
             "default": 45, "min": 15, "max": 180, "step": 1, "integer": True},
            {"name": "language", "label": "Language", "type": "options",
             "options": ["english", "french", "spanish"], "default": "english"},
            {"name": "language_level", "label": "Language level", "type": "options",
             "options": ["", "beginner", "intermediate", "advanced", "native"], "default": ""},
            {"name": "story_tone", "label": "Story tone", "type": "options",
             "options_source": "story_tones", "default": ""},
            {"name": "idea", "label": "Idea or prompt", "type": "textarea",
             "default": "", "max_length": 4000},
            {"name": "webhook_url", "label": "Webhook URL", "type": "string",
             "default": "", "max_length": 2048},
            _provider_options_field("script"),
        ],
        "capabilities": {"retry": True, "cancel": False},
        "executor": "scriptase.engine.adapters.script:generate",
    },
    "project.existing": {
        "type_version": 1,
        "display_name": "Existing Project",
        "description": "Select an existing project (WIP preferred over initial) without rewriting it.",
        "category": "input",
        "icon": "folder-open",
        # Only used by the Re-export Existing Project template.
        "hidden": True,
        "inputs": [_TRIGGER_IN],
        "outputs": [_CONTROL_OUT, _out("project_id", "project_id"), _out("project", "editor_project")],
        "config_schema": [
            {"name": "project_id", "label": "Project ID", "type": "string", "default": "",
             "required": True, "pattern": "^p[pm]_[A-Za-z0-9]{6}$"},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.project:existing",
    },
    "tts.generate": {
        # v2: `engine` became `provider_id` (contracts.md §41.3 M1).
        # v4: narration voices curated to the starred set; "Ashley" retired.
        "type_version": 4,
        "migrations": {
            1: "scriptase.engine.config_migrations:tts_generate_1_to_2",
            2: "scriptase.engine.config_migrations:tts_generate_2_to_3",
            3: "scriptase.engine.config_migrations:tts_generate_3_to_4",
        },
        "display_name": "Text to Speech",
        "description": "Generate narration audio from the script.",
        "category": "audio",
        "icon": "mic",
        "inputs": [_TRIGGER_IN, _in("script", "script", required=True), _in("settings", "project_settings")],
        "outputs": [_CONTROL_OUT, _out("audio", "audio_file"), _out("metadata", "tts_metadata")],
        "config_schema": [
            _provider_field("tts"),
            {"name": "voice", "label": "Voice", "type": "options",
             "options_source": "tts_voices", "default": "Sarah"},
            {"name": "speed", "label": "Speed", "type": "number",
             "default": 1.0, "min": 0.5, "max": 2.0, "step": 0.1},
            _provider_options_field("tts"),
        ],
        # TTS execution remains serialized conservatively across providers.
        "capabilities": {"retry": True, "cancel": False, "parallel_safe": False},
        "executor": "scriptase.engine.adapters.tts:generate",
    },
    "timing.align": {
        "type_version": 1,
        # Step 5.3 / product §10: user-facing name is Timing (V2: Force Alignment).
        "display_name": "Timing",
        "description": (
            "Word-level timestamps for the narration. AUTO uses native TTS "
            "timings when the provider advertises them; otherwise force-aligns "
            "with stable-whisper. Downstream always sees one alignment schema."
        ),
        "category": "timing",
        "icon": "clock",
        "inputs": [_TRIGGER_IN, _in("audio", "audio_file", required=True), _in("script", "script", required=True)],
        "outputs": [_CONTROL_OUT, _out("alignment", "alignment")],
        "config_schema": [],
        "capabilities": {"retry": True, "cancel": False},
        "executor": "scriptase.engine.adapters.timing:align",
    },
    "segment.run": {
        "type_version": 1,
        "display_name": "Segmenter",
        "description": "Split the alignment into scene-sized segments.",
        "category": "timing",
        "icon": "scissors",
        "inputs": [_TRIGGER_IN, _in("alignment", "alignment", required=True)],
        "outputs": [_CONTROL_OUT, _out("segments", "segments")],
        "config_schema": [
            {"name": "segment_config", "label": "Segmenter overrides", "type": "json", "default": {}},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.segmenter:run",
    },
    "scenes.blueprint": {
        "type_version": 1,
        "display_name": "Scene Director",
        "description": "Directs each segment into a scene: visual direction, scene description, and image prompt.",
        "category": "ai",
        "icon": "film",
        "inputs": [_TRIGGER_IN, _in("segments", "segments", required=True),
                   _in("script", "script", required=True), _in("settings", "project_settings")],
        "outputs": [_CONTROL_OUT, _out("scenes", "scenes"), _out("image_prompts", "image_prompts")],
        "config_schema": [
            # M4 (contracts.md §41.3): additive and optional, so no bump.
            _provider_field("scene_director"),
            {"name": "webhook_url", "label": "Webhook URL", "type": "string", "default": ""},
            {"name": "style", "label": "Visual style", "type": "options",
             "options_source": "style_templates", "default": "cinematic"},
            {"name": "style_prompt", "label": "Custom style notes", "type": "textarea", "default": ""},
            {"name": "story_tone", "label": "Story tone", "type": "options",
             "options_source": "story_tones", "default": ""},
            _provider_options_field("scene_director"),
        ],
        "capabilities": {"retry": True, "cancel": False},
        "executor": "scriptase.engine.adapters.scene_director:blueprint",
    },
    "storyboard.generate": {
        # v2: `provider` became `provider_id`; the two gemini_ws-gated fields
        # moved into per-run provider options (contracts.md §41.3 M2).
        "type_version": 3,
        "migrations": {
            1: "scriptase.engine.config_migrations:storyboard_generate_1_to_2",
            2: "scriptase.engine.config_migrations:storyboard_generate_2_to_3",
        },
        "display_name": "Storyboard",
        "description": "Reference images per scene (never timeline media — see contracts D4).",
        "category": "assets",
        "icon": "grid",
        "inputs": [_TRIGGER_IN, _in("scenes", "scenes", required=True), _in("settings", "project_settings")],
        "outputs": [_CONTROL_OUT, _out("images", "storyboard_images")],
        "config_schema": [
            _provider_field("image"),
            {"name": "aspect_ratio", "label": "Aspect ratio", "type": "options",
             "options": _ASPECT_RATIOS, "default": "9:16"},
            {"name": "style", "label": "Visual style", "type": "options",
             "options_source": "style_templates", "default": "cinematic"},
            {"name": "image_model", "label": "Image model", "type": "string", "default": ""},
            _provider_options_field("image"),
        ],
        "capabilities": {"retry": True, "cancel": False},
        "executor": "scriptase.engine.adapters.image:generate",
    },
    "animator.generate": {
        # v2: `provider` became `provider_id`; the gated mode/quality/duration/
        # auto_type fields moved into per-run provider options (§41.3 M3).
        "type_version": 3,
        "migrations": {
            1: "scriptase.engine.config_migrations:animator_generate_1_to_2",
            2: "scriptase.engine.config_migrations:animator_generate_2_to_3",
        },
        "display_name": "Animator",
        "description": "Timeline media (video/image) per scene via the asset grabber.",
        "category": "assets",
        "icon": "image",
        "inputs": [_TRIGGER_IN, _in("scenes", "scenes", required=True),
                   _in("storyboard", "storyboard_images"), _in("settings", "project_settings")],
        "outputs": [_CONTROL_OUT, _out("assets", "animation_assets")],
        "config_schema": [
            _provider_field("video"),
            {"name": "aspect_ratio", "label": "Aspect ratio", "type": "options",
             "options": _ASPECT_RATIOS, "default": "9:16"},
            {"name": "arguments", "label": "Extra arguments", "type": "string", "default": ""},
            # Step 11.1. The image gate guards *this* node: `video.py:213` calls
            # `enforce_image_gate_for_video(inputs, merged, context)` where
            # `merged` is this node's configuration, so this is the only place
            # the three keys are read. Declaring them on `storyboard.generate`
            # as well would render three controls that nothing consumes — the
            # Storyboard adapter has no gate call, and `inherited_config` here
            # merges the `project_settings` port, never another node's config.
            *_quality_gate_fields(),
            _provider_options_field("video"),
        ],
        "capabilities": {"retry": True, "cancel": False},
        "executor": "scriptase.engine.adapters.video:generate",
    },
    "review.run": {
        # Step 11.1 — the `review` domain finally gets a node. It was the only
        # one of six with no consumer, so `plan_job_repairs` and friends had
        # nothing to plan against. `PRIMARY_STAGE_BY_TYPE` already reserved this
        # key for the Review stage (`jobs/stage_projection.py:64`).
        "type_version": 1,
        "display_name": "Review",
        "description": (
            "Quality review of the generated stills and clips. Deterministic "
            "technical validators always run; the selected review provider adds "
            "semantic findings when enabled. Emits structured issues only."
        ),
        "category": "ai",
        "icon": "shield-check",
        # Job review and the image quality gate run without a canvas node, so
        # this is an opt-in stage rather than part of the Full Video graph.
        "hidden": True,
        # Every media input is optional so one node can review stills, clips, or
        # both, and a graph that only produced one of them still validates.
        "inputs": [_TRIGGER_IN,
                   _in("images", "storyboard_images"),
                   _in("assets", "animation_assets"),
                   _in("scenes", "scenes"),
                   _in("settings", "project_settings")],
        "outputs": [_CONTROL_OUT, _out("issues", "generic_json")],
        "config_schema": [
            {
                **_provider_field("review"),
                # Technical review has no provider dependency. The prototype
                # catalogue intentionally ships no semantic provider, so a
                # provider is required only when that optional pass is enabled.
                "display_options": {"show": {"semantic": [True]}},
            },
            {"name": "subject", "label": "Review subject", "type": "options",
             "options": ["auto", "images", "videos"], "default": "auto",
             "description": "AUTO reviews whichever media ports are connected."},
            # Provider selection and "am I willing to pay for it" are separate
            # decisions: the technical validators are free and always run, so
            # semantic review is opt-in rather than implied by having a provider
            # bound. Mirrors `image_gate_semantic` on the Animator.
            {"name": "semantic", "label": "Run semantic review",
             "type": "boolean", "default": False,
             "description": (
                 "Ask the review provider for semantic findings on top of the "
                 "technical checks. Slower, and it may cost a provider call."
             )},
            {"name": "aspect_ratio", "label": "Expected aspect ratio", "type": "options",
             "options": _ASPECT_RATIOS, "default": "9:16"},
            {"name": "require_audio", "label": "Clips must carry audio",
             "type": "boolean", "default": False,
             "display_options": {"hide": {"subject": ["images"]}}},
            # Phase 11.3 owns escalation and repair. Until then this node
            # reports; it does not decide. Default off so adding Review to a
            # working graph cannot start failing runs.
            {"name": "fail_on_blocking", "label": "Fail this node on blocking issues",
             "type": "boolean", "default": False,
             "description": (
                 "Raise QUALITY_GATE_FAILED instead of passing the issues "
                 "downstream. Leave off to let the Repair Router handle them."
             )},
            _provider_options_field("review"),
        ],
        "capabilities": {"retry": True, "cancel": False},
        "executor": "scriptase.engine.adapters.review:run",
    },
    "script.analyze": {
        # Step 16.2 — the `viral` domain's only node. Sits after Script and
        # before everything expensive, which is the whole point: the score is
        # the cheapest signal in the graph and it is worthless once TTS,
        # Storyboard, and Animator have already been paid for.
        "type_version": 1,
        "display_name": "Script Analyzer",
        "description": (
            "Score the script for virality before an expensive stage runs. "
            "The default provider is offline, deterministic, and free; it "
            "reports a 0-100 score with a per-dimension breakdown and never "
            "blocks the run."
        ),
        "category": "ai",
        "icon": "gauge",
        "schema": {"glyph": "📈", "accent": "#e0a44a", "role": "branch"},
        # `script` is the only required input — the analyzer must be usable on
        # nothing but pasted text. `story` and `scenes` sharpen the score when
        # the graph happens to have them and are unwired in the Full Video
        # template on purpose: wiring `scenes` would drag the analyzer behind
        # Segments and Scenes, which is exactly what it exists to precede.
        "inputs": [_TRIGGER_IN,
                   _in("script", "script", required=True),
                   _in("story", "generic_json"),
                   _in("scenes", "scenes")],
        "outputs": [_CONTROL_OUT, _out("score", "generic_json")],
        "config_schema": [
            _provider_field("viral"),
            {"name": "target_duration",
             "label": "Target duration (seconds)", "type": "number",
             "default": 0, "min": 0, "max": 600, "step": 1, "integer": True,
             "description": (
                 "What the script was written to reach, which is what pacing "
                 "is judged against. Leave at 0 to take it from the story "
                 "document, or from the 45-second default when there is none."
             )},
            _provider_options_field("viral"),
        ],
        # Free and side-effect-free, so a retry is always safe. Nothing
        # downstream consumes the `score` port in a shipped template, so a
        # failure here is reported and never strands the run.
        "capabilities": {"retry": True, "cancel": False},
        "executor": "scriptase.engine.adapters.viral:analyze",
    },
    "captions.generate": {
        "type_version": 1,
        "display_name": "Caption Generator",
        "description": "Word-level captions grouped from the alignment.",
        "category": "video",
        "icon": "type",
        "schema": {"glyph": "T", "accent": "#3fb68b", "role": "branch"},
        "inputs": [_TRIGGER_IN, _in("alignment", "alignment", required=True)],
        "outputs": [_CONTROL_OUT, _out("captions", "captions")],
        "config_schema": [
            {"name": "preset_id", "label": "Caption preset", "type": "options",
             "options_source": "caption_presets", "default": "bold_popup"},
            {"name": "words_per_group", "label": "Words per caption", "type": "number",
             "default": 3, "min": 1, "max": 10, "step": 1},
            {"name": "enabled", "label": "Enabled", "type": "boolean", "default": True},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.captions:generate",
    },
    "music.select": {
        "type_version": 1,
        "display_name": "Background Music",
        "description": "Pick a background track by tone, at random, or explicitly.",
        "category": "audio",
        "icon": "music",
        "schema": {"glyph": "♪", "accent": "#e0a44a", "role": "branch"},
        "inputs": [_TRIGGER_IN, _in("settings", "project_settings"), _in("project_id", "project_id")],
        "outputs": [_CONTROL_OUT, _out("track", "music_track")],
        "config_schema": [
            {"name": "mode", "label": "Selection mode", "type": "options",
             "options": ["tone", "random", "specific"], "default": "tone"},
            {"name": "story_tone", "label": "Story tone", "type": "options",
             "options_source": "story_tones", "default": "",
             "display_options": {"show": {"mode": ["tone"]}}},
            {"name": "track_ref", "label": "Track", "type": "string", "default": "",
             "display_options": {"show": {"mode": ["specific"]}}},
            {"name": "volume", "label": "Volume", "type": "number",
             "default": 0.15, "min": 0.0, "max": 1.0, "step": 0.05},
            {"name": "fade_in", "label": "Fade in (s)", "type": "number",
             "default": 2.0, "min": 0.0, "max": 10.0, "step": 0.5},
            {"name": "fade_out", "label": "Fade out (s)", "type": "number",
             "default": 3.0, "min": 0.0, "max": 10.0, "step": 0.5},
            {"name": "loop", "label": "Loop", "type": "boolean", "default": True},
            {"name": "ducking_enabled", "label": "Duck under voice", "type": "boolean", "default": True},
            {"name": "ducking_level", "label": "Ducking level", "type": "number",
             "default": 0.20, "min": 0.0, "max": 1.0, "step": 0.05},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.music:select",
    },
    "assemble.project": {
        "type_version": 1,
        "display_name": "Assemble Project",
        "description": "Merge audio, scenes, and assets into an editor project.",
        "category": "video",
        "icon": "layers",
        "inputs": [_TRIGGER_IN, _in("assets", "animation_assets", required=True),
                   _in("metadata", "tts_metadata", required=True), _in("scenes", "scenes", required=True),
                   _in("captions", "captions"), _in("music", "music_track"),
                   _in("settings", "project_settings")],
        "outputs": [_CONTROL_OUT, _out("project", "editor_project")],
        "config_schema": [],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.compose:assemble",
    },
    "timeline.project": {
        "type_version": 1,
        "display_name": "Timeline Project",
        "description": "Persist the assembled project for the timeline editor.",
        "category": "output",
        "icon": "sliders",
        "inputs": [_TRIGGER_IN, _in("project", "editor_project", required=True)],
        "outputs": [_CONTROL_OUT, _out("project", "editor_project"), _out("project_id", "project_id")],
        "config_schema": [],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.compose:timeline_project",
    },
    "export.video": {
        "type_version": 1,
        "display_name": "Video Export",
        "description": "Render the final video with FFmpeg.",
        "category": "output",
        "icon": "download",
        "inputs": [_TRIGGER_IN, _in("project", "editor_project", required=True),
                   _in("settings", "project_settings")],
        "outputs": [_CONTROL_OUT, _out("video", "video_file")],
        "config_schema": [
            {"name": "profile", "label": "Export profile", "type": "options",
             "options_source": "export_profiles", "default": "yt_shorts"},
            {"name": "captions", "label": "Bake captions", "type": "boolean", "default": True},
            {"name": "grain", "label": "Grain overlay", "type": "boolean", "default": False},
        ],
        "capabilities": {"retry": True, "cancel": True},
        "executor": "scriptase.engine.adapters.export:video",
    },
    "utility.set_value": {
        "type_version": 1,
        "display_name": "Set Value",
        "description": "Emit a configured JSON value, optionally sequenced by an incoming value.",
        "category": "utility",
        "icon": "edit-3",
        "hidden": True,
        "inputs": [_TRIGGER_IN, _in("value", "generic_json")],
        "outputs": [_CONTROL_OUT, _out("value", "generic_json")],
        "config_schema": [
            {"name": "value", "label": "Value", "type": "json", "default": None},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.utilities:set_value",
    },
    "utility.condition": {
        "type_version": 1,
        "display_name": "Condition",
        "description": "Route one JSON value to exactly one of two explicit branches.",
        "category": "utility",
        "icon": "git-branch",
        "hidden": True,
        "inputs": [_TRIGGER_IN, _in("value", "generic_json", required=True)],
        "outputs": [
            {**_out("true", "generic_json"), "conditional": True},
            {**_out("false", "generic_json"), "conditional": True},
        ],
        "config_schema": [
            {"name": "operator", "label": "Operator", "type": "options",
             "options": ["truthy", "falsy", "equals", "not_equals", "contains"], "default": "truthy"},
            {"name": "compare_to", "label": "Compare to", "type": "json", "default": None,
             "display_options": {"show": {"operator": ["equals", "not_equals", "contains"]}}},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.utilities:condition",
    },
    "utility.merge": {
        "type_version": 1,
        "display_name": "Merge",
        "description": "Join active branch values after all connected branches resolve.",
        "category": "utility",
        "icon": "git-merge",
        "hidden": True,
        "inputs": [{"id": "values", "type": "generic_json", "required": True, "multiple": True}],
        "outputs": [_CONTROL_OUT, _out("value", "generic_json")],
        "config_schema": [
            {"name": "mode", "label": "Merge mode", "type": "options",
             "options": ["array", "first", "object"], "default": "array"},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.utilities:merge",
    },
    "utility.wait": {
        "type_version": 1,
        "display_name": "Wait",
        "description": "Delay a branch and pass its JSON value through unchanged.",
        "category": "utility",
        "icon": "clock",
        "hidden": True,
        "inputs": [_TRIGGER_IN, _in("value", "generic_json")],
        "outputs": [_CONTROL_OUT, _out("value", "generic_json")],
        "config_schema": [
            {"name": "delay_ms", "label": "Delay (milliseconds)", "type": "number",
             "default": 1000, "min": 0, "max": 300000, "step": 1, "integer": True},
        ],
        "capabilities": {"retry": False, "cancel": True, "cacheable": False},
        "executor": "scriptase.engine.adapters.utilities:wait",
    },
    "workflow.output": {
        "type_version": 1,
        "display_name": "Workflow Output",
        "description": "Record a value as a result of this workflow.",
        "category": "utility",
        "icon": "flag",
        "inputs": [_TRIGGER_IN, {"id": "value", "type": "dynamic", "required": True, "multiple": False}],
        "outputs": [],
        "config_schema": [
            {"name": "port_type", "label": "Value type", "type": "options",
             "options": DYNAMIC_PORT_TYPES, "default": "generic_json", "required": True},
            {"name": "label", "label": "Label", "type": "string", "default": "", "max_length": 120},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.control:workflow_output",
    },
    "stub.input": {
        "type_version": 1,
        "display_name": "Sample Input",
        "description": "Editable sample data feeding an unconnected input (testing).",
        "category": "testing",
        "icon": "flask",
        "hidden": True,
        "inputs": [],
        "outputs": [{"id": "value", "type": "dynamic"}],
        "config_schema": [
            {"name": "port_type", "label": "Data type", "type": "options",
             "options": DYNAMIC_PORT_TYPES, "default": "generic_json", "required": True},
            {"name": "payload", "label": "Sample payload", "type": "json", "default": {}},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.stubs:sample_input",
    },
    "stub.output": {
        "type_version": 1,
        "display_name": "Result Viewer",
        "description": "Captures a node's output for inspection (testing; pinning in Phase 4).",
        "category": "testing",
        "icon": "eye",
        "hidden": True,
        "inputs": [{"id": "value", "type": "dynamic", "required": True, "multiple": False}],
        "outputs": [{"id": "value", "type": "dynamic"}],
        "config_schema": [
            {"name": "port_type", "label": "Data type", "type": "options",
             "options": DYNAMIC_PORT_TYPES, "default": "generic_json", "required": True},
            {"name": "pinned", "label": "Pin edited result", "type": "boolean", "default": False},
            {"name": "payload", "label": "Pinned payload", "type": "json", "default": {},
             "display_options": {"show": {"pinned": [True]}}},
        ],
        "capabilities": {"retry": False, "cancel": False},
        "executor": "scriptase.engine.adapters.stubs:result_viewer",
    },
}

_BUILTIN_NODE_KEYS = frozenset(_NODE_TYPES)
_BUILTIN_NODE_TYPES = deepcopy(_NODE_TYPES)


def load_generated_node_types(directory=None):
    """Load source-controlled node definitions emitted by the scaffolder.

    Definitions live outside this module so adding a node never requires
    rewriting the hand-maintained catalog.  Loading happens once at process
    start, which makes a scaffolded node available to the API and scheduler
    on the next application start.
    """
    root = Path(directory) if directory is not None else Path(__file__).with_name("node_definitions")
    generated = {}
    if not root.is_dir():
        return generated

    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot load generated node definition {path}: {exc}") from exc
        key = payload.get("key") if isinstance(payload, dict) else None
        definition = payload.get("definition") if isinstance(payload, dict) else None
        if not isinstance(key, str) or not isinstance(definition, dict):
            raise RuntimeError(f"Generated node definition {path} must contain key and definition")
        if key in generated or key in _BUILTIN_NODE_KEYS:
            raise RuntimeError(f"Duplicate workflow node key {key!r} in {path}")
        required = {
            "type_version", "display_name", "description", "category", "icon",
            "inputs", "outputs", "config_schema", "capabilities", "executor",
        }
        missing = sorted(required - definition.keys())
        if missing:
            raise RuntimeError(f"Generated node {key!r} is missing: {', '.join(missing)}")
        if definition["category"] not in CATEGORIES:
            raise RuntimeError(f"Generated node {key!r} has unknown category {definition['category']!r}")
        if not isinstance(definition.get("hidden", False), bool):
            raise RuntimeError(f"Generated node {key!r} hidden flag must be a boolean")
        for port in definition["inputs"] + definition["outputs"]:
            if port.get("type") not in PORT_TYPES:
                raise RuntimeError(
                    f"Generated node {key!r} port {port.get('id')!r} has invalid type {port.get('type')!r}"
                )
        migrations = definition.get("migrations", {})
        if not isinstance(migrations, dict):
            raise RuntimeError(f"Generated node {key!r} migrations must be an object")
        for version, target in migrations.items():
            try:
                source_version = int(version)
            except (TypeError, ValueError):
                raise RuntimeError(
                    f"Generated node {key!r} migration versions must be integers"
                ) from None
            if source_version < 1 or source_version >= definition["type_version"]:
                raise RuntimeError(
                    f"Generated node {key!r} migration {version!r} is outside its version range"
                )
            if not isinstance(target, str) or ":" not in target:
                raise RuntimeError(
                    f"Generated node {key!r} migration {version!r} must be a module:function string"
                )
        generated[key] = definition
    return generated


def _with_resilience_capabilities(node_types):
    """Return a catalog with backend-owned recovery capabilities applied."""
    catalog = deepcopy(node_types)
    for type_key, definition in catalog.items():
        capabilities = definition.setdefault("capabilities", {})
        has_control_output = any(
            port.get("id") == "control" and port.get("type") == "control"
            for port in definition.get("outputs", [])
        )
        recoverable = has_control_output and type_key != "trigger.manual"
        capabilities.setdefault("error_output", recoverable)
        capabilities.setdefault("skip_optional", recoverable)
        output_ids = {port.get("id") for port in definition.get("outputs", [])}
        if capabilities["error_output"] and "error" not in output_ids:
            definition["outputs"].append(_out("error", "control"))
    return catalog


def reload_generated_node_types(directory=None):
    """Atomically refresh generated definitions while Flask keeps running.

    Loading and validation finish before the process-wide catalog is changed,
    so a partially-written or invalid developer file cannot corrupt requests
    or executions already using the registry.
    """
    global _NODE_TYPES
    refreshed = deepcopy(_BUILTIN_NODE_TYPES)
    refreshed.update(load_generated_node_types(directory))
    refreshed = _with_resilience_capabilities(refreshed)
    for definition in refreshed.values():
        definition.setdefault("hidden", False)
    _NODE_TYPES = refreshed
    return len(refreshed)


reload_generated_node_types()

# Fields internal to the backend, stripped from the served form.
_INTERNAL_FIELDS = ("executor", "migrations")


def get_node_type(type_key):
    """Return the full internal definition for a node type, or None."""
    node = _NODE_TYPES.get(type_key)
    return deepcopy(node) if node is not None else None


def all_node_types():
    return deepcopy(_NODE_TYPES)


def is_supported(type_key, type_version):
    node = _NODE_TYPES.get(type_key)
    return bool(node) and node["type_version"] == type_version


def serialize_registry():
    """Presentation-safe registry payload for GET /api/workflow/node-types."""
    node_types = {}
    for key, definition in _NODE_TYPES.items():
        public = deepcopy({k: v for k, v in definition.items() if k not in _INTERNAL_FIELDS})
        public["type"] = key
        for field in public.get("config_schema") or ():
            _annotate_option_context(field)
        node_types[key] = public
    return {
        "registry_version": REGISTRY_VERSION,
        "port_types": list(PORT_TYPES),
        "categories": deepcopy(CATEGORIES),
        "node_types": node_types,
    }


def _annotate_option_context(field):
    """Tell the client which context parameters this field's source accepts.

    The editor cannot guess: a source rejects a parameter it does not declare
    (§23.1), so sending `provider` to every dropdown would answer
    `OPTION_CONTEXT_INVALID`, and sending it to none is why the `voice`
    dropdown could not follow the node's provider before step 15.2. Derived
    from `ASYNC_OPTION_SOURCES`, so a new context-sensitive source needs no
    frontend edit.
    """
    spec = ASYNC_OPTION_SOURCES.get(field.get("options_source"))
    if spec is not None and spec.context:
        field["options_context"] = list(spec.context)
