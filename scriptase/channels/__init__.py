"""ChannelProfile: reusable identity and production rules for a content brand.

Populated in steps 1.1 and 1.3. A Channel lives *above* Jobs and is never a
processing node. ``visual_direction.pattern`` is a structured ordered map of
narrative role to shot direction, never one free-text field — that is what makes
Scene Director deterministic and a Channel genuinely reusable.

Channels reference provider *instance ids*, never duplicated account
configuration, and never credentials.
"""

from scriptase.channels.cadence import (
    ChannelCadenceService,
    channel_cadence_service,
)
from scriptase.channels.models import (
    CHANNEL_ID_RE,
    CHANNEL_SCHEMA_VERSION,
    DEFAULT_SCRIPT_TEMPLATE_BRIEF,
    DEFAULT_SCRIPT_TEMPLATE_SECTIONS,
    MusicLibrary,
    CadenceSource,
    ChannelDraft,
    ChannelProfile,
    ContentCadence,
    PatternEntry,
    ScriptTemplate,
    VisualDirection,
    WATERMARK_POSITIONS,
    parse_channel,
    parse_draft,
    validation_problems,
)
from scriptase.channels.presets import (
    preset_to_channel_draft,
    seed_starter_channels,
)
from scriptase.channels.routes import channels_bp
from scriptase.channels.store import (
    ChannelConflict,
    ChannelNotFound,
    ChannelValidationError,
    channel_summary,
    create_channel,
    default_draft,
    delete_channel,
    get_channel,
    list_channels,
    update_channel,
)

__all__ = [
    "CHANNEL_ID_RE",
    "CHANNEL_SCHEMA_VERSION",
    "DEFAULT_SCRIPT_TEMPLATE_BRIEF",
    "DEFAULT_SCRIPT_TEMPLATE_SECTIONS",
    "MusicLibrary",
    "CadenceSource",
    "ContentCadence",
    "ChannelDraft",
    "ChannelProfile",
    "PatternEntry",
    "ScriptTemplate",
    "VisualDirection",
    "WATERMARK_POSITIONS",
    "parse_channel",
    "parse_draft",
    "validation_problems",
    "ChannelConflict",
    "ChannelNotFound",
    "ChannelValidationError",
    "channel_summary",
    "create_channel",
    "default_draft",
    "delete_channel",
    "get_channel",
    "list_channels",
    "update_channel",
    "preset_to_channel_draft",
    "seed_starter_channels",
    "channels_bp",
    "ChannelCadenceService",
    "channel_cadence_service",
]
