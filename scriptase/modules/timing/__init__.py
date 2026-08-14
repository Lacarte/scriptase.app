"""Timing (V2 "Force Alignment"). Local service, not a provider domain.

Step 0.3 extracts the Whisper/stable-ts aligner out of the Flask blueprint into
``timing/service.py``: ``_run_alignment``, ``_validate_alignment``,
``_fix_gaps_with_audio``, ``_fix_zero_duration_words``.

Downstream consumes one canonical alignment artifact regardless of which timing
strategy ran.

``_step_timing`` (V2 ``studio/pipeline/services.py``) lives in ``service.py`` too,
so nothing has to reach through a ``routes.py`` to align. ``timing_bp`` is this
package's own transport and is exported, never imported from.
"""

from .routes import timing_bp

__all__ = ["timing_bp"]
