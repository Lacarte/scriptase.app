# Scriptase

Channel-aware, provider-driven, local-first AI video production.

A Channel holds the reusable identity and production rules for a content brand.
A Job runs one video from a Channel and a Workflow. Underneath, a single
node-based DAG engine executes everything — the simple Production view is a
projection of that same graph, not a second engine.

Default production path: Script → Voice → Timing → Segmentation → Scene
Direction → Image → Video → Review → Compose → Export.

## Setup

```bash
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt
cd frontend && npm install
```

## Run

```bash
venv/Scripts/python.exe app.py          # backend on 127.0.0.1:5000
cd frontend && npm run dev              # dev server, proxies /api to the backend
```

## Verify

`python` and `pytest` are not on PATH — always use the venv interpreter.

```bash
venv/Scripts/python.exe -m pytest tests/ -q
cd frontend && npm run test
cd frontend && npm run build            # writes ../static/dist
```

Tests that call a real provider are behind `@pytest.mark.live` and run only with
`STS_LIVE=1`.

## Documentation

Plans and contracts:

- `plans/proposition-final.md` — authoritative specification
- `plans/implementation-plan.md` — phase and step breakdown
- `plans/contracts.md` — frozen machine contracts
- `CLAUDE.md` — working notes and non-negotiables for contributors and agents

Building workflows:

- [`docs/workflow-guide.md`](docs/workflow-guide.md) — building and running a workflow
- [`docs/workflow-nodes.md`](docs/workflow-nodes.md) — node reference (generated)
- [`docs/workflow-node-author-guide.md`](docs/workflow-node-author-guide.md) — adding a node
- [`docs/workflow-canvas-performance.md`](docs/workflow-canvas-performance.md) — canvas performance notes

Building providers:

- [`docs/providers.md`](docs/providers.md) — provider reference (generated)
- [`docs/provider-author-guide.md`](docs/provider-author-guide.md) — adding a provider, including
  its troubleshooting section
- [`docs/provider-template/`](docs/provider-template/) — copy-paste starting point

The four generated references are rewritten from the live registry and provider hub.
Regenerate them, and fail the build on drift, with:

```bash
venv/Scripts/python.exe -m scriptase.engine.docs             # rewrite all four
venv/Scripts/python.exe -m scriptase.engine.docs --check     # node-doc drift gate
venv/Scripts/python.exe -m scriptase.providers.docs --check  # provider-doc drift gate
```
