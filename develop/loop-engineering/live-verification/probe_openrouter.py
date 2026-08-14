"""Check OpenRouter key validity and credit balance (dev-only helper)."""
import json
import urllib.request

key = ""
with open(".env", encoding="utf-8") as handle:
    for line in handle:
        if line.startswith("OPENROUTER_API_KEY="):
            key = line.split("=", 1)[1].strip()

req = urllib.request.Request(
    "https://openrouter.ai/api/v1/key",
    headers={"Authorization": f"Bearer {key}"},
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        print(json.dumps(json.load(r), indent=1))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read(300))
