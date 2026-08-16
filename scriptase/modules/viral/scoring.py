"""The six deterministic dimension scorers (step 16.1).

Each scorer takes the normalised :class:`ScriptDoc` and returns a 0..1 score
with the structured reasons behind it. Nothing here touches the network, the
clock, or a random source: identical input must always produce byte-identical
output, so every float is rounded at the boundary and every iteration order is
fixed by a tuple, never by a set or a dict comprehension over user data.

Word rate reuses ``WORDS_PER_SECOND`` from the script prompts rather than
restating it — the scorer must measure against the same rate the writer was
told to hit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from scriptase.modules.script.prompts import WORDS_PER_SECOND

from .archetypes import ARCHETYPES, count_weak_openers, match_archetypes
from .models import ScoreReason

# The mandated script structure (script/prompts.py OUTPUT STRUCTURE).
SECTION_KEYS: tuple[str, ...] = ("hook", "build", "climax", "cta")

# Acceptable share of total words per section.
SECTION_SHARE_BANDS: dict[str, tuple[float, float]] = {
    "hook": (0.05, 0.18),
    "build": (0.40, 0.70),
    "climax": (0.12, 0.35),
    "cta": (0.02, 0.12),
}

# Word rate may drift this far from target before it costs anything — the same
# +/-10% the writer is held to — and scores zero at DEAD.
RATE_FREE_BAND = 0.10
RATE_DEAD_BAND = 0.50

# Spoken narration reads well between these mean sentence lengths.
RHYTHM_IDEAL = (8.0, 18.0)
RHYTHM_DEAD = (3.0, 32.0)
LONG_SENTENCE_WORDS = 30

# Open loops per 100 words at which the dimension saturates.
LOOP_DENSITY_TARGET = 1.5

_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:" + "|".join(SECTION_KEYS) + r")\s*:\s*",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\u2026])\s+")

_OPEN_LOOP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(source, re.IGNORECASE)
    for source in (
        r"\bbut here'?s\b",
        r"\bhere'?s (the thing|why|where it gets)\b",
        r"\bwhat most (people )?(don'?t|never) (realiz|know|see)\w*\b",
        r"\bbut that'?s not (the|all|even)\b",
        r"\band that'?s when\b",
        r"\bbut first\b",
        r"\bthe reason why\b",
        r"\bwait until you\b",
        r"\bit gets (worse|stranger|weirder)\b",
        r"\bthere'?s a catch\b",
        r"\bstay with me\b",
        r"\bby the end\b",
        r"\bmore on that\b",
        r"\bwhich brings us to\b",
        r"\byou'?ll see why\b",
        r"\bbut there'?s a (problem|twist|reason)\b",
        r"\bthe (real )?twist\b",
        r"\bnobody expected\b",
    )
)

_CTA_ACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(source, re.IGNORECASE)
    for source in (
        r"\b(follow|comment|share|subscribe|save this|send this)\b",
        r"\b(tell me|let me know|drop a)\b",
        r"\b(ask yourself|think about|remember this|watch for)\b",
        r"\bwhat would you\b",
        r"\bnext time you\b",
        r"\b(try|notice|count) (this|it|them)\b",
        r"\?\s*$",
    )
)


def word_count(text: str) -> int:
    """Count words the way the script service does, so totals agree."""
    return len((text or "").split())


def strip_labels(text: str) -> str:
    """Remove the ``Hook:`` / ``Build:`` / ``Climax:`` / ``CTA:`` labels."""
    return _LABEL_RE.sub("\n", text or "").strip()


def split_sentences(text: str) -> list[str]:
    """Split narration into sentences, dropping empties."""
    flat = " ".join((text or "").split())
    if not flat:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(flat) if part.strip()]


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 4)


@dataclass(frozen=True)
class ScriptDoc:
    """One script, normalised into everything the scorers need.

    Built by :func:`build_doc` so no scorer re-parses the text and the metrics
    reported to the caller are the ones the score was actually computed from.
    """

    sections: dict[str, str]
    story_text: str
    section_words: dict[str, int]
    total_words: int
    target_duration: int
    narrative_roles: tuple[str, ...] = ()
    sentences: list[str] = field(default_factory=list)

    @property
    def estimated_duration(self) -> float:
        return round(self.total_words / WORDS_PER_SECOND, 2)

    def share(self, key: str) -> float:
        if not self.total_words:
            return 0.0
        return round(self.section_words.get(key, 0) / self.total_words, 4)

    @property
    def opening_line(self) -> str:
        source = self.sections.get("hook") or self.story_text
        sentences = split_sentences(source)
        return sentences[0] if sentences else ""


def build_doc(
    sections: dict[str, str] | None,
    story_text: str | None,
    target_duration: int,
    narrative_roles: tuple[str, ...] = (),
) -> ScriptDoc:
    """Normalise raw script fields into a :class:`ScriptDoc`.

    Either half may be missing: sections alone are enough, and unlabelled
    ``story_text`` alone falls back to treating the whole script as Build so
    pacing and open loops still score.
    """
    clean_sections = {
        key: " ".join(str((sections or {}).get(key) or "").split())
        for key in SECTION_KEYS
    }
    narration = strip_labels(story_text or "")
    if not any(clean_sections.values()):
        clean_sections["build"] = narration
    if not narration:
        narration = "\n\n".join(clean_sections[key] for key in SECTION_KEYS if clean_sections[key])

    section_words = {key: word_count(value) for key, value in clean_sections.items()}
    total = sum(section_words.values()) or word_count(narration)
    return ScriptDoc(
        sections=clean_sections,
        story_text=narration,
        section_words=section_words,
        total_words=total,
        target_duration=max(1, int(target_duration or 0)),
        narrative_roles=tuple(str(role or "").strip().lower() for role in narrative_roles),
        sentences=split_sentences(narration),
    )


def _section_positions(doc: ScriptDoc) -> list[tuple[int, str]]:
    """Where each non-empty section first appears in the narration."""
    haystack = doc.story_text.lower()
    found: list[tuple[int, str]] = []
    for key in SECTION_KEYS:
        body = doc.sections.get(key) or ""
        if not body:
            continue
        needle = " ".join(body.split()[:8]).lower()
        index = haystack.find(needle) if needle else -1
        if index >= 0:
            found.append((index, key))
    found.sort()
    return found


def score_hook(doc: ScriptDoc) -> tuple[float, list[ScoreReason]]:
    """Hook presence, length, and position — is there one, and is it first?"""
    reasons: list[ScoreReason] = []
    hook = doc.sections.get("hook") or ""
    if not hook:
        reasons.append(ScoreReason(code="hook_missing", impact="negative"))
        if "hook" in doc.narrative_roles:
            reasons.append(
                ScoreReason(
                    code="hook_role_present",
                    impact="positive",
                    detail={"position": doc.narrative_roles.index("hook")},
                )
            )
            return 0.15, reasons
        return 0.0, reasons

    score = 0.30
    reasons.append(ScoreReason(code="hook_present", impact="positive", detail={"words": doc.section_words["hook"]}))

    sentences = len(split_sentences(hook))
    if sentences in (1, 2):
        score += 0.35
        reasons.append(ScoreReason(code="hook_length_ideal", impact="positive", detail={"sentences": sentences}))
    elif sentences == 3:
        score += 0.20
        reasons.append(ScoreReason(code="hook_length_loose", impact="negative", detail={"sentences": sentences}))
    else:
        score += 0.05
        reasons.append(ScoreReason(code="hook_too_many_sentences", impact="negative", detail={"sentences": sentences}))

    share = doc.share("hook")
    if share > SECTION_SHARE_BANDS["hook"][1] + 0.05:
        score -= 0.15
        reasons.append(ScoreReason(code="hook_too_long", impact="negative", detail={"share": share}))

    positions = _section_positions(doc)
    if not positions:
        score += 0.35
    elif positions[0][1] == "hook":
        score += 0.35
        reasons.append(ScoreReason(code="hook_position_ideal", impact="positive", detail={"index": 0}))
    else:
        reasons.append(
            ScoreReason(
                code="hook_not_first",
                impact="negative",
                detail={"first_section": positions[0][1]},
            )
        )

    if doc.narrative_roles:
        if doc.narrative_roles[0] == "hook":
            reasons.append(ScoreReason(code="hook_role_leads", impact="positive", detail={"role": "hook"}))
        else:
            score -= 0.10
            reasons.append(
                ScoreReason(
                    code="hook_role_not_first",
                    impact="negative",
                    detail={"first_role": doc.narrative_roles[0]},
                )
            )

    return _clamp(score), reasons


def score_opening_line(doc: ScriptDoc) -> tuple[float, list[ScoreReason]]:
    """Opening-line strength measured against the fifteen hook archetypes."""
    reasons: list[ScoreReason] = []
    opening = doc.opening_line
    if not opening:
        return 0.0, [ScoreReason(code="opening_missing", impact="negative")]

    matches = match_archetypes(opening)
    starters = {a.id: a.starter for a in ARCHETYPES}
    if matches:
        best = matches[0]
        score = best.confidence
        reasons.append(
            ScoreReason(
                code="archetype_matched",
                impact="positive",
                detail={
                    "archetype": best.id,
                    "starter": starters[best.id],
                    "signals": best.hits,
                    "confidence": best.confidence,
                },
            )
        )
        if len(matches) >= 2:
            score += 0.10
            reasons.append(
                ScoreReason(
                    code="archetype_layered",
                    impact="positive",
                    detail={"archetypes": [m.id for m in matches]},
                )
            )
    else:
        score = 0.0
        reasons.append(ScoreReason(code="archetype_none", impact="negative"))

    generic = count_weak_openers(opening)
    if generic:
        score -= 0.35 * generic
        reasons.append(ScoreReason(code="opening_generic", impact="negative", detail={"signals": generic}))

    words = word_count(opening)
    if words < 4:
        score -= 0.10
        reasons.append(ScoreReason(code="opening_too_short", impact="negative", detail={"words": words}))
    elif words > 30:
        score -= 0.15
        reasons.append(ScoreReason(code="opening_too_long", impact="negative", detail={"words": words}))

    return _clamp(score), reasons


def _rate_score(deviation: float) -> float:
    if deviation <= RATE_FREE_BAND:
        return 1.0
    span = RATE_DEAD_BAND - RATE_FREE_BAND
    return max(0.0, 1.0 - (deviation - RATE_FREE_BAND) / span)


def _rhythm_score(mean_words: float) -> float:
    low_ideal, high_ideal = RHYTHM_IDEAL
    low_dead, high_dead = RHYTHM_DEAD
    if low_ideal <= mean_words <= high_ideal:
        return 1.0
    if mean_words < low_ideal:
        return max(0.0, (mean_words - low_dead) / (low_ideal - low_dead))
    return max(0.0, (high_dead - mean_words) / (high_dead - high_ideal))


def score_pacing(doc: ScriptDoc) -> tuple[float, list[ScoreReason]]:
    """Word rate against the target duration, plus spoken sentence rhythm."""
    reasons: list[ScoreReason] = []
    estimated = doc.estimated_duration
    deviation = abs(estimated - doc.target_duration) / doc.target_duration
    rate = _rate_score(deviation)
    detail = {
        "words": doc.total_words,
        "estimated_duration": estimated,
        "target_duration": doc.target_duration,
        "deviation": round(deviation, 4),
    }
    if deviation <= RATE_FREE_BAND:
        reasons.append(ScoreReason(code="word_rate_on_target", impact="positive", detail=detail))
    elif estimated > doc.target_duration:
        reasons.append(ScoreReason(code="word_rate_over", impact="negative", detail=detail))
    else:
        reasons.append(ScoreReason(code="word_rate_under", impact="negative", detail=detail))

    sentences = doc.sentences
    if sentences:
        mean_words = round(doc.total_words / len(sentences), 2)
        rhythm = _rhythm_score(mean_words)
        long_sentences = sum(1 for s in sentences if word_count(s) > LONG_SENTENCE_WORDS)
        if long_sentences:
            share = round(long_sentences / len(sentences), 4)
            rhythm = max(0.0, rhythm - share)
            reasons.append(
                ScoreReason(
                    code="sentences_too_long",
                    impact="negative",
                    detail={"count": long_sentences, "share": share, "threshold": LONG_SENTENCE_WORDS},
                )
            )
        rhythm_detail = {"mean_sentence_words": mean_words, "sentences": len(sentences)}
        if rhythm >= 0.999:
            reasons.append(ScoreReason(code="sentence_rhythm_ideal", impact="positive", detail=rhythm_detail))
        else:
            reasons.append(ScoreReason(code="sentence_rhythm_off", impact="negative", detail=rhythm_detail))
    else:
        rhythm = 0.0
        reasons.append(ScoreReason(code="no_sentences", impact="negative"))

    return _clamp(0.65 * rate + 0.35 * rhythm), reasons


def score_open_loops(doc: ScriptDoc) -> tuple[float, list[ScoreReason]]:
    """Curiosity gaps that carry the viewer across the middle of the script."""
    reasons: list[ScoreReason] = []
    matched = [
        pattern.pattern
        for pattern in _OPEN_LOOP_PATTERNS
        if pattern.search(doc.story_text)
    ]
    body = " ".join(doc.sections[key] for key in ("build", "climax") if doc.sections[key])
    mid_questions = sum(1 for s in split_sentences(body) if s.endswith("?"))
    loops = len(matched) + mid_questions

    if not loops:
        return 0.0, [ScoreReason(code="open_loops_none", impact="negative")]

    density = round(loops / max(1.0, doc.total_words / 100.0), 4)
    score = max(0.35, min(1.0, density / LOOP_DENSITY_TARGET))
    reasons.append(
        ScoreReason(
            code="open_loops_found",
            impact="positive",
            detail={"count": loops, "markers": len(matched), "questions": mid_questions, "density": density},
        )
    )
    if density < LOOP_DENSITY_TARGET / 2:
        reasons.append(
            ScoreReason(
                code="open_loops_sparse",
                impact="negative",
                detail={"density": density, "target": LOOP_DENSITY_TARGET},
            )
        )

    if any(pattern.search(doc.sections["build"]) for pattern in _OPEN_LOOP_PATTERNS):
        score += 0.10
        reasons.append(ScoreReason(code="open_loops_in_build", impact="positive"))

    return _clamp(score), reasons


def score_cta(doc: ScriptDoc) -> tuple[float, list[ScoreReason]]:
    """Is there a close, and does it ask the viewer for anything?"""
    cta = doc.sections.get("cta") or ""
    if not cta:
        return 0.0, [ScoreReason(code="cta_missing", impact="negative")]

    reasons = [ScoreReason(code="cta_present", impact="positive", detail={"words": doc.section_words["cta"]})]
    score = 0.45

    signals = sum(1 for pattern in _CTA_ACTION_PATTERNS if pattern.search(cta))
    if signals:
        score += 0.35
        reasons.append(ScoreReason(code="cta_action_signal", impact="positive", detail={"signals": signals}))
    else:
        reasons.append(ScoreReason(code="cta_no_action_signal", impact="negative"))

    sentences = len(split_sentences(cta))
    if sentences == 1:
        score += 0.20
        reasons.append(ScoreReason(code="cta_length_ideal", impact="positive", detail={"sentences": sentences}))
    elif sentences == 2:
        score += 0.10
        reasons.append(ScoreReason(code="cta_length_loose", impact="negative", detail={"sentences": sentences}))
    else:
        reasons.append(ScoreReason(code="cta_too_long", impact="negative", detail={"sentences": sentences}))

    return _clamp(score), reasons


def _share_deviation(share: float, band: tuple[float, float]) -> float:
    low, high = band
    if share < low:
        return min(1.0, (low - share) / low)
    if share > high:
        return min(1.0, (share - high) / max(1e-6, 1.0 - high))
    return 0.0


def score_balance(doc: ScriptDoc) -> tuple[float, list[ScoreReason]]:
    """Do the four mandated sections carry proportionate weight?"""
    reasons: list[ScoreReason] = []
    deviations: list[float] = []
    for key in SECTION_KEYS:
        band = SECTION_SHARE_BANDS[key]
        share = doc.share(key)
        deviation = _share_deviation(share, band)
        deviations.append(deviation)
        if not doc.sections[key]:
            reasons.append(ScoreReason(code="section_missing", impact="negative", detail={"section": key}))
        elif deviation > 0.0:
            code = "section_share_low" if share < band[0] else "section_share_high"
            reasons.append(
                ScoreReason(
                    code=code,
                    impact="negative",
                    detail={"section": key, "share": share, "band": list(band)},
                )
            )

    score = 1.0 - (sum(deviations) / len(deviations))
    if not reasons:
        reasons.append(ScoreReason(code="section_balance_ideal", impact="positive"))
    return _clamp(score), reasons


# Declaration order matches models.DIMENSION_IDS.
SCORERS = (
    ("hook", score_hook),
    ("opening_line", score_opening_line),
    ("pacing", score_pacing),
    ("open_loops", score_open_loops),
    ("cta", score_cta),
    ("balance", score_balance),
)
