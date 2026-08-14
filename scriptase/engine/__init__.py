"""Node-based DAG execution engine — the single authoritative execution model.

Lifted from V2's ``studio/workflows/`` in step 0.2: ``cache``, ``scheduler``
(with ``ProjectLock`` and ``ArtifactPromoter``), ``registry``, ``validation``,
``expressions``, ``events``, ``redaction``, ``migrations``,
``config_migrations``, the trigger trio, ``asset_gc``, ``project_archive``,
``scaffold``, and ``docs``.

Nothing here may import from a module ``routes.py``. ``workflows_bp`` is this
package's own transport and is the one exception — it is exported, never
imported from.
"""

from .routes import workflows_bp

__all__ = ["workflows_bp"]
