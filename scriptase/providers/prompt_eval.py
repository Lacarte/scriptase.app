"""Prompt evaluation harness — step 5.4.

Scene Director (and later Review) are prompt-driven. A prompt change currently
has no regression signal beyond full exact-text golden equality, which is too
brittle for free-form image prompts.

This harness extends the ported provider golden-fixture machinery
(``tests/fixtures/providers/<domain>/<provider>/{request,raw_response,
expected_result}.json``) with structural expectations over:

  * recorded provider responses (replayed offline — no network, no credits)
  * offline deterministic planners (``plan_scene_specs_from_direction``)
  * prompt *builder* contracts (required instructional markers must still
    appear in the built system prompt)

Equality is structural (counts, roles, types, field presence, contract rules),
never exact-text match of free-form prompt wording.

Fixture layout (separate from the provider-boundary trio so §46 validation
stays untouched)::

    tests/fixtures/prompt_eval/
        <domain>/<case_id>/
            case.json                 # source descriptor
            expected_structure.json   # structural expectations

Run offline::

    venv/Scripts/python.exe -m scriptase.providers.prompt_eval --check
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from config import ROOT_DIR
from scriptase.modules.scene_director.providers.contract import (
    NARRATIVE_ROLES,
    SCENESPEC_FIELDS,
    SceneSpec,
    coerce_scene_specs,
)
from scriptase.providers import fixtures as provider_fixtures


PROMPT_EVAL_SCHEMA_VERSION = 1
PROMPT_EVAL_DIR = os.path.join(ROOT_DIR, "tests", "fixtures", "prompt_eval")

CASE_FILE = "case.json"
EXPECTED_STRUCTURE_FILE = "expected_structure.json"

SCENE_TYPES = frozenset({"image", "video", "text"})

# Instructional markers the Scene Director system prompt must retain. Removing
# any of these is a prompt regression the harness catches offline without
# spending provider credits.
SCENE_DIRECTOR_PROMPT_MARKERS: tuple[str, ...] = (
    "You are a visual scene planner and prompt writer",
    "Return exactly ONE scene for every input segment",
    "Match each input index exactly",
    "First and last scenes must NOT be text",
    "narrative_role:",
    "type_of_scene:",
    "image_prompt:",
    "Return ONLY valid JSON. No markdown. No code fences",
    "No two consecutive scenes may use the same shot type",
)


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Drift:
    """One structural mismatch between expected and actual."""

    path: str
    message: str
    expected: Any = None
    actual: Any = None

    def format(self) -> str:
        parts = [f"{self.path}: {self.message}"]
        if self.expected is not None or self.actual is not None:
            parts.append(f"  expected={self.expected!r}")
            parts.append(f"  actual  ={self.actual!r}")
        return "\n".join(parts)


@dataclass
class EvalReport:
    """Result of evaluating one case or one contract suite."""

    case_id: str
    domain: str
    drifts: list[Drift] = field(default_factory=list)
    source_kind: str = ""
    credits_spent: int = 0  # always 0 — harness is offline-only

    @property
    def ok(self) -> bool:
        return not self.drifts

    def summary(self) -> str:
        status = "PASS" if self.ok else f"FAIL ({len(self.drifts)} drift(s))"
        return f"[{status}] {self.domain}/{self.case_id}"


# ---------------------------------------------------------------------------
# Structure extraction
# ---------------------------------------------------------------------------


def _scenes_from_payload(payload: Any) -> list[SceneSpec]:
    """Pull scenes out of a raw webhook body, result envelope, or scene list."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return coerce_scene_specs(payload)
    if not isinstance(payload, Mapping):
        return []
    if "payload" in payload and isinstance(payload.get("payload"), Mapping):
        inner = payload["payload"]
        if "scenes" in inner:
            return coerce_scene_specs(inner.get("scenes") or [])
    if "scenes" in payload:
        return coerce_scene_specs(payload.get("scenes") or [])
    return []


def extract_scene_structure(payload: Any) -> dict[str, Any]:
    """Project scenes into the structural axes the harness compares.

    Free-form ``image_prompt`` text is reduced to presence/emptiness — never
    carried as a string for equality checks.
    """
    scenes = _scenes_from_payload(payload)
    roles: list[str] = []
    types: list[str] = []
    indexes: list[int] = []
    nonempty_prompts: list[bool] = []
    fields_present: list[list[str]] = []

    for scene in scenes:
        dumped = scene.model_dump()
        roles.append((scene.narrative_role or "").strip().lower())
        types.append((scene.type_of_scene or "").strip().lower())
        indexes.append(int(scene.index))
        nonempty_prompts.append(bool((scene.image_prompt or "").strip()))
        present = [
            name
            for name in SCENESPEC_FIELDS
            if _field_present(dumped.get(name))
        ]
        # Also track presentation fields the prompt contract requires.
        for name in ("index", "type_of_scene", "title"):
            if name not in present and _field_present(dumped.get(name)):
                present.append(name)
        fields_present.append(present)

    return {
        "scene_count": len(scenes),
        "roles": roles,
        "types": types,
        "indexes": indexes,
        "nonempty_prompts": nonempty_prompts,
        "fields_present": fields_present,
        "first_type": types[0] if types else "",
        "last_type": types[-1] if types else "",
    }


def _field_present(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return True
    return bool(value)


# ---------------------------------------------------------------------------
# Structural comparison
# ---------------------------------------------------------------------------


def compare_structure(
    actual: Mapping[str, Any] | Any,
    expected: Mapping[str, Any],
    *,
    path: str = "",
) -> list[Drift]:
    """Compare structural axes. Exact free-form prompt text is never required.

    ``expected`` keys that are present are checked; absent keys are ignored so
    a case can pin only the axes it cares about. The optional ``rules`` object
    enables contract checks that do not need a frozen expected value.
    """
    if not isinstance(expected, Mapping):
        return [Drift(path or "<root>", "expected structure must be an object",
                      expected=type(expected).__name__)]

    actual_struct = (
        extract_scene_structure(actual)
        if not _looks_like_structure(actual)
        else dict(actual)
    )
    drifts: list[Drift] = []
    prefix = path or "structure"

    for key in ("scene_count", "roles", "types", "indexes"):
        if key not in expected:
            continue
        want = expected[key]
        got = actual_struct.get(key)
        if want != got:
            drifts.append(Drift(
                f"{prefix}.{key}",
                "structural mismatch",
                expected=want,
                actual=got,
            ))

    rules = expected.get("rules") or {}
    if isinstance(rules, Mapping):
        drifts.extend(_apply_rules(actual_struct, rules, prefix=prefix))

    return drifts


def _looks_like_structure(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and "scene_count" in value
        and "roles" in value
    )


def _apply_rules(
    actual: Mapping[str, Any],
    rules: Mapping[str, Any],
    *,
    prefix: str,
) -> list[Drift]:
    drifts: list[Drift] = []
    count = int(actual.get("scene_count") or 0)
    roles = list(actual.get("roles") or [])
    types = list(actual.get("types") or [])
    indexes = list(actual.get("indexes") or [])
    nonempty = list(actual.get("nonempty_prompts") or [])
    fields_present = list(actual.get("fields_present") or [])

    if rules.get("indexes_dense_from_zero"):
        want = list(range(count))
        if indexes != want:
            drifts.append(Drift(
                f"{prefix}.rules.indexes_dense_from_zero",
                "indexes must be 0..n-1 in order",
                expected=want,
                actual=indexes,
            ))

    if rules.get("first_not_text") and types:
        if types[0] == "text":
            drifts.append(Drift(
                f"{prefix}.rules.first_not_text",
                "first scene must not be type_of_scene=text",
                expected="not text",
                actual=types[0],
            ))

    if rules.get("last_not_text") and types:
        if types[-1] == "text":
            drifts.append(Drift(
                f"{prefix}.rules.last_not_text",
                "last scene must not be type_of_scene=text",
                expected="not text",
                actual=types[-1],
            ))

    if rules.get("roles_in_vocabulary"):
        for i, role in enumerate(roles):
            if role and role not in NARRATIVE_ROLES:
                drifts.append(Drift(
                    f"{prefix}.roles[{i}]",
                    "narrative_role outside vocabulary",
                    expected=sorted(NARRATIVE_ROLES),
                    actual=role,
                ))

    if rules.get("types_in_vocabulary"):
        for i, scene_type in enumerate(types):
            if scene_type and scene_type not in SCENE_TYPES:
                drifts.append(Drift(
                    f"{prefix}.types[{i}]",
                    "type_of_scene outside vocabulary",
                    expected=sorted(SCENE_TYPES),
                    actual=scene_type,
                ))

    if rules.get("nonempty_image_prompt"):
        for i, ok in enumerate(nonempty):
            if not ok:
                drifts.append(Drift(
                    f"{prefix}.scenes[{i}].image_prompt",
                    "image_prompt must be non-empty",
                    expected="non-empty string",
                    actual="",
                ))

    required = rules.get("required_fields") or []
    if required:
        required_list = [str(x) for x in required]
        for i, present in enumerate(fields_present):
            missing = [f for f in required_list if f not in present]
            # index is always present on SceneSpec (defaults to 0); treat as ok
            # when the scene exists.
            if "index" in missing and count > 0:
                missing = [f for f in missing if f != "index"]
            if missing:
                drifts.append(Drift(
                    f"{prefix}.scenes[{i}].fields",
                    "required structural fields missing or empty",
                    expected=required_list,
                    actual=present,
                ))

    min_count = rules.get("min_scene_count")
    if min_count is not None and count < int(min_count):
        drifts.append(Drift(
            f"{prefix}.rules.min_scene_count",
            "too few scenes",
            expected=f">= {min_count}",
            actual=count,
        ))

    max_count = rules.get("max_scene_count")
    if max_count is not None and count > int(max_count):
        drifts.append(Drift(
            f"{prefix}.rules.max_scene_count",
            "too many scenes",
            expected=f"<= {max_count}",
            actual=count,
        ))

    must_include_roles = rules.get("must_include_roles") or []
    if must_include_roles:
        role_set = set(roles)
        for role in must_include_roles:
            if str(role).lower() not in role_set:
                drifts.append(Drift(
                    f"{prefix}.rules.must_include_roles",
                    f"missing required narrative_role {role!r}",
                    expected=list(must_include_roles),
                    actual=roles,
                ))

    return drifts


# ---------------------------------------------------------------------------
# Case loading and evaluation
# ---------------------------------------------------------------------------


def prompt_eval_root(root: str | None = None) -> str:
    return os.path.abspath(root or PROMPT_EVAL_DIR)


def list_cases(root: str | None = None) -> list[tuple[str, str]]:
    """Every ``(domain, case_id)`` under the prompt-eval fixture tree."""
    base = prompt_eval_root(root)
    found: list[tuple[str, str]] = []
    if not os.path.isdir(base):
        return found
    for domain in sorted(os.listdir(base)):
        domain_dir = os.path.join(base, domain)
        if not os.path.isdir(domain_dir) or domain.startswith((".", "_")):
            continue
        for case_id in sorted(os.listdir(domain_dir)):
            case_dir = os.path.join(domain_dir, case_id)
            if not os.path.isdir(case_dir):
                continue
            if os.path.isfile(os.path.join(case_dir, CASE_FILE)):
                found.append((domain, case_id))
    return found


def case_dir(domain: str, case_id: str, *, root: str | None = None) -> str:
    return os.path.join(prompt_eval_root(root), domain, case_id)


def load_case(domain: str, case_id: str, *, root: str | None = None) -> dict[str, Any]:
    path = os.path.join(case_dir(domain, case_id, root=root), CASE_FILE)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{domain}/{case_id}: case.json must be an object")
    return data


def load_expected_structure(
    domain: str, case_id: str, *, root: str | None = None
) -> dict[str, Any]:
    path = os.path.join(
        case_dir(domain, case_id, root=root), EXPECTED_STRUCTURE_FILE
    )
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(
            f"{domain}/{case_id}: expected_structure.json must be an object"
        )
    return data


def resolve_payload(case: Mapping[str, Any]) -> Any:
    """Materialise the offline payload a case evaluates.

    Sources:
      * ``provider_fixture`` — load recorded ``raw_response.json`` (and
        optionally ``expected_result.json``) from the golden-fixture tree
      * ``inline`` — scenes embedded in the case file
      * ``offline_planner`` — run the deterministic Channel-direction planner
    """
    source = case.get("source") or {}
    if not isinstance(source, Mapping):
        raise ValueError("case.source must be an object")
    kind = str(source.get("kind") or "").strip()

    if kind == "provider_fixture":
        domain = str(source.get("domain") or case.get("domain") or "")
        provider_id = str(source.get("provider_id") or "")
        which = str(source.get("file") or "raw_response.json")
        if which not in provider_fixtures.FIXTURE_FILES:
            # Allow expected_result / raw_response only.
            raise ValueError(
                f"provider_fixture file must be one of {provider_fixtures.FIXTURE_FILES}"
            )
        return provider_fixtures.load_fixture(domain, provider_id, which)

    if kind == "inline":
        if "scenes" in source:
            return {"scenes": source["scenes"]}
        if "payload" in source:
            return source["payload"]
        raise ValueError("inline source requires scenes or payload")

    if kind == "offline_planner":
        return _run_offline_planner(source)

    raise ValueError(
        f"unknown case.source.kind {kind!r}; "
        "expected provider_fixture | inline | offline_planner"
    )


def _run_offline_planner(source: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic, credential-free SceneSpec generation for a script."""
    from scriptase.modules.scene_director.visual_direction import (
        plan_scene_specs_from_direction,
    )

    segments = list(source.get("segments") or [])
    direction = source.get("visual_direction") or {}
    script = str(source.get("script") or "")
    style = str(
        source.get("style")
        or (direction.get("style") if isinstance(direction, Mapping) else "")
        or "cinematic"
    )
    specs = plan_scene_specs_from_direction(
        segments,
        direction,
        script=script,
        style_spec={"identity": {"render_mode": style}},
    )
    # Provider-owned minimal wording so image_prompt presence rules hold.
    # Lives here only as harness scaffolding for the offline planner path —
    # production providers own their own wording packages.
    scenes: list[dict[str, Any]] = []
    for i, spec in enumerate(specs):
        row = spec.model_dump()
        if not (row.get("image_prompt") or "").strip():
            shot = (row.get("camera") or "medium").strip() or "medium"
            words = (row.get("narration") or "")[:80]
            row["image_prompt"] = f"{shot}, offline planner scene of: {words}, {style}"
        if not (row.get("type_of_scene") or "").strip():
            # Mirror the prompt rule: first/last are not text; middle may vary.
            n = len(specs)
            if i == 0 or i == n - 1:
                row["type_of_scene"] = "video"
            elif (row.get("narrative_role") or "").lower() == "text_accent":
                row["type_of_scene"] = "text"
            else:
                row["type_of_scene"] = "video"
        scenes.append(row)
    return {"scenes": scenes}


def evaluate_case(
    domain: str,
    case_id: str,
    *,
    root: str | None = None,
) -> EvalReport:
    """Evaluate one prompt-eval case offline. Never spends provider credits."""
    case = load_case(domain, case_id, root=root)
    expected = load_expected_structure(domain, case_id, root=root)
    source = case.get("source") or {}
    kind = str(source.get("kind") or "") if isinstance(source, Mapping) else ""
    report = EvalReport(
        case_id=case_id,
        domain=str(case.get("domain") or domain),
        source_kind=kind,
        credits_spent=0,
    )
    try:
        payload = resolve_payload({**case, "domain": domain})
    except Exception as exc:  # noqa: BLE001 — surface as structural drift
        report.drifts.append(Drift(
            "source",
            f"failed to resolve offline payload: {exc}",
        ))
        return report
    report.drifts.extend(compare_structure(payload, expected))
    return report


def evaluate_all(*, root: str | None = None) -> list[EvalReport]:
    """Evaluate every committed prompt-eval case plus prompt-builder contracts."""
    reports = [
        evaluate_case(domain, case_id, root=root)
        for domain, case_id in list_cases(root)
    ]
    reports.append(evaluate_prompt_contracts())
    return reports


# ---------------------------------------------------------------------------
# Prompt-builder contracts (instructional marker presence)
# ---------------------------------------------------------------------------


def build_sample_scene_director_prompt() -> str:
    """Build a representative system prompt offline with tiny synthetic inputs."""
    from scriptase.modules.scene_director.providers.prompts import (
        build_scene_system_prompt,
    )

    style_spec = {
        "identity": {"id": "cinematic", "label": "Cinematic", "render_mode": "cinematic"},
        "camera_grammar": {"hook": ["wide"], "peak": ["close-up"]},
    }
    visual_bible = {
        "core_theme_hint": "recognition",
        "world_anchor": "corridor of repeating symbols",
        "anchor_subject": "solitary figure",
        "palette_guardrails": ["cool", "charcoal"],
        "tone_arc": "unease to doubt",
    }
    blueprints = [
        {
            "index": 0,
            "narrative_role": "hook",
            "preferred_scene_type": "video",
            "target_shot_type": "wide",
            "camera_move": "slow push-in",
        },
        {
            "index": 1,
            "narrative_role": "peak",
            "preferred_scene_type": "video",
            "target_shot_type": "close-up",
            "camera_move": "static",
        },
    ]
    return build_scene_system_prompt(
        style_spec,
        visual_bible,
        blueprints,
        plan_summary={"scene_count": 2},
    )


def evaluate_prompt_contracts(
    *,
    prompt_text: str | None = None,
    markers: Sequence[str] | None = None,
) -> EvalReport:
    """Assert the Scene Director system prompt still carries its contracts.

    A deliberate deletion of a required instructional marker is a prompt
    regression and fails this check offline.
    """
    report = EvalReport(
        case_id="prompt_contract",
        domain="scene_director",
        source_kind="prompt_builder",
        credits_spent=0,
    )
    text = prompt_text if prompt_text is not None else build_sample_scene_director_prompt()
    required = list(markers if markers is not None else SCENE_DIRECTOR_PROMPT_MARKERS)
    for marker in required:
        if marker not in text:
            report.drifts.append(Drift(
                "prompt.markers",
                "required instructional marker missing from system prompt",
                expected=marker,
                actual="(absent)",
            ))
    return report


# ---------------------------------------------------------------------------
# Validation / CLI
# ---------------------------------------------------------------------------


def validate_prompt_eval_fixtures(root: str | None = None) -> list[str]:
    """Sanity-check the prompt-eval fixture tree. Empty list == healthy."""
    base = prompt_eval_root(root)
    problems: list[str] = []
    if not os.path.isdir(base):
        return [f"{base} does not exist"]

    cases = list_cases(base)
    if not cases:
        problems.append("no prompt-eval cases found")
    for domain, case_id in cases:
        directory = case_dir(domain, case_id, root=base)
        for name in (CASE_FILE, EXPECTED_STRUCTURE_FILE):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                problems.append(f"{domain}/{case_id}: {name} is missing")
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{domain}/{case_id}/{name}: {exc}")
                continue
            sanitation = provider_fixtures.validate_sanitation(payload)
            problems.extend(
                f"{domain}/{case_id}/{name}: {item}" for item in sanitation
            )
        # Case must resolve offline without credits.
        try:
            case = load_case(domain, case_id, root=base)
            resolve_payload({**case, "domain": domain})
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{domain}/{case_id}: cannot resolve offline: {exc}")
    return problems


def check(*, root: str | None = None) -> int:
    """Run the full harness. Return process exit code (0 = green)."""
    fixture_problems = validate_prompt_eval_fixtures(root)
    for problem in fixture_problems:
        print(f"FIXTURE: {problem}")
    reports = evaluate_all(root=root)
    failed = 0
    for report in reports:
        print(report.summary())
        if report.credits_spent != 0:
            print(f"  ERROR: harness spent {report.credits_spent} credits (must be 0)")
            failed += 1
        for drift in report.drifts:
            print(f"  {drift.format()}")
            failed += 1
    if fixture_problems:
        failed += len(fixture_problems)
    if failed:
        print(f"prompt-eval: {failed} problem(s)")
        return 1
    print(f"prompt-eval: {len(reports)} check(s) clean (0 credits)")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scriptase prompt evaluation harness (step 5.4)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="evaluate all cases and prompt contracts offline",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="override the prompt-eval fixture root",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    # Default (and only) action is --check so `python -m ...` is useful bare.
    return check(root=args.root)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_FILE",
    "EXPECTED_STRUCTURE_FILE",
    "PROMPT_EVAL_DIR",
    "PROMPT_EVAL_SCHEMA_VERSION",
    "SCENE_DIRECTOR_PROMPT_MARKERS",
    "Drift",
    "EvalReport",
    "build_sample_scene_director_prompt",
    "case_dir",
    "check",
    "compare_structure",
    "evaluate_all",
    "evaluate_case",
    "evaluate_prompt_contracts",
    "extract_scene_structure",
    "list_cases",
    "load_case",
    "load_expected_structure",
    "main",
    "prompt_eval_root",
    "resolve_payload",
    "validate_prompt_eval_fixtures",
]
