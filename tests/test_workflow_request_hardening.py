"""Step 6.3: request hardening.

Covers the three trust-boundary gaps closed in this step:
- body-size limits that chunked transfer encoding (no Content-Length) cannot bypass,
- server-side rejection of option values outside the allowlisted resolver's list,
- branding upload caps for both request size (chunked-proof) and asset count.

Every rejection must use the standard `{error: {code, message}}` envelope.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from PIL import Image

from scriptase.engine import options as workflow_options
from scriptase.engine import persistence
from scriptase.engine import workflows_bp
from scriptase.engine.validation import MAX_DOCUMENT_BYTES, validate_workflow, validation_errors


def _client():
    app = Flask(__name__)
    app.register_blueprint(workflows_bp)
    return app.test_client()


def _png_bytes(size=(4, 4)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 200, 150)).save(buffer, format="PNG")
    return buffer.getvalue()


def _export_workflow(profile):
    """Minimal draft with an async-options field (export_profiles is static)."""
    return {
        "schema_version": 1,
        "name": "Hardening",
        "nodes": [{
            "id": "n_export", "type": "export.video", "type_version": 1,
            "name": "Export", "position": {"x": 0, "y": 0},
            "configuration": {"profile": profile}, "disabled": False,
        }],
        "edges": [],
    }


def _chunked_post(client, path, raw, content_type):
    """Simulate chunked transfer encoding: a terminated input stream with no
    Content-Length header, exactly what a chunked-decoding WSGI server hands
    Werkzeug (`wsgi.input_terminated`)."""
    return client.post(
        path,
        input_stream=io.BytesIO(raw),
        content_type=content_type,
        headers={"Transfer-Encoding": "chunked"},
        environ_overrides={"wsgi.input_terminated": True},
    )


def _assert_envelope(test, resp, status, code):
    test.assertEqual(resp.status_code, status)
    error = resp.get_json()["error"]
    test.assertEqual(error["code"], code)
    test.assertTrue(error["message"])


class ChunkedBodyLimitTests(unittest.TestCase):
    def setUp(self):
        self.client = _client()

    def test_oversized_chunked_json_is_rejected(self):
        raw = b'{"workflow": "' + b"x" * MAX_DOCUMENT_BYTES + b'"}'
        resp = _chunked_post(self.client, "/api/workflow/validate", raw, "application/json")
        _assert_envelope(self, resp, 413, "REQUEST_TOO_LARGE")

    def test_small_chunked_json_is_processed(self):
        # Proves the chunked simulation actually delivers a body: the request
        # succeeds instead of failing the empty/malformed-body check.
        raw = json.dumps({"workflow": _export_workflow("tiktok")}).encode()
        resp = _chunked_post(self.client, "/api/workflow/validate", raw, "application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("problems", resp.get_json())

    def test_declared_content_length_oversize_is_rejected(self):
        raw = b'{"workflow": "' + b"x" * MAX_DOCUMENT_BYTES + b'"}'
        resp = self.client.post(
            "/api/workflow/validate", data=raw, content_type="application/json"
        )
        _assert_envelope(self, resp, 413, "REQUEST_TOO_LARGE")

    def test_non_json_content_type_is_rejected(self):
        resp = self.client.post(
            "/api/workflow/validate", data=b'{"workflow": {}}', content_type="text/plain"
        )
        _assert_envelope(self, resp, 400, "BAD_REQUEST")


class OptionValueValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sts_hardening_")
        self.old_workflows = persistence.WORKFLOWS_DIR
        self.old_trash = persistence.TRASH_DIR
        persistence.WORKFLOWS_DIR = os.path.join(self.temp.name, "workflows")
        persistence.TRASH_DIR = os.path.join(self.temp.name, "trash")
        os.makedirs(persistence.WORKFLOWS_DIR, exist_ok=True)
        self.client = _client()

    def tearDown(self):
        persistence.WORKFLOWS_DIR = self.old_workflows
        persistence.TRASH_DIR = self.old_trash
        self.temp.cleanup()

    def test_invalid_option_value_rejected_on_save(self):
        resp = self.client.post(
            "/api/workflows", json={"workflow": _export_workflow("not_a_profile")}
        )
        _assert_envelope(self, resp, 422, "WORKFLOW_INVALID")
        problems = resp.get_json()["error"]["details"]["problems"]
        self.assertTrue(any(
            "configuration.profile" in problem.get("path", "") for problem in problems
        ))
        self.assertEqual(os.listdir(persistence.WORKFLOWS_DIR), [])

    def test_valid_option_value_saves(self):
        resp = self.client.post(
            "/api/workflows", json={"workflow": _export_workflow("tiktok")}
        )
        self.assertEqual(resp.status_code, 201)

    def test_validate_endpoint_reports_invalid_option_value(self):
        resp = self.client.post(
            "/api/workflow/validate", json={"workflow": _export_workflow("not_a_profile")}
        )
        self.assertEqual(resp.status_code, 200)
        problems = resp.get_json()["problems"]
        self.assertTrue(any(
            "configuration.profile" in problem.get("path", "") for problem in problems
        ))

    def test_unavailable_source_fails_open(self):
        # A missing provider must never block saving — only bad values do.
        def _boom(_ctx):
            raise RuntimeError("provider offline")

        workflow_options.clear_option_cache()
        self.addCleanup(workflow_options.clear_option_cache)
        with patch.dict(workflow_options._RESOLVERS, {"export_profiles": _boom}):
            problems = validation_errors(
                validate_workflow(_export_workflow("anything_goes"), require_identity=False)
            )
        self.assertFalse(any(
            "allowed option" in problem["message"] for problem in problems
        ))

    def test_non_string_option_value_is_rejected(self):
        workflow_options.clear_option_cache()
        problems = validation_errors(
            validate_workflow(_export_workflow(True), require_identity=False)
        )
        self.assertTrue(any(
            "allowed option" in problem["message"] for problem in problems
        ))


class BrandingUploadLimitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="sts_branding_hard_")
        patcher = patch("scriptase.engine.routes.BRANDING_DIR", self.tempdir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tempdir, True)
        self.client = _client()

    def _upload(self, data, filename):
        return self.client.post(
            "/api/workflow/branding",
            data={"file": (io.BytesIO(data), filename, "image/png")},
            content_type="multipart/form-data",
        )

    def test_asset_count_cap_is_enforced(self):
        with patch("scriptase.engine.routes.MAX_BRANDING_ASSETS", 2):
            self.assertEqual(self._upload(_png_bytes(), "one.png").status_code, 201)
            self.assertEqual(self._upload(_png_bytes(), "two.png").status_code, 201)
            resp = self._upload(_png_bytes(), "three.png")
        _assert_envelope(self, resp, 409, "LIMIT_EXCEEDED")
        self.assertEqual(len(os.listdir(self.tempdir)), 2)

    def test_oversized_chunked_upload_is_rejected(self):
        boundary = "hardeningboundary"
        head = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"big.png\"\r\nContent-Type: image/png\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        body = head + _png_bytes() + b"\x00" * (7 * 1024 * 1024) + tail
        resp = _chunked_post(
            self.client,
            "/api/workflow/branding",
            body,
            f"multipart/form-data; boundary={boundary}",
        )
        _assert_envelope(self, resp, 413, "REQUEST_TOO_LARGE")
        self.assertEqual(os.listdir(self.tempdir), [])

    def test_oversized_declared_upload_is_rejected_before_parsing(self):
        blob = _png_bytes() + b"\x00" * (7 * 1024 * 1024)
        resp = self._upload(blob, "big.png")
        _assert_envelope(self, resp, 413, "REQUEST_TOO_LARGE")
        self.assertEqual(os.listdir(self.tempdir), [])


if __name__ == "__main__":
    unittest.main()
