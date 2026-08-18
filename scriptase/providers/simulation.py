"""Credential-free provider request simulations (plan step 5.2).

Simulations are platform-owned fixtures.  They intentionally do not accept
settings, construct a provider, or call a transport: the Providers console is
an explanation of the round-trip shape, never a disguised live request.
"""

from __future__ import annotations

from hashlib import sha256


KIND_LABELS = {
    "cloud": "api",
    "extension": "extension",
    "webhook": "n8n",
    "local": "local",
}


def _fixture(domain: str) -> tuple[str, dict, dict]:
    fixtures = {
        "tts": (
            "synthesize",
            {"text": "A sample narration line.", "voice": "default", "format": "mp3"},
            {"status": "ok", "artifact": "simulated/audio.mp3", "duration_sec": 2.4},
        ),
        "image": (
            "generate_image",
            {"prompt": "A cinematic sample frame", "aspect": "9:16"},
            {"status": "ok", "artifact": "simulated/frame.png", "width": 1080, "height": 1920},
        ),
        "video": (
            "animate_frame",
            {"frame": "simulated/frame.png", "duration_sec": 5, "aspect": "9:16"},
            {"status": "ok", "artifact": "simulated/clip.mp4", "frames": 150, "fps": 30},
        ),
        "scene_director": (
            "build_scenes",
            {"script": "A short sample script.", "target_duration_sec": 30},
            {"status": "ok", "scene_count": 3, "artifact": "simulated/scenes.json"},
        ),
        "viral": (
            "score_script",
            {"script": "A short sample script.", "target_duration_sec": 30},
            {"status": "ok", "overall": 72, "grade": "strong", "source": "simulated"},
        ),
    }
    return fixtures.get(domain, (
        "invoke",
        {"input": "Sample provider request"},
        {"status": "ok", "output": "Sample provider response"},
    ))


def build_simulation(*, domain: str, provider_id: str, instance_id: str, kind: str) -> dict:
    """Build a deterministic, JSON-safe round-trip with no provider settings."""
    transport = KIND_LABELS.get(kind, "local")
    operation, request, response = _fixture(domain)
    simulation_id = "sim_" + sha256(
        f"{domain}:{provider_id}:{instance_id}:{transport}".encode("utf-8")
    ).hexdigest()[:10]
    steps = {
        "api": ["Build dummy payload", "Sign with placeholder credential", "Mock API response"],
        "extension": ["Build dummy command", "Mock extension hand-off", "Mock artifact callback"],
        "n8n": ["Build dummy webhook body", "Mock workflow execution", "Mock webhook response"],
        "local": ["Load dummy input", "Run fixture locally", "Return deterministic response"],
    }[transport]
    return {
        "simulation_id": simulation_id,
        "simulated": True,
        "domain": domain,
        "provider_id": provider_id,
        "provider_type": provider_id,
        "instance_id": instance_id,
        "kind": transport,
        "transport": f"{transport}://simulated/{provider_id}",
        "operation": operation,
        "steps": steps,
        "request": request,
        "response": {"request_id": simulation_id, **response},
        "elapsed_ms": 0,
    }
