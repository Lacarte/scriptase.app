"""ChannelProfile: reusable identity and production rules for a content brand.

Populated in steps 1.1 and 1.3. A Channel lives *above* Jobs and is never a
processing node. ``visual_direction.pattern`` is a structured ordered map of
narrative role to shot direction, never one free-text field — that is what makes
Scene Director deterministic and a Channel genuinely reusable.

Channels reference provider *instance ids*, never duplicated account
configuration, and never credentials.
"""
