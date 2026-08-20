"""Loop-engineering orchestrator for the Scriptase build.

Parses plans/implementation-plan.md into
phases/steps (the markdown stays the single source of truth), tracks
progress in develop/loop-engineering/runtime/state.json, and drives an
execute -> validate -> correct -> review -> commit cycle per step until
the requested phase (or step) is complete.

The orchestrator NEVER trusts an agent's claim of success: after every agent
invocation it runs pytest, vitest, and the production build itself, and only
a green board lets a step be marked done.

Usage (from the repo root, or via run.bat in this folder):
    venv/Scripts/python.exe develop/loop-engineering/loop_engineering.py --status
    venv/Scripts/python.exe develop/loop-engineering/loop_engineering.py --phase 2
    venv/Scripts/python.exe develop/loop-engineering/loop_engineering.py --until 2.5
    venv/Scripts/python.exe develop/loop-engineering/loop_engineering.py --steps 1
    venv/Scripts/python.exe develop/loop-engineering/loop_engineering.py --dry-run --phase 2
    venv/Scripts/python.exe develop/loop-engineering/loop_engineering.py --sync-git

Roles are configurable from the command line. NOTE: the `agy` agent requires an
interactive Google OAuth login and CANNOT authenticate in a headless run -- if it
is used as --coding-fallback while unauthenticated, it prints an auth URL, waits
60s, and exits 1, halting the loop. Use `--coding-fallback codex` or `none`
unless `agy` has been logged in beforehand.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# Windows terminals may default to CP-1252, which cannot print the status
# symbols used throughout this runner. Keep direct Python invocation as robust
# as run.bat (which also selects UTF-8).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def say(message: str, *, icon: str = "·") -> None:
    """Narrated console output: every action the loop takes, timestamped."""
    print(f"[{dt.datetime.now():%H:%M:%S}] {icon} {message}", flush=True)


def elapsed(since: float) -> str:
    seconds = int(time.monotonic() - since)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _completion_beep() -> None:
    """Make a finish sound, degrading quietly when the machine cannot.

    `winsound.Beep` drives the legacy PC-speaker API and raises
    `RuntimeError: Failed to beep` on machines with no beep device — common on
    modern hardware, over RDP, and wherever the Beep driver is disabled. That
    made every completed run end on a red error line for a purely cosmetic
    feature. MessageBeep uses the sound scheme instead and works there.
    """
    if sys.platform == "win32":
        import winsound
        try:
            winsound.Beep(1100, 220)
            return
        except RuntimeError:
            try:
                winsound.MessageBeep(winsound.MB_OK)
                return
            except Exception:
                pass
    sys.stdout.write("\a")
    sys.stdout.flush()


def _show_completion_dialog(title: str, message: str) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    # MB_ICONINFORMATION | MB_TASKMODAL | MB_SETFOREGROUND | MB_TOPMOST
    flags = 0x00000040 | 0x00002000 | 0x00010000 | 0x00040000
    ctypes.windll.user32.MessageBoxW(None, message, title, flags)


def notify_loop_finished(title: str, message: str, *, enabled: bool = True) -> None:
    """Beep three times and show a foreground, topmost completion dialog."""
    if not enabled:
        return
    try:
        for index in range(3):
            _completion_beep()
            if index < 2:
                time.sleep(0.12)
    except Exception:
        # A missing finish chime is not worth a warning line on an otherwise
        # successful run; _completion_beep already degrades through every
        # available option before giving up.
        pass
    try:
        _show_completion_dialog(title, message)
    except Exception as exc:
        say(f"finish notification dialog failed: {exc}", icon="!")

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "plans" / "implementation-plan.md"
LOOP_DIR = ROOT / "develop" / "loop-engineering" / "runtime"
STATE_PATH = LOOP_DIR / "state.json"
LOG_DIR = LOOP_DIR / "logs"

PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
AGENT_TIMEOUT_S = 60 * 60          # one hour per agent invocation
VALIDATE_TIMEOUT_S = 15 * 60

STEP_RE = re.compile(r"^### (\d+\.\d+) (.+?)\s*$", re.M)
PHASE_RE = re.compile(r"^## Phase (\d+) — (.+?)\s*$", re.M)
DONE_WHEN_RE = re.compile(r"\*\*Done when:\*\*\s*(.+?)(?=\n\n|\n###|\n---|\n## |\Z)", re.S)
# Commits made so far use "step 2.3 - ..." and "steps 1.6 + 1.7 - ..."
COMMIT_STEP_RE = re.compile(r"steps? (\d+\.\d+)(?: \+ (\d+\.\d+))?")


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

@dataclass
class Step:
    id: str
    title: str
    body: str
    done_when: str
    phase: int

    @property
    def sort_key(self):
        major, minor = self.id.split(".")
        return (int(major), int(minor))


@dataclass
class Plan:
    phases: dict[int, str] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def phase_steps(self, phase: int) -> list[Step]:
        return [s for s in self.steps if s.phase == phase]


def parse_plan(text: str) -> Plan:
    plan = Plan()
    for match in PHASE_RE.finditer(text):
        plan.phases[int(match.group(1))] = match.group(2)

    matches = list(STEP_RE.finditer(text))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        done = DONE_WHEN_RE.search(body)
        plan.steps.append(Step(
            id=match.group(1),
            title=match.group(2),
            body=body,
            done_when=done.group(1).strip() if done else "",
            phase=int(match.group(1).split(".")[0]),
        ))
    plan.steps.sort(key=lambda s: s.sort_key)
    return plan


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.is_file():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state.setdefault("done", [])
        state.setdefault("history", [])
        state.setdefault("epoch", "")
        return state
    return {"done": [], "history": [], "epoch": ""}


def save_state(state: dict) -> None:
    LOOP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def record(state: dict, step_id: str, event: str, detail: str = "") -> None:
    state["history"].append({
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "step": step_id,
        "event": event,
        "detail": detail[:400],
    })
    save_state(state)


def steps_done_in_git(epoch: str = "") -> set[str]:
    """Steps already delivered, inferred from commit subjects.

    `epoch` is the commit the CURRENT plan started from. Step ids are only
    unique within one plan: this repo carries commits for `step 0.1` through
    `step 16.3` from a delivered plan, so a renumbered follow-up plan that also
    starts at 0.1 would be marked complete before it began. Scanning only
    `epoch..HEAD` scopes detection to the plan actually in flight.
    """
    rng = f"{epoch}..HEAD" if epoch else "-200"
    out = run_capture(["git", "log", "--oneline", rng], cwd=ROOT)
    done = set()
    for line in out.splitlines():
        for match in COMMIT_STEP_RE.finditer(line):
            done.add(match.group(1))
            if match.group(2):
                done.add(match.group(2))
    return done


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def run_capture(cmd, cwd=ROOT, timeout=120) -> str:
    result = run_capture_result(cmd, cwd=cwd, timeout=timeout)
    return (result.stdout or "") + (result.stderr or "")


def run_capture_result(cmd, cwd=ROOT, timeout=120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, shell=isinstance(cmd, str), encoding="utf-8", errors="replace",
    )


@dataclass
class LoggedResult:
    returncode: int
    output_lines: int
    blocker: str = ""


AGENT_BLOCKERS = (
    # Vendors word exhaustion differently and a near-miss reads as a generic
    # crash, so match on the distinctive fragment rather than a whole sentence.
    # Two escapes so far: agy's "Individual quota reached" and codex's "You've
    # hit your usage limit" — the latter is NOT a superstring of "you've hit
    # your limit", because of the word in the middle.
    "hit your limit",
    "hit your usage limit",
    "usage limit",
    "purchase more credits",
    "rate limit exceeded",
    "quota exceeded",
    # agy says "Individual quota reached. Please upgrade your subscription" —
    # none of the phrases above match it, so a quota-limited agy was reported as
    # a generic non-zero exit and halted the run instead of handing off to the
    # configured fallback.
    "quota reached",
    "upgrade your subscription",
    "insufficient credits",
    "credit balance is too low",
)

AGENT_CHOICES = ("claude", "grok", "agy", "codex", "opencode")
GROK_MODEL = "grok-4.5"
# opencode routes to many providers; the loop pins one so a run is reproducible
# and so a model change is a visible edit rather than a silent default shift.
# Override per run with OPENCODE_MODEL. `opencode models` lists the rest.
OPENCODE_MODEL = os.environ.get("OPENCODE_MODEL", "opencode/nemotron-3-ultra-free")


def agent_executable(agent: str) -> str | None:
    """Resolve an agent CLI, including Grok's default per-user install path."""
    executable = shutil.which(agent)
    if executable:
        return executable
    if agent == "grok":
        candidate = Path.home() / ".grok" / "bin" / "grok.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def run_logged(cmd, log_file: Path, cwd=ROOT, timeout=AGENT_TIMEOUT_S) -> LoggedResult:
    """Run a command streaming combined output to console + log file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log:
        log.write(f"\n===== {dt.datetime.now().isoformat()} :: {cmd}\n")
        log.flush()
        process = subprocess.Popen(
            cmd, cwd=str(cwd), shell=isinstance(cmd, str),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        output_lines = 0
        blocker = ""
        output_queue: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            for line in process.stdout:
                output_queue.put(line)
            output_queue.put(None)

        threading.Thread(target=read_output, daemon=True).start()
        deadline = time.monotonic() + timeout
        last_output = time.monotonic()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                log.write("\n!! TIMEOUT — process killed\n")
                return LoggedResult(124, output_lines, "agent timed out")
            try:
                line = output_queue.get(timeout=min(15, remaining))
            except queue.Empty:
                say(f"agent process is still alive — no new console output for {elapsed(last_output)}")
                continue
            if line is None:
                break
            output_lines += 1
            last_output = time.monotonic()
            lowered = line.lower()
            # Capture both kinds of fatal line: a usage limit means switch agent,
            # a transient upstream fault means retry the same one. They are told
            # apart downstream by which list the captured text matches.
            if not blocker and any(marker in lowered
                                   for marker in AGENT_BLOCKERS + AGENT_TRANSIENT):
                blocker = line.strip()
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            log.flush()
        process.wait()
        return LoggedResult(process.returncode or 0, output_lines, blocker)


def agent_run_ok(result: LoggedResult, state: dict, scope: str, stage: str) -> bool:
    """Never treat a silent, limited, or failed agent invocation as success."""
    # A blocker phrase only counts when the agent actually died with it: a
    # healthy long run can QUOTE "you've hit your limit" (docs, log echoes)
    # without being limited — that false positive halted step 9.5 once.
    blocker_fatal = agent_limit_reached(result)
    if blocker_fatal:
        detail = f"{stage} blocked: {result.blocker}"
    elif result.returncode != 0:
        detail = f"{stage} exited with code {result.returncode}"
    elif result.output_lines == 0:
        detail = f"{stage} produced no output"
    else:
        return True
    record(state, scope, "halt", detail)
    say(f"HALT — {detail}. This work remains incomplete and is safe to resume.", icon="✗")
    return False


def agent_limit_reached(result: LoggedResult) -> bool:
    """Whether an invocation failed because its account was limited.

    Must match the limit list specifically: run_logged also captures transient
    upstream faults into the same field, and those call for a retry of the same
    agent rather than a permanent switch to the fallback.
    """
    if not result.blocker:
        return False
    if not any(marker in result.blocker.lower() for marker in AGENT_BLOCKERS):
        return False
    return result.returncode != 0 or result.output_lines < 80


AGENT_TRANSIENT = (
    "overloaded_error",
    "api error: 529",
    "api error: 503",
    "api error: 500",
    "internal server error",
    "econnreset",
    "socket hang up",
    "service unavailable",
)

TRANSIENT_RETRIES = 3


def agent_hit_transient(result: LoggedResult) -> bool:
    """Whether an invocation died from a passing upstream fault.

    Distinct from a usage limit: a limit means switch agent, a transient means
    wait and try the same one again. `API Error: 529 Overloaded` ended a
    seven-step run three minutes in, which no amount of falling back would have
    helped — the other vendor was fine, and so was this one a minute later.
    """
    if result.returncode == 0:
        return False
    blob = (result.blocker or "").lower()
    return any(marker in blob for marker in AGENT_TRANSIENT)


def run_agent(agent: str, prompt: str, log_file: Path, *, fallback: str = "none",
              fallback_state: dict | None = None) -> LoggedResult:
    """Run a coding agent, retrying transient faults and falling back on limits."""
    if fallback_state and fallback_state.get("active") and fallback != "none":
        say(f"coding fallback is active — launching {fallback} instead of {agent}")
        agent = fallback
    result = run_logged(agent_cmd(agent, prompt), log_file)

    for attempt in range(1, TRANSIENT_RETRIES + 1):
        if not agent_hit_transient(result):
            break
        delay = 20 * attempt
        say(f"{agent} hit a transient upstream fault ({result.blocker}) — "
            f"retrying in {delay}s ({attempt}/{TRANSIENT_RETRIES})", icon="!")
        time.sleep(delay)
        result = run_logged(agent_cmd(agent, prompt), log_file)
    if fallback != "none" and fallback != agent and agent_limit_reached(result):
        say(f"{agent} reached its credit/usage limit — switching coding work to {fallback} "
            "for the rest of this run",
            icon="!")
        if fallback_state is not None:
            fallback_state["active"] = True
        with log_file.open("a", encoding="utf-8") as log:
            log.write(f"\n===== LIMIT FALLBACK :: {agent} -> {fallback}\n")
        return run_logged(agent_cmd(fallback, prompt), log_file)
    return result


def unfinished_phase_baselines(state: dict) -> dict[int, str]:
    """Return phase reviews that started but were never recorded as done."""
    unfinished: dict[int, str] = {}
    for event in state.get("history", []):
        match = re.fullmatch(r"phase-(\d+)", str(event.get("step", "")))
        if not match:
            continue
        phase = int(match.group(1))
        if event.get("event") == "start":
            # Preserve the first unmatched baseline so repeated restarts still
            # review every commit made during the phase.
            unfinished.setdefault(phase, str(event.get("detail", "")))
        elif event.get("event") == "done":
            unfinished.pop(phase, None)
    return unfinished


def ensure_agents_available(args) -> None:
    """Fail before touching the worktree if a selected agent CLI is missing."""
    selected = {args.builder, args.fixer}
    if args.reviewer != "none":
        selected.add(args.reviewer)
    if args.coding_fallback != "none":
        selected.add(args.coding_fallback)
    missing = sorted(agent for agent in selected if agent_executable(agent) is None)
    if missing:
        names = ", ".join(missing)
        sys.exit(f"Cannot start: required agent command(s) not found: {names}")


# ---------------------------------------------------------------------------
# Validation (never trust the agent)
# ---------------------------------------------------------------------------

def failure_excerpt(output: str, *, context_lines: int = 20) -> str:
    """The lines a fixer actually needs, not merely the last ones printed.

    Taking a blind tail loses the failures whenever anything prints after the
    summary. That happened for real: loguru's atexit handler writes to a closed
    stream after pytest finishes, so a step with nine failing tests handed the
    fixer 'ValueError: I/O operation on closed file' and nothing else. It spent
    forty minutes editing unrelated files.

    Structured markers are collected first and always survive truncation; the
    trailing context is appended after them.
    """
    lines = output.strip().splitlines()
    markers, seen = [], set()
    for line in lines:
        stripped = line.strip()
        is_marker = (
            stripped.startswith(("FAILED ", "ERROR ", "FAIL ", "E   "))
            or re.match(r"^\d+ (failed|error)", stripped)
            or re.search(r"\b\d+ failed\b", stripped)
            or "Error:" in stripped and "npm" not in stripped
        )
        if is_marker and stripped not in seen:
            seen.add(stripped)
            markers.append(stripped)

    tail = [l for l in lines[-context_lines:]]
    if not markers:
        return "\n".join(tail)

    parts = ["Failures:"] + markers[:40]
    parts += ["", f"Last {len(tail)} lines of output:"] + tail
    return "\n".join(parts)


def tree_fingerprint() -> str:
    """Identity of the working tree: HEAD plus the exact dirty state.

    If this is unchanged since the last green board, the board cannot have
    changed either — nothing was edited, so re-running the suites is pure cost.
    """
    head = run_capture(["git", "rev-parse", "HEAD"], cwd=ROOT).strip()
    dirty = run_capture(["git", "status", "--porcelain"], cwd=ROOT)
    import hashlib
    return head + ":" + hashlib.sha256(dirty.encode("utf-8", "replace")).hexdigest()[:16]


_LAST_GREEN_FINGERPRINT = ""


def validate(log_file: Path, *, allow_cache: bool = True) -> tuple[bool, str]:
    """Run the board. Cheapest check first so a red fails fast.

    Order is deliberate: the production build takes ~2s and vitest ~5s, while
    pytest takes ~200s. Running pytest first meant a broken frontend cost three
    and a half minutes before reporting a two-second failure.
    """
    global _LAST_GREEN_FINGERPRINT
    fingerprint = tree_fingerprint()
    if allow_cache and fingerprint and fingerprint == _LAST_GREEN_FINGERPRINT:
        say("validate: skipped — nothing changed since the last green board", icon="✓")
        return True, "all green (cached)"

    checks = [
        ("build", "npm run build", ROOT / "frontend"),
        ("vitest", "npm run test", ROOT / "frontend"),
        ("pytest", [str(PYTHON), "-m", "pytest", "tests/", "-q", "--tb=short"], ROOT),
    ]
    for name, cmd, cwd in checks:
        started = time.monotonic()
        say(f"validate: running {name} ({'backend test suite' if name == 'pytest' else 'frontend test suite' if name == 'vitest' else 'production build'})")
        try:
            result = run_capture_result(cmd, cwd=cwd, timeout=VALIDATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return False, f"{name} timed out"
        output = (result.stdout or "") + (result.stderr or "")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as log:
            log.write(f"\n----- validate:{name}\n{output}\n")
        if result.returncode != 0:
            say(f"validate: {name} is RED after {elapsed(started)}", icon="✗")
            return False, f"{name} FAILED:\n{failure_excerpt(output)}"
        say(f"validate: {name} green in {elapsed(started)}", icon="✓")
    _LAST_GREEN_FINGERPRINT = fingerprint
    return True, "all green"


def working_tree_dirty() -> bool:
    return bool(run_capture(["git", "status", "--porcelain"]).strip())


def commit_all(message: str) -> None:
    run_capture(["git", "add", "-A"])
    run_capture(["git", "commit", "-m", message], timeout=300)


def head_commit() -> str:
    return run_capture(["git", "rev-parse", "--short", "HEAD"]).strip()


# ---------------------------------------------------------------------------
# Agent prompts
# ---------------------------------------------------------------------------

# On this machine 'python' and 'pytest' are NOT on PATH — bare 'python' resolves to a
# non-existent interpreter. Agents that guess waste turns on a confusing error, so every
# prompt names the exact commands the orchestrator itself uses in validate().
VERIFY = (
    "Verification commands — 'python' and 'pytest' are NOT on PATH on this machine, "
    "always use the venv interpreter: from the repo root run "
    "'venv/Scripts/python.exe -m pytest tests/ -q', then from frontend/ run "
    "'npm run test' and 'npm run build'."
)

AGREEMENTS = (
    "Working agreements: implement ONLY this step (do not start other steps); "
    "follow existing conventions and plans/contracts.md; "
    "read CLAUDE.md at the repo root before touching code. " + VERIFY + " "
    "Get all three green BEFORE committing; finish with exactly one commit whose "
    "subject contains 'step {step_id}'. Do not push."
)


def execute_prompt(step: Step) -> str:
    return (
        f"You are executing step {step.id} of the Scriptase plan "
        f"(plans/implementation-plan.md). Step {step.id}: {step.title}.\n\n"
        f"Step description:\n{step.body}\n\n"
        f"Done when: {step.done_when}\n\n" + AGREEMENTS.format(step_id=step.id)
    )


def failure_signature(detail: str) -> str:
    """A stable identity for a board failure, ignoring timings and paths.

    Used to notice that a fix attempt changed code but not the outcome — the
    fixer committing something and the board failing identically means it is
    going in circles, and each further attempt costs a full agent invocation.
    """
    text = re.sub(r"\d+", "#", detail or "")
    text = re.sub(r"[A-Za-z]:\\[^\s]+|/[^\s]+/", "<path>", text)
    return " ".join(text.split())[:400]


def fix_prompt(step: Step, failure: str, *, attempt: int = 1, repeated: bool = False) -> str:
    escalation = ""
    if repeated:
        escalation = (
            " IMPORTANT: your previous fix committed changes but the board failed in "
            "exactly the same way. Do not retry the same approach — diagnose why the "
            "last change did not affect this failure before editing anything else."
        )
    return (
        f"The build/test board is RED after work on step {step.id} ({step.title}) "
        f"(fix attempt {attempt}). "
        f"Diagnose and fix the failures below, re-run the suites until green, "
        f"then commit the fix with subject 'fix: step {step.id} validation'. "
        f"Do not start new features.{escalation}\n\n{VERIFY}\n\nFailure output:\n{failure}"
    )


def review_prompt(step: Step, before: str, after: str) -> str:
    return (
        f"Review the commits {before}..{after} implementing step {step.id} "
        f"({step.title}) of plans/implementation-plan.md. Hunt for real "
        f"bugs: correctness, contract violations vs plans/contracts.md, "
        f"security, edge cases. Fix what you find, get every suite green, then commit "
        f"fixes with subject 'fix(review): step {step.id}'. If nothing needs fixing, "
        f"change nothing.\n\n{VERIFY}"
    )


def phase_review_prompt(phase: int, title: str, steps: list[Step], before: str, after: str) -> str:
    ids = ", ".join(s.id for s in steps)
    return (
        f"Adversarial review of Phase {phase} ({title}) of "
        f"plans/implementation-plan.md — commits {before}..{after}, "
        f"covering steps {ids}.\n"
        f"1) Hunt for real bugs across the WHOLE phase: correctness, integration "
        f"seams between the steps, contract violations vs "
        f"plans/contracts.md, security, edge cases.\n"
        f"2) Smoke test: {VERIFY} Also verify the Flask app still boots "
        f"(venv/Scripts/python.exe -c \"import app\").\n"
        f"3) Fix every bug you find, keep all suites green, and commit the fixes "
        f"with subject 'fix(review): phase {phase}'.\n"
        f"If nothing needs fixing, change nothing."
    )


def agent_cmd(agent: str, prompt: str) -> str:
    escaped = prompt.replace('"', "'")
    if agent == "codex":
        # `codex exec` defaults to a read-only sandbox for any project that is not
        # listed as trusted in ~/.codex/config.toml, and this repo is not. Without an
        # explicit sandbox mode the agent reasons for 20 minutes and writes nothing,
        # then the guard halts because no commit landed past the baseline.
        return f'codex exec --sandbox workspace-write "{escaped}"'
    if agent == "claude":
        return f'claude -p --permission-mode acceptEdits "{escaped}"'
    if agent == "grok":
        executable = agent_executable("grok") or "grok"
        return (f'"{executable}" --model {GROK_MODEL} '
                f'--permission-mode bypassPermissions --output-format plain -p "{escaped}"')
    if agent == "agy":
        return (f'agy --mode accept-edits --dangerously-skip-permissions '
                f'--print-timeout 60m -p "{escaped}"')
    if agent == "opencode":
        # `run` is the headless subcommand; the bare `opencode` command opens a
        # TUI and would hang a loop forever. `--auto` approves any permission
        # not explicitly denied, which is what lets it edit without a human —
        # the same bargain as claude's acceptEdits and codex's workspace-write.
        return f'opencode run --auto -m {OPENCODE_MODEL} "{escaped}"'
    raise ValueError(f"Unsupported agent: {agent}")


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def run_reviewer(agent: str, prompt: str, log_file: Path, *, fallback: str = "none") -> LoggedResult:
    """Run the reviewer, degrading to the fallback when its account is limited.

    The reviewer bypassed run_agent entirely, so a usage-limited reviewer halted
    a step whose build had already passed. Codex hitting a three-day lockout
    stopped step 6.2 with its work committed and its board green.
    """
    result = run_logged(agent_cmd(agent, prompt), log_file)
    if fallback != "none" and fallback != agent and agent_limit_reached(result):
        say(f"reviewer {agent} is limited — falling back to {fallback} for the review",
            icon="!")
        with log_file.open("a", encoding="utf-8") as log:
            log.write(f"\n===== REVIEWER LIMIT FALLBACK :: {agent} -> {fallback}\n")
        return run_logged(agent_cmd(fallback, prompt), log_file)
    return result


def run_step(step: Step, state: dict, args, *, review: bool = True, push: bool = True) -> bool:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"{stamp}_step_{step.id.replace('.', '-')}.log"
    step_started = time.monotonic()

    print("\n" + "=" * 72)
    say(f"STEP {step.id} — {step.title}", icon="▶")
    say(f"goal: {step.done_when[:160] or '(no explicit done-when)'}")
    say(f"full agent output is streaming to {log_file.relative_to(ROOT)}")
    record(state, step.id, "start")

    if working_tree_dirty():
        say("guard: working tree has uncommitted changes — committing them so "
            "this step starts from a clean baseline", icon="!")
        commit_all(f"chore(loop): absorb uncommitted changes before step {step.id}")

    baseline = head_commit()
    say(f"baseline commit is {baseline}; everything after it belongs to this step")

    # 1) EXECUTE
    say(f"stage 1/4 EXECUTE — launching the builder agent ({args.builder}) with the "
        f"step description + done-when criteria; it will implement step {step.id}", icon="▶")
    stage = time.monotonic()
    result = run_agent(args.builder, execute_prompt(step), log_file,
                       fallback=args.coding_fallback, fallback_state=args.fallback_state)
    say(f"builder agent finished in {elapsed(stage)}")
    if not agent_run_ok(result, state, step.id, "builder agent"):
        # An agent that finishes its work and then hangs is killed by the
        # timeout and reported as a failure, throwing away completed work. This
        # happened once and cost a full hour: the tree was dirty and the board
        # was green, and the step had to be recovered by hand. Before halting,
        # check whether the work is actually there and passing.
        if result.blocker == "agent timed out" and working_tree_dirty():
            say("agent timed out with uncommitted work — checking whether it "
                "finished before it hung", icon="!")
            ok, _ = validate(log_file)
            if ok:
                say("board is green — salvaging the work instead of halting", icon="✓")
                commit_all(f"feat(workflow): step {step.id} - {step.title} (loop auto-commit)")
                record(state, step.id, "salvaged", "timed out after completing; board green")
            else:
                return False
        else:
            return False
    if working_tree_dirty():
        say("builder left uncommitted changes — committing them on its behalf")
        commit_all(f"feat(workflow): step {step.id} - {step.title} (loop auto-commit)")
    if head_commit() == baseline:
        detail = "builder agent completed without producing any code or commit changes"
        record(state, step.id, "halt", detail)
        say(f"HALT — {detail}. Step {step.id} remains incomplete.", icon="✗")
        return False

    # 2) VALIDATE + CORRECT loop
    say("stage 2/4 VALIDATE — running pytest, vitest, and the production build "
        "myself (agent claims are never trusted)", icon="▶")
    for attempt in range(1, args.max_fix_attempts + 1):
        ok, detail = validate(log_file)
        if ok:
            say("board is green — validation passed", icon="✓")
            break
        say(f"board is RED (fix attempt {attempt}/{args.max_fix_attempts}) — "
            f"launching the {args.fixer} fixer with the failure output", icon="✗")
        record(state, step.id, "validation_red", detail)
        stage = time.monotonic()
        fix_baseline = head_commit()
        result = run_agent(args.fixer, fix_prompt(step, detail), log_file,
                           fallback=args.coding_fallback, fallback_state=args.fallback_state)
        say(f"fixer finished in {elapsed(stage)} — re-validating")
        if not agent_run_ok(result, state, step.id, "validation fixer"):
            return False
        if working_tree_dirty():
            commit_all(f"fix: step {step.id} validation (loop auto-commit)")
        if head_commit() == fix_baseline:
            detail = "validation fixer completed without producing any changes"
            record(state, step.id, "halt", detail)
            say(f"HALT — {detail}. Step {step.id} remains incomplete.", icon="✗")
            return False
    else:
        record(state, step.id, "halt", "validation still red after max fix attempts")
        say(f"HALT — still red after {args.max_fix_attempts} fix attempts. "
            f"A human needs to look. Full log: {log_file}", icon="✗")
        return False

    # 3) REVIEW (adversarial pass) + re-validate
    if not review:
        say("stage 3/4 REVIEW — deferred to the phase-level review pass")
    elif args.reviewer != "none":
        say(f"stage 3/4 REVIEW — {args.reviewer} audits commits {baseline}..{head_commit()} "
            f"for real bugs and fixes what it finds", icon="▶")
        stage = time.monotonic()
        post_build_commit = head_commit()
        result = run_reviewer(args.reviewer, review_prompt(step, baseline, post_build_commit),
                              log_file, fallback=args.coding_fallback)
        say(f"reviewer finished in {elapsed(stage)}")
        if not agent_run_ok(result, state, step.id, "reviewer agent"):
            return False
        review_changed = working_tree_dirty()
        if review_changed:
            say("reviewer left uncommitted fixes — committing them")
            commit_all(f"fix(review): step {step.id} (loop auto-commit)")
        if not review_changed and head_commit() == post_build_commit:
            # The reviewer touched nothing, so the board it would be re-checking
            # is the identical board that was green a moment ago.
            say("reviewer made no changes — board is unchanged, skipping re-validation", icon="✓")
            ok, detail = True, "all green (unchanged)"
        else:
            say("re-validating after review (a reviewer can break the board too)")
            ok, detail = validate(log_file)
        if not ok:
            say("reviewer broke the board — one repair pass", icon="✗")
            record(state, step.id, "review_red", detail)
            result = run_agent(args.fixer, fix_prompt(step, detail), log_file,
                               fallback=args.coding_fallback, fallback_state=args.fallback_state)
            if not agent_run_ok(result, state, step.id, "post-review fixer"):
                return False
            if working_tree_dirty():
                commit_all(f"fix: step {step.id} post-review (loop auto-commit)")
            ok, detail = validate(log_file)
            if not ok:
                record(state, step.id, "halt", "red after review repair")
                say(f"HALT — red after review repair. Full log: {log_file}", icon="✗")
                return False
        say("board still green after review", icon="✓")
    else:
        say("stage 3/4 REVIEW — skipped (--reviewer none)")

    # 4) DONE
    say("stage 4/4 DONE — recording the step in runtime/state.json", icon="▶")
    if step.id not in state["done"]:
        state["done"].append(step.id)
    record(state, step.id, "done", head_commit())
    if push and not args.no_push:
        say("pushing commits to origin")
        run_capture(["git", "push"], timeout=600)
    elif not push:
        say("push deferred to the end of the phase")
    else:
        say("push skipped (--no-push) — commits are local only")
    say(f"step {step.id} COMPLETE at {head_commit()} (total {elapsed(step_started)})", icon="✓")
    return True


def run_phase(phase: int, steps: list[Step], plan: Plan, state: dict, args,
              *, resume_baseline: str | None = None) -> bool:
    """Phase-level cycle: build every step (validated individually), then one
    adversarial review + smoke test over the whole phase before moving on."""
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"{stamp}_phase_{phase}.log"
    phase_started = time.monotonic()
    title = plan.phases.get(phase, "")

    print("\n" + "#" * 72)
    say(f"PHASE {phase} — {title}: {len(steps)} step(s) to build "
        f"({', '.join(s.id for s in steps) or 'review resume only'})", icon="▶")
    baseline = resume_baseline or head_commit()
    if resume_baseline:
        say(f"resuming unfinished Phase {phase} from baseline {baseline}; "
            "the phase will not be complete until its review passes", icon="!")
    else:
        record(state, f"phase-{phase}", "start", baseline)

    say(f"part 1/2 BUILD — {args.builder} implements each step in order; every step is "
        f"validated (pytest/vitest/build) before the next one starts")
    for step in steps:
        if not run_step(step, state, args, review=False, push=False):
            say(f"PHASE {phase} stopped inside step {step.id}", icon="✗")
            return False

    if args.reviewer != "none":
        say(f"part 2/2 PHASE REVIEW — {args.reviewer} audits ALL phase commits "
            f"{baseline}..{head_commit()}, smoke-tests the app, and fixes bugs", icon="▶")
        stage = time.monotonic()
        review_steps = steps or plan.phase_steps(phase)
        result = run_reviewer(args.reviewer,
                              phase_review_prompt(phase, title, review_steps,
                                                  baseline, head_commit()),
                              log_file, fallback=args.coding_fallback)
        say(f"phase reviewer finished in {elapsed(stage)}")
        if not agent_run_ok(result, state, f"phase-{phase}", "phase reviewer"):
            return False
        if working_tree_dirty():
            say("reviewer left uncommitted fixes — committing them")
            commit_all(f"fix(review): phase {phase} (loop auto-commit)")
        say("re-validating the board after the phase review")
        ok, detail = validate(log_file)
        if not ok:
            say("phase review left the board RED — one repair pass", icon="✗")
            record(state, f"phase-{phase}", "review_red", detail)
            repair_step = (steps or plan.phase_steps(phase))[-1]
            result = run_agent(args.fixer, fix_prompt(repair_step, detail), log_file,
                               fallback=args.coding_fallback, fallback_state=args.fallback_state)
            if not agent_run_ok(result, state, f"phase-{phase}", "phase repair agent"):
                return False
            if working_tree_dirty():
                commit_all(f"fix: phase {phase} post-review (loop auto-commit)")
            ok, detail = validate(log_file)
            if not ok:
                record(state, f"phase-{phase}", "halt", "red after phase review repair")
                say(f"HALT — phase {phase} red after review repair. Log: {log_file}", icon="✗")
                return False
        say("board green after phase review", icon="✓")

    record(state, f"phase-{phase}", "done", head_commit())
    if not args.no_push:
        say("pushing the whole phase to origin")
        run_capture(["git", "push"], timeout=600)
    say(f"PHASE {phase} COMPLETE in {elapsed(phase_started)} — proceeding", icon="✓")
    return True


def pick_targets(plan: Plan, state: dict, args) -> list[Step]:
    done = set(state["done"])
    pending = [s for s in plan.steps if s.id not in done]
    if args.phase is not None:
        pending = [s for s in pending if s.phase == args.phase]
    if args.until:
        limit = plan.step(args.until)
        if not limit:
            sys.exit(f"Unknown step id: {args.until}")
        pending = [s for s in pending if s.sort_key <= limit.sort_key]
    if args.steps:
        pending = pending[: args.steps]
    return pending


def step_pace(state: dict) -> tuple[float, int]:
    """Median minutes per completed step, and how many samples back it."""
    starts, durations = {}, []
    for event in state.get("history", []):
        stamp = dt.datetime.fromisoformat(event["ts"])
        step_id = str(event.get("step", ""))
        if "." not in step_id:
            continue
        if event["event"] == "start":
            starts[step_id] = stamp
        elif event["event"] in ("done", "salvaged") and step_id in starts:
            minutes = (stamp - starts.pop(step_id)).total_seconds() / 60
            if 0 < minutes < 240:
                durations.append(minutes)
    if not durations:
        return 0.0, 0
    durations.sort()
    return durations[len(durations) // 2], len(durations)


def run_doctor(plan: Plan, state: dict) -> bool:
    """Pre-flight the environment before spending agent time on it.

    Every halt this loop has suffered was an environment problem discovered
    late: a missing permission allowlist burned three fix attempts, an agent
    that could not authenticate headlessly burned an hour, a read-only agent
    sandbox would have produced nothing for twenty minutes, and a batch file
    saved with LF endings closed the console instantly. All of them are
    checkable in seconds.
    """
    ok = True

    def check(label: str, passed: bool, detail: str = "", fatal: bool = True) -> None:
        nonlocal ok
        if passed:
            say(f"{label}: {detail or 'ok'}", icon="✓")
        else:
            say(f"{label}: {detail}", icon="✗" if fatal else "!")
            if fatal:
                ok = False

    print("\n" + "=" * 72)
    say("DOCTOR — checking the environment before any agent runs", icon="▶")

    check("venv python", PYTHON.is_file(), str(PYTHON) if PYTHON.is_file()
          else f"missing — create it: python -m venv {ROOT / 'venv'}")

    node = shutil.which("node")
    check("node", bool(node), node or "not on PATH — install Node 18+")
    check("npm", bool(shutil.which("npm")), shutil.which("npm") or "not on PATH")

    modules = ROOT / "frontend" / "node_modules"
    check("frontend deps", modules.is_dir(),
          "installed" if modules.is_dir() else "missing — run: cd frontend && npm install")

    check("git repo", (ROOT / ".git").is_dir(), "present" if (ROOT / ".git").is_dir()
          else "not a git repository; progress detection needs commits")

    dirty = run_capture(["git", "status", "--porcelain"], cwd=ROOT).strip()
    check("working tree", True,
          "clean" if not dirty else f"{len(dirty.splitlines())} uncommitted file(s) — "
          "the guard will absorb them into a baseline commit", fatal=False)

    check("plan parses", bool(plan.steps),
          f"{len(plan.steps)} steps in {len(plan.phases)} phases")
    missing_done = [s.id for s in plan.steps if not s.done_when.strip()]
    check("done-when lines", not missing_done,
          "every step has one" if not missing_done else f"missing on {missing_done}")

    check("plan epoch", bool(state.get("epoch")),
          state.get("epoch", "")[:12] or "unset — step ids from an earlier plan may be "
          "mistaken for this one's", fatal=False)

    # A .bat saved with LF endings closes the console the moment a label is used.
    bat = ROOT / "develop" / "loop-engineering" / "run.bat"
    if bat.is_file():
        raw = bat.read_bytes()
        lf_only = raw.count(b"\n") - raw.count(b"\r\n")
        check("run.bat line endings", lf_only == 0,
              "CRLF" if lf_only == 0 else f"{lf_only} bare LF lines — cmd.exe will exit mid-script")

    allowlist = ROOT / ".claude" / "settings.local.json"
    check("permission allowlist", allowlist.is_file(),
          "present" if allowlist.is_file() else
          "missing — headless agents cannot answer prompts and a denied npm test "
          "silently cripples the builder", fatal=False)

    if os.environ.get("CLAUDECODE"):
        check("nested session", False,
              "running inside Claude Code — the claude builder cannot launch here; "
              "use a normal terminal or --builder codex", fatal=False)

    for agent in AGENT_CHOICES:
        found = agent_executable(agent) or shutil.which(agent)
        check(f"agent {agent}", True, found or "not installed", fatal=False)

    median, samples = step_pace(state)
    if samples:
        remaining = sum(1 for s in plan.steps if s.id not in set(state["done"]))
        eta = median * remaining
        say(f"pace: {median:.0f} min/step over {samples} samples — "
            f"{remaining} left ≈ {eta / 60:.1f}h", icon="·")

    print()
    say("doctor: ready to run" if ok else "doctor: fix the items above first",
        icon="✓" if ok else "✗")
    return ok


def print_status(plan: Plan, state: dict) -> None:
    done = set(state["done"])
    unfinished_reviews = unfinished_phase_baselines(state)
    print(f"Plan: {PLAN_PATH.name} — {len(plan.steps)} steps in {len(plan.phases)} phases\n")
    for phase, title in sorted(plan.phases.items()):
        steps = plan.phase_steps(phase)
        completed = sum(1 for s in steps if s.id in done)
        review_pending = phase in unfinished_reviews
        marker = "✔" if completed == len(steps) and steps and not review_pending else "!" if review_pending else " "
        suffix = " — REVIEW INCOMPLETE" if review_pending else ""
        print(f" [{marker}] Phase {phase} — {title}  ({completed}/{len(steps)}){suffix}")
        for step in steps:
            flag = "✔" if step.id in done else "·"
            print(f"      {flag} {step.id}  {step.title}")
    nxt = next((s for s in plan.steps if s.id not in done), None)
    print(f"\nNext step: {nxt.id} — {nxt.title}" if nxt else "\nAll steps complete.")

    # "When will it be done?" is answerable from this run's own history.
    median, samples = step_pace(state)
    if nxt and samples:
        remaining = sum(1 for s in plan.steps if s.id not in done)
        eta_minutes = median * remaining
        finish = dt.datetime.now() + dt.timedelta(minutes=eta_minutes)
        print(f"Pace: {median:.0f} min/step over {samples} completed step(s) — "
              f"{remaining} left ≈ {eta_minutes / 60:.1f}h, finishing about "
              f"{finish:%H:%M}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show plan progress and exit")
    ap.add_argument("--doctor", action="store_true",
                    help="check the environment (venv, node, agents, plan, allowlist) and exit")
    ap.add_argument("--skip-doctor", action="store_true",
                    help="start even if the pre-flight environment check fails")
    ap.add_argument("--all", action="store_true", help="run every remaining step, phase by phase, to the end of the plan")
    ap.add_argument("--by-phase", action="store_true",
                    help="phase-level cycle: build all steps of a phase, then ONE "
                         "review+smoke-test pass over the whole phase before advancing")
    ap.add_argument("--phase", type=int, help="run until this phase is complete")
    ap.add_argument("--until", help="run through this step id (e.g. 2.5)")
    ap.add_argument("--steps", type=int, help="run at most N steps")
    ap.add_argument("--dry-run", action="store_true", help="show what would run")
    ap.add_argument("--builder", choices=AGENT_CHOICES, default="claude",
                    help="agent used to implement steps (default: claude)")
    ap.add_argument("--fixer", choices=AGENT_CHOICES, default="claude",
                    help="agent used to diagnose and repair failures (default: claude)")
    ap.add_argument("--coding-fallback", choices=[*AGENT_CHOICES, "none"], default="codex",
                    help="retry builder/fixer work with this agent when the selected agent "
                         "hits a credit or usage limit (default: codex)")
    ap.add_argument("--reviewer", choices=[*AGENT_CHOICES, "none"], default="codex",
                    help="agent used for adversarial review (default: codex)")
    ap.add_argument("--max-fix-attempts", type=int, default=3)
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-finish-notification", action="store_true",
                    help="do not beep or show the topmost completion dialog")
    ap.add_argument("--mark-done-through", metavar="STEP", help="mark all steps up to STEP as done")
    ap.add_argument("--sync-git", action="store_true", help="merge steps found in git log into done state")
    args = ap.parse_args()
    args.fallback_state = {"active": False}

    plan = parse_plan(PLAN_PATH.read_text(encoding="utf-8"))
    state = load_state()

    if args.sync_git or not state["done"]:
        found = steps_done_in_git(state.get("epoch", "")) & {s.id for s in plan.steps}
        state["done"] = sorted(set(state["done"]) | found,
                               key=lambda i: (int(i.split(".")[0]), int(i.split(".")[1])))
        save_state(state)

    if args.mark_done_through:
        limit = plan.step(args.mark_done_through)
        if not limit:
            sys.exit(f"Unknown step id: {args.mark_done_through}")
        state["done"] = sorted(
            {s.id for s in plan.steps if s.sort_key <= limit.sort_key} | set(state["done"]),
            key=lambda i: (int(i.split(".")[0]), int(i.split(".")[1])))
        save_state(state)
        print(f"Marked done through {limit.id}.")

    if args.by_phase and not (args.all or args.phase is not None or args.until):
        args.all = True  # --by-phase alone means: run everything, phase by phase

    if args.doctor:
        sys.exit(0 if run_doctor(plan, state) else 1)

    if args.status or not (args.all or args.phase is not None or args.until or args.steps):
        print_status(plan, state)
        return

    # An unattended run should never discover a missing venv or an unusable
    # agent an hour in. --dry-run skips it because it spends nothing anyway.
    if not args.dry_run and not args.skip_doctor and not run_doctor(plan, state):
        sys.exit("Refusing to start: the environment is not ready (see doctor above). "
                 "Re-run with --skip-doctor to override.")

    targets = pick_targets(plan, state, args)
    unfinished_reviews = unfinished_phase_baselines(state) if args.by_phase else {}
    target_phases = {s.phase for s in targets}
    if args.all:
        resume_phases = set(unfinished_reviews)
    elif args.phase is not None:
        resume_phases = {args.phase} & set(unfinished_reviews)
    elif args.until:
        until_step = plan.step(args.until)
        resume_phases = {p for p in unfinished_reviews if until_step and p <= until_step.phase}
    else:
        resume_phases = target_phases & set(unfinished_reviews)
    phase_numbers = sorted(target_phases | resume_phases)

    if not targets and not phase_numbers:
        print("Nothing to do — selected scope is already complete.")
        return

    if args.dry_run:
        print(f"Agents: builder={args.builder}, fixer={args.fixer}, "
              f"coding fallback={args.coding_fallback}, reviewer={args.reviewer}")
        if args.by_phase:
            print("Would run, phase by phase (build all steps, then one phase review):")
            for phase in phase_numbers:
                ids = ", ".join(s.id for s in targets if s.phase == phase) or "review resume only"
                print(f"  Phase {phase}: {ids}  → then {args.reviewer} phase review + smoke test")
        else:
            print("Would run, in order:")
            for step in targets:
                print(f"  {step.id}  {step.title}")
        return

    ensure_agents_available(args)

    run_started = time.monotonic()
    print("=" * 72)
    say(f"LOOP START — plan: {PLAN_PATH.relative_to(ROOT)}", icon="▶")
    scope = ", ".join(s.id for s in targets) or "unfinished phase review only"
    say(f"scope: {len(targets)} step(s) → {scope}")
    say(f"mode: {'phase-level cycles (build phase → review phase → advance)' if args.by_phase else 'step-level cycles'} · "
        f"builder: {args.builder} · fixer: {args.fixer} · reviewer: {args.reviewer} · "
        f"max fix attempts: {args.max_fix_attempts} · "
        f"push: {'off' if args.no_push else 'on'}")

    completed = []
    if args.by_phase:
        for phase in phase_numbers:
            phase_steps = [s for s in targets if s.phase == phase]
            if not run_phase(phase, phase_steps, plan, state, args,
                             resume_baseline=unfinished_reviews.get(phase)):
                duration = elapsed(run_started)
                say(f"LOOP STOPPED in phase {phase} after {duration} — "
                    f"completed before the halt: {', '.join(completed) or 'none'}", icon="✗")
                notify_loop_finished(
                    "Loop Engineering Stopped",
                    f"The engineering loop stopped in Phase {phase} after {duration}.\n\n"
                    f"Completed before the halt: {', '.join(completed) or 'none'}.",
                    enabled=not args.no_finish_notification,
                )
                sys.exit(1)
            completed.extend(s.id for s in phase_steps)
    else:
        say("each step runs: EXECUTE (builder agent) → VALIDATE (pytest/vitest/build) "
            "→ CORRECT while red → REVIEW (adversarial audit) → commit + record")
        for step in targets:
            if not run_step(step, state, args):
                duration = elapsed(run_started)
                say(f"LOOP STOPPED at step {step.id} after {duration} — "
                    f"{len(completed)} step(s) completed before the halt: "
                    f"{', '.join(completed) or 'none'}", icon="✗")
                notify_loop_finished(
                    "Loop Engineering Stopped",
                    f"The engineering loop stopped at Step {step.id} after {duration}.\n\n"
                    f"Completed before the halt: {', '.join(completed) or 'none'}.",
                    enabled=not args.no_finish_notification,
                )
                sys.exit(1)
            completed.append(step.id)

    print("\n" + "=" * 72)
    say(f"LOOP COMPLETE — {len(completed)} step(s) in {elapsed(run_started)}: "
        f"{', '.join(completed)}", icon="✓")
    say("last commits:")
    print(run_capture(["git", "log", "--oneline", "-8"]))
    notify_loop_finished(
        "Loop Engineering Complete",
        f"The engineering loop finished successfully.\n\n"
        f"Completed {len(completed)} step(s) in {elapsed(run_started)}:\n"
        f"{', '.join(completed)}",
        enabled=not args.no_finish_notification,
    )


if __name__ == "__main__":
    main()
