"""Smoke-test the local scene-blueprint webhook with a tiny payload (dev-only)."""
import json
import urllib.request

payload = {
    "alignment": [
        {"begin": 0.0, "end": 0.3, "word": "The"},
        {"begin": 0.3, "end": 0.8, "word": "garden"},
        {"begin": 0.8, "end": 1.4, "word": "waited."},
    ],
    "transcript": "The garden waited.",
    "script": "The garden waited.",
    "segments": [{"index": 0, "text": "The garden waited.", "begin": 0.0, "end": 1.4}],
    "style": "cinematic",
    "aspect_ratio": "9:16",
}

req = urllib.request.Request(
    "http://127.0.0.1:5678/webhook/scene-blueprint-generator",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=180) as r:
    body = r.read().decode("utf-8", "replace")
    print("HTTP", r.status, len(body), "bytes")
    print(body[:600])
