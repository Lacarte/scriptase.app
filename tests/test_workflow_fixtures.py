"""Step 2.5: sample fixtures, stub payload validation, and stub graphs."""

import unittest

from flask import Flask

from scriptase.engine import workflows_bp
from scriptase.engine.registry import DYNAMIC_PORT_TYPES
from scriptase.engine.sample_data import (
    all_sample_payloads,
    sample_payload,
    validate_fixtures,
    validate_stub_payload,
)
from scriptase.engine.validation import validate_workflow, validation_errors


def _codes(problems):
    return {problem["code"] for problem in problems}


class FixtureContractTests(unittest.TestCase):
    def test_fixture_set_is_frozen_and_valid(self):
        """Manifest hashes, per-type payload rules, and cross-file coherence."""
        self.assertEqual(validate_fixtures(), [])

    def test_every_dynamic_port_type_has_an_accepted_sample_payload(self):
        payloads = all_sample_payloads()
        self.assertEqual(set(payloads), set(DYNAMIC_PORT_TYPES))
        for port_type, payload in payloads.items():
            with self.subTest(port_type=port_type):
                self.assertEqual(validate_stub_payload(port_type, payload), [])


class StubPayloadValidationTests(unittest.TestCase):
    def test_structural_violations_are_rejected(self):
        cases = [
            ("script", ""),                       # empty
            ("script", 42),                       # wrong type
            ("project_id", "not-an-id"),
            ("alignment", {"transcript": "hi", "alignment": []}),
            ("alignment", {"transcript": "hi", "alignment": [
                {"word": "a", "begin": 2.0, "end": 1.0}]}),
            ("segments", {"segments": [
                {"start": 0.0, "end": 2.0, "words": "a"},
                {"start": 1.0, "end": 3.0, "words": "b"},   # overlap
            ]}),
            ("scenes", {"scenes": [{"index": 0, "image_prompt": ""}]}),
            ("storyboard_images", {
                "total": 3, "ready": 3, "errors": 0,
                "scene_statuses": {"0": {"status": "ready"}},   # count mismatch
            }),
            ("music_track", {"track_ref": "media/music.wav", "volume": 2.0}),
        ]
        for port_type, payload in cases:
            with self.subTest(port_type=port_type):
                problems = validate_stub_payload(port_type, payload)
                self.assertIn("STUB_PAYLOAD_INVALID", _codes(problems))

    def test_file_references_cannot_escape_the_fixture_root(self):
        for ref in ("../secrets.txt", "/etc/passwd", "C:/windows/system32", "media/../../x"):
            with self.subTest(ref=ref):
                payload = dict(sample_payload("audio_file"))
                payload["wav_path"] = ref
                problems = validate_stub_payload("audio_file", payload)
                self.assertIn("STUB_PAYLOAD_INVALID", _codes(problems))

    def test_missing_fixture_reference_is_flagged(self):
        payload = dict(sample_payload("audio_file"))
        payload["wav_path"] = "media/does-not-exist.wav"
        problems = validate_stub_payload("audio_file", payload)
        self.assertIn("SAMPLE_FIXTURE_MISSING", _codes(problems))

    def test_unknown_port_type_is_rejected(self):
        problems = validate_stub_payload("nope", {"anything": 1})
        self.assertIn("STUB_PAYLOAD_INVALID", _codes(problems))


def _draft(nodes=None, edges=None, settings=None):
    return {
        "schema_version": 1,
        "name": "Stub draft",
        "description": "",
        "nodes": nodes or [],
        "edges": edges or [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": settings or {"on_error": "stop"},
        "extensions": {},
    }


def _stub_graph(payload=None):
    """Lone Segmenter fed by a Sample Input, watched by a Result Viewer."""
    return _draft(
        nodes=[
            {
                "id": "n_stub_in", "type": "stub.input", "type_version": 1,
                "name": "Sample alignment", "position": {"x": 0, "y": 0},
                "configuration": {
                    "port_type": "alignment",
                    "payload": payload if payload is not None else sample_payload("alignment"),
                },
                "disabled": False,
            },
            {
                "id": "n_seg", "type": "segment.run", "type_version": 1,
                "name": "Segmenter", "position": {"x": 260, "y": 0},
                "configuration": {"segment_config": {}},
                "disabled": False,
            },
            {
                "id": "n_view", "type": "stub.output", "type_version": 1,
                "name": "View segments", "position": {"x": 520, "y": 0},
                "configuration": {"port_type": "segments"},
                "disabled": False,
            },
        ],
        edges=[
            {
                "id": "e_1", "source_node": "n_stub_in", "source_port": "value",
                "target_node": "n_seg", "target_port": "alignment", "edge_type": "data",
            },
            {
                "id": "e_2", "source_node": "n_seg", "source_port": "segments",
                "target_node": "n_view", "target_port": "value", "edge_type": "data",
            },
        ],
    )


class StubGraphValidationTests(unittest.TestCase):
    def test_stub_fed_graph_is_fully_valid(self):
        problems = validate_workflow(_stub_graph(), require_identity=False)
        self.assertEqual(problems, [])

    def test_invalid_stub_payload_fails_validation(self):
        document = _stub_graph(payload={"transcript": "", "alignment": "nope"})
        problems = validate_workflow(document, require_identity=False)
        self.assertIn("STUB_PAYLOAD_INVALID", _codes(validation_errors(problems)))

    def test_stub_payload_referencing_outside_fixtures_fails(self):
        payload = sample_payload("alignment")
        payload["artifact_refs"] = ["../../output/tts/pp_XXXXXX/voice.wav"]
        problems = validate_workflow(_stub_graph(payload=payload), require_identity=False)
        self.assertIn("STUB_PAYLOAD_INVALID", _codes(validation_errors(problems)))

    def test_auto_attach_stubs_setting_round_trips(self):
        document = _stub_graph()
        document["settings"] = {"on_error": "stop", "auto_attach_stubs": False}
        self.assertEqual(validate_workflow(document, require_identity=False), [])

    def test_bad_settings_are_rejected(self):
        for settings in (
            {"on_error": "stop", "auto_attach_stubs": "yes"},
            {"on_error": "stop", "surprise": 1},
        ):
            with self.subTest(settings=settings):
                document = _draft(settings=settings)
                problems = validate_workflow(document, require_identity=False)
                self.assertTrue(validation_errors(problems))


class NodeTypesEndpointTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        self.client = app.test_client()

    def test_endpoint_serves_sample_payloads_without_internals(self):
        data = self.client.get("/api/workflow/node-types").get_json()
        self.assertEqual(set(data["sample_payloads"]), set(DYNAMIC_PORT_TYPES))
        self.assertNotIn("executor", str(data["sample_payloads"]))
        for definition in data["node_types"].values():
            self.assertNotIn("executor", definition)

    def test_validate_endpoint_accepts_a_stub_graph(self):
        resp = self.client.post("/api/workflow/validate", json={"workflow": _stub_graph()})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["problems"], [])
        self.assertEqual(data["warnings"], [])


if __name__ == "__main__":
    unittest.main()
