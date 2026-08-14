"""Bootstrap a repo-scoped local n8n serving the scene-blueprint webhook.

Step 6.1 fallback: the hosted production n8n rejected webhook calls (workflow
inactive, API key revoked), so live verification self-hosts the repo's own
workflow export with the OpenRouter key from .env.

Usage (from the repo root):
    python _dev/loop-engineering/live-verification/setup_local_n8n.py   # import + activate
    python _dev/loop-engineering/live-verification/setup_local_n8n.py start  # run n8n

Data lives in _dev/loop-engineering/live-verification/n8n-data (gitignored).
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DATA_DIR = os.path.join(HERE, "n8n-data")
WORKFLOW = os.path.join(REPO, "_dev", "automation", "n8n", "scene-generator.json")
WORKFLOW_ID = "1ga5ercqD130rcAH"
CREDENTIAL_ID = "mbWrJSQdMKz6Ve5M"  # "OpenRouter account" referenced by the workflow


def _openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        with open(os.path.join(REPO, ".env"), encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("OPENROUTER_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("OPENROUTER_API_KEY not found in environment or .env")
    return key


def _env() -> dict:
    env = dict(os.environ)
    env.update({
        "N8N_USER_FOLDER": DATA_DIR,
        "N8N_PORT": "5678",
        "N8N_SECURE_COOKIE": "false",
        "N8N_DIAGNOSTICS_ENABLED": "false",
        "N8N_PERSONALIZATION_ENABLED": "false",
        "DB_SQLITE_POOL_SIZE": "1",
    })
    return env


def _n8n(*args: str) -> None:
    command = ["n8n", *args]
    print("->", " ".join(command))
    subprocess.run(command, env=_env(), check=True, shell=(os.name == "nt"))


def setup() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    credentials_file = os.path.join(DATA_DIR, "credentials-import.json")
    with open(credentials_file, "w", encoding="utf-8") as handle:
        json.dump([{
            "id": CREDENTIAL_ID,
            "name": "OpenRouter account",
            "type": "openRouterApi",
            "data": {"apiKey": _openrouter_key()},
        }], handle)
    # The repo export is a full instance dump; instance-specific relations
    # (shared/project/version rows) violate local FK constraints, so import
    # only the portable graph fields.
    with open(WORKFLOW, encoding="utf-8") as handle:
        full = json.load(handle)
    sanitized = {
        key: full[key]
        for key in ("id", "name", "nodes", "connections", "settings", "staticData", "pinData")
        if key in full
    }
    # Verified live 2026-08-05: the production model (google/gemini-2.5-flash)
    # is rejected with HTTP 402 while the OpenRouter balance is negative, but
    # free-tier models still complete. Pin a free model for local verification.
    model = os.environ.get("STS_LIVE_OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
    for node in sanitized["nodes"]:
        if node["type"].endswith("lmChatOpenRouter"):
            node["parameters"]["model"] = model
            # Free-tier models queue upstream; the node's default request
            # timeout (~10s observed) aborts them, so raise it explicitly.
            node["parameters"]["options"] = {
                **node["parameters"].get("options", {}),
                "timeout": 180000,
                "maxRetries": 2,
            }
    # The export references an error-handler workflow that is not imported.
    sanitized.get("settings", {}).pop("errorWorkflow", None)
    workflow_file = os.path.join(DATA_DIR, "workflow-import.json")
    with open(workflow_file, "w", encoding="utf-8") as handle:
        json.dump(sanitized, handle)
    try:
        _n8n("import:credentials", f"--input={credentials_file}")
        _n8n("import:workflow", f"--input={workflow_file}")
        _n8n("publish:workflow", f"--id={WORKFLOW_ID}")  # n8n 2.x draft/publish model
    finally:
        os.remove(credentials_file)
    print("Local n8n bootstrapped. Run with: python", os.path.relpath(__file__, REPO), "start")


def start() -> None:
    subprocess.run(["n8n", "start"], env=_env(), check=True, shell=(os.name == "nt"))


def status() -> None:
    _n8n("list:workflow")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "setup"
    {"start": start, "status": status}.get(mode, setup)()
