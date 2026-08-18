# Loop Engineering — Playbook

The playbook, based on what actually worked in this project. Three stages,
each with a copy-paste prompt, then the operational lessons learned running
it for real.

## 1. Create the plan

```
Read the codebase first. I want to [GOAL — e.g. "add X feature"].
Write three documents in plans/:

1. proposition-final.md — the authoritative spec: objective, architectural
   decisions, what must be preserved, data schemas, API surface, security
   rules, and a definition of done.

2. implementation-plan.md — break the spec into phases and commit-sized
   steps. STRICT FORMAT (the loop orchestrator parses it):
   - phases as:  ## Phase N — Title
   - steps as:   ### N.M Title
   - every step ends with:  **Done when:** <verifiable criteria>
   Phase 0 must be audit/contracts (verify the plan against the real code
   before building). Each step must leave the app working.
```

Ground every claim in the actual code — read the files, don't assume.
The format rules matter: `loop_engineering.py` parses exactly those headings
and `**Done when:**` lines, and detects progress from commit subjects
containing `step N.M`.

## 2. Gate the plan before building

```
Review plans/implementation-plan.md against
proposition-final.md and the real repository. Check every step's
inputs/outputs against actual code, resolve contradictions in favor of
working behavior, freeze the machine contracts (schemas, API shapes, error
codes) in contracts.md, and record a gate: what's complete, what's deferred
with an owner, what blocks Phase 1. Do not start implementation.
```

This is the round that caught the studio/scenes-doesn't-exist class of
problems here — cheapest bugs you'll ever fix.

## 3. Run it

Hands-free (the orchestrator):

```bat
develop\loop-engineering\run.bat --status            &:: see progress + next step
develop\loop-engineering\run.bat --dry-run --phase 2 &:: preview
develop\loop-engineering\run.bat --phase 2           &:: execute until phase 2 done
develop\loop-engineering\run.bat --all               &:: run to the end, step-level cycles
develop\loop-engineering\run.bat --by-phase          &:: run to the end, PHASE-level cycles
```

`--by-phase` is the "one shot" overnight mode: the builder implements every
step of a phase (each still validated individually so failures can't
compound), then the reviewer audits + smoke-tests the **whole phase's
commits** in one pass and fixes what it finds — only then does the loop
advance to the next phase.

Agents are selectable per role — `--builder`, `--fixer`, `--reviewer`, each
`codex|claude|grok|agy` (`--reviewer none` to skip review). Grok uses the
installed `grok-4.5` model. Defaults: Claude builds
and fixes, AGY retries coding work when the primary reaches a credit/usage limit,
and Codex reviews. Configure the fallback with `--coding-fallback`; use `none`
to disable it. Mixing vendors (one builds, the other reviews) gives a genuinely
independent second opinion.

For a new project, point `PLAN_PATH` at the new plan (or copy the folder)
and seed state with `--mark-done-through` / `--sync-git`.

**Watch it live** — in a second terminal:

```powershell
powershell -ExecutionPolicy Bypass -File develop\loop-engineering\watch.ps1
```

The orchestrator streams agent output into its own console and
`runtime/logs/` as it happens (with a heartbeat when the agent goes quiet).
watch.ps1 adds a translated view of Claude-builder transcripts: one
timestamped line per action (`TOOL`/`SAY`/`DENY`/`ERR`), `GIT` the instant a
commit lands, `AGENT` on each new spawn. It starts at the live edge (no
replay), is read-only, and closes itself when the runner stops. Codex agents
don't write these transcripts — during codex stages, watch the orchestrator
console and `GIT` lines instead.

Interactive (session-driven): just say

```
execute step 2.4 then commit
```

Naming the step beats "next phase" — it's one commit-sized unit,
unambiguous, and the commit subject (`step 2.4`) keeps the orchestrator's
state in sync automatically. Periodically interleave:

```
review the new implementation, find bugs   ← adversarial pass, report only
fix the critical and high findings, then commit
```

The one-liner that ties it together for a brand-new goal:

```
Plan first: transform [GOAL] into
plans/implementation-plan.md using the
phase/step/Done-when format the loop orchestrator parses, gate it against
the real code, then execute it step by step — validate and commit after
each step.
```

## Operational lessons (learned the hard way)

- **Permissions before launch.** Headless agents cannot answer permission
  prompts — a denied `npm test` silently cripples the builder. Keep an
  allowlist in `.claude/settings.local.json` covering at least:
  `npm`, `npx`, `node`, `pytest`, `python`, `venv/Scripts/python.exe`, `cd`,
  `git add/commit/status/diff/log/show`, plus read-only helpers
  (`ls`, `cat`, `grep`, `find`, `wc`, `head`, `tail`). Compound commands
  (`a && b`, `a; b`) are approved part-by-part, so simple single-purpose
  entries beat clever one-liners.
- **Quota limits are detected, not trusted.** If the builder or fixer replies
  "You've hit your limit" / "usage limit reached" (etc.), the run switches
  coding to the configured fallback for the remainder of the run. A failed
  fallback, a limited reviewer, other non-zero exits, or no output still
  **halts** with a `halt` event instead of advancing — a do-nothing agent must
  never mark a step done. The board is
  green from the *previous* step, which is exactly why validation alone can't
  catch this. State and unfinished phase-review baselines survive restarts, so
  every commit made during a phase still gets reviewed.
- **If false completions ever slip into state** (they did once, before the
  guard existed): remove the step ids from `runtime/state.json` `done` and
  add an `invalidated` history event saying why. The loop will rebuild them
  for real.
- **Validation is never delegated.** The orchestrator itself runs pytest,
  vitest, and the production build after every agent invocation; a step is
  only done on a green board with a real commit past the baseline.
- **Never let a step commit on a red board** — when driving interactively,
  say "tests must be green before committing".
- **One writer at a time.** Don't run the loop while an interactive session
  (Claude or codex) is editing the same repo. The guard stage auto-commits
  any dirty tree (`chore(loop): absorb uncommitted changes`) so each cycle
  starts from a clean baseline — stray edits get swept into that commit.
- **Run from a terminal, not double-click**, for scrollback and Ctrl+C.
  Double-clicking `run.bat` safely shows status and pauses instead.
- **Watch the first cycle end-to-end** before leaving a run unattended.
