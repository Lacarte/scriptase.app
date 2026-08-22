"""Curated Inworld narration voices — the only voices offered for TTS.

Generated from starred_voices.csv (beside this file). Voices are referenced
everywhere by their Voice ID (the id field), never the display name. Flag is a
two-letter code (us/gb/mx/es) or "" when none applies (e.g. French).
"""

from __future__ import annotations

STARRED_VOICES = [
    {"id": "Alain", "name": "Alain", "language": "French", "lang_code": "FR", "gender": "male", "flag": ""},
    {"id": "Alistair", "name": "Alistair", "language": "English", "lang_code": "EN", "gender": "male", "flag": "us"},
    {"id": "Alvaro", "name": "Alvaro", "language": "Spanish", "lang_code": "ES", "gender": "male", "flag": "es"},
    {"id": "default-ofw8mqnvn6z4uenfqu9epq__aron", "name": "Aron", "language": "English", "lang_code": "EN", "gender": "neutral", "flag": "us"},
    {"id": "Beatrice", "name": "Beatrice", "language": "English", "lang_code": "EN", "gender": "female", "flag": "gb"},
    {"id": "default-ofw8mqnvn6z4uenfqu9epq__bella", "name": "Bella", "language": "English", "lang_code": "EN", "gender": "neutral", "flag": "us"},
    {"id": "Cordelia", "name": "Cordelia", "language": "English", "lang_code": "EN", "gender": "female", "flag": "gb"},
    {"id": "Deborah", "name": "Deborah", "language": "English", "lang_code": "EN", "gender": "female", "flag": "us"},
    {"id": "Dennis", "name": "Dennis", "language": "English", "lang_code": "EN", "gender": "male", "flag": "us"},
    {"id": "Graham", "name": "Graham", "language": "English", "lang_code": "EN", "gender": "male", "flag": "gb"},
    {"id": "Hank", "name": "Hank", "language": "English", "lang_code": "EN", "gender": "male", "flag": "us"},
    {"id": "Hélène", "name": "Hélène", "language": "French", "lang_code": "FR", "gender": "female", "flag": ""},
    {"id": "Ignacio", "name": "Ignacio", "language": "Spanish", "lang_code": "ES", "gender": "male", "flag": "es"},
    {"id": "default-ofw8mqnvn6z4uenfqu9epq__john_doe", "name": "John Doe", "language": "English", "lang_code": "EN", "gender": "neutral", "flag": "us"},
    {"id": "Luna", "name": "Luna", "language": "English", "lang_code": "EN", "gender": "female", "flag": "us"},
    {"id": "Penelope", "name": "Penelope", "language": "English", "lang_code": "EN", "gender": "female", "flag": "us"},
    {"id": "Rocio", "name": "Rocio", "language": "Spanish", "lang_code": "ES", "gender": "female", "flag": "es"},
    {"id": "Rosalind", "name": "Rosalind", "language": "English", "lang_code": "EN", "gender": "female", "flag": "gb"},
    {"id": "Sarah", "name": "Sarah", "language": "English", "lang_code": "EN", "gender": "female", "flag": "us"},
    {"id": "Sofia", "name": "Sofia", "language": "Spanish", "lang_code": "ES", "gender": "female", "flag": "mx"},
    {"id": "Veronica", "name": "Veronica", "language": "English", "lang_code": "EN", "gender": "female", "flag": "us"},
    {"id": "Wendy", "name": "Wendy", "language": "English", "lang_code": "EN", "gender": "female", "flag": "gb"},
    {"id": "Winifred", "name": "Winifred", "language": "English", "lang_code": "EN", "gender": "female", "flag": "gb"},
    {"id": "Winston", "name": "Winston", "language": "English", "lang_code": "EN", "gender": "male", "flag": "gb"},
    {"id": "Étienne", "name": "Étienne", "language": "French", "lang_code": "FR", "gender": "male", "flag": ""},
]

STARRED_VOICE_IDS = frozenset(v["id"] for v in STARRED_VOICES)


def starred_voice(voice_id):
    """The curated voice record for an id, or None."""
    return next((v for v in STARRED_VOICES if v["id"] == voice_id), None)


def is_starred(voice_id) -> bool:
    return voice_id in STARRED_VOICE_IDS
