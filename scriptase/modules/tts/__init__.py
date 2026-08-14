"""Voice synthesis. Provider-capable.

Providers that declare the ``native_word_timing`` capability and return
``word_timings`` in result metadata stamp both onto the TTS audio/metadata
ports. Timing strategy AUTO (step 5.3) then normalises those timestamps
instead of running Whisper force-alignment.

Nothing may import business logic from ``routes.py``. ``tts_bp`` is this
package's own transport and is the one exception — it is exported, never
imported from. ``_step_tts`` lives in ``tts/service.py`` for exactly that
reason.
"""

from .routes import tts_bp

__all__ = ["tts_bp"]
