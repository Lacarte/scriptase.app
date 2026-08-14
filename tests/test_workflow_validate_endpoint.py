"""Step 2.2: POST /api/workflow/validate contract."""

import unittest

from flask import Flask

from scriptase.engine import workflows_bp


def _draft(nodes=None, edges=None):
    return {
        "schema_version": 1,
        "name": "Draft",
        "description": "",
        "nodes": nodes or [],
        "edges": edges or [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
    }


def _script_node(text=""):
    return {
        "id": "n_1",
        "type": "script.input",
        "type_version": 1,
        "name": "Script",
        "position": {"x": 0, "y": 0},
        "configuration": {"text": text},
        "disabled": False,
    }


class ValidateEndpointTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        self.client = app.test_client()

    def _post(self, body):
        return self.client.post("/api/workflow/validate", json=body)

    def test_valid_empty_draft(self):
        resp = self._post({"workflow": _draft()})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["problems"], [])

    def test_incomplete_draft_yields_warnings_not_errors(self):
        resp = self._post({"workflow": _draft(nodes=[_script_node(text="")])})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data["valid"])
        self.assertTrue(any("required" in w["message"] for w in data["warnings"]))

    def test_graph_problems_are_data_not_transport_errors(self):
        node = _script_node(text="hello")
        node["type"] = "nope.missing"
        resp = self._post({"workflow": _draft(nodes=[node])})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(data["valid"])
        self.assertTrue(data["problems"])

    def test_malformed_transport_is_400(self):
        resp = self.client.post(
            "/api/workflow/validate", data="[]", content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"]["code"], "BAD_REQUEST")

        for body in ({}, {"workflow": []}, {"workflow": None}):
            with self.subTest(body=body):
                resp = self._post(body)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["error"]["code"], "BAD_REQUEST")

    def test_non_loopback_is_403(self):
        resp = self.client.post(
            "/api/workflow/validate",
            json={"workflow": _draft()},
            environ_overrides={"REMOTE_ADDR": "10.0.0.9"},
        )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
