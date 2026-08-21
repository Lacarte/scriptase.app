"""Step 16.2 — the `script.analyze` node and the `viral` provider domain.

Done when: the node runs inside the Full Video graph and emits a typed result
that the Composer path ignores and Review can read.

Those three clauses map onto ``FullVideoGraphTests`` (it is in the template and
schedules), ``ComposerIsolationTests`` (nothing downstream consumes it, and it
cannot strand the export), and ``TypedResultTests`` (the payload round-trips
through the frozen 16.1 ``ViralScore``).
"""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scriptase.engine.adapters import viral as viral_adapter
from scriptase.engine.adapters.common import AdapterContext, AdapterError
from scriptase.engine.models import workflow_draft
from scriptase.engine.registry import (
    ASYNC_OPTION_SOURCES,
    all_node_types,
    get_node_type,
    serialize_registry,
)
from scriptase.engine.scheduler import WorkflowScheduler, deterministic_order
from scriptase.engine.templates import full_video_template, serialize_templates
from scriptase.engine.validation import validate_workflow, validation_errors
from scriptase.jobs.stage_projection import (
    PRIMARY_STAGE_BY_TYPE,
    assign_nodes_to_stages,
    node_type_is_provider_capable,
)
from scriptase.modules.viral.models import DIMENSION_IDS, ViralScore
from scriptase.modules.viral.providers.contract import (
    ViralRequest,
    ViralResultPayload,
)
from scriptase.modules.viral.providers.deterministic.provider import (
    DeterministicViralProvider,
)
from scriptase.providers.boundary import invoke as boundary_invoke
from scriptase.providers.domains import DOMAINS, SHARED_CAPABILITIES, get_domain
from scriptase.providers.hub import hub
from scriptase.providers.invocation import build_invocation
from scriptase.providers.results import SUCCEEDED, ProviderResult, validate_egress

NODE = "script.analyze"
DOMAIN = "viral"

VIRAL_CAPS = frozenset({"script_scoring", "dimension_breakdown", "offline"})

# A script with all four mandated sections, an archetype opening, an open loop,
# and a real CTA. Paired with WEAK below to prove the score separates.
STRONG_SECTIONS = {
    "hook": "Did you know the strongest bridge ever built was designed by someone who had never seen one?",
    "build": (
        "He worked from letters alone, drawing what he imagined from second-hand "
        "description. Every engineer who reviewed the plans said the span could "
        "not hold. They were wrong, and the reason why is stranger than the "
        "design itself. The material he chose had never been tested at that "
        "scale, so nobody had the data to say it would fail."
    ),
    "climax": (
        "When the first load rolled across, the deck did not flex at all. The "
        "reviewers had modelled the wrong failure entirely."
    ),
    "cta": "Follow for the story of the letter that started it.",
}

WEAK_TEXT = "This is a video. It is about a thing. The thing happened. Okay."


def _node(node_id: str, type_key: str, configuration: dict | None = None) -> dict:
    definition = get_node_type(type_key)
    resolved = {
        field["name"]: field.get("default") for field in definition["config_schema"]
    }
    resolved.update(configuration or {})
    return {
        "id": node_id,
        "type": type_key,
        "type_version": definition["type_version"],
        "name": definition["display_name"],
        "position": {"x": 0, "y": 0},
        "configuration": resolved,
        "disabled": False,
    }


def _context(**kwargs) -> AdapterContext:
    base = {"project_id": "pm_VIR162", "node_id": "n_analyze", "job_id": "job_VIR162"}
    base.update(kwargs)
    return AdapterContext(**base)


# ---------------------------------------------------------------------------
# Domain catalog and provider package
# ---------------------------------------------------------------------------


class ViralDomainCatalogTests(unittest.TestCase):
    """The seventh domain is declared as data, exactly like the sixth."""

    def test_viral_is_in_catalog_with_its_vocabulary(self):
        self.assertIn(DOMAIN, DOMAINS)
        spec = DOMAINS[DOMAIN]
        self.assertEqual(spec.default_provider, "deterministic")
        self.assertEqual(spec.package, "scriptase.modules.viral.providers")
        for cap in VIRAL_CAPS:
            self.assertIn(cap, spec.capability_vocabulary)
        for shared in SHARED_CAPABILITIES:
            self.assertIn(shared, spec.capability_vocabulary)

    def test_request_and_result_models_resolve(self):
        spec = get_domain(DOMAIN)
        self.assertTrue(spec.request_model.endswith("ViralRequest"))
        self.assertTrue(spec.result_model.endswith("ViralResultPayload"))

    def test_the_result_model_is_the_frozen_score_itself(self):
        # 16.1 froze ViralScore as the node contract precisely so the arithmetic
        # could be replaced without a schema change. A second, parallel result
        # model would be the drift that decision exists to prevent.
        self.assertIs(ViralResultPayload, ViralScore)

    def test_the_option_source_follows_the_domain(self):
        # P32's promise: a new domain is a spec entry, not a new resolver.
        self.assertIn("viral_providers", ASYNC_OPTION_SOURCES)
        self.assertEqual(ASYNC_OPTION_SOURCES["viral_providers"].domain, DOMAIN)

    def test_settings_defaults_include_viral_from_the_catalog(self):
        from scriptase.providers import settings_manager

        block = settings_manager._default_settings()["domains"][DOMAIN]
        self.assertEqual(block["selected_instance_id"], "deterministic")
        self.assertEqual(block["instances"]["deterministic"]["type"], "deterministic")

    def test_a_settings_file_stamped_before_the_domain_existed_is_backfilled(self):
        """The v8→v9 case: v8 never re-runs, so the block would stay missing."""
        from scriptase.providers.settings_migrations import (
            SETTINGS_VERSION,
            apply_migrations,
        )

        stored = {
            "version": 8,
            "domains": {
                "script": {
                    "selected_instance_id": "gemini",
                    "instances": {"gemini": {"type": "gemini", "label": "g", "settings": {}}},
                }
            },
        }
        migrated, changed = apply_migrations(stored, {})
        self.assertTrue(changed)
        self.assertEqual(migrated["version"], SETTINGS_VERSION)
        self.assertEqual(
            migrated["domains"][DOMAIN]["selected_instance_id"], "deterministic"
        )
        # Step 7.1 restored the script catalogue; v11 backfills when needed and
        # v16 renames the id gemini -> script_n8n.
        self.assertEqual(migrated["domains"]["script"]["selected_instance_id"], "script_n8n")


class DeterministicProviderTests(unittest.TestCase):
    """Discovery, the v2 envelope, and the error boundary."""

    @classmethod
    def setUpClass(cls):
        hub.discover(DOMAIN)

    def setUp(self):
        self.provider = DeterministicViralProvider()
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_viral_")

    def tearDown(self):
        self.temp.cleanup()

    def _invocation(self, **options):
        return build_invocation(
            None,
            domain=DOMAIN,
            provider_id="deterministic",
            project_id="job_VIR162",
            output_dir=self.temp.name,
            settings={},
            options=options,
        )

    def test_the_default_provider_is_discovered(self):
        instance = hub.get(DOMAIN, "deterministic")
        self.assertIsNotNone(instance)
        assert instance is not None
        self.assertEqual(instance.manifest.domain, DOMAIN)
        self.assertTrue(VIRAL_CAPS.issubset(set(instance.manifest.capabilities)))

    def test_scoring_travels_through_the_standard_envelope(self):
        request = ViralRequest(
            job_id="job_VIR162", sections=STRONG_SECTIONS, target_duration=45
        )
        invocation = self._invocation()
        raw = self.provider.invoke(request, invocation)
        self.assertIsInstance(raw, ProviderResult)

        result = boundary_invoke(
            lambda inv: self.provider.invoke(request, inv),
            invocation,
            provider_version="1.0.0",
            contract_version=2,
        )
        self.assertEqual(result.status, SUCCEEDED)
        self.assertEqual(result.domain, DOMAIN)
        self.assertEqual(result.provenance.domain, DOMAIN)
        self.assertEqual(validate_egress(result.to_dict()), [])
        self.assertEqual(
            [d["id"] for d in result.payload["dimensions"]], list(DIMENSION_IDS)
        )

    def test_a_strong_and_a_weak_script_stay_separated_through_the_node_path(self):
        strong = self.provider.score(
            ViralRequest(job_id="j", sections=STRONG_SECTIONS, target_duration=45)
        )
        weak = self.provider.score(
            ViralRequest(job_id="j", story_text=WEAK_TEXT, target_duration=45)
        )
        self.assertGreater(strong.score, weak.score + 20, (strong.score, weak.score))

    def test_identical_input_scores_identically(self):
        request = ViralRequest(job_id="j", sections=STRONG_SECTIONS)
        first = self.provider.score(request).model_dump()
        second = self.provider.score(request).model_dump()
        self.assertEqual(first, second)

    def test_the_error_boundary_wraps_a_broken_scorer(self):
        from scriptase.providers.errors import ProviderError

        class BoomProvider(DeterministicViralProvider):
            def score(self, request, *, settings=None):
                raise RuntimeError("internal traceback with /secret/path")

        with self.assertRaises(ProviderError) as ctx:
            boundary_invoke(
                lambda inv: BoomProvider().invoke(
                    ViralRequest(job_id="j", story_text=WEAK_TEXT), inv
                ),
                self._invocation(),
            )
        self.assertNotIn("/secret/path", ctx.exception.message)


class ViralRequestValidationTests(unittest.TestCase):
    def test_unknown_sections_are_dropped_not_scored(self):
        request = ViralRequest(
            job_id="j", sections={"hook": "a hook", "outro": "not a section"}
        )
        self.assertEqual(set(request.sections), {"hook"})

    def test_an_absurd_duration_is_clamped_rather_than_rejected(self):
        # A Channel asking for a 20-minute script is a scoring input, not a
        # validation failure — the node must never block a run.
        self.assertEqual(ViralRequest(job_id="j", target_duration=99999).target_duration, 600)
        self.assertEqual(ViralRequest(job_id="j", target_duration=1).target_duration, 5)

    def test_an_empty_request_reports_that_it_has_nothing_to_score(self):
        self.assertFalse(ViralRequest(job_id="j").has_content)


# ---------------------------------------------------------------------------
# The node
# ---------------------------------------------------------------------------


class NodeRegistrationTests(unittest.TestCase):
    def test_the_node_is_registered_at_v1(self):
        self.assertIn(NODE, all_node_types())
        self.assertEqual(get_node_type(NODE)["type_version"], 1)

    def test_only_the_script_port_is_required(self):
        definition = get_node_type(NODE)
        required = {p["id"] for p in definition["inputs"] if p.get("required")}
        self.assertEqual(required, {"script"})
        # `story` and `scenes` exist so a graph that has them scores better;
        # needing either would defeat running before the expensive stages.
        self.assertLessEqual(
            {"story", "scenes"}, {p["id"] for p in definition["inputs"]}
        )

    def test_it_emits_exactly_one_data_port(self):
        outputs = {p["id"]: p["type"] for p in get_node_type(NODE)["outputs"]}
        # `error` is normalized on by the registry for every node carrying the
        # `error_output` capability; the analyzer contributes one data port.
        data_ports = {k: v for k, v in outputs.items() if v != "control"}
        self.assertEqual(data_ports, {"score": "generic_json"})

    def test_it_is_provider_capable_against_the_viral_domain(self):
        self.assertTrue(node_type_is_provider_capable(NODE))
        provider_field = next(
            f for f in get_node_type(NODE)["config_schema"] if f["name"] == "provider_id"
        )
        self.assertEqual(provider_field["provider_domain"], DOMAIN)
        # The default comes from the catalog, never a literal in the node.
        self.assertEqual(provider_field["default"], DOMAINS[DOMAIN].default_provider)

    def test_the_executor_is_never_served_to_the_browser(self):
        served = serialize_registry()["node_types"][NODE]
        self.assertNotIn("executor", served)

    def test_it_owns_the_script_stage_not_a_stage_of_its_own(self):
        self.assertEqual(PRIMARY_STAGE_BY_TYPE[NODE], "script")


class AdapterTests(unittest.TestCase):
    """The adapter assembles a request from ports and dispatches; no scoring."""

    def _run(self, inputs, config=None, context=None):
        configuration = {"provider_id": "deterministic", "target_duration": 0}
        configuration.update(config or {})
        return viral_adapter.analyze(
            inputs, configuration, context or _context()
        )["score"]

    def test_pasted_text_alone_is_enough_to_score(self):
        payload = self._run({"script": WEAK_TEXT})
        self.assertEqual(payload["job_id"], "job_VIR162")
        self.assertEqual(payload["provider_type"], "deterministic")
        self.assertIsInstance(payload["score"], int)
        self.assertIn(payload["band"], ("poor", "weak", "solid", "strong"))

    def test_a_story_document_supplies_sections_and_the_target_duration(self):
        payload = self._run(
            {
                "script": " ".join(STRONG_SECTIONS.values()),
                "story": {
                    "sections": STRONG_SECTIONS,
                    "story_text": " ".join(STRONG_SECTIONS.values()),
                    "metadata": {"duration": 60},
                },
            }
        )
        self.assertEqual(payload["target_duration"], 60)
        balance = next(
            d for d in payload["viral_score"]["dimensions"] if d["id"] == "balance"
        )
        # Sections present means balance is actually measured rather than zeroed.
        self.assertGreater(balance["score"], 0.0)

    def test_configured_duration_outranks_the_story_document(self):
        payload = self._run(
            {"script": WEAK_TEXT, "story": {"metadata": {"duration": 60}}},
            config={"target_duration": 20},
        )
        self.assertEqual(payload["target_duration"], 20)

    def test_the_unset_duration_field_does_not_mask_the_story_document(self):
        # The field defaults to 0 rather than 45 so "left alone" and "set to
        # 45" stay distinguishable. Without that, a node straight out of the
        # palette would silently outrank the script's real target.
        self.assertEqual(get_node_type(NODE)["config_schema"][1]["default"], 0)
        payload = self._run({"script": WEAK_TEXT, "story": {"metadata": {"duration": 90}}})
        self.assertEqual(payload["target_duration"], 90)

    def test_scene_narrative_roles_are_read_when_the_graph_has_them(self):
        payload = self._run(
            {
                "script": " ".join(STRONG_SECTIONS.values()),
                "scenes": {
                    "scenes": [
                        {"id": "s1", "narrative_role": "hook"},
                        {"id": "s2", "narrative_role": "build"},
                    ]
                },
            }
        )
        self.assertIsInstance(payload["score"], int)

    def test_an_empty_script_is_a_structured_adapter_error(self):
        with self.assertRaises(AdapterError) as ctx:
            self._run({"script": "   "})
        self.assertEqual(ctx.exception.code, "MISSING_REQUIRED_INPUT")

    def test_a_canvas_run_without_a_job_still_reports(self):
        payload = self._run(
            {"script": WEAK_TEXT},
            context=AdapterContext(project_id="pm_VIR162", node_id="n_analyze"),
        )
        self.assertEqual(payload["job_id"], "pm_VIR162")

    def test_the_adapter_holds_no_scoring_logic(self):
        """Weights and thresholds live behind the domain, never in the node."""
        source = (
            Path(__file__).resolve().parents[1]
            / "scriptase" / "engine" / "adapters" / "viral.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("DIMENSION_WEIGHTS", source)
        self.assertNotIn("score_script", source)


class TypedResultTests(unittest.TestCase):
    """Done-when: a typed result Review can read."""

    def test_the_payload_round_trips_through_the_frozen_score(self):
        payload = viral_adapter.analyze(
            {"script": " ".join(STRONG_SECTIONS.values())},
            {"provider_id": "deterministic", "target_duration": 45},
            _context(),
        )["score"]
        # `ViralScore` forbids extra keys, so this only passes if the adapter
        # nested the frozen document instead of flattening its own fields into
        # it. That exact round trip is how 16.3 reads the breakdown.
        restored = ViralScore.model_validate(payload["viral_score"])
        self.assertEqual(restored.score, payload["score"])
        self.assertEqual(restored.band, payload["band"])
        self.assertEqual([d.id for d in restored.dimensions], list(DIMENSION_IDS))
        self.assertIsNotNone(restored.dimension("hook"))

    def test_reasons_are_structured_codes_and_never_prose(self):
        payload = viral_adapter.analyze(
            {"script": WEAK_TEXT},
            {"provider_id": "deterministic", "target_duration": 45},
            _context(),
        )["score"]
        restored = ViralScore.model_validate(payload["viral_score"])
        for dimension in restored.dimensions:
            for reason in dimension.reasons:
                self.assertRegex(reason.code, r"^[a-z0-9_]+$")
                self.assertIn(reason.impact, ("positive", "negative"))

    def test_a_weak_script_is_visibly_worse_than_a_strong_one(self):
        def run(inputs):
            return viral_adapter.analyze(
                inputs,
                {"provider_id": "deterministic", "target_duration": 45},
                _context(),
            )["score"]["score"]

        strong = run(
            {
                "script": " ".join(STRONG_SECTIONS.values()),
                "story": {"sections": STRONG_SECTIONS},
            }
        )
        self.assertGreater(strong, run({"script": WEAK_TEXT}) + 20)


# ---------------------------------------------------------------------------
# The Full Video graph
# ---------------------------------------------------------------------------


class FullVideoGraphTests(unittest.TestCase):
    """Done-when: the node runs inside the Full Video graph."""

    def setUp(self):
        self.template = full_video_template()

    def _analyze_node(self):
        return next(n for n in self.template["nodes"] if n["type"] == NODE)

    def test_the_template_contains_the_analyzer_fed_from_script(self):
        self.assertEqual(self._analyze_node()["id"], "n_analyze")
        edge = next(
            e for e in self.template["edges"] if e["target_node"] == "n_analyze"
        )
        self.assertEqual((edge["source_node"], edge["source_port"]), ("n_script", "script"))
        self.assertEqual(edge["target_port"], "script")

    def test_the_template_still_validates_and_orders(self):
        draft = deepcopy(self.template)
        draft.pop("template_id", None)
        problems = validate_workflow(draft, require_identity=False, require_complete=False)
        self.assertEqual(validation_errors(problems), [])
        self.assertIn("n_analyze", deterministic_order(draft))

    def test_every_built_in_template_still_builds(self):
        ids = [item["template_id"] for item in serialize_templates()]
        self.assertIn("full_video", ids)

    def test_it_lands_on_the_script_stage_beside_the_script_node(self):
        assignment = assign_nodes_to_stages(self.template)
        self.assertEqual(assignment["script"], ["n_script", "n_analyze"])

    def test_it_runs_before_voice_in_the_scheduled_order(self):
        draft = deepcopy(self.template)
        draft.pop("template_id", None)
        order = deterministic_order(draft)
        self.assertLess(order.index("n_analyze"), order.index("n_tts"))


class ComposerIsolationTests(unittest.TestCase):
    """Done-when: the Composer path ignores the result."""

    def setUp(self):
        self.template = full_video_template()

    def test_nothing_downstream_consumes_the_score_port(self):
        consumers = [
            edge for edge in self.template["edges"] if edge["source_node"] == "n_analyze"
        ]
        self.assertEqual(consumers, [])

    def test_the_composer_inputs_are_unchanged(self):
        assemble = sorted(
            (e["source_node"], e["target_port"])
            for e in self.template["edges"]
            if e["target_node"] == "n_assemble"
        )
        self.assertEqual(
            assemble,
            sorted(
                [
                    ("n_animator", "assets"),
                    ("n_captions", "captions"),
                    ("n_music", "music"),
                    ("n_scenes", "scenes"),
                    ("n_setup", "settings"),
                    ("n_tts", "metadata"),
                ]
            ),
        )

    def test_the_analyzer_opts_out_of_the_stop_policy(self):
        analyze = next(n for n in self.template["nodes"] if n["type"] == NODE)
        self.assertEqual(analyze["on_error"], {"policy": "continue_error"})
        # Every other node keeps the engine default rather than restating it.
        for node in self.template["nodes"]:
            if node["type"] != NODE:
                self.assertNotIn("on_error", node, node["id"])

    def test_a_failing_analyzer_cannot_strand_the_export(self):
        """It is a terminal branch, so its failure reaches no other node."""
        draft = deepcopy(self.template)
        draft.pop("template_id", None)
        draft["workflow_id"] = "wf_VIR162"
        draft["created_at"] = "2026-08-16T00:00:00Z"
        draft["updated_at"] = "2026-08-16T00:00:00Z"
        for node in draft["nodes"]:
            if node["type"] == "script.input":
                node["configuration"]["text"] = "Narration for the isolation probe."

        def resolver(node):
            def execute(inputs, config, context):
                if node["type"] == NODE:
                    raise AdapterError("PROVIDER_UNAVAILABLE", "scorer is down")
                return {
                    port["id"]: ({"ok": True} if port["type"] == "control" else {})
                    for port in get_node_type(node["type"])["outputs"]
                }

            return execute

        with tempfile.TemporaryDirectory(prefix="sts_16_2_") as root:
            scheduler = WorkflowScheduler(
                draft,
                project_id="pm_VIR162",
                output_dir=root,
                executor_resolver=resolver,
            )
            record = scheduler.run()

        statuses = record.node_statuses
        self.assertEqual(statuses["n_analyze"], "failed")
        # Everything on the spine past Script still ran through to the export.
        for node_id in ("n_tts", "n_assemble", "n_timeline", "n_export", "n_output"):
            self.assertEqual(statuses[node_id], "succeeded", node_id)


class SavedWorkflowCompatibilityTests(unittest.TestCase):
    """A graph saved before 16.2 keeps loading; nothing is retroactive."""

    def test_a_workflow_without_the_analyzer_still_validates(self):
        document = workflow_draft(name="Pre-16.2 graph")
        document["nodes"] = [
            _node("n_trigger", "trigger.manual"),
            _node("n_script", "script.input", {"text": "Legacy narration."}),
        ]
        document["edges"] = [
            {
                "id": "e1",
                "source_node": "n_trigger",
                "source_port": "control",
                "target_node": "n_script",
                "target_port": "trigger",
                "edge_type": "control",
            }
        ]
        problems = validate_workflow(document, require_identity=False, require_complete=False)
        self.assertEqual(validation_errors(problems), [])

    def test_an_analyzer_saved_without_provider_id_falls_back_to_the_default(self):
        # M4 (contracts §41.3): a read, never a write — the fallback must not
        # rewrite the fingerprinted configuration.
        from scriptase.engine.adapters.common import provider_id

        self.assertEqual(provider_id(DOMAIN, {}), "deterministic")
        self.assertEqual(provider_id(DOMAIN, {"provider_id": "custom"}), "custom")


if __name__ == "__main__":
    unittest.main()
