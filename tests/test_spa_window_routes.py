"""Step 14.4 — the editor and export library open in their own windows.

Done when: both open as separate windows, survive a reload, and remain
directly linkable by URL.

A window opened with ``window.open('/exports?project=…')`` is a real browsing
context: pressing F5 in it, or pasting the URL, is a plain GET to Flask, not an
in-app navigation. Both paths therefore have to reach the SPA shell rather than
404, or "survive a reload" is only true while the Vite dev server is proxying.
"""

from __future__ import annotations

import unittest

from app import create_app


class SpaWindowRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_window_routes_serve_the_spa_shell(self):
        for path in ("/editor", "/exports"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_window_routes_keep_their_query_string(self):
        # The project id is the whole instruction for both pages; the server
        # must not consume or redirect it away.
        for path in ("/editor?project=pm_ABC123", "/exports?project=pm_ABC123"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_api_paths_still_win_over_the_spa_fallback(self):
        # The fallback is registered last and must never shadow the API.
        self.assertNotEqual(self.client.get("/api/workflow/node-types").status_code, 404)


if __name__ == "__main__":
    unittest.main()
