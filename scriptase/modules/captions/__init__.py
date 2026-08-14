"""Captions — a local, single-implementation service. **Not** a provider domain.

Its mode, tone, and preset fields look like provider selection and are not. The
requirement on this module is no regression, not migration.

Step 0.3 extracts ``_group_words_into_captions`` and ``CAPTION_PRESETS`` out of
the Flask blueprint into ``captions/service.py`` and ``captions/presets.py``.

Nothing may import business logic from ``routes.py``. ``captions_bp`` is this
package's own transport and is the one exception — it is exported, never
imported from.
"""

from .routes import captions_bp

__all__ = ["captions_bp"]
