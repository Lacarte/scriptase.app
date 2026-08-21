"""Story generation engine — parses LLM output into structured sections.

Structure is per-channel: a Channel's template is the single source of the beats
(labels + order). This module parses whatever labels a script carries and maps
them to the four canonical *roles* (hook/build/climax/cta) the virality scorer
is built on, so any structure stays scoreable. `DEFAULT_SECTIONS` is the fallback
for a channel that declares none and for back-compat.
"""

import re

# The canonical roles the virality scorer reasons about. Every template's beats
# are mapped onto these; they are NOT the labels a script must use.
CANONICAL_ROLES = ("hook", "build", "climax", "cta")

# The default beats when a channel declares no template (also the legacy shape).
DEFAULT_SECTIONS = ("Hook", "Build", "Climax", "CTA")


def _label_key(label: str) -> str:
    """A stable dict key for a beat label ('Turn' -> 'turn', 'Why?' -> 'why')."""
    return re.sub(r"[^a-z0-9]+", "_", str(label or "").strip().lower()).strip("_")


def parse_story_sections(raw_text: str, labels=None) -> dict:
    """Parse LLM output into sections keyed by the beat labels it uses.

    `labels` is the ordered beat vocabulary (a Channel's template). Defaults to
    the canonical Hook/Build/Climax/CTA. Returns:
      - sections: {label_key: content} for the parsed beats
      - roles: {hook/build/climax/cta: content} mapped for scoring
      - story_text: the labeled body, reassembled in order
      - word_count, labels: the beat vocabulary actually used
    """
    text = (raw_text or "").strip()
    beats = [str(b).strip() for b in (labels or DEFAULT_SECTIONS) if str(b).strip()]
    if not beats:
        beats = list(DEFAULT_SECTIONS)
    keys = [_label_key(b) for b in beats]

    sections = {k: "" for k in keys}
    pattern = r"(?:^|\n)\s*(" + "|".join(re.escape(b) for b in beats) + r")\s*:\s*"
    parts = re.split(pattern, text, flags=re.IGNORECASE)

    key_by_lower = {b.lower(): _label_key(b) for b in beats}
    current_key = None
    for part in parts:
        normalized = part.strip().lower()
        if normalized in key_by_lower:
            current_key = key_by_lower[normalized]
        elif current_key and current_key in sections:
            sections[current_key] = part.strip()

    has_labels = any(sections.values())
    if not has_labels:
        # No labels found — keep the text as-is, park it under the middle role.
        roles = {r: "" for r in CANONICAL_ROLES}
        roles["build"] = text
        return {
            "sections": {keys[0] if keys else "build": text},
            "roles": roles,
            "story_text": text,
            "word_count": len(text.split()),
            "labels": beats,
        }

    # Reassemble the labeled body in the template's order.
    story_parts = [f"{beat}: {sections[key]}"
                   for beat, key in zip(beats, keys) if sections.get(key)]
    story_text = "\n\n".join(story_parts)

    return {
        "sections": sections,
        "roles": map_beats_to_roles(sections, beats),
        "story_text": story_text,
        "word_count": len(story_text.split()),
        "labels": beats,
    }


def map_beats_to_roles(sections: dict, labels) -> dict:
    """Map a template's beats onto the four canonical scorer roles.

    The scorer reasons about hook/build/climax/cta. Any template maps by
    position: the FIRST beat is the hook, the LAST is the cta, and the middle
    beats fill build (all but the last middle) and climax (the last middle).
    A beat already named exactly hook/build/climax/cta keeps its role.
    """
    beats = [str(b).strip() for b in (labels or DEFAULT_SECTIONS) if str(b).strip()]
    keys = [_label_key(b) for b in beats]
    roles = {r: "" for r in CANONICAL_ROLES}
    if not keys:
        return roles

    n = len(keys)
    # Exact-name beats win their role directly.
    for beat, key in zip(beats, keys):
        low = beat.strip().lower()
        if low in CANONICAL_ROLES and sections.get(key):
            roles[low] = sections[key]

    def _fill(role, key):
        if not roles[role] and sections.get(key):
            roles[role] = sections[key]

    # Positional fill for anything not already role-named.
    _fill("hook", keys[0])
    _fill("cta", keys[-1])
    middle = keys[1:-1] if n >= 3 else []
    if middle:
        # Last middle beat -> climax; everything before it -> build (joined).
        _fill("climax", middle[-1])
        build_parts = [sections.get(k, "") for k in middle[:-1] if sections.get(k)]
        if build_parts and not roles["build"]:
            roles["build"] = "\n\n".join(build_parts)
        # If there was only one middle beat, it already went to climax; make sure
        # build isn't empty by borrowing the hook-adjacent content is wrong —
        # instead leave build empty, which the scorer tolerates.
    elif n == 2:
        # Hook + CTA only — nothing to build/climax.
        pass
    return roles


# Section markers a script body may carry. The canonical four the engine emits,
# plus common Channel-template labels so an older script that still has them is
# also cleaned before narration.
_SECTION_LABELS = (
    "Hook", "Build", "Climax", "CTA",
    "Turn", "Why", "Reframe", "Landing", "Setup", "Payoff", "Twist", "Resolution",
)
_LABEL_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:" + "|".join(_SECTION_LABELS) + r")[ \t]*:[ \t]*",
    flags=re.IGNORECASE,
)


def strip_section_labels(text: str, labels=None) -> str:
    """Remove leading section markers (Hook:/Build:/…) so narration speaks prose.

    The stored script keeps its labels — the editor shows structure and the
    virality scorer needs them — but the voice should not read "Hook colon".
    `labels` is the channel's beats; when given they are stripped in addition to
    the built-in set, so any custom template narrates cleanly. Each marker
    becomes a paragraph break; runs of blank lines are collapsed.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    label_re = _LABEL_RE
    extra = [str(b).strip() for b in (labels or ()) if str(b).strip()]
    if extra:
        vocab = list(dict.fromkeys([*_SECTION_LABELS, *extra]))
        label_re = re.compile(
            r"(?:^|\n)[ \t]*(?:" + "|".join(re.escape(b) for b in vocab) + r")[ \t]*:[ \t]*",
            flags=re.IGNORECASE,
        )
    cleaned = label_re.sub("\n\n", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
