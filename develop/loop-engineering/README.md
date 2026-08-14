# Loop Engineering

Plan-aware orchestrator that executes the workflow-builder upgrade
([phases-plans/implementation-plan.md](phases-plans/implementation-plan.md))
step by step: **execute → validate → correct → review → commit**, until the
selected phase or step range is complete.

## Layout

| Path | What |
|---|---|
| `loop_engineering.py` | The orchestrator (single file, stdlib only) |
| `run.bat` | Launcher — forwards all arguments from anywhere |
| `runtime/state.json` | Progress + event history (gitignored) |
| `runtime/logs/` | Full agent/validation output per step (gitignored) |

## Quick start

Double-click `run.bat`, choose an agent profile, and run all remaining work
phase by phase. The first (and command-line default) profile uses Claude for
coding, automatically retries limit-blocked coding tasks with AGY, and uses
Codex for review. All-Codex, all-Claude, AGY-code/Codex-review, and Grok 4.5
code/AGY-fallback/Codex-review profiles are also available. The window prints
the selected roles, current phase, step, and stage, and stays open with the final
exit code. Agent output and idle-process heartbeats appear in the main window.
When a real run completes or stops early, the runner beeps three times and
opens a foreground, topmost Windows dialog with the result. Pass
`--no-finish-notification` to suppress both notifications in automation or CI.

```bat
_dev\loop-engineering\run.bat --status            &:: where am I? what's next?
_dev\loop-engineering\run.bat --dry-run --phase 2 &:: what would run
_dev\loop-engineering\run.bat --phase 2           &:: finish phase 2
_dev\loop-engineering\run.bat --steps 1           &:: exactly one step
_dev\loop-engineering\run.bat --all               &:: everything, step-level cycles
_dev\loop-engineering\run.bat --by-phase          &:: everything, PHASE-level cycles
_dev\loop-engineering\run.bat --all --no-finish-notification &:: silent finish
```

`--by-phase` is the "one shot" mode: the selected builder handles every step of a phase
(each still validated individually so failures can't compound), then the
reviewer audits + smoke-tests the **whole phase's commits** in one pass and
fixes what it finds — only then does the loop advance to the next phase.

## How a step runs

1. **Guard** — dirty working tree is committed first, so every cycle starts clean.
2. **Execute** — Claude gets the step's full
   description, its *Done when* criteria, and the working agreements.
3. **Validate** — the orchestrator itself runs `pytest`, `npm run test`, and
   `npm run build`. Agent claims are never trusted.
4. **Correct** — while red: Claude receives a fixer prompt with the failure tail, up to
   `--max-fix-attempts` (default 3). Still red → **halt** with a log pointer.
5. **Review** — Codex audits exactly that
   step's commit range, fixes what it finds; the board is re-validated.
6. **Done** — step recorded in `runtime/state.json`, pushed (unless `--no-push`).

Coding-agent quota/rate-limit messages during builder or fixer work trigger one
retry with AGY. Other agent failures, an unsuccessful AGY fallback, timeouts, silent
exits, and builder/fixer runs that produce no changes are hard failures. The loop
halts without marking that work complete. An interrupted phase review is shown as
`REVIEW INCOMPLETE` and is resumed before later phases on the next phase-mode run.

Grok is selectable from the CLI as `--builder grok`, `--fixer grok`, or
`--reviewer grok`. The runner uses model `grok-4.5` and resolves either a `grok`
command on PATH or the standard Windows install at `%USERPROFILE%\.grok\bin\grok.exe`.

## State

- Progress is auto-seeded from commit subjects matching `step N.N` /
  `steps N.N + N.N`; re-scan any time with `--sync-git`.
- Steps delivered outside that convention: `--mark-done-through 0.4`.
- The plan markdown is parsed live — editing the plan is enough; there is no
  second plan file to maintain.

## Cautions

- Don't run the loop while an interactive session edits the same repo —
  one writer at a time.
- Headless agents cannot answer interactive permission prompts; keep Codex's
  non-interactive execution permissions configured for this trusted workspace.
- Watch the first live cycle end-to-end before leaving it unattended.
