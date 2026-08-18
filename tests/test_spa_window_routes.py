"""Steps 14.4 and 1.1 — client routes have to reach the SPA shell.

Step 14.4: the editor and export library open in their own windows. A window
opened with ``window.open('/library?project=…')`` is a real browsing context —
pressing F5 in it, or pasting the URL, is a plain GET to Flask, not an in-app
navigation.

Step 1.1: every previous route redirects rather than returning a 404. The
redirect itself is vue-router's job, but the app has to load before it can run
one, so Flask must answer the *old* paths with the shell too.
"""

from __future__ import annotations

import unittest

from app import create_app

#: Ordered create, run, monitor, output, configure (step 1.1).
DESTINATIONS = (
    "/script",
    "/production",
    "/schema",
    "/library",
    "/channels",
    "/providers",
)

#: Reachable without being destinations.
OTHER_CLIENT_ROUTES = ("/", "/channels/ch_ABC123", "/workflow", "/editor")

#: Paths that existed before step 1.1 renamed them.
PREVIOUS_PATHS = ("/exports", "/settings/providers")


class SpaWindowRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_every_destination_serves_the_spa_shell(self):
        for path in DESTINATIONS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_other_client_routes_serve_the_spa_shell(self):
        for path in OTHER_CLIENT_ROUTES:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_previous_paths_reach_the_shell_rather_than_404(self):
        # Flask serves the app; vue-router then redirects to the new path.
        for path in PREVIOUS_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_window_routes_keep_their_query_string(self):
        # The project id is the whole instruction for both pages; the server
        # must not consume or redirect it away.
        for path in (
            "/editor?project=pm_ABC123",
            "/library?project=pm_ABC123",
            "/exports?project=pm_ABC123",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_api_paths_still_win_over_the_spa_fallback(self):
        # The fallback is registered last and must never shadow the API — and
        # /providers now sits one segment away from the provider API.
        self.assertNotEqual(self.client.get("/api/workflow/node-types").status_code, 404)
        self.assertNotEqual(self.client.get("/api/providers").status_code, 404)


if __name__ == "__main__":
    unittest.main()
