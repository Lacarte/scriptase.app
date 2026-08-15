"""Step 11.1 — the review node and the exposed quality-gate configuration.

Done when: `review.run` appears in the node catalogue with its config rendering
in the inspector, the three gate keys are settable from the UI, and saved
workflows migrate without manual edits.
"""

from __future__ import annotations

import os
import shutil
import unittest

from PIL import Image

from config import OUTPUT_DIR
from scriptase.engine.adapters import AdapterContext, AdapterError
from scriptase.engine.adapters import review as review_adapter
from scriptase.engine.migrations import migrate_workflow
from scriptase.engine.models import workflow_draft
from scriptase.engine.options import _RESOLVERS, _provider_options
from scriptase.engine.registry import (
    ASYNC_OPTION_SOURCES,
    all_node_types,
    get_node_type,
    serialize_registry,
)
from scriptase.engine.validation import validate_workflow
from scriptase.jobs.stage_projection import (
    PRIMARY_STAGE_BY_TYPE,
    node_type_is_provider_capable,
)
from scriptase.providers.domains import DOMAINS

GATE_KEYS = ("skip_quality_gate", "image_gate_max_repairs", "image_gate_semantic")

# Widgets ConfigField.vue can actually draw. A field outside this set renders
# "Unsupported field type" — which is the same as not being reachable.
RENDERABLE = {
    "string", "textarea", "number", "boolean", "options",
    "json", "media_asset", "provider", "provider_options",
}

# The gate rebases any absolute path onto OUTPUT_DIR (`resolve_managed_path`),
# so fixtures live under the managed root rather than a temp directory.
FIXTURE_REF = "storyboard/pm_REV111"
FIXTURE_ROOT = os.path.join(OUTPUT_DIR, *FIXTURE_REF.split("/"))


def _write_png(name: str, width: int, height: int) -> str:
    path = os.path.join(FIXTURE_ROOT, name)
    os.makedirs(FIXTURE_ROOT, exist_ok=True)
    Image.new("RGB", (width, height), (30, 60, 90)).save(path, format="PNG")
    return f"{FIXTURE_REF}/{name}"


def _write_garbage(name: str) -> str:
    path = os.path.join(FIXTURE_ROOT, name)
    os.makedirs(FIXTURE_ROOT, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"not-a-real-image-payload")
    return f"{FIXTURE_REF}/{name}"


def _workflow(nodes):
    document = workflow_draft(name="Review probe")
    document["workflow_id"] = "wf_RV1101"
    document["created_at"] = "2026-08-15T00:00:00Z"
    document["updated_at"] = "2026-08-15T00:00:00Z"
    document["nodes"] = nodes
    return document


def _node(node_id, type_key, configuration, *, type_version=None):
    definition = get_node_type(type_key)
    return {
        "id": node_id,
        "type": type_key,
        "type_version": definition["type_version"] if type_version is None else type_version,
        "name": definition["display_name"],
        "position": {"x": 0, "y": 0},
        "configuration": configuration,
        "disabled": False,
    }


def _errors(document):
    problems = validate_workflow(document)
    return [p for p in problems if p.get("severity", "error") == "error"]


# ---------------------------------------------------------------------------
# The node is in the catalogue and renders
# ---------------------------------------------------------------------------


class ReviewNodeRegistrationTests(unittest.TestCase):
    def test_review_run_is_registered(self):
        self.assertIn("review.run", all_node_types())
        definition = get_node_type("review.run")
        self.assertEqual(definition["type_version"], 1)
        self.assertEqual(
            definition["executor"], "scriptase.engine.adapters.review:run"
        )

    def test_review_run_reaches_the_orphaned_review_domain(self):
        """The sixth domain finally has a consumer."""
        definition = get_node_type("review.run")
        provider_fields = [
            field
            for field in definition["config_schema"]
            if field["type"] == "provider"
        ]
        self.assertEqual(len(provider_fields), 1)
        self.assertEqual(provider_fields[0]["provider_domain"], "review")
        self.assertEqual(
            provider_fields[0]["default"], DOMAINS["review"].default_provider
        )
        self.assertTrue(node_type_is_provider_capable("review.run"))

    def test_review_providers_option_source_is_allowlisted_and_resolvable(self):
        spec = ASYNC_OPTION_SOURCES["review_providers"]
        self.assertEqual(spec.domain, "review")
        self.assertEqual(spec.cache, "settings")
        # P32: the shared resolver serves the sixth domain with no new code.
        self.assertIs(_RESOLVERS["review_providers"], _provider_options)

    def test_every_config_field_has_a_renderer(self):
        for field in get_node_type("review.run")["config_schema"]:
            with self.subTest(field=field["name"]):
                self.assertIn(field["type"], RENDERABLE)
                self.assertIn("default", field)
                if field["type"] in ("options", "provider"):
                    self.assertTrue(
                        field.get("options") or field.get("options_source")
                    )

    def test_display_options_reference_declared_fields(self):
        definition = get_node_type("review.run")
        names = {field["name"] for field in definition["config_schema"]}
        for field in definition["config_schema"]:
            display = field.get("display_options") or {}
            for mode in ("show", "hide"):
                for reference in (display.get(mode) or {}):
                    self.assertIn(reference, names, field["name"])

    def test_review_run_lands_on_the_review_production_stage(self):
        self.assertEqual(PRIMARY_STAGE_BY_TYPE["review.run"], "review")

    def test_serialized_registry_exposes_the_node_without_internals(self):
        served = serialize_registry()["node_types"]["review.run"]
        self.assertEqual(served["type"], "review.run")
        self.assertNotIn("executor", served)
        self.assertNotIn("migrations", served)


# ---------------------------------------------------------------------------
# The gate keys are settable
# ---------------------------------------------------------------------------


class QualityGateConfigTests(unittest.TestCase):
    """Before 11.1 these keys were read by `gates.py` and declared nowhere, so
    save-time validation rejected every attempt to set one."""

    def test_the_video_node_declares_all_three_gate_keys(self):
        names = [f["name"] for f in get_node_type("animator.generate")["config_schema"]]
        for key in GATE_KEYS:
            self.assertIn(key, names)

    def test_setting_the_gate_keys_validates(self):
        document = _workflow([
            _node("n_video", "animator.generate", {
                "provider_id": "grok_automa",
                "skip_quality_gate": False,
                "image_gate_max_repairs": 3,
                "image_gate_semantic": True,
            }),
        ])
        self.assertEqual(_errors(document), [])

    def test_out_of_range_repair_count_is_rejected(self):
        document = _workflow([
            _node("n_video", "animator.generate", {"image_gate_max_repairs": 99}),
        ])
        problems = _errors(document)
        self.assertTrue(
            any("image_gate_max_repairs" in (p.get("path") or "") for p in problems),
            problems,
        )

    def test_a_non_integer_repair_count_is_rejected(self):
        document = _workflow([
            _node("n_video", "animator.generate", {"image_gate_max_repairs": 1.5}),
        ])
        self.assertTrue(_errors(document))

    def test_the_declared_defaults_match_what_the_gate_already_assumed(self):
        """Declaring a key must not change the behaviour of a saved workflow."""
        defaults = {
            f["name"]: f["default"]
            for f in get_node_type("animator.generate")["config_schema"]
        }
        # gates.py:712 — `cfg.get("skip_quality_gate") is True`
        self.assertIs(defaults["skip_quality_gate"], False)
        # gates.py:751 — `cfg.get("image_gate_max_repairs", 1)`
        self.assertEqual(defaults["image_gate_max_repairs"], 1)
        # gates.py:757 — `bool(cfg.get("image_gate_semantic", False))`
        self.assertIs(defaults["image_gate_semantic"], False)


# ---------------------------------------------------------------------------
# Saved workflows keep loading
# ---------------------------------------------------------------------------


class SavedWorkflowCompatibilityTests(unittest.TestCase):
    def test_the_visual_nodes_did_not_bump_type_version(self):
        """contracts §41.2: an additive optional key with a default is not a bump.

        A bump without a shipped `N → N+1` migration makes every saved workflow
        containing the node unloadable, and a bump *with* a no-op migration only
        invalidates the config fingerprint the fallback exists to preserve.
        """
        self.assertEqual(get_node_type("storyboard.generate")["type_version"], 2)
        self.assertEqual(get_node_type("animator.generate")["type_version"], 2)

    def test_a_saved_workflow_without_the_new_keys_migrates_untouched(self):
        saved = _workflow([
            _node("n_video", "animator.generate", {
                "provider_id": "grok_automa", "aspect_ratio": "9:16",
            }),
            _node("n_image", "storyboard.generate", {"provider_id": "gemini_ws"}),
        ])
        result = migrate_workflow(saved)
        self.assertEqual(result.trail, [])
        self.assertFalse(result.read_only)
        self.assertEqual(
            result.document["nodes"][0]["configuration"],
            {"provider_id": "grok_automa", "aspect_ratio": "9:16"},
        )
        self.assertEqual(_errors(result.document), [])

    def test_a_v1_animator_still_migrates_through_its_one_hop(self):
        saved = _workflow([
            _node("n_video", "animator.generate", {"provider": "grok"}, type_version=1),
        ])
        result = migrate_workflow(saved)
        self.assertEqual([hop["to_version"] for hop in result.trail], [2])
        configuration = result.document["nodes"][0]["configuration"]
        self.assertEqual(configuration["provider_id"], "grok_automa")
        self.assertNotIn("provider", configuration)

    def test_a_review_node_validates_with_only_its_defaults(self):
        document = _workflow([_node("n_review", "review.run", {})])
        self.assertEqual(_errors(document), [])


# ---------------------------------------------------------------------------
# The executor
# ---------------------------------------------------------------------------


class ReviewExecutorTests(unittest.TestCase):
    def setUp(self):
        self.context = AdapterContext(project_id="pm_REV111", node_id="n_review")

    def tearDown(self):
        shutil.rmtree(FIXTURE_ROOT, ignore_errors=True)

    def test_a_broken_still_produces_a_structured_blocking_issue(self):
        bad = _write_garbage("broken.png")
        result = review_adapter.run(
            {"images": {"scene_statuses": {"0": {
                "scene_id": "scn_BAD001", "artifact_ref": bad,
            }}}},
            {"subject": "images"},
            self.context,
        )

        payload = result["issues"]
        self.assertFalse(payload["clean"])
        self.assertGreaterEqual(payload["blocking_issue_count"], 1)
        self.assertEqual(payload["images_checked"], 1)
        self.assertEqual(payload["videos_checked"], 0)
        for issue in payload["issues"]:
            # Structured only — never free text (contracts §9).
            self.assertIsInstance(issue, dict)
            self.assertIn(issue["severity"], {"low", "medium", "high", "critical"})
            self.assertTrue(issue["issue_type"])
            self.assertEqual(issue["target_node_id"], "n_review")
            self.assertEqual(issue["scene_id"], "scn_BAD001")

    def test_a_good_still_is_clean(self):
        good = _write_png("good.png", 1080, 1920)
        result = review_adapter.run(
            {"images": {"scene_statuses": {"0": {
                "scene_id": "scn_OK0001", "artifact_ref": good,
            }}}},
            {"subject": "images", "aspect_ratio": "9:16"},
            self.context,
        )
        self.assertTrue(result["issues"]["clean"], result["issues"]["issues"])
        self.assertEqual(result["issues"]["issue_count"], 0)

    def test_a_wrong_aspect_ratio_is_caught(self):
        wide = _write_png("wide.png", 1920, 1080)
        result = review_adapter.run(
            {"images": {"scene_statuses": {"0": {"artifact_ref": wide}}}},
            {"subject": "images", "aspect_ratio": "9:16"},
            self.context,
        )
        self.assertIn(
            "aspect_ratio",
            [issue.get("check_id") for issue in result["issues"]["issues"]],
        )

    def test_no_absolute_path_reaches_the_issues_port(self):
        bad = _write_garbage("broken.png")
        result = review_adapter.run(
            {"images": {"scene_statuses": {"0": {"artifact_ref": bad}}}},
            {"subject": "images"},
            self.context,
        )
        self.assertTrue(result["issues"]["issues"])
        for issue in result["issues"]["issues"]:
            path_ref = issue.get("path_ref")
            if path_ref:
                self.assertFalse(os.path.isabs(path_ref), path_ref)
                self.assertNotIn(":", path_ref)

    def test_fail_on_blocking_raises_the_frozen_gate_code(self):
        bad = _write_garbage("broken.png")
        with self.assertRaises(AdapterError) as caught:
            review_adapter.run(
                {"images": {"scene_statuses": {"0": {"artifact_ref": bad}}}},
                {"subject": "images", "fail_on_blocking": True},
                self.context,
            )
        self.assertEqual(caught.exception.code, "QUALITY_GATE_FAILED")
        self.assertGreaterEqual(
            caught.exception.details["blocking_issue_count"], 1
        )

    def test_blocking_issues_pass_downstream_by_default(self):
        """Reporting is 11.1; deciding is 11.3."""
        bad = _write_garbage("broken.png")
        result = review_adapter.run(
            {"images": {"scene_statuses": {"0": {"artifact_ref": bad}}}},
            {"subject": "images"},
            self.context,
        )
        self.assertGreaterEqual(result["issues"]["blocking_issue_count"], 1)

    def test_subject_images_ignores_a_connected_animator_port(self):
        good = _write_png("good.png", 1080, 1920)
        result = review_adapter.run(
            {
                "images": {"scene_statuses": {"0": {"artifact_ref": good}}},
                "assets": {"artifact_refs": ["animator/pm_X/0/clip.mp4"]},
            },
            {"subject": "images", "aspect_ratio": "9:16"},
            self.context,
        )
        self.assertEqual(result["issues"]["videos_checked"], 0)

    def test_nothing_to_review_is_a_structured_failure(self):
        with self.assertRaises(AdapterError) as caught:
            review_adapter.run({}, {}, self.context)
        self.assertEqual(caught.exception.code, "MISSING_REQUIRED_INPUT")

    def test_the_technical_only_path_never_touches_the_provider_hub(self):
        """Semantic review is opt-in; the free path must stay free."""
        constructed = []

        class _Boom(review_adapter._SemanticPass):
            def __init__(self, *args, **kwargs):
                constructed.append(args)
                raise AssertionError("semantic pass must not be constructed")

        good = _write_png("good.png", 1080, 1920)
        original = review_adapter._SemanticPass
        review_adapter._SemanticPass = _Boom
        try:
            review_adapter.run(
                {"images": {"scene_statuses": {"0": {"artifact_ref": good}}}},
                {"subject": "images", "aspect_ratio": "9:16"},
                self.context,
            )
        finally:
            review_adapter._SemanticPass = original
        self.assertEqual(constructed, [])

    def test_semantic_findings_are_appended_to_the_technical_ones(self):
        calls = []

        class _Stub:
            def __init__(self, selected, config, context):
                calls.append(selected)

            def __call__(self, unit, *, subject_kind, job_id):
                return [{
                    "job_id": job_id,
                    "issue_type": "visual_mismatch",
                    "severity": "medium",
                    "confidence": 0.6,
                    "reason": "subject drifted from the prompt",
                    "suggested_action": "re-prompt",
                }]

        good = _write_png("good.png", 1080, 1920)
        original = review_adapter._SemanticPass
        review_adapter._SemanticPass = _Stub
        try:
            result = review_adapter.run(
                {"images": {"scene_statuses": {"0": {"artifact_ref": good}}}},
                {"subject": "images", "aspect_ratio": "9:16", "semantic": True},
                self.context,
            )
        finally:
            review_adapter._SemanticPass = original

        self.assertEqual(calls, [DOMAINS["review"].default_provider])
        payload = result["issues"]
        self.assertTrue(payload["semantic"])
        self.assertEqual(payload["issue_count"], 1)
        # Medium is not blocking, so the node still passes.
        self.assertEqual(payload["blocking_issue_count"], 0)

    def test_the_real_semantic_provider_dispatches_through_the_hub(self):
        """No stub: the shipped `semantic` package runs behind the boundary.

        `_SemanticPass` builds a ReviewRequest, a ProviderInvocation, and calls
        `boundary.invoke`, so this is the test that catches a signature drift in
        any of the three.
        """
        good = _write_png("good.png", 1080, 1920)
        result = review_adapter.run(
            {"images": {"scene_statuses": {"0": {
                "scene_id": "scn_SEM001",
                "artifact_ref": good,
                "image_prompt": "a quiet harbor at dusk",
                "caption": "harbor",
            }}}},
            {"subject": "images", "aspect_ratio": "9:16", "semantic": True},
            self.context,
        )
        payload = result["issues"]
        self.assertTrue(payload["semantic"])
        self.assertEqual(payload["units_checked"], 1)
        for issue in payload["issues"]:
            self.assertIsInstance(issue, dict)
            self.assertTrue(issue.get("reason"))
            self.assertIn(issue["severity"], {"low", "medium", "high", "critical"})


if __name__ == "__main__":
    unittest.main()
