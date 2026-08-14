"""Voice synthesis. Provider-capable.

Where a provider advertises native word timing, Timing consumes it instead of
running alignment (step 5.3).

Nothing may import business logic from ``routes.py``. ``tts_bp`` is this
package's own transport and is the one exception — it is exported, never
imported from. ``_step_tts`` lives in ``tts/service.py`` for exactly that
reason.
"""

from .routes import tts_bp

__all__ = ["tts_bp"]
