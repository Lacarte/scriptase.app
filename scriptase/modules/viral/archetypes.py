"""The fifteen hook archetypes, as detectors (step 16.1).

``scriptase.modules.script.prompts._ANGLE_STARTERS`` tells the writer *how* to
open. This module recognises whether the writer actually did, one detector per
starter and in the same order — ``tests/test_viral_scoring.py`` asserts the 1:1
alignment so the two lists cannot drift apart silently.

Detection is regex over the opening line only: offline, deterministic, and free.
Archetypes deliberately overlap ("what if" is also a question); the scorer takes
the strongest match and reports every id that fired.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Archetype(NamedTuple):
    """One hook archetype and the surface signals that betray it."""

    id: str
    starter: str
    patterns: tuple[re.Pattern[str], ...]


def _patterns(*sources: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(source, re.IGNORECASE) for source in sources)


# Order matches `_ANGLE_STARTERS` exactly and breaks ties in match ranking.
ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        "little_known_fact",
        "Start with a little-known fact or paradox",
        _patterns(
            r"\b(most people|almost nobody|hardly anyone|few people|barely anyone)\b",
            r"\b(don'?t know|never realiz|have no idea|aren'?t told|won'?t tell you)\b",
            r"\b(paradox|little[- ]known|overlooked|counterintuitive|hidden in plain sight)\b",
            r"\b\d{1,3}(\.\d+)?\s?(%|percent)\b",
        ),
    ),
    Archetype(
        "personal_anecdote",
        "Open with a personal anecdote or first-person scenario",
        _patterns(
            r"^\s*(i|my|we)\b",
            r"\b(when i was|i used to|i once|the day i|i remember|i spent)\b",
            r"\bmy (mother|father|mom|dad|friend|boss|doctor|grandmother|grandfather|neighbou?r)\b",
        ),
    ),
    Archetype(
        "provocative_question",
        "Begin with a provocative question that challenges assumptions",
        _patterns(
            r"\?\s*$",
            r"^\s*(why|how|who|which|when)\b",
            r"\b(ever wonder|ask yourself|did you know|have you noticed)\b",
        ),
    ),
    Archetype(
        "sensory_scene",
        "Start with a vivid sensory scene the listener can picture",
        _patterns(
            r"\b(imagine|picture this|picture yourself|close your eyes)\b",
            r"\byou can (smell|hear|feel|taste|see)\b",
            r"\b(smell|scent|taste|texture|echo|silence|damp|glow|hum|flicker)\w*\b",
            r"\bthe (air|light|sound|smell|silence)\b",
        ),
    ),
    Archetype(
        "controversial_claim",
        "Open with a bold controversial claim",
        _patterns(
            r"\beverything you (know|think|believe|were taught)\b",
            r"\bis a (lie|myth|scam|fraud|con)\b",
            r"\b(never worked|doesn'?t work|is dead wrong|is complete nonsense)\b",
            r"\b(no one|nobody) (wants to|will) (tell|admit|say)\b",
        ),
    ),
    Archetype(
        "historical_event",
        "Begin with a historical event most people have never heard of",
        _patterns(
            r"\b(1[0-9]{3}|20[0-2][0-9])\b",
            r"\b(centur(y|ies)|decades? ago|years ago|ancient|medieval|empire|dynasty|revolution)\b",
            r"\bin (january|february|march|april|may|june|july|august|september|october|november|december)\b",
        ),
    ),
    Archetype(
        "what_if",
        "Start with a 'what if' thought experiment",
        _patterns(
            r"\bwhat if\b",
            r"\b(imagine if|suppose for a|suppose that|what would happen if)\b",
            r"\bwhat would you\b",
        ),
    ),
    Archetype(
        "belief_subversion",
        "Open with a common belief and immediately subvert it",
        _patterns(
            r"\b(you|we) (think|believe|assume|were told)\b",
            r"\b(most|many) people (think|believe|assume)\b",
            r"\b(but actually|in reality|the truth is|turns out|except (that|it))\b",
            r"\bthat'?s not (true|what|how)\b",
        ),
    ),
    Archetype(
        "countdown_list",
        "Begin with a countdown, list, or pattern that builds tension",
        _patterns(
            r"^\s*\d{1,2}\b",
            r"\b(two|three|four|five|six|seven|ten) (things|reasons|signs|ways|rules|habits|mistakes|types|stages)\b",
            r"\b(here are|number one|the first one|counting down)\b",
        ),
    ),
    Archetype(
        "mid_action",
        "Start mid-action, dropping the listener into a dramatic moment",
        _patterns(
            r"^\s*(he|she|they|it) (was|were|had|slammed|ran|screamed|froze|collapsed)\b",
            r"\b(at that moment|the moment|seconds later|by the time|just as|halfway through)\b",
            r"\b(alarm|siren|gunshot|scream|crash|blood|smoke|explosion)\w*\b",
        ),
    ),
    Archetype(
        "impossible_science",
        "Open with a scientific discovery that sounds impossible",
        _patterns(
            r"\b(scientists?|researchers?|physicists?|neuroscientists?|biologists?)\b",
            r"\b(stud(y|ies)|experiment|discover(ed|y)|trial|lab|peer[- ]reviewed)\b",
            r"\b(quantum|neurons?|dna|gravity|entropy|evolution|brain scans?|particles?)\b",
        ),
    ),
    Archetype(
        "intimate_confession",
        "Begin with a quiet, intimate confession",
        _patterns(
            r"\bi (never|have never|still haven'?t) told\b",
            r"\b(confess|confession|admit|ashamed|embarrass|guilt)\w*\b",
            r"\b(secretly|no one knows this|between you and me)\b",
        ),
    ),
    Archetype(
        "contradictory_truths",
        "Start with two contradictory truths side by side",
        _patterns(
            r"\bboth\b.+\band\b",
            r"\b(at the same time|simultaneously|and yet|yet also)\b",
            r"\b(right and wrong|true and false|safest.+deadliest|smallest.+largest)\b",
        ),
    ),
    Archetype(
        "warning_prediction",
        "Open with a warning or ominous prediction",
        _patterns(
            r"\b(warning|be warned|danger(ous)?|about to|before it'?s too late)\b",
            r"\bwill (soon|never|change|collapse|disappear|end)\b",
            r"\bby 20[2-9][0-9]\b",
        ),
    ),
    Archetype(
        "universal_unspoken",
        "Begin by describing something everyone does but nobody talks about",
        _patterns(
            r"\b(everyone|everybody) (does|has|feels|is)\b",
            r"\bwe all\b",
            r"\b(nobody talks about|no one talks about|no one admits|never mention)\b",
            r"\b(out loud|in public|behind closed doors)\b",
        ),
    ),
)

ARCHETYPE_IDS: tuple[str, ...] = tuple(a.id for a in ARCHETYPES)

# Openings that announce the video instead of starting it. Any hit is a penalty
# regardless of what else matched.
WEAK_OPENERS: tuple[re.Pattern[str], ...] = _patterns(
    r"^\s*(hi|hey|hello|welcome|so)\b",
    r"\b(in this (video|short|clip)|in today'?s video|today (i|we)('| a)?l?l?\b)",
    r"\b(let me tell you|i want to talk about|i'?m going to (tell|show|talk))\b",
    r"\bthis (is|video is) (a )?(story |video )?about\b",
    r"\bwe('| wi)?ll (discuss|explore|look at|cover)\b",
    r"\b(like and subscribe|don'?t forget to subscribe)\b",
)


class ArchetypeMatch(NamedTuple):
    """A fired archetype and how strongly it fired."""

    id: str
    hits: int
    confidence: float


def match_archetypes(opening: str) -> list[ArchetypeMatch]:
    """Match an opening line against every archetype.

    Returns matches ordered by descending confidence, ties broken by declaration
    order, so the result is stable for identical input.
    """
    text = (opening or "").strip()
    if not text:
        return []

    matches: list[ArchetypeMatch] = []
    for index, archetype in enumerate(ARCHETYPES):
        hits = sum(1 for pattern in archetype.patterns if pattern.search(text))
        if hits:
            # One signal is suggestive, three make it unambiguous.
            confidence = min(1.0, 0.6 + 0.2 * (hits - 1))
            matches.append(ArchetypeMatch(archetype.id, hits, round(confidence, 4)))
    matches.sort(key=lambda m: (-m.confidence, -m.hits, ARCHETYPE_IDS.index(m.id)))
    return matches


def count_weak_openers(opening: str) -> int:
    """Count announcement-style patterns in an opening line."""
    text = (opening or "").strip()
    if not text:
        return 0
    return sum(1 for pattern in WEAK_OPENERS if pattern.search(text))
