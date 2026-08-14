"""Music — a local, single-implementation service. **Not** a provider domain.

Like captions, its mode and tone fields resemble provider selection but are not.
The requirement on this module is no regression, not migration.

Nothing may import business logic from ``routes.py`` — track selection lives in
``music/selector.py``. ``music_bp`` is this package's own transport and is the
one exception — it is exported, never imported from.
"""

from .routes import music_bp

__all__ = ["music_bp"]
