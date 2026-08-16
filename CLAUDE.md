# Scriptase — working notes for agents

Channel-aware, provider-driven, local-first AI video production. Evolution of
ScriptToScene Studio **V2** at
`D:\@Workspace\@Development\@Scripts\@Python\ScriptToScene-Studio-V2`.

Read before touching anything:

| Document | Role |
|---|---|
| `plans/proposition-final.md` | Authoritative spec, port ledger, security rules, definition of done |
| `plans/implementation-plan.md` | Executable phase/step breakdown. **Format is load-bearing** |
| `plans/contracts.md` | Frozen machine contracts (schemas, API shapes, error codes) |

---

## The one rule everything else hangs off

> **Nodes are the execution model. Steps are the user experience.**

One node-based engine is authoritative. The Production view is a *projection* of
that same graph, computed on the backend (step 2.2). Never build a second
step-based execution engine, and never hardcode a step array in the frontend.

## Verification — `python` and `pytest` are NOT on PATH

Always use the venv interpreter. All three must be green before any commit;
the loop orchestrator runs them itself and never trusts an agent's claim.

```bash
venv/Scripts/python.exe -m pytest tests/ -q     # from the repo root
cd frontend && npm run test                     # vitest
cd frontend && npm run build                    # writes ../static/dist
```

Added once the engine lands (step 0.2):

```bash
venv/Scripts/python.exe -m scriptase.engine.docs --check     # node-doc drift gate
venv/Scripts/python.exe -m scriptase.providers.docs --check  # provider-doc drift gate
```

Tests touching real providers stay behind `@pytest.mark.live` (`STS_LIVE=1`).
Several are known-unavailable: the WaveSpeed key returns 401, the hosted n8n
webhook is retired, OpenRouter's balance is negative, and one video provider
needs a human driving a browser. A skipped `live` test is expected; a skipped
anything-else is a defect.

## Running the app

`start.bat` is the only entry point. It provisions and launches; the second run
is a ~2s no-op.

```bash
start.bat                 # dev: Flask :5000 + Vite :5173 with HMR
start.bat -Mode prod      # build the frontend, serve it from Flask alone
start.bat -Mode setup     # provision only, do not launch
start.bat -NoChromium     # skip the bundled browser, use the default one
start.bat -NoAutomation   # skip the vendored ai-web-auto server and its venv
start.bat -NoPull         # skip the fast-forward pull from origin
start.bat -Reinstall      # force a dependency reinstall
```

What it does before launching: fast-forward pull from origin, verify Python
3.10+/Node 18+, create or repair `venv/`, reinstall Python deps when
`requirements.txt` changes and Node deps when `package-lock.json` changes
(SHA-256 stamps beside each artifact), provision `tools/automation/ai-web-auto`'s
separate venv the same way, and load `.env`.

Five things worth knowing:

- **`.env` is read by the launcher, not by Python.** `config.py` uses
  `os.environ` only, so the backend carries no dotenv dependency and tests stay
  hermetic. Setting a real environment variable overrides `.env`.
- **Children die with the launcher.** Flask, ai-web-auto and Vite are placed in a
  Windows Job Object with `KILL_ON_JOB_CLOSE`, so closing the window cannot
  orphan a process holding port 5000. Don't add port-killing or
  window-title-killing back.
- **The pull never blocks startup.** It is `--ff-only`, skipped when the tree is
  dirty, and every failure warns and launches on local code.
- **The order is Flask, ai-web-auto, Chromium, Vite.** The extensions dial the
  backend WebSocket and the automation socket as they load. Chromium is the one
  child deliberately outside the Job Object — it holds the Grok and Google logins
  and is reused across runs — and the one whose failure is a warning, degrading
  to the default browser.
- **ai-web-auto is vendored, not integrated.** `tools/automation/ai-web-auto/` is
  a pinned copy of a separate project with its own venv and its own `:8765`
  WebSocket server, driven by one browser extension and by nothing in
  `scriptase/`. `tools/automation.ps1` provisions and runs it; every failure
  there is a warning. Edit `tools/automation/serve.py`, never the vendored tree —
  see its `VENDOR.md`.

## Layout

```
app.py  config.py  pytest.ini  requirements.txt
plans/                      spec, plan, contracts
scriptase/
  engine/                   ← V2 studio/workflows (+ adapters/)   [step 0.2]
  providers/                ← V2 studio/shared/providers_common   [step 0.2]
  artifacts/                typed, versioned, content-addressed   [step 1.2]
  channels/                 ChannelProfile model, store, routes   [steps 1.1, 1.3]
  jobs/                     Job model, orchestration, stage projection
  review/                   validators, ReviewIssue, Repair Router
  modules/                  script tts timing segmenter scene_director
                            image video captions music compose     [step 0.3]
  shared/                   io_utils, security, validation helpers
frontend/src/features/      production channels workflow providers
tests/  bin/  resources/  models/  output/
develop/loop-engineering/   the orchestrator that runs implementation-plan.md
```

Package renames applied on the way in from V2: `studio`→`scriptase`,
`story`→`script`, `build_scene_blueprints`→`scene_director`,
`storyboard`→`image`, `animator`→`video`, `editor`→`compose`. Provider **domain
ids** rename with them; an alias map keeps imported V2 settings resolving.
`output/` stays V2-compatible so the Phase 10 import works.

## Non-negotiables

**Security**

- Secrets are write-only. Never in an API response, workflow JSON, Job snapshot,
  execution record, SSE event, log, error, archive, notification, or export.
  Environment fallbacks may be *used*, never *returned*.
- Channel snapshots capture provider **instance references**, never credentials.
- No port payload contains an absolute filesystem path — managed relative
  references only.
- Never trust a browser-supplied filesystem path; uploads go through managed
  endpoints with type and size validation.
- Workflow and provider API routes stay loopback-only.

**Structure**

- No module imports business logic from a `routes.py`. Blueprints are transport.
- A provider may never modify a node definition, adapter, route, or generic UI
  component. Adding a provider means creating and registering its package alone.
- No prompt text outside a provider package.
- Music and Captions are local single-implementation services, **not** provider
  domains. Their mode/tone/preset fields look like provider selection and are
  not. The requirement on them is no regression, not migration.
- `-P` never appears in a stage or node name. Provider capability is metadata.

**Data**

- Artifacts are typed, immutable, and versioned. A repair never erases the
  evidence of what it replaced.
- Scene identity is stable across re-segmentation; ordinal position is
  presentation data.
- Review returns structured issues only — never free text.
- Repair the smallest responsible scope. Never regenerate every scene because
  one failed. Never leave a repair loop unbounded.
- `type_version` migrations are unforgiving by design: the runner refuses to
  skip a hop and marks future-version documents read-only. **Every node
  configuration change ships its migration in the same step**, or saved
  workflows break.

## Working with the loop orchestrator

`develop/loop-engineering/` drives `plans/implementation-plan.md`.

```bash
develop\loop-engineering\run.bat --status        # progress + next step
develop\loop-engineering\run.bat --dry-run --phase 2
develop\loop-engineering\run.bat --phase 2
```

- It parses `## Phase N — Title`, `### N.M Title`, and a literal `**Done when:**`
  line per step. **Do not reformat those headings.**
- Progress is detected from commit subjects containing `step N.M`, so commit as
  `feat(scope): step 0.1 - <what changed>`.
- Implement **only** the named step. Leave the app working at every commit.
- One writer at a time — do not run the loop while an interactive session is
  editing the repo.

Headless agents cannot answer permission prompts, so
`.claude/settings.local.json` carries the allowlist. A denied `npm test`
silently cripples the builder. It grants read access to the V2 repo (and denies
writes to it) because Phase 0 ports from there.

## Phase 0 open items

- Step 0.2 reconciles `frontend/package.json` with V2's, so the ported Vitest
  suites and Vue Flow / dagre versions line up. The scaffold pins are
  placeholders.
- `requirements.txt` carries the core only; 0.2 and 0.3 add their own
  dependencies as they land.
