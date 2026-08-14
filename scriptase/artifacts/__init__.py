"""Typed, versioned, content-addressed artifacts (step 1.2).

Replaces V2's ``artifact_refs: list[str]`` naming convention with a real
``Artifact``: stable id, kind, owning job, owning scene, version, content hash,
relative managed path, size, mime, provenance reference, and ``superseded_by``.

Versions are immutable and additive — a repair never erases the evidence of what
it replaced. This layer sits *above* the engine's ``ArtifactPromoter`` and cache
integrity re-hashing and records what they produce.
"""
