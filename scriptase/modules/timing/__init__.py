"""Timing (V2 "Force Alignment"). Local service, not a provider domain.

Step 0.3 extracts the Whisper/stable-ts aligner out of the Flask blueprint into
``timing/service.py``: ``_run_alignment``, ``_validate_alignment``,
``_fix_gaps_with_audio``, ``_fix_zero_duration_words``.

Downstream consumes one canonical alignment artifact regardless of which timing
strategy ran.
"""
