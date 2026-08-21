"""Story generation engine — parses LLM output into structured sections."""

import re


def parse_story_sections(raw_text: str) -> dict:
    """Parse raw LLM output into structured story sections.

    Expects labels: Hook:, Build:, Climax:, CTA:
    Returns dict with keys: hook, build, climax, cta, story_text
    """
    text = raw_text.strip()

    sections = {"hook": "", "build": "", "climax": "", "cta": ""}
    labels = ["Hook", "Build", "Climax", "CTA"]

    # Build a regex that splits on section labels
    pattern = r"(?:^|\n)\s*(" + "|".join(labels) + r")\s*:\s*"
    parts = re.split(pattern, text, flags=re.IGNORECASE)

    # parts alternates: [preamble, label, content, label, content, ...]
    current_key = None
    for part in parts:
        normalized = part.strip().lower()
        if normalized in [l.lower() for l in labels]:
            current_key = normalized
        elif current_key and current_key in sections:
            sections[current_key] = part.strip()

    # If parsing failed (no labels found), keep original text as-is
    has_labels = any(sections.values())
    if not has_labels:
        sections["build"] = text
        # Return original text unchanged — don't prepend labels
        return {
            "sections": sections,
            "story_text": text,
            "word_count": len(text.split()),
        }

    # Reconstruct full story text from labeled sections
    story_parts = []
    for label in labels:
        key = label.lower()
        if sections.get(key):
            story_parts.append(f"{label}: {sections[key]}")
    story_text = "\n\n".join(story_parts)

    word_count = len(story_text.split())

    return {
        "sections": sections,
        "story_text": story_text,
        "word_count": word_count,
    }


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


def strip_section_labels(text: str) -> str:
    """Remove leading section markers (Hook:/Build:/…) so narration speaks prose.

    The stored script keeps its labels — the editor shows structure and the
    virality scorer needs them — but the voice should not read "Hook colon".
    Each marker becomes a paragraph break; runs of blank lines are collapsed.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    # Replace each label occurrence with a paragraph break (empty at the very
    # start), then normalize whitespace.
    cleaned = _LABEL_RE.sub("\n\n", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
