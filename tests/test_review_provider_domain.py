"""Step 7.3 — Review provider domain.

Done when: a semantic reviewer returns structured issues through the standard
result envelope and error boundary, and adding it required no change outside
its own package and the domain catalogue.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scriptase.providers.boundary import invoke as boundary_invoke, wrap_exception
from scriptase.providers.domains import DOMAINS, SHARED_CAPABILITIES, get_domain
from scriptase.providers.errors import ProviderError
from scriptase.providers.hub import hub
from scriptase.providers.invocation import build_invocation
from scriptase.providers.results import (
    SUCCEEDED,
    ProviderResult,
    validate_egress,
)
from scriptase.review.models import assert_structured_review_result
from scriptase.review.providers.contract import (
    SUBJECT_CAPABILITY,
    ReviewRequest,
    ReviewResultPayload,
)
from scriptase.review.providers.semantic.provider import SemanticReviewProvider


REVIEW_CAPS = frozenset(
    {"image_review", "video_review", "text_review", "structured_output"}
)

# Surfaces that must remain untouched when a domain is added as data only.
# Adding `review` must not require edits here (framework redesign).
_FRAMEWORK_SURFACES = (
    "scriptase/providers/hub.py",
    "scriptase/providers/registry.py",
    "scriptase/providers/routes.py",
    "scriptase/providers/catalog.py",
    "scriptase/providers/settings_manager.py",
)


class ReviewDomainCatalogTests(unittest.TestCase):
    """Domain catalogue declares review with the step-7.3 vocabulary."""

    def test_review_is_in_catalog_with_required_capabilities(self):
        self.assertIn("review", DOMAINS)
        spec = DOMAINS["review"]
        self.assertEqual(spec.id, "review")
        self.assertEqual(spec.default_provider, "semantic")
        self.assertEqual(spec.package, "scriptase.review.providers")
        for cap in REVIEW_CAPS:
            self.assertIn(cap, spec.capability_vocabulary)
        for shared in SHARED_CAPABILITIES:
            self.assertIn(shared, spec.capability_vocabulary)

    def test_request_and_result_models_resolve(self):
        spec = get_domain("review")
        self.assertTrue(spec.request_model.endswith("ReviewRequest"))
        self.assertTrue(spec.result_model.endswith("ReviewResultPayload"))
        # Models import cleanly from the declared package paths.
        from scriptase.review.providers.contract import (  # noqa: F401
            ReviewRequest as RR,
            ReviewResultPayload as RP,
        )

        self.assertIs(RR, ReviewRequest)
        self.assertIs(RP, ReviewResultPayload)


class ReviewProviderDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hub.discover("review")

    def test_semantic_provider_is_discovered(self):
        instance = hub.get("review", "semantic")
        self.assertIsNotNone(instance)
        assert instance is not None
        self.assertEqual(instance.id, "semantic")
        self.assertEqual(instance.manifest.domain, "review")
        caps = set(instance.manifest.capabilities)
        self.assertTrue(REVIEW_CAPS.issubset(caps), caps)

    def test_catalog_includes_review_domain(self):
        catalog = hub.catalog()
        self.assertIn("review", catalog)
        ids = {row["id"] for row in catalog["review"]["providers"]}
        self.assertIn("semantic", ids)


class SemanticReviewerEnvelopeTests(unittest.TestCase):
    """Done-when: structured issues via ProviderResult + error boundary."""

    def setUp(self):
        self.provider = SemanticReviewProvider()
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_review_")
        self.output_dir = self.temp.name

    def tearDown(self):
        self.temp.cleanup()

    def _invocation(self, **options):
        return build_invocation(
            None,
            domain="review",
            provider_id="semantic",
            project_id="job_REV73A",
            output_dir=os.path.join(self.output_dir, "review", "job_REV73A"),
            settings={"min_text_words": 8, "confidence": 0.9},
            options=options,
        )

    def test_text_review_returns_structured_issues_in_envelope(self):
        request = ReviewRequest(
            job_id="job_REV73A",
            subject_kind="text",
            scene_id="scn_AAAAAA",
            target_node_id="node_script_1",
            text="TODO write the real narration later",
            expected_subject="ancient oak",
        )
        invocation = self._invocation()
        raw = self.provider.invoke(request, invocation)
        self.assertIsInstance(raw, ProviderResult)

        # Platform boundary stamps provenance and re-validates egress.
        result = boundary_invoke(
            lambda inv: self.provider.invoke(request, inv),
            invocation,
            provider_version="1.0.0",
            contract_version=2,
        )
        self.assertEqual(result.status, SUCCEEDED)
        self.assertEqual(result.domain, "review")
        self.assertEqual(result.provider_id, "semantic")
        self.assertEqual(result.provenance.domain, "review")

        leaks = validate_egress(result.to_dict())
        self.assertEqual(leaks, [])

        payload = result.payload
        self.assertIn("issues", payload)
        self.assertFalse(payload["clean"])
        self.assertGreater(payload["issue_count"], 0)
        self.assertEqual(payload["capability"], "text_review")

        structured = assert_structured_review_result(payload)
        self.assertTrue(structured)
        types = {item.issue_type for item in structured}
        self.assertIn("script_defect", types)
        # Free-text findings are forbidden.
        for item in structured:
            self.assertTrue(item.reason)
            self.assertIn(item.severity, ("low", "medium", "high", "critical"))
            self.assertGreaterEqual(item.confidence, 0.0)
            self.assertLessEqual(item.confidence, 1.0)

    def test_clean_text_returns_empty_issues_list(self):
        request = ReviewRequest(
            job_id="job_REV73A",
            subject_kind="text",
            text=(
                "Under the ancient oak the traveler paused, listening to the "
                "wind move through the branches before continuing south."
            ),
            expected_subject="ancient oak",
        )
        result = self.provider.invoke(request, self._invocation())
        self.assertIsInstance(result, ProviderResult)
        self.assertTrue(result.payload["clean"])
        self.assertEqual(result.payload["issue_count"], 0)
        self.assertEqual(result.payload["issues"], [])
        assert_structured_review_result(result.payload)

    def test_image_and_video_and_structured_capabilities(self):
        cases = [
            (
                ReviewRequest(
                    job_id="job_REV73A",
                    subject_kind="image",
                    artifact_ref="jobs/job_REV73A/scenes/scn_1/still.png",
                    image_prompt="a red sports car on a mountain road",
                    expected_subject="blue sedan",
                ),
                "image_review",
                "visual_mismatch",
            ),
            (
                ReviewRequest(
                    job_id="job_REV73A",
                    subject_kind="video",
                    artifact_ref="jobs/job_REV73A/scenes/scn_1/clip.mp4",
                    duration_s=12.0,
                    expected_duration_s=4.0,
                ),
                "video_review",
                "timing_drift",
            ),
            (
                ReviewRequest(
                    job_id="job_REV73A",
                    subject_kind="structured",
                    structured={"title": "ok"},
                    required_keys=["title", "scenes"],
                ),
                "structured_output",
                "policy_violation",
            ),
        ]
        for request, capability, expected_type in cases:
            with self.subTest(kind=request.subject_kind):
                self.assertEqual(SUBJECT_CAPABILITY[request.subject_kind], capability)
                result = self.provider.invoke(request, self._invocation())
                self.assertEqual(result.payload["capability"], capability)
                structured = assert_structured_review_result(result.payload)
                types = {item.issue_type for item in structured}
                self.assertIn(expected_type, types)

    def test_free_text_result_is_rejected_by_payload_schema(self):
        # Pydantic rejects a non-list `issues` first; assert_structured_review_result
        # rejects free-text list items and bare strings. Both paths forbid free text.
        with self.assertRaises((TypeError, Exception)):
            ReviewResultPayload.model_validate(
                {
                    "issues": "this is free text and must not be accepted",
                    "subject_kind": "text",
                    "capability": "text_review",
                }
            )
        with self.assertRaises(TypeError):
            assert_structured_review_result("free text review failed")
        with self.assertRaises(TypeError):
            assert_structured_review_result(
                {"issues": ["just a string finding", "another string"]}
            )

    def test_error_boundary_wraps_provider_exceptions(self):
        class BoomProvider(SemanticReviewProvider):
            def review(self, request, *, settings=None):
                raise RuntimeError("internal model traceback with /secret/path")

        provider = BoomProvider()
        invocation = self._invocation()
        with self.assertRaises(ProviderError) as ctx:
            boundary_invoke(
                lambda inv: provider.invoke(
                    ReviewRequest(job_id="job_REV73A", text="hello world enough words"),
                    inv,
                ),
                invocation,
            )
        err = ctx.exception
        self.assertIsInstance(err, ProviderError)
        # str(exc) must never leak into the safe message.
        self.assertNotIn("/secret/path", err.message)
        self.assertNotIn("traceback", err.message.lower())
        self.assertIn("review", err.message.lower())

    def test_wrap_exception_uses_review_generic_message(self):
        wrapped = wrap_exception(
            ValueError("raw details"),
            domain="review",
            provider_id="semantic",
        )
        self.assertIsInstance(wrapped, ProviderError)
        self.assertIn("review", wrapped.message.lower())
        self.assertNotIn("raw details", wrapped.message)


class NoFrameworkRedesignTests(unittest.TestCase):
    """Done-when: domain addition is data + own package, not framework edits.

    Hub / registry / routes / catalog / settings_manager must not grow
    review-specific branches. Discovery and defaults come from DOMAINS alone.
    """

    def test_framework_surfaces_have_no_review_special_cases(self):
        root = Path(__file__).resolve().parents[1]
        # Patterns that would indicate a hard-coded sixth-domain branch rather
        # than reading the catalog.
        forbidden = (
            'if domain == "review"',
            "if domain == 'review'",
            '== "review"',
            "== 'review'",
        )
        for relative in _FRAMEWORK_SURFACES:
            path = root / relative
            source = path.read_text(encoding="utf-8")
            for needle in forbidden:
                with self.subTest(file=relative, needle=needle):
                    self.assertNotIn(
                        needle,
                        source,
                        f"{relative} hard-codes review; domains must stay data-driven",
                    )

    def test_settings_defaults_include_review_from_catalog(self):
        from scriptase.providers import settings_manager

        defaults = settings_manager._default_settings()
        self.assertIn("review", defaults["domains"])
        block = defaults["domains"]["review"]
        self.assertEqual(block["selected_instance_id"], "semantic")
        self.assertIn("semantic", block["instances"])
        self.assertEqual(block["instances"]["semantic"]["type"], "semantic")

    def test_registry_valid_domains_tracks_catalog(self):
        from scriptase.providers.registry import ProviderRegistry

        self.assertEqual(ProviderRegistry.VALID_DOMAINS, frozenset(DOMAINS))
        self.assertIn("review", ProviderRegistry.VALID_DOMAINS)


class ReviewRequestValidationTests(unittest.TestCase):
    def test_absolute_artifact_ref_rejected(self):
        with self.assertRaises(Exception):
            ReviewRequest(
                job_id="job_REV73A",
                subject_kind="image",
                artifact_ref=r"D:\secrets\still.png",
            )

    def test_from_configuration_maps_aliases(self):
        req = ReviewRequest.from_configuration(
            {
                "project_id": "job_FROMCFG",
                "kind": "image",
                "ref": "jobs/x/still.png",
                "prompt": "a lighthouse at dusk",
                "subject": "lighthouse",
            }
        )
        self.assertEqual(req.job_id, "job_FROMCFG")
        self.assertEqual(req.subject_kind, "image")
        self.assertEqual(req.artifact_ref, "jobs/x/still.png")
        self.assertEqual(req.image_prompt, "a lighthouse at dusk")
        self.assertEqual(req.expected_subject, "lighthouse")


if __name__ == "__main__":
    unittest.main()
