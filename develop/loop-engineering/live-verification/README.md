# Live-provider verification (steps 6.1 + 14.5)

Runs the Full Video template through the real workflow runner
(`ExecutionManager` → `WorkflowScheduler` → adapters) against real providers.
The suite lives in `tests/test_live_providers.py`, is marked `@pytest.mark.live`
(registered in `pytest.ini`), and is skipped unless `STS_LIVE=1`.

**Phase 14 gate (step 14.5):** deterministic fixture-backed coverage for every
visual provider lives in `tests/test_visual_provider_gate.py` and does **not**
require live credentials. Live checks remain opt-in so blocked providers
(WaveSpeed key, human-driven Automa) never weaken the green CI gate.

## Procedure

```bash
# 1. One-time: local n8n serving the scene-blueprint webhook (needs `npm i -g n8n`).
#    Imports the repo's workflow export + the OpenRouter credential from .env,
#    then publishes it. Data stays in n8n-data/ (gitignored).
python _dev/loop-engineering/live-verification/setup_local_n8n.py

# 2. Start local n8n (leave running):
python _dev/loop-engineering/live-verification/setup_local_n8n.py start

# 3. Run the live suite (spends OpenRouter/Kie AI credits; ~4 min):
venv/Scripts/python.exe _dev/loop-engineering/live-verification/run_live.py
```

Environment knobs:

| Variable | Default | Purpose |
|---|---|---|
| `STS_LIVE` | unset | `1` enables the live suite (set by `run_live.py`) |
| `STS_LIVE_TIMEOUT` | `1800` | Full-run budget in seconds |
| `STS_LIVE_SCENES_WEBHOOK` | local n8n URL | Scene-blueprint webhook override |
| `STS_LIVE_STORYBOARD` | unset | `1` restores the storyboard branch + test |
| `STS_LIVE_OPENROUTER_MODEL` | `nvidia/nemotron-3-super-120b-a12b:free` | Model pinned into the local n8n workflow |

## Provider status

| Provider | Status | Notes |
|---|---|---|
| Kokoro TTS (local ONNX) | ✅ live-verified (2026-08-05) | `voice.wav` in the project TTS dir; service-level cache by text fingerprint |
| stable-whisper tiny.en | ✅ live-verified (2026-08-05) | Word spans use `begin`/`end` keys; zero-duration words post-fixed |
| Segmenter (local) | ✅ live-verified (2026-08-05) | 5 scenes from the 48-word script |
| Scene blueprint (n8n + OpenRouter) | ✅ live-verified (2026-08-05) | Hosted Railway webhook is dead (workflow inactive + API key revoked + **OpenRouter balance negative** → paid models return HTTP 402). Local n8n + free model works |
| WaveSpeed storyboard (`wavespeed_direct`) | ❌ blocked | Key rejected on every model (HTTP 401 "Invalid API key", verified 2026-08-05). Fixture-backed path green in 14.5. Replace the key, then set `STS_LIVE_STORYBOARD=1` |
| WaveSpeed webhook / gemini_ws storyboard | ⏭ not automatable / blocked | `gemini_ws` needs a human-driven browser extension; webhook depends on n8n storyboard workflow. Both covered by mocked/fixture gates in 14.2 + 14.5 |
| Kie AI animator | ✅ live-verified (2026-08-05) — the Phase 14 direct-provider live path | 5/5 images generated + downloaded (nano-banana; per-image latency 10 s–2.5 min). Full Video live run pins `kie_ai` + `mode=image` |
| grok_automa animator | ⏭ not automatable | Requires a human-driven Automa browser session. Fixture-backed path green in 14.3 + 14.5 |
| FFmpeg export | ✅ live-verified (2026-08-05) | Playable 1080×1920 mp4 with video+audio streams (ffprobe-checked) |

### Phase 14.5 compatibility notes

- Public job IDs remain the project id; `media_job.json` is written beside
  `storyboard.json` / `grabber_job.json` and does not replace them.
- Storyboard and Animator pages, pipeline, and workflow nodes all dispatch
  generically through the provider hub (no `if provider_id == …` branches).
- Deterministic gate: `venv/Scripts/python.exe -m pytest tests/test_visual_provider_gate.py -q`
- Live gate (optional credits): `venv/Scripts/python.exe _dev/loop-engineering/live-verification/run_live.py`

## Product fixes that came out of the live runs

- `studio/workflows/adapters/common.py` — empty (`""`/`None`) node config values
  no longer mask configured inherited project settings (music/scenes tone bug).
- `studio/workflows/adapters/storyboard.py` — zero generated images now raises
  `STORYBOARD_FAILED` instead of reporting success.
- `studio/workflows/adapters/animator.py` — zero generated assets now raises
  `ANIMATOR_FAILED` instead of reporting success.

Fixture regressions for all three live findings are in
`tests/test_workflow_adapters.py`.
