"""Sync-artifact provider body — one produced file, no network, no model.

Writes through `invocation.stage_artifact` when the scheduler supplied one, so
the artifact is invisible until the node succeeds (§30.2), and returns the
relative ref rather than the path (§31.2).
"""

import os

# A minimal RIFF header followed by silence. Real bytes, so the artifact the
# boundary verifies is a real file, but deterministic and tiny.
_RIFF = b"RIFF$\x00\x00\x00WAVEfmt "


class FixtureArtifactProvider:
    """A provider whose one output is a file it wrote itself."""

    def __init__(self):
        self.shutdown_calls = 0

    def invoke(self, request, invocation):
        from scriptase.providers.results import (
            ProviderResult,
            normalize_ref,
        )

        options = {**dict(invocation.settings), **dict(invocation.options)}
        # Either the domain request model (§32.3) or the plain mapping a caller
        # built by hand: a provider reads fields, not a concrete class.
        fields = request if isinstance(request, dict) else request.model_dump()
        text = str(fields.get("text", ""))
        voice = str(fields.get("voice") or options.get("voice") or "fx_calm")
        speed = float(fields.get("speed") or options.get("speed") or 1.0)
        sample_rate = int(options.get("sample_rate") or 24000)

        ref = self._write(invocation, f"{voice}.wav")
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload={
                "audio_ref": ref,
                # Deterministic and derived, so two runs of the same request
                # produce byte-identical results.
                "duration_seconds": round(len(text) / (12.0 * speed), 3),
                "sample_rate": sample_rate,
                "format": "wav",
                "voice": voice,
                "characters_billed": len(text),
            },
            artifact_refs=[ref],
            metadata={"engine": "fixture", "speed": speed},
        )

    def _write(self, invocation, name: str) -> str:
        from scriptase.providers.results import normalize_ref

        destination = os.path.join(invocation.output_dir, name)
        path = (
            invocation.stage_artifact(destination)
            if invocation.stage_artifact is not None
            else destination
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(_RIFF)
        # The ref names the *managed* destination, not the staging path.
        return normalize_ref(destination)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def create() -> FixtureArtifactProvider:
    return FixtureArtifactProvider()


def validate_settings(settings: dict) -> list[dict]:
    speed = settings.get("speed")
    if isinstance(speed, (int, float)) and speed > 1.5:
        return [{
            "field": "speed",
            "severity": "warning",
            "message": "Speeds above 1.5 are hard to follow",
        }]
    return []


def health_check(settings: dict) -> dict:
    return {"status": "ok", "latency_ms": 0, "message": "Fixture synthesizer is ready"}
