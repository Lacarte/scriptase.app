"""Sync-document provider body — deterministic, offline, credential-free.

Two entry points over one core, which is the point of the fixture:

  * `generate(configuration, project_id=…)` is the concrete seam the `script`
    domain dispatches through today (`adapters/story.py:37`). Implementing it
    is what lets this provider run on the real `story.generate` node with no
    adapter, registry, or component edit.
  * `invoke(request, invocation)` is the v2 contract (contracts.md §30/§31).
    It returns the standardized envelope the boundary validates.

Both call `_document()`, so the node result and the standardized result can be
asserted against each other rather than against two hand-written expectations.
"""

import os

_SECTIONS = ("hook", "build", "climax", "cta")


class FixtureDocumentProvider:
    """A script provider whose output depends only on its inputs."""

    def __init__(self):
        self.shutdown_calls = 0

    # -- the concrete `script` seam --------------------------------------

    def generate(self, configuration, *, project_id: str) -> dict:
        """The shape `adapters/story.py` consumes: a document plus its `path`."""
        document, path = _document(configuration, project_id)
        return {**document, "path": path}

    # -- the v2 invocation contract --------------------------------------

    def invoke(self, request, invocation):
        from scriptase.providers.results import (
            ProviderResult,
            normalize_ref,
        )

        options = {**dict(invocation.options), **dict(request or {})}
        document, path = _document(options, invocation.project_id)
        ref = normalize_ref(path)
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            # No `path`: an absolute filesystem path may not cross the egress
            # boundary (§31.2). The ref is how a consumer finds the file.
            payload={**document, "document_ref": ref},
            artifact_refs=[ref],
            metadata={"sections": len(_SECTIONS)},
        )

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _document(configuration, project_id: str) -> tuple[dict, str]:
    """Build the document and write it inside the managed output directory."""
    import config
    from scriptase.shared.io_utils import safe_json_write

    settings = dict(configuration or {})
    voice = str(settings.get("voice_of") or "narrator")
    epigraph = str(settings.get("epigraph") or "")
    chapters = int(settings.get("chapter_count") or 0) if settings.get("chaptered") else 0

    sections = {name: f"{voice}:{name}" for name in _SECTIONS}
    story_text = "\n".join(sections[name] for name in _SECTIONS)
    document = {
        "project_id": project_id,
        "story_text": story_text,
        "sections": sections,
        "metadata": {
            "voice_of": voice,
            "chapters": chapters,
            "epigraph": epigraph,
            "word_count": len(story_text.split()),
            # Never the literal id: the platform stamps provenance, and a
            # provider that writes its own identity here is how §31.3 gets
            # bypassed. Left out on purpose.
        },
    }
    path = os.path.join(config.OUTPUT_DIR, "fixture_document", project_id, "document.json")
    safe_json_write(path, document, indent=2)
    return document, path


def create() -> FixtureDocumentProvider:
    return FixtureDocumentProvider()


def validate_settings(settings: dict) -> list[dict]:
    """The half a JSON schema cannot express (§22.5)."""
    if settings.get("chaptered") and not settings.get("epigraph"):
        return [{
            "field": "epigraph",
            "severity": "warning",
            "message": "A chaptered document reads better with an epigraph",
        }]
    return []


def health_check(settings: dict) -> dict:
    configured = bool(settings.get("api_key"))
    return {
        "status": "ok" if configured else "warn",
        "latency_ms": 0,
        "message": "Fixture document provider is offline-only",
    }
