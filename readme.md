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

- `plans/proposition-final.md` — authoritative specification
- `plans/implementation-plan.md` — phase and step breakdown
- `plans/contracts.md` — frozen machine contracts
- `CLAUDE.md` — working notes and non-negotiables for contributors and agents
