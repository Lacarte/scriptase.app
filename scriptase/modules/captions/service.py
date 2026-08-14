"""Captions Module — caption grouping.

Split out of ``captions/routes.py`` in step 0.3: the caption grouping helper is
business logic, so it lives here and the blueprint stays pure transport. This
module must never import flask.
"""

# ---------------------------------------------------------------------------
# Helpers consumed by the editor's auto-caption pipeline
#
# These two functions used to live here, were dropped during a refactor, and
# the editor's `_resolve_project_captions` and `editor_assemble` paths still
# import them. Their absence caused captions to silently disappear from every
# new project (the import error was swallowed by a debug-level except block,
# leaving exports with `captions: None` and no on-screen warning).
#
# Restoring them is the smallest fix that makes captions reappear without
# refactoring the editor.
# ---------------------------------------------------------------------------


def _group_words_into_captions(alignment, words_per_group: int = 3) -> list:
    """Group timed words from alignment.json into N-word caption chunks.

    Accepts the schema produced by the alignment step:
        [{"word": "Hello", "begin": 0.12, "end": 0.34}, ...]

    Returns a list of caption dicts shaped for the editor / renderer:
        [{"text": "Hello world today",
          "start": 0.12, "end": 0.95,
          "words": [{"word": ..., "begin": ..., "end": ...}, ...]}, ...]

    The `words` sub-list is preserved so karaoke-style presets can highlight
    each word as it is spoken. Empty/invalid entries are skipped silently.
    """
    if not isinstance(alignment, list) or not alignment:
        return []

    n = max(1, int(words_per_group or 1))
    captions = []
    bucket = []

    def _flush():
        if not bucket:
            return
        text = " ".join(str(w.get("word", "")).strip() for w in bucket if w.get("word"))
        if not text:
            return
        starts = [float(w.get("begin", 0) or 0) for w in bucket]
        ends = [float(w.get("end", 0) or 0) for w in bucket]
        captions.append({
            "text": text,
            "start": min(starts) if starts else 0.0,
            "end": max(ends) if ends else 0.0,
            "words": list(bucket),
        })

    for word in alignment:
        if not isinstance(word, dict):
            continue
        if not str(word.get("word", "")).strip():
            continue
        bucket.append(word)
        if len(bucket) >= n:
            _flush()
            bucket = []

    # Trailing partial group (e.g. 11 words / 3 = 3 full + 2 leftover)
    if bucket:
        _flush()

    return captions
