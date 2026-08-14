"""Step 2.3: allowlisted option sources + managed branding uploads."""

import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from PIL import Image

from scriptase.engine import workflows_bp


def _png_bytes(size=(4, 4)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 200, 150)).save(buffer, format="PNG")
    return buffer.getvalue()


class OptionSourceTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        self.client = app.test_client()

    def test_static_source_resolves(self):
        resp = self.client.get("/api/workflow/options/export_profiles")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["source"], "export_profiles")
        values = [opt["value"] for opt in data["options"]]
        self.assertEqual(values, ["yt_shorts", "tiktok", "reels", "yt_landscape", "square"])
        for opt in data["options"]:
            self.assertIn("label", opt)

    def test_story_tones_resolve_from_selector(self):
        resp = self.client.get("/api/workflow/options/story_tones")
        self.assertEqual(resp.status_code, 200)
        options = resp.get_json()["options"]
        self.assertGreater(len(options), 1)
        self.assertEqual(options[0]["value"], "")  # blank = no tone

    def test_unknown_source_is_rejected(self):
        resp = self.client.get("/api/workflow/options/evil_source")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["error"]["code"], "NOT_FOUND")

    def test_non_loopback_is_403(self):
        resp = self.client.get(
            "/api/workflow/options/export_profiles",
            environ_overrides={"REMOTE_ADDR": "10.2.2.2"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_resolver_table_matches_allowlist(self):
        from scriptase.engine.options import _RESOLVERS
        from scriptase.engine.registry import ASYNC_OPTION_SOURCES
        self.assertEqual(set(_RESOLVERS), set(ASYNC_OPTION_SOURCES))


class BrandingUploadTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="sts_branding_")
        patcher = patch("scriptase.engine.routes.BRANDING_DIR", self.tempdir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tempdir, True)
        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        self.client = app.test_client()

    def _upload(self, data, filename, mimetype="image/png"):
        return self.client.post(
            "/api/workflow/branding",
            data={"file": (io.BytesIO(data), filename, mimetype)},
            content_type="multipart/form-data",
        )

    def test_valid_upload_and_list(self):
        resp = self._upload(_png_bytes(), "My Logo.png")
        self.assertEqual(resp.status_code, 201)
        asset = resp.get_json()["asset"]
        self.assertTrue(asset["ref"].startswith("branding/"))
        self.assertTrue(asset["url"].startswith("/output/branding/"))
        self.assertTrue(os.path.isfile(os.path.join(self.tempdir, asset["filename"])))

        listed = self.client.get("/api/workflow/branding").get_json()["assets"]
        self.assertEqual([a["filename"] for a in listed], [asset["filename"]])

    def test_traversal_filename_is_sanitized(self):
        resp = self._upload(_png_bytes(), "..\\..\\evil.png")
        self.assertEqual(resp.status_code, 201)
        filename = resp.get_json()["asset"]["filename"]
        self.assertNotIn("..", filename)
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)
        self.assertTrue(os.path.isfile(os.path.join(self.tempdir, filename)))

    def test_bad_extension_rejected(self):
        resp = self._upload(_png_bytes(), "logo.svg", mimetype="image/svg+xml")
        self.assertEqual(resp.status_code, 400)

    def test_non_image_bytes_rejected(self):
        resp = self._upload(b"#!/bin/sh\nrm -rf /", "logo.png")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("decodable", resp.get_json()["error"]["message"])

    def test_oversize_rejected(self):
        blob = _png_bytes() + b"\x00" * (5 * 1024 * 1024)
        resp = self._upload(blob, "big.png")
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(os.listdir(self.tempdir), [])

    def test_missing_file_rejected(self):
        resp = self.client.post(
            "/api/workflow/branding", data={}, content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
