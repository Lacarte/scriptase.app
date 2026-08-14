"""Environment probe for step 6.1 live-provider verification (dev-only helper)."""
import shutil
import urllib.request

for url in [
    "http://127.0.0.1:5050/api/health",
    "http://127.0.0.1:5678/healthz",
]:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            print(url, r.status, r.read(500).decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print(url, "ERR", e)

print("ffmpeg:", shutil.which("ffmpeg"))
