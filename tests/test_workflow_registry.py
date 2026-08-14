"""Step 1.2 tests: workflow node-type registry + /api/workflow/node-types."""

import json
import unittest

from flask import Flask

from scriptase.engine import workflows_bp
from scriptase.engine.registry import (
    ASYNC_OPTION_SOURCES,
    CATEGORIES,
    DYNAMIC_PORT_TYPES,
    PORT_TYPES,
    REGISTRY_VERSION,
    all_node_types,
    get_node_type,
    is_supported,
    serialize_registry,
)

EXPECTED_TYPES = {
    "trigger.manual", "project.setup", "script.input", "story.generate", "project.existing",
    "tts.generate", "timing.align", "segment.run", "scenes.blueprint",
    "storyboard.generate", "animator.generate", "captions.generate",
    "music.select", "assemble.project", "timeline.project", "export.video",
    "utility.set_value", "utility.condition", "utility.merge", "utility.wait",
    "workflow.output", "stub.input", "stub.output",
}


class RegistryContractTests(unittest.TestCase):
    def test_catalog_is_complete(self):
        self.assertLessEqual(EXPECTED_TYPES, set(all_node_types().keys()))

    def test_every_node_has_required_fields(self):
        for key, node in all_node_types().items():
            for field in ("type_version", "display_name", "description",
                          "category", "icon", "inputs", "outputs",
                          "config_schema", "capabilities", "executor"):
                self.assertIn(field, node, f"{key} missing {field}")
            self.assertIsInstance(node["type_version"], int)
            self.assertGreaterEqual(node["type_version"], 1)
            self.assertIn(node["category"], CATEGORIES, key)

    def test_port_types_and_ids_are_valid(self):
        valid = set(PORT_TYPES) | {"dynamic"}
        for key, node in all_node_types().items():
            in_ids = [p["id"] for p in node["inputs"]]
            out_ids = [p["id"] for p in node["outputs"]]
            self.assertEqual(len(in_ids), len(set(in_ids)), f"{key} duplicate input ids")
            self.assertEqual(len(out_ids), len(set(out_ids)), f"{key} duplicate output ids")
            for port in node["inputs"]:
                self.assertIn(port["type"], valid, f"{key}.{port['id']}")
                self.assertIn("required", port, f"{key}.{port['id']}")
                self.assertIn("multiple", port, f"{key}.{port['id']}")
            for port in node["outputs"]:
                self.assertIn(port["type"], valid, f"{key}.{port['id']}")

    def test_dynamic_ports_only_on_dynamic_nodes(self):
        for key, node in all_node_types().items():
            dynamic = [p for p in node["inputs"] + node["outputs"] if p["type"] == "dynamic"]
            if dynamic:
                self.assertIn(key, ("workflow.output", "stub.input", "stub.output"), key)
                schema_names = {f["name"] for f in node["config_schema"]}
                self.assertIn("port_type", schema_names, f"{key} needs port_type config")

    def test_config_schema_integrity(self):
        widget_types = {"string", "textarea", "number", "boolean", "options",
                        "json", "media_asset", "provider", "provider_options"}
        for key, node in all_node_types().items():
            names = [f["name"] for f in node["config_schema"]]
            self.assertEqual(len(names), len(set(names)), f"{key} duplicate config names")
            for field in node["config_schema"]:
                self.assertIn(field["type"], widget_types, f"{key}.{field['name']}")
                self.assertIn("default", field, f"{key}.{field['name']}")
                if field["type"] in ("options", "provider"):
                    has_static = bool(field.get("options"))
                    source = field.get("options_source")
                    self.assertTrue(has_static or source, f"{key}.{field['name']}")
                    if source:
                        self.assertIn(source, ASYNC_OPTION_SOURCES, f"{key}.{field['name']}")
                show = (field.get("display_options") or {}).get("show", {})
                for ref in show:
                    self.assertIn(ref, names, f"{key}.{field['name']} references unknown field {ref}")

    def test_control_out_on_every_producing_node(self):
        # Frozen §3.1: every core node except stubs/workflow.output emits control.
        for key, node in all_node_types().items():
            if key.startswith("stub.") or key in {"workflow.output", "utility.condition"}:
                continue
            self.assertIn("control", [p["id"] for p in node["outputs"]], key)

    def test_version_lookup(self):
        self.assertTrue(is_supported("tts.generate", 2))
        self.assertFalse(is_supported("tts.generate", 1))
        self.assertFalse(is_supported("nope.missing", 1))
        self.assertIsNone(get_node_type("nope.missing"))

    def test_dynamic_port_types_exclude_control(self):
        self.assertNotIn("control", DYNAMIC_PORT_TYPES)
        self.assertTrue(set(DYNAMIC_PORT_TYPES) < set(PORT_TYPES))


class SerializationTests(unittest.TestCase):
    def test_serialized_shape(self):
        payload = serialize_registry()
        self.assertEqual(payload["registry_version"], REGISTRY_VERSION)
        self.assertEqual(payload["port_types"], PORT_TYPES)
        self.assertLessEqual(EXPECTED_TYPES, set(payload["node_types"].keys()))
        for key, node in payload["node_types"].items():
            self.assertEqual(node["type"], key)

    def test_no_internal_fields_leak(self):
        payload = serialize_registry()
        for key, node in payload["node_types"].items():
            self.assertNotIn("executor", node, key)
        # Everything served must be JSON-serializable (no callables/objects).
        json.dumps(payload)

    def test_serialization_does_not_mutate_registry(self):
        payload = serialize_registry()
        payload["node_types"]["tts.generate"]["display_name"] = "tampered"
        self.assertEqual(all_node_types()["tts.generate"]["display_name"], "Text to Speech")
        self.assertIn("executor", get_node_type("tts.generate"))


class NodeTypesEndpointTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        self.client = app.test_client()

    def test_endpoint_serves_registry(self):
        resp = self.client.get("/api/workflow/node-types")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["registry_version"], REGISTRY_VERSION)
        self.assertLessEqual(EXPECTED_TYPES, set(data["node_types"].keys()))
        for node in data["node_types"].values():
            self.assertNotIn("executor", node)

    def test_endpoint_rejects_non_loopback(self):
        resp = self.client.get(
            "/api/workflow/node-types",
            environ_overrides={"REMOTE_ADDR": "10.1.2.3"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["error"]["code"], "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
