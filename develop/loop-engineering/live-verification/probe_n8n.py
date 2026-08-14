"""Probe the railway n8n public API with the configured key (dev-only helper)."""
import json
import urllib.request

KEY = json.load(open(".mcp.json", encoding="utf-8"))["mcpServers"]["n8n-mcp"]["env"]["N8N_API_KEY"]
BASE = "https://n8n-production-6197.up.railway.app"

req = urllib.request.Request(
    f"{BASE}/api/v1/workflows?limit=50",
    headers={"X-N8N-API-KEY": KEY, "Accept": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
        for wf in data.get("data", []):
            print(wf["id"], "active=", wf["active"], wf["name"])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read(300))
