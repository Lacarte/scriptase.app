"""TTS Text Normalization Pipeline

Expands contractions, abbreviations, currencies, units, dates, times,
ordinals, and numbers into speakable text.  Also provides sentence
splitting into breathing-sized blocks for chunked TTS generation.
"""

import re

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

_CONTRACTIONS = {
    "you'd": "you would", "you'll": "you will", "you're": "you are", "you've": "you have",
    "I'd": "I would", "I'll": "I will", "I'm": "I am", "I've": "I have",
    "he'd": "he would", "he'll": "he will", "he's": "he is",
    "she'd": "she would", "she'll": "she will", "she's": "she is",
    "it'd": "it would", "it'll": "it will", "it's": "it is",
    "we'd": "we would", "we'll": "we will", "we're": "we are", "we've": "we have",
    "they'd": "they would", "they'll": "they will", "they're": "they are", "they've": "they have",
    "that's": "that is", "that'd": "that would", "that'll": "that will",
    "who's": "who is", "who'd": "who would", "who'll": "who will",
    "what's": "what is", "what'd": "what did", "what'll": "what will",
    "where's": "where is", "when's": "when is", "why's": "why is", "how's": "how is",
    "isn't": "is not", "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "won't": "will not", "wouldn't": "would not", "don't": "do not", "doesn't": "does not",
    "didn't": "did not", "can't": "cannot", "couldn't": "could not", "shouldn't": "should not",
    "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
    "mustn't": "must not", "mightn't": "might not", "needn't": "need not",
    "let's": "let us", "there's": "there is", "here's": "here is", "o'clock": "of the clock",
}

_ORDINALS = {
    r'\b1st\b': 'first', r'\b2nd\b': 'second', r'\b3rd\b': 'third',
    r'\b4th\b': 'fourth', r'\b5th\b': 'fifth', r'\b6th\b': 'sixth',
    r'\b7th\b': 'seventh', r'\b8th\b': 'eighth', r'\b9th\b': 'ninth',
    r'\b10th\b': 'tenth', r'\b11th\b': 'eleventh', r'\b12th\b': 'twelfth',
    r'\b13th\b': 'thirteenth', r'\b14th\b': 'fourteenth', r'\b15th\b': 'fifteenth',
    r'\b20th\b': 'twentieth', r'\b21st\b': 'twenty first', r'\b22nd\b': 'twenty second',
    r'\b23rd\b': 'twenty third', r'\b30th\b': 'thirtieth', r'\b31st\b': 'thirty first',
}

_FOREIGN_WORDS = {
    r'\bANICCA\b': '[anicca](/ɐnˈiːkɐ/)',
}

_ABBREVIATIONS = {
    r'\bDr\.\b': 'Doctor', r'\bMr\.\b': 'Mister', r'\bMrs\.\b': 'Missus', r'\bMs\.\b': 'Miss',
    r'\bProf\.\b': 'Professor', r'\bSt\.\b': 'Saint', r'\bAve\.\b': 'Avenue',
    r'\bBlvd\.\b': 'Boulevard', r'\bDept\.\b': 'Department', r'\bEst\.\b': 'Estimated',
    r'\betc\.\b': 'et cetera', r'\be\.g\.\b': 'for example', r'\bi\.e\.\b': 'that is',
    r'\bvs\.\b': 'versus', r'\bapprox\.\b': 'approximately',
    r'\bmin\.\b': 'minutes', r'\bmax\.\b': 'maximum', r'\bno\.\b': 'number',
    r'\bAPI\b': 'A P I', r'\bURL\b': 'U R L', r'\bHTTP\b': 'H T T P',
    r'\bHTML\b': 'H T M L', r'\bCSS\b': 'C S S', r'\bSQL\b': 'S Q L',
    r'\bRBQ\b': 'R B Q', r'\bID\b': 'I D', r'\bPIN\b': 'pin',
    r'\bOTP\b': 'O T P', r'\bSMS\b': 'S M S', r'\bPDF\b': 'P D F',
}

_UNITS = {
    r'(\d+)\s?km\b': r'\1 kilometers', r'(\d+)\s?m\b': r'\1 meters',
    r'(\d+)\s?cm\b': r'\1 centimeters', r'(\d+)\s?mm\b': r'\1 millimeters',
    r'(\d+)\s?kg\b': r'\1 kilograms', r'(\d+)\s?g\b': r'\1 grams',
    r'(\d+)\s?mg\b': r'\1 milligrams', r'(\d+)\s?lb\b': r'\1 pounds',
    r'(\d+)\s?oz\b': r'\1 ounces', r'(\d+)\s?mph\b': r'\1 miles per hour',
    r'(\d+)\s?kph\b': r'\1 kilometers per hour',
    r'(\d+)\s?°C\b': r'\1 degrees Celsius', r'(\d+)\s?°F\b': r'\1 degrees Fahrenheit',
    r'(\d+)\s?%': r'\1 percent',
    r'(\d+)\s?MB\b': r'\1 megabytes', r'(\d+)\s?GB\b': r'\1 gigabytes',
    r'(\d+)\s?TB\b': r'\1 terabytes', r'(\d+)\s?ms\b': r'\1 milliseconds',
    r'(\d+)\s?fps\b': r'\1 frames per second',
}

_SYMBOLS = {
    '&': 'and', '@': 'at', '#': 'number', '=': 'equals',
    '>': 'greater than', '<': 'less than',
    '|': '', '\\': '',
    '\u2013': '-',
    '\u201c': '"', '\u201d': '"', '\u2018': "'", '\u2019': "'",
    # Preserved for Kokoro intonation/pronunciation:
    #   + (stress links), / (phonetic /slashes/), ~ (approx but rare)
    #   \u2014 em dash, \u2026 ellipsis — used for intonation
    #   ˈ ˌ stress markers, [] () markdown link syntax
}

_DATE_MONTHS = {
    '01': 'January', '02': 'February', '03': 'March', '04': 'April',
    '05': 'May', '06': 'June', '07': 'July', '08': 'August',
    '09': 'September', '10': 'October', '11': 'November', '12': 'December',
}

# ---------------------------------------------------------------------------
# Kokoro pronunciation markers
# ---------------------------------------------------------------------------

# Matches: [word](/phonetic/) or [word](-1) or [word](+2)
_KOKORO_LINK_RE = re.compile(r'\[([^\[\]]+)\]\(([^)]+)\)')


def _protect_kokoro(text):
    """Extract Kokoro markdown links, returning (cleaned_text, replacements)."""
    replacements = []
    def _sub(m):
        placeholder = f"\x00KK{len(replacements)}\x00"
        replacements.append(m.group(0))
        return placeholder
    return _KOKORO_LINK_RE.sub(_sub, text), replacements


def _restore_kokoro(text, replacements):
    """Restore protected Kokoro markers."""
    for i, original in enumerate(replacements):
        text = text.replace(f"\x00KK{i}\x00", original)
    return text


# ---------------------------------------------------------------------------
# Expansion helpers
# ---------------------------------------------------------------------------


def _expand_symbols(text):
    for sym, rep in _SYMBOLS.items():
        text = text.replace(sym, rep)
    return text


def _expand_foreign_words(text):
    for p, r in _FOREIGN_WORDS.items():
        text = re.sub(p, r, text, flags=re.IGNORECASE)
    return text


def _expand_contractions(text):
    for c, e in _CONTRACTIONS.items():
        text = re.sub(re.escape(c), e, text, flags=re.IGNORECASE)
    return text


def _expand_abbreviations(text):
    for p, r in _ABBREVIATIONS.items():
        text = re.sub(p, r, text, flags=re.IGNORECASE)
    return text


def _expand_currency(text):
    text = re.sub(r'\$(\d+)', r'\1 dollars', text)
    text = re.sub(r'€(\d+)', r'\1 euros', text)
    text = re.sub(r'£(\d+)', r'\1 pounds', text)
    text = re.sub(r'¥(\d+)', r'\1 yen', text)
    text = re.sub(r'HTG\s?(\d+)', r'\1 Haitian gourdes', text)
    return text


def _expand_units(text):
    for p, r in _UNITS.items():
        text = re.sub(p, r, text, flags=re.IGNORECASE)
    return text


def _expand_dates(text):
    def _replace(m):
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{_DATE_MONTHS.get(mo, mo)} {int(d)}, {y}"
    return re.sub(r'\b(\d{4})-(\d{2})-(\d{2})\b', _replace, text)


def _expand_time(text):
    text = re.sub(
        r'\b(\d{1,2}):(\d{2})\s?(am|pm)\b',
        lambda m: f"{m.group(1)} {m.group(2)} {m.group(3).replace('am','a m').replace('pm','p m')}",
        text, flags=re.IGNORECASE)
    text = re.sub(
        r'\b(\d{1,2})\s?(am|pm)\b',
        lambda m: f"{m.group(1)} {m.group(2).replace('am','a m').replace('pm','p m')}",
        text, flags=re.IGNORECASE)
    return text


def _expand_ordinals(text):
    for p, r in _ORDINALS.items():
        text = re.sub(p, r, text, flags=re.IGNORECASE)
    return text


def _expand_numbers(text):
    try:
        from num2words import num2words
        def _float_repl(m):
            whole = num2words(int(m.group(1)))
            decimals = " ".join(num2words(int(d)) for d in m.group(2))
            return f"{whole} point {decimals}"
        text = re.sub(r'\b(\d+)\.(\d+)\b', _float_repl, text)
        text = re.sub(r'\b(\d+)\b', lambda m: num2words(int(m.group(1))), text)
    except ImportError:
        pass
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_for_tts(text: str) -> str:
    """Full TTS normalization pipeline. Order matters.

    Kokoro markdown links like [word](/phonetic/) and [word](-1) are
    protected from expansion and restored at the end.
    """
    text = _expand_foreign_words(text)
    text, kokoro = _protect_kokoro(text)
    text = _expand_symbols(text)
    text = _expand_contractions(text)
    text = _expand_abbreviations(text)
    text = _expand_currency(text)
    text = _expand_units(text)
    text = _expand_dates(text)
    text = _expand_time(text)
    text = _expand_ordinals(text)
    text = _expand_numbers(text)
    text = re.sub(r'\s+', ' ', text)
    text = _restore_kokoro(text, kokoro)
    return text.strip()


def clean_for_tts(text: str) -> str:
    """Strip markdown formatting, URLs, and excess whitespace.

    Preserves Kokoro pronunciation links [word](/phonetic/), stress
    markers (ˈ ˌ), and intonation punctuation (—…).
    """
    text = _expand_foreign_words(text)
    text, kokoro = _protect_kokoro(text)
    text = re.sub(r"[*_#`~]", "", text)
    text = re.sub(r"https?://\S+", "link", text)
    # Strip only orphan brackets (not part of Kokoro links — already protected)
    text = re.sub(r"[\[\]]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = _restore_kokoro(text, kokoro)
    return text.strip()


def tts_breathing_blocks(text: str, min_chars: int = 150, max_chars: int = 200) -> list[str]:
    """Split text into breathing-sized blocks for chunked TTS generation.

    Each block aims for *min_chars*-*max_chars*, preferring sentence
    boundaries, then comma/semicolon boundaries, then word boundaries.
    """
    if not text or not text.strip():
        return []

    text, kokoro = _protect_kokoro(text)
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u2013", "-")
    # Preserve em dash and ellipsis for Kokoro intonation
    text = re.sub(r"\s+", " ", text).strip()
    text = _restore_kokoro(text, kokoro)

    sentences = re.findall(r".+?(?:\u2026|\.{3}|[.!?\u2014])(?:\s+|$)", text)
    if not sentences:
        sentences = [text]

    blocks: list[str] = []
    cur = ""

    def flush():
        nonlocal cur
        if cur.strip():
            blocks.append(cur.strip())
        cur = ""

    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if not cur:
            cur = s
            continue
        if len(cur) + 1 + len(s) <= max_chars:
            cur = f"{cur} {s}"
            continue
        if len(cur) >= min_chars:
            flush()
            cur = s
            continue
        parts = re.split(r"(?<=[,;:])\s+", s)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if not cur:
                cur = p
                continue
            if len(cur) + 1 + len(p) <= max_chars:
                cur = f"{cur} {p}"
            else:
                flush()
                cur = p
    flush()

    # Merge short blocks with neighbors
    min_block = 80
    hard_limit = max_chars + min_block
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(blocks):
            if len(blocks[i]) >= min_block:
                i += 1
                continue
            if i + 1 < len(blocks):
                merged = f"{blocks[i]} {blocks[i + 1]}"
                if len(merged) <= hard_limit:
                    blocks[i] = merged
                    blocks.pop(i + 1)
                    changed = True
                    if len(blocks[i]) >= min_block:
                        i += 1
                    continue
            if i > 0:
                merged = f"{blocks[i - 1]} {blocks[i]}"
                if len(merged) <= hard_limit:
                    blocks[i - 1] = merged
                    blocks.pop(i)
                    changed = True
                    continue
            i += 1

    return blocks


def format_breathing_blocks(text: str, min_chars: int = 150, max_chars: int = 200) -> str:
    """Format text into bracket-wrapped breathing blocks for display."""
    blocks = tts_breathing_blocks(text, min_chars, max_chars)
    if not blocks:
        return text.strip()
    if len(blocks) == 1:
        return blocks[0]
    return "\n\n".join(f"[{b}]" for b in blocks)


def validate_brackets(text: str) -> str:
    """Check bracket formatting quality.

    Returns "none", "well_formed", or "malformed".
    """
    if "[" not in text and "]" not in text:
        return "none"
    if text.count("[") != text.count("]"):
        return "malformed"
    if "[[" in text or "]]" in text or "[]" in text:
        return "malformed"
    depth = 0
    outside_chars = []
    for ch in text:
        if ch == "[":
            depth += 1
            if depth > 1:
                return "malformed"
        elif ch == "]":
            depth -= 1
            if depth < 0:
                return "malformed"
        elif depth == 0:
            outside_chars.append(ch)
    if depth != 0:
        return "malformed"
    outside = "".join(outside_chars).strip()
    if outside:
        return "malformed"
    return "well_formed"
