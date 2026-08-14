"""Check whether free OpenRouter models work despite the negative balance."""
import json
import urllib.request

key = [l.split("=", 1)[1].strip() for l in open(".env", encoding="utf-8")
       if l.startswith("OPENROUTER_API_KEY=")][0]

req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={})
with urllib.request.urlopen(req, timeout=20) as r:
    models = json.load(r)["data"]
free = [m["id"] for m in models
        if m["id"].endswith(":free") and ("gemini" in m["id"] or "llama" in m["id"] or "deepseek" in m["id"])]
print("free candidates:", free[:10])

for model in free[:4]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 10,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
            print(model, "->", data["choices"][0]["message"]["content"][:40])
            break
    except urllib.error.HTTPError as e:
        print(model, "-> HTTP", e.code, e.read(200))
