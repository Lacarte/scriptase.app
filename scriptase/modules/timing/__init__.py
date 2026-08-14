"""Timing (V2 "Force Alignment"). Local service, not a provider domain.

Step 0.3 extracted the Whisper/stable-ts aligner out of the Flask blueprint into
``timing/service.py``. Step 5.3 renames the user-facing concept to Timing and
adds strategy AUTO: use native TTS word timings when the provider advertises
``native_word_timing``, otherwise force-align.

Downstream consumes one canonical alignment artifact regardless of which path
ran — the segmenter cannot tell them apart.

``_step_timing`` lives in ``service.py`` so nothing reaches through a
``routes.py`` to align. ``timing_bp`` is this package's own transport and is
exported, never imported from.
"""

from .routes import timing_bp

__all__ = ["timing_bp"]
