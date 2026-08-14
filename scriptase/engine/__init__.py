"""Node-based DAG execution engine — the single authoritative execution model.

Populated in step 0.2 by lifting V2's ``studio/workflows/`` verbatim: ``cache``,
``scheduler`` (with ``ProjectLock`` and ``ArtifactPromoter``), ``registry``,
``validation``, ``expressions``, ``events``, ``redaction``, ``migrations``,
``config_migrations``, the trigger trio, ``asset_gc``, ``project_archive``,
``scaffold``, ``contract_tests``, and ``docs``.

Nothing here may import from a module ``routes.py``.
"""
