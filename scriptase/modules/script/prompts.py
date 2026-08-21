"""Prompt templates for story generation."""

import random
import re
import string

from scriptase.modules.scene_director.templates import STORY_CATEGORIES, TEMPLATES_BY_ID  # noqa: F401 — re-exported

# The default beats when a channel declares no template. Kept here (not imported
# from engine) to avoid a cycle; engine.DEFAULT_SECTIONS mirrors this.
DEFAULT_SECTIONS = ("Hook", "Build", "Climax", "CTA")

# Approximate words per second for spoken narration at 1.0x speed
WORDS_PER_SECOND = 2.5


def compute_word_target(duration_seconds: int) -> int:
    """Compute approximate word count target from duration."""
    return max(20, round(duration_seconds * WORDS_PER_SECOND))


LANGUAGE_LEVEL_HINTS = {
    "beginner": "Use very simple vocabulary, short sentences (5-8 words), basic grammar, and common everyday words. Avoid idioms, slang, and complex structures.",
    "intermediate": "Use clear vocabulary with some descriptive words. Mix short and medium sentences. Occasional idioms are fine but keep language accessible.",
    "advanced": "Use rich vocabulary, varied sentence structures, literary devices, and natural idioms. Write with sophistication but keep it spoken-natural.",
    "native": "Write as a native speaker would naturally speak — colloquialisms, cultural references, natural rhythm, and full expressive range.",
}

_CATEGORY_TOPIC_BANKS = {
    "motivation": [
        "fear of being seen trying",
        "rebuilding self-trust after breaking promises to yourself",
        "the boredom of repetition before progress appears",
        "recovering after a humiliating failure",
        "quiet discipline when nobody is watching",
        "leaving an identity that keeps you small",
        "the cost of comfort and procrastination",
        "social comparison and envy",
        "relapse, setbacks, and starting again",
        "focus in a distracted life",
        "choosing long-term self-respect over short-term relief",
        "the loneliness of outgrowing your old habits",
    ],
    "philosophy": [
        "identity and the stories you tell about yourself",
        "time, mortality, and wasted years",
        "meaning in ordinary routines",
        "the tension between freedom and responsibility",
        "memory and how it edits reality",
        "self-deception and comforting illusions",
        "loneliness in a crowded world",
        "the difference between attention and truth",
        "how language shapes thought",
        "the cost of wanting certainty",
        "silence, contemplation, and inner noise",
        "the gap between the life you perform and the life you feel",
    ],
    "psychology": [
        "subtle manipulation in everyday conversations",
        "people-pleasing and weak boundaries",
        "status games and social dominance",
        "envy, insecurity, and hidden resentment",
        "attachment, rejection, and control",
        "the masks people wear to be accepted",
        "shame loops and self-sabotage",
        "group pressure and borrowed beliefs",
        "micro-behaviors that reveal intention",
        "respect versus fear",
        "projection and blaming others for what you hide",
        "how power shifts inside relationships",
    ],
    "crime": [
        "small lies that cracked a case open",
        "ordinary routines before a crime",
        "misdirection and false suspects",
        "witness memory and unreliable details",
        "digital traces and overlooked evidence",
        "a motive hiding inside a family dynamic",
        "cold-case turning points",
        "interrogation pressure and contradictions",
        "the first thing investigators got wrong",
        "quiet behavioral tells after a crime",
        "missing timeline gaps",
        "the cost of one wrong assumption",
    ],
    "horror": [
        "a familiar home becoming hostile",
        "mirrors, reflections, and doubled selves",
        "sleep paralysis and late-night dread",
        "rituals no one fully understands",
        "recurring dreams that bleed into waking life",
        "ordinary objects turning uncanny",
        "children noticing what adults ignore",
        "locked rooms and forbidden spaces",
        "fog, woods, or empty roads at night",
        "body signals that something is wrong",
        "found recordings and distorted messages",
        "folklore that turns out to be practical advice",
    ],
    "religion": [
        "forgotten biblical figures",
        "moral paradoxes inside scripture",
        "faith under pressure",
        "judgment versus mercy",
        "prophecy and unintended consequences",
        "hidden motives behind sacred decisions",
        "betrayal, exile, and return",
        "obedience, sacrifice, and fear",
        "symbols, visions, and warnings",
        "the human cost of divine tests",
        "small acts of faith in impossible conditions",
        "how one verse changes the meaning of a story",
    ],
    "mystery": [
        "coded messages and patterns",
        "missing records and erased history",
        "manufactured narratives",
        "public myths versus private truth",
        "the one detail everyone ignored",
        "front organizations and hidden networks",
        "information control and selective leaks",
        "whistleblowers and paranoia",
        "ritual, secrecy, and symbolism",
        "false explanations built to calm the crowd",
        "coincidences that feel too clean",
        "what happens when curiosity goes too far",
    ],
    "romance": [
        "almost-relationships and missed timing",
        "fear of vulnerability",
        "one small gesture that changes everything",
        "distance, silence, and longing",
        "jealousy and misread signals",
        "reconciliation after pride",
        "chosen tenderness in hard moments",
        "unsent messages and unfinished feelings",
        "love colliding with ambition",
        "memory after separation",
        "the cost of staying emotionally guarded",
        "quiet devotion instead of grand gestures",
    ],
    "children": [
        "friendship after conflict",
        "bravery in a small everyday moment",
        "kindness to someone left out",
        "bedtime fears and imagination",
        "learning honesty after a mistake",
        "sharing and jealousy",
        "a tiny adventure close to home",
        "patience and trying again",
        "wonder in ordinary things",
        "curiosity that leads to trouble",
        "siblings learning empathy",
        "turning embarrassment into courage",
    ],
    "science": [
        "a scientific fact with emotional consequences",
        "time, scale, and human smallness",
        "the body doing strange hidden work",
        "future technology changing identity",
        "why a common belief is wrong",
        "space, distance, and cosmic loneliness",
        "AI, memory, and imitation",
        "invisible systems shaping daily life",
        "an experiment that changed how we see reality",
        "unexpected survival strategies in nature",
        "the ethics behind a discovery",
        "how one tiny mechanism changes everything",
    ],
    "anecdote": [
        "an awkward confession",
        "workplace absurdity",
        "family tension at the wrong moment",
        "a stranger showing unexpected kindness",
        "petty conflict that escalates too far",
        "an embarrassing online mistake",
        "travel chaos and bad timing",
        "a revenge plan backfiring",
        "boundary-setting with difficult people",
        "a coincidence that feels unbelievable",
        "regret after saying the quiet part out loud",
        "a moral dilemma with no clean answer",
    ],
    "survival": [
        "rationing, weather, and exhaustion",
        "improvising with limited tools",
        "a split-second decision under stress",
        "human conflict making danger worse",
        "the body shutting down in extreme conditions",
        "hope versus realism",
        "a survival rule that sounds wrong but works",
        "navigating without certainty",
        "injury, fear, and mental endurance",
        "the problem of trusting others",
        "tiny mistakes becoming life-threatening",
        "the relief and guilt of being rescued",
    ],
    "history": [
        "forgotten turning points",
        "ordinary people inside major events",
        "small decisions with huge consequences",
        "betrayal, succession, and power",
        "propaganda and historical mythmaking",
        "a city, artifact, or empire at the edge of collapse",
        "survival during upheaval",
        "misread warnings before disaster",
        "leaders versus systems",
        "what history remembers wrong",
        "daily life in a brutal era",
        "the hidden cost of a famous victory",
    ],
    "curiosity": [
        "a weird fact with serious implications",
        "common habits with hidden origins",
        "strange design choices in daily life",
        "a myth everyone repeats",
        "the logic behind something that looks irrational",
        "an overlooked rule shaping behavior",
        "the hidden reason something feels familiar",
        "a phenomenon people notice but misread",
        "an invention with surprising side effects",
        "why an old belief still survives",
        "how a tiny detail changes the whole story",
        "a question people rarely think to ask",
    ],
}

_NICHE_TOPIC_BANKS = {
    "dark_psychology": [
        "love bombing and sudden withdrawal",
        "triangulation and making people compete for attention",
        "guilt as a tool of control",
        "mirroring, charm, and strategic imitation",
        "boundary tests disguised as jokes",
        "silent treatment and emotional punishment",
        "the hunger for status and dominance",
        "people who weaponize vulnerability",
        "the psychology of humiliation",
        "why insecure people crave control",
        "social masks that collapse under pressure",
        "how fear can look like confidence",
    ],
    "stoicism": [
        "control versus obsession",
        "reputation and insult",
        "grief without collapse",
        "anger, provocation, and restraint",
        "comfort addiction and voluntary discomfort",
        "impermanence and letting go",
        "duty during chaos",
        "envy and comparison",
        "wealth, status, and inner freedom",
        "boredom, waiting, and patience",
        "turning setbacks into training",
        "discipline without self-hatred",
    ],
    "existential": [
        "the strangeness of being conscious",
        "how memory edits identity",
        "mortality and unfinished lives",
        "the emptiness of routine success",
        "freedom as a burden",
        "the fear of being ordinary",
        "loneliness inside constant connection",
        "meaning created versus meaning discovered",
        "selfhood as performance",
        "what silence reveals",
        "the absurdity of wanting permanent certainty",
        "the distance between your inner life and outer role",
    ],
    "motivation": [
        "identity before achievement",
        "discipline during boring seasons",
        "fear of embarrassment",
        "rebuilding after wasted time",
        "self-respect earned in private",
        "breaking dependence on motivation spikes",
        "escaping comfort that is quietly ruining you",
        "consistency after relapse",
        "the courage to be bad before getting good",
        "using pain as information instead of drama",
        "what happens when nobody validates your progress",
        "the slow compounding of tiny choices",
    ],
    "wealth": [
        "status traps and fake success",
        "lifestyle inflation",
        "scarcity mindset after money arrives",
        "quiet wealth versus loud wealth",
        "delayed gratification in a culture of display",
        "debt and invisible financial stress",
        "envy disguised as ambition",
        "self-worth tied to income",
        "risk, leverage, and patience",
        "the habits that keep people broke even when they earn more",
        "greed versus security",
        "money exposing character",
    ],
    "true_crime": [
        "the suspect who looked too normal",
        "a timeline with one missing hour",
        "behavior after the crime that gave everything away",
        "the witness nobody took seriously",
        "tiny forensic details with huge consequences",
        "family loyalty blocking the truth",
        "an alibi that was almost perfect",
        "cold-case evidence rediscovered years later",
        "the moment investigators changed theory",
        "a lie told for the wrong reason",
        "digital footprints nobody expected",
        "the danger of locking onto the first suspect",
    ],
    "horror": [
        "a ritual inherited without explanation",
        "hearing something answer back from an empty room",
        "a safe place turning predatory",
        "nighttime habits that become survival rules",
        "a child recognizing the threat before adults do",
        "an ordinary object holding a wrong presence",
        "dream logic leaking into daylight",
        "one forbidden room everyone pretends not to notice",
        "a family secret that wants to be repeated",
        "something old living behind a local superstition",
        "fear of your own body betraying you",
        "the cost of curiosity after the first warning",
    ],
    "biblical": [
        "a neglected biblical figure with a hard choice",
        "judgment and mercy colliding in the same story",
        "prophecy misunderstood by the people hearing it",
        "faith that looks irrational from the outside",
        "symbols, visions, and coded warnings",
        "betrayal from inside a sacred circle",
        "obedience when the outcome makes no sense",
        "small acts of faith in eras of collapse",
        "the human pain behind a famous miracle",
        "a harsh passage that becomes clearer in context",
        "exile, return, and spiritual identity",
        "fear of divine silence",
    ],
    "conspiracy": [
        "public stories built to hide private agendas",
        "the record that went missing at the right time",
        "symbols that matter only if you know the system",
        "how panic can be manufactured",
        "front groups and plausible deniability",
        "information drip-fed to shape belief",
        "ritual, power, and selective secrecy",
        "what makes people easier to deceive",
        "the whistleblower nobody wanted to hear",
        "a coincidence that becomes a pattern",
        "why conspiracy thinking can feel emotionally addictive",
        "the line between paranoia and pattern recognition",
    ],
    "romance": [
        "emotional timing instead of compatibility",
        "love after distance or silence",
        "the cost of acting unbothered",
        "small tenderness after conflict",
        "fear of saying too much too soon",
        "a connection that changes through absence",
        "jealousy exposing deeper insecurity",
        "choosing softness over pride",
        "the memory of one ordinary moment",
        "ambition pulling two people apart",
        "reconciliation that requires honesty",
        "learning to receive love without suspicion",
    ],
    "children": [
        "kindness toward someone excluded",
        "a first brave act",
        "fixing a friendship after a mistake",
        "learning patience in a fun way",
        "curiosity causing harmless chaos",
        "sharing when it feels unfair",
        "bedtime fear turning into imagination",
        "a sibling conflict ending in empathy",
        "discovering wonder in a tiny everyday detail",
        "choosing honesty after panic",
        "turning embarrassment into confidence",
        "a small adventure with a big feeling",
    ],
    "sci_fi": [
        "memory editing and identity loss",
        "AI sounding human in uncomfortable ways",
        "parallel lives and alternate regrets",
        "first contact with something indifferent to us",
        "future cities that solve one problem and create another",
        "time distortion and unfinished choices",
        "the body changed by technology",
        "simulation logic versus lived feeling",
        "loneliness in highly advanced societies",
        "messages from extinct civilizations",
        "ethical costs of perfect convenience",
        "humanity imitating machines instead of the reverse",
    ],
    "reddit": [
        "a painfully awkward confession",
        "petty revenge with consequences",
        "family drama in public",
        "a weird workplace power struggle",
        "a stranger doing something unforgettable",
        "travel chaos from one bad choice",
        "a boundary finally being enforced",
        "an online mistake that won't die",
        "a coincidence too strange to explain cleanly",
        "telling a lie that grows legs",
        "helping someone and regretting it",
        "finding out you were the problem all along",
    ],
    "two_choices": [
        "comfort versus growth",
        "honesty versus belonging",
        "revenge versus peace",
        "safety versus freedom",
        "ambition versus love",
        "control versus trust",
        "justice versus mercy",
        "approval versus self-respect",
        "certainty versus discovery",
        "loyalty versus truth",
        "patience versus impulse",
        "power versus integrity",
    ],
}

_STYLE_TOPIC_BANKS = {
    "stickman_animation": [
        "a tense conversation at work or school",
        "scrolling alone late at night",
        "an unread message that changes your mood",
        "a quiet commute with racing thoughts",
        "a friend pulling away without explanation",
        "a small public embarrassment",
        "a daily habit nobody notices",
        "family expectations in an ordinary room",
        "a boring practice session before any payoff",
        "a tiny act of courage in a plain everyday setting",
    ],
    "stickman_glow": [
        "lying awake in the dark with one heavy thought",
        "feeling isolated in a crowded room",
        "the chest-tightening moment before speaking honestly",
        "sitting alone after an argument",
        "watching your inner spark dim under pressure",
        "holding onto one small reason not to give up",
        "carrying hope quietly through a bleak day",
        "finding a flicker of meaning inside exhaustion",
    ],
}

_NARRATIVE_LENSES = {
    "motivation": [
        "Treat motivation as identity, shame, boredom, or recovery — not just productivity advice",
        "Center the story on one concrete human struggle instead of abstract grindset language",
        "Show what the character is losing by staying stuck, not just what success looks like",
    ],
    "stoicism": [
        "Make the philosophy practical and lived-in, not a quote carousel",
        "Focus on one human weakness and how restraint changes the outcome",
        "Turn the idea into a test of character under pressure",
    ],
    "existential": [
        "Keep it intimate and human, not only cosmic and abstract",
        "Tie the idea to one ordinary moment that suddenly feels profound",
        "Let the tension come from consciousness, memory, time, or selfhood",
    ],
    "dark_psychology": [
        "Anchor the story in subtle social behavior, not cartoon villain monologues",
        "Make the threat psychologically plausible and recognizable",
        "Focus on power shifts, hidden motives, and emotional leverage",
    ],
    "true_crime": [
        "Build suspense through small details, timelines, and contradictions",
        "Let one overlooked fact slowly change the whole picture",
        "Make the story feel investigative rather than sensational for its own sake",
    ],
    "horror": [
        "Start from a normal routine and let dread contaminate it",
        "Use one uncanny detail to make the whole world feel unsafe",
        "Favor implication and inevitability over random gore",
    ],
    "biblical": [
        "Bring out the human stakes inside the sacred material",
        "Focus on one hard decision, warning, or paradox inside the scripture",
        "Make the spiritual tension feel alive, not merely recited",
    ],
    "conspiracy": [
        "Build the feeling of pattern recognition without becoming incoherent",
        "Let one suspicious detail escalate into a larger hidden system",
        "Keep the tone investigative, uneasy, and specific",
    ],
    "romance": [
        "Make the story hinge on vulnerability, timing, or restraint",
        "Let one simple moment carry the emotional weight",
        "Favor emotional precision over generic declarations of love",
    ],
    "children": [
        "Keep the lesson inside a playful, tangible moment",
        "Make the emotional conflict small enough for a child and real enough to matter",
        "End with warmth, wonder, or earned courage",
    ],
    "sci_fi": [
        "Use one speculative idea to pressure a very human emotion",
        "Make the future strange but emotionally legible",
        "Let the concept reshape identity, memory, or choice",
    ],
    "reddit": [
        "Tell it like a lived incident with sharp human details",
        "Make the tension come from embarrassment, misunderstanding, or messy consequences",
        "Favor specificity and awkward realism over polished moralizing",
    ],
    "two_choices": [
        "Build the story around a true tradeoff with emotional cost on both sides",
        "Let the dilemma reveal character rather than offering an easy slogan",
        "Make the choice feel concrete, urgent, and irreversible",
    ],
}

_RUT_WARNINGS = {
    "motivation": "Do not default to generic 'just start', 'wake up earlier', 'discipline beats motivation', or hustle-speech framing unless the user's idea specifically asks for that angle.",
    "stoicism": "Do not default to generic Marcus Aurelius quote summaries, 'control what you can', or detached monk clichés unless the specific idea demands it.",
    "existential": "Do not default to 'you are alone in the universe' or vague cosmic sadness. Vary the tension through time, memory, identity, absurdity, routine, or choice.",
    "dark_psychology": "Do not make every story about obvious manipulation masterminds. Use everyday social power, insecurity, subtle control, shame, and status behavior too.",
    "true_crime": "Do not reuse the same serial-killer or missing-girl formula. Vary the case shape, motive, evidence pattern, and investigative turning point.",
    "horror": "Do not rely on the same haunted house or shadow in the hallway setup every time. Rotate through rituals, body fear, folklore, dreams, objects, children, and ordinary places.",
    "biblical": "Do not only retell the most famous miracles. Vary the stories through minor figures, moral paradoxes, warnings, prophecy, exile, sacrifice, and hidden motives.",
    "conspiracy": "Do not reuse the same shadowy-elite monologue every time. Vary the mechanism: records, symbols, fronts, leaks, panic, cover stories, and belief shaping.",
}

_GENERIC_LENSES = [
    "Make the story hinge on one fresh central conflict, not a familiar slogan",
    "Use a concrete human scenario instead of broad abstract lecturing",
    "Vary the emotional arc, the reveal, and the final takeaway — not just the hook",
]


# The default beats and their per-beat writing guidance. A channel template that
# uses these exact labels gets this rich direction; custom beats get a concise,
# position-aware instruction generated from the template.
_DEFAULT_BEAT_GUIDANCE = {
    "hook": ("1-2 sentences — immediate attention grab, pattern interrupt, or shocking "
             "statement that promises secret knowledge or a surprising truth"),
    "build": ("Core narrative — context, tension, escalation. This is the longest section. "
              "Use contrast between what people believe vs. what's really happening. "
              "Escalate from subtle, low-stakes observations to high-stakes revelations. "
              "Include practical, observable examples so the viewer can recognize them in "
              "real life. End key passages with open loops like 'but here's what most don't realize.'"),
    "climax": ("Peak moment — the twist, revelation, or emotional peak. Blend authority "
               "(science, evolution, psychology) with emotional stakes."),
    "cta": ("1 sentence — call to action, question, or cliffhanger that reminds the viewer "
            "what's at stake"),
}


def _beat_guidance(beat: str, index: int, total: int) -> str:
    """Writing direction for one beat: rich for the canonical four, else generic."""
    key = re.sub(r"[^a-z0-9]+", "_", str(beat).strip().lower()).strip("_")
    if key in _DEFAULT_BEAT_GUIDANCE:
        return _DEFAULT_BEAT_GUIDANCE[key]
    if index == 0:
        return "Open with an immediate attention grab — a hook that promises a payoff."
    if index == total - 1:
        return "Land the piece — a memorable close, call to action, or lingering question."
    return f"Advance the narrative through this beat ('{beat}') — keep the momentum building."


def _beats(sections) -> list[str]:
    beats = [str(s).strip() for s in (sections or DEFAULT_SECTIONS) if str(s).strip()]
    return beats or list(DEFAULT_SECTIONS)


def _build_structure_block(sections) -> str:
    """The OUTPUT STRUCTURE section, generated from the channel's beats."""
    beats = _beats(sections)
    total = len(beats)
    labels_csv = " / ".join(f"{b}:" for b in beats)
    lines = [
        f"OUTPUT STRUCTURE — write EXACTLY {total} sections, each on its own line, "
        f"each beginning with its label followed by a colon. Use these labels, in "
        f"this order, and no others: {labels_csv}",
    ]
    for i, beat in enumerate(beats):
        lines.append(f"{beat}: [{_beat_guidance(beat, i, total)}]")
    return "\n\n".join(lines)


def _structure_reminder(sections) -> str:
    """A final, emphatic restatement — the last instruction the model reads."""
    beats = _beats(sections)
    example = "  ".join(f"{b}: …" for b in beats)
    return (
        "CRITICAL — before you answer, confirm your script has every one of these "
        f"labels, spelled exactly, each starting its own line: {', '.join(beats)}. "
        f"The shape must be:\n{example}\n"
        "A script missing any label is invalid. Do not merge, rename, or omit a label."
    )


def build_story_system_prompt(
    preset_style: str,
    story_category: str,
    duration: int,
    language: str,
    story_tone: str = None,
    language_level: str = None,
    sections=None,
) -> str:
    """Build the system prompt for the LLM story generation call.

    `sections` is the Channel template's ordered beats — the single source of the
    script's structure. Defaults to Hook/Build/Climax/CTA when absent.
    """
    word_target = compute_word_target(duration)

    # Resolve style description
    template = TEMPLATES_BY_ID.get(preset_style, {})
    style_name = template.get("name", preset_style)
    style_desc = template.get("description", "")

    # Resolve story tone (from niche system)
    tone_line = ""
    if story_tone:
        from scriptase.channels.presets import STORY_TONES
        tone_desc = STORY_TONES.get(story_tone, "")
        if tone_desc:
            tone_line = f"NARRATION TONE: {story_tone} — {tone_desc}\n"

    # Language level instruction
    level_line = ""
    if language_level:
        hint = LANGUAGE_LEVEL_HINTS.get(language_level, "")
        level_line = f"LANGUAGE LEVEL: {language_level} — {hint}\n"

    return (
        f"You are a viral short-form content writer specializing in {story_category} stories.\n"
        f"Your stories are designed for {duration}-second spoken narration videos.\n\n"
        f"VISUAL STYLE: {style_name} — {style_desc}\n"
        f"{tone_line}"
        f"{level_line}"
        f"Match the emotional tone and vocabulary to this visual style.\n\n"
        f"Write in {language}. Target approximately {word_target} words total.\n\n"
        "The script must read as natural spoken flow suitable for voiceover — no "
        "titles, no summaries, no stage directions. The ONLY structural markers "
        "allowed (and required) are the exact section labels defined below.\n\n"
        f"{_build_structure_block(sections)}\n\n"
        "WRITING RULES:\n"
        "- Use simple, everyday language — even when explaining complex ideas. "
        "Write like you're explaining to a smart friend, not a professor. "
        "Short words beat long words. If a 10-year-old can't follow it, simplify.\n"
        "- Plain text only. No markdown, no formatting, no emojis, no asterisks.\n"
        "- Write as spoken narration — short punchy sentences, conversational rhythm, "
        "natural pauses through line breaks.\n"
        f"- Total word count must be within ±10% of {word_target} words.\n"
        f"- Write entirely in {language}.\n"
        "- No meta-commentary, instructions, or stage directions — but the section "
        "labels above are mandatory, not meta-text.\n"
        "- Reinforce key phrases and recurring motifs to build authority and memorability.\n\n"
        + _structure_reminder(sections)
    )


_ANGLE_STARTERS = [
    "Start with a little-known fact or paradox",
    "Open with a personal anecdote or first-person scenario",
    "Begin with a provocative question that challenges assumptions",
    "Start with a vivid sensory scene the listener can picture",
    "Open with a bold controversial claim",
    "Begin with a historical event most people have never heard of",
    "Start with a 'what if' thought experiment",
    "Open with a common belief and immediately subvert it",
    "Begin with a countdown, list, or pattern that builds tension",
    "Start mid-action, dropping the listener into a dramatic moment",
    "Open with a scientific discovery that sounds impossible",
    "Begin with a quiet, intimate confession",
    "Start with two contradictory truths side by side",
    "Open with a warning or ominous prediction",
    "Begin by describing something everyone does but nobody talks about",
]


def _unique_seed() -> str:
    """Generate a short random seed to break LLM/cache deduplication."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))


def _sample_unique(items, count: int) -> list[str]:
    seen = set()
    values = []
    for raw in items or []:
        item = str(raw or "").strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(item)
    if len(values) <= count:
        return values
    return random.sample(values, count)


def _recent_story_concepts(
    preset_style: str,
    story_category: str,
    language: str,
    *,
    limit: int = 4,
) -> list[str]:
    from scriptase.modules.script.history import load_history

    history = load_history(preset_style, story_category, language)
    concepts = []
    seen = set()
    for entry in reversed(history):
        concept = str(entry.get("concept_family") or "").strip()
        if not concept:
            continue
        key = concept.lower()
        if key in seen:
            continue
        seen.add(key)
        concepts.append(concept)
        if len(concepts) >= limit:
            break
    concepts.reverse()
    return concepts


def _resolve_niche_topic_context(
    preset_style: str,
    story_category: str,
    niche_preset: str = None,
) -> dict:
    preset = {}
    niche = ""
    label = ""
    description = ""

    if niche_preset:
        from scriptase.channels.presets import get_presets, normalize_preset_id

        preset = get_presets().get(normalize_preset_id(niche_preset), {}) or {}
        niche = str(preset.get("niche") or "").strip().lower()
        label = str(preset.get("label") or "").strip()
        description = str(preset.get("description") or "").strip()

    style_id = str(preset_style or "").strip().lower()
    category_id = str(story_category or "").strip().lower()

    return {
        "preset": preset,
        "niche": niche,
        "label": label,
        "description": description,
        "style_id": style_id,
        "category_id": category_id,
        "topic_bank": _NICHE_TOPIC_BANKS.get(niche) or _CATEGORY_TOPIC_BANKS.get(category_id) or [],
        "style_bank": _STYLE_TOPIC_BANKS.get(style_id) or [],
        "lens_bank": _NARRATIVE_LENSES.get(niche) or _NARRATIVE_LENSES.get(category_id) or _GENERIC_LENSES,
        "rut_warning": _RUT_WARNINGS.get(niche) or _RUT_WARNINGS.get(category_id) or "",
    }


def choose_story_concept_family(
    preset_style: str,
    story_category: str,
    language: str,
    niche_preset: str = None,
) -> str:
    context = _resolve_niche_topic_context(preset_style, story_category, niche_preset=niche_preset)
    topic_bank = context.get("topic_bank") or []
    if not topic_bank:
        return ""

    recent = {item.lower() for item in _recent_story_concepts(preset_style, story_category, language)}
    candidates = [item for item in topic_bank if str(item or "").strip().lower() not in recent]
    if not candidates:
        candidates = list(topic_bank)
    return random.choice(candidates) if candidates else ""


def _build_topic_coverage_block(
    preset_style: str,
    story_category: str,
    language: str,
    niche_preset: str = None,
    concept_family: str = None,
) -> str:
    context = _resolve_niche_topic_context(preset_style, story_category, niche_preset=niche_preset)
    label = context.get("label") or ""
    description = context.get("description") or ""
    topic_bank = context.get("topic_bank") or []
    style_bank = context.get("style_bank") or []
    lens_bank = context.get("lens_bank") or _GENERIC_LENSES
    rut_warning = context.get("rut_warning") or ""
    recent_concepts = _recent_story_concepts(preset_style, story_category, language)

    lines = []
    if label and description:
        lines.append(f"NICHE FIT: Keep the story emotionally compatible with this preset: {label} — {description}")
    elif label:
        lines.append(f"NICHE FIT: Keep the story emotionally compatible with this preset: {label}")

    if concept_family:
        lines.append(
            f"CONCEPT FAMILY FOR THIS RUN: Center the whole story on this fresh concept: {concept_family}."
        )

    if recent_concepts:
        lines.append(
            "RECENT CONCEPT FAMILIES TO AVOID: "
            + "; ".join(recent_concepts)
            + "."
        )

    topic_choices = _sample_unique(topic_bank, 7)
    if topic_choices:
        lines.append(
            "TOPIC COVERAGE: Explore the wider territory of this niche instead of its most common cliché. "
            f"Strong directions for this run include: {'; '.join(topic_choices)}."
        )

    scene_choices = _sample_unique(style_bank, 5)
    if scene_choices:
        lines.append(
            "GROUND IT IN SCENES: Favor concrete, relatable moments such as: "
            f"{'; '.join(scene_choices)}."
        )

    if rut_warning:
        lines.append(f"AVOID THE USUAL ANGLE: {rut_warning}")

    lines.append(f"NARRATIVE LENS: {random.choice(lens_bank)}.")
    lines.append(
        "Make the whole story feel different in subject, conflict, stakes, emotional arc, and final takeaway — not just the opening line."
    )
    return "\n".join(lines)


def build_story_user_prompt(
    preset_style: str,
    story_category: str,
    duration: int,
    language: str,
    idea: str = None,
    niche_preset: str = None,
    concept_family: str = None,
    *,
    angle_pool: list[str] | None = None,
    extra_directives: list[str] | None = None,
    word_target_ratio: float = 1.0,
) -> str:
    """Build the user prompt for the story generation call.

    The keyword-only overrides are the Lab variant knobs (they default to the
    built-in behaviour): ``angle_pool`` restricts which opening angles may be
    picked, ``extra_directives`` appends experimental instruction lines, and
    ``word_target_ratio`` scales the duration-derived word target.
    """
    from scriptase.modules.script.history import format_history_for_prompt

    word_target = compute_word_target(duration)
    try:
        ratio = float(word_target_ratio or 1.0)
    except (TypeError, ValueError):
        ratio = 1.0
    if ratio != 1.0:
        word_target = max(20, round(word_target * ratio))

    seed = _unique_seed()
    pool = [str(a).strip() for a in (angle_pool or ()) if str(a).strip()] or _ANGLE_STARTERS
    angle = random.choice(pool)
    base = (
        f"Write a viral {story_category} story for a {duration}-second voiceover video. "
        f"Target: {word_target} words. Language: {language}. Style: {preset_style}. "
        "Natural spoken flow only — no titles, no meta-text, no formatting.\n\n"
        f"CREATIVE DIRECTION: {angle}. "
        "Choose a fresh, unexpected angle — avoid generic hooks about 'ancient wisdom' or 'what they don't tell you'. "
        f"[uid:{seed}]"
    )

    topic_block = _build_topic_coverage_block(
        preset_style,
        story_category,
        language,
        niche_preset=niche_preset,
        concept_family=concept_family or choose_story_concept_family(
            preset_style,
            story_category,
            language,
            niche_preset=niche_preset,
        ),
    )
    if topic_block:
        base += f"\n\n{topic_block}"

    # Inject per-preset history so Gemini actively dodges its own past stories.
    history_block = format_history_for_prompt(preset_style, story_category, language)
    if history_block:
        base += f"\n\n{history_block}"

    if idea:
        base += f"\n\nBuild the story around this idea:\n{idea}"

    directives = [str(x).strip() for x in (extra_directives or ()) if str(x).strip()]
    if directives:
        base += "\n\nADDITIONAL DIRECTIONS:\n" + "\n".join(f"- {line}" for line in directives)
    return base
