# ai-web-auto (vendored)

Upstream is its own git repository. This tree is a copy, not a submodule, and
nothing in it is edited.

| | |
|---|---|
| Source | `ScriptToScene-Studio-V2/_dev/automation/extensions/ai-web-auto` |
| Revision | `6c82e975769cda7927fd8b035d721e743a1ef6c8` (branch `master`) |
| Taken | `ai_web_auto_backend/` and `requirements.txt` |

## Why a copy

A submodule needs a reachable remote and a `git submodule update` that every
clone, every CI run and the loop orchestrator would have to get right; the
upstream remote is a local directory on one machine. A copy is honest about what
this is: a pinned snapshot of ~90 KB of Python that Scriptase runs as a
subprocess.

## What was deliberately left behind

- `venv/` — 1.3 GB, and provisioned per-machine by `tools/automation.ps1`.
- `.git/` — a nested repository inside this one confuses every tool that walks
  the tree, `git status` first.
- `ai-web-auto-extension/` — already ported, with the endpoint made
  configurable, to `tools/extensions/ai-web-auto-extension` in step 15.2.
  Vendoring it again would create a second copy to keep in sync, and the copy
  the browser loads would not be the one anybody edited.
- `created-extensions/`, `learning-process/`, `_projects/`, `scratch/`,
  `CLAUDE.md`, `runner.bat` — the upstream authoring workspace. Scriptase runs
  the server; it does not develop it here.
- `__pycache__/` — build output.

## The boundary

Everything Scriptase owns lives one level up, outside this directory:

- `tools/automation/serve.py` — the headless entry point. Upstream's
  `automation_controller.py` is an interactive stdin REPL, which cannot be a
  launcher child: it would eat the console's stdin and block on `input()`.
- `tools/automation/requirements.txt` — what the launcher installs, which is
  the transport subset of the file below it. See the comments there.
- `tools/automation.ps1` — provisioning and process lifecycle.

Re-vendoring is therefore a straight overwrite of `ai_web_auto_backend/` and
`requirements.txt`, with nothing of ours to merge back in.
