"""Cross-cutting helpers: atomic IO, managed-path security, validation helpers.

Populated in step 0.2 from V2's ``io_utils.py`` (Windows-aware atomic write with
backup recovery) and ``security.py`` (managed-path joins). Never trust a
browser-supplied filesystem path.
"""
