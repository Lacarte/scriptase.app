"""Step 16.3: provider reference and author guide cannot drift from the hub."""

import unittest
from pathlib import Path

from scriptase.providers.docs import (
    DEFAULT_AUTHOR_OUTPUT,
    DEFAULT_REFERENCE_OUTPUT,
    generate_provider_author_guide,
    generate_provider_reference,
    main as provider_docs_main,
)
from scriptase.providers.domains import DOMAINS, SHARED_CAPABILITIES
from scriptase.providers.errors import PROVIDER_CODES
from scriptase.providers.hub import hub
from scriptase.providers.settings_schema import WIDGET_TYPES
from scriptase.engine.docs import main as workflow_docs_main

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
REPO_ROOT = Path(__file__).resolve().parents[1]


class ProviderReferenceGenerationTests(unittest.TestCase):
    def setUp(self):
        self.content = generate_provider_reference()

    def test_committed_reference_matches_generated_output(self):
        self.assertTrue(
            DEFAULT_REFERENCE_OUTPUT.exists(),
            "docs/providers.md is missing — run python -m scriptase.engine.docs",
        )
        self.assertEqual(
            DEFAULT_REFERENCE_OUTPUT.read_text(encoding="utf-8"),
            self.content,
            "docs/providers.md is stale — regenerate with: python -m scriptase.engine.docs",
        )

    def test_check_mode_agrees_with_drift_assertion(self):
        self.assertEqual(provider_docs_main(["--check"]), 0)
        self.assertEqual(workflow_docs_main(["--check"]), 0)

    def test_every_domain_and_registered_provider_documented(self):
        hub.discover_all()
        for domain_id, spec in DOMAINS.items():
            with self.subTest(domain=domain_id):
                self.assertIn(f"`{domain_id}`", self.content)
                self.assertIn(spec.label, self.content)
                self.assertIn(f"`{spec.default_provider}`", self.content)
                for provider in hub.list(domain_id):
                    self.assertIn(f"`{provider.id}`", self.content)
                    self.assertIn(provider.manifest.label, self.content)

    def test_request_result_and_capability_tables_are_present(self):
        for domain_id, spec in DOMAINS.items():
            with self.subTest(domain=domain_id):
                if spec.request_model:
                    self.assertIn(spec.request_model, self.content)
                if spec.result_model:
                    self.assertIn(spec.result_model, self.content)
                for cap in sorted(spec.capability_vocabulary)[:3]:
                    self.assertIn(f"`{cap}`", self.content)

    def test_shared_capabilities_and_error_codes_documented(self):
        for cap in SHARED_CAPABILITIES:
            self.assertIn(f"`{cap}`", self.content)
        for code in PROVIDER_CODES:
            self.assertIn(f"`{code}`", self.content)

    def test_no_absolute_paths_or_secret_values_leak(self):
        self.assertNotIn("C:\\", self.content)
        self.assertNotIn("D:\\", self.content)
        # Manifest environment maps and raw credentials must not be dumped.
        self.assertNotIn('"environment"', self.content)
        self.assertNotIn("api_key\":", self.content)

    def test_generated_header_marks_file_as_machine_written(self):
        self.assertTrue(self.content.startswith("<!-- GENERATED FILE"))
        self.assertIn("python -m scriptase.engine.docs", self.content)


class ProviderAuthorGuideTests(unittest.TestCase):
    def setUp(self):
        self.content = generate_provider_author_guide()

    def test_committed_author_guide_matches_generated_output(self):
        self.assertTrue(DEFAULT_AUTHOR_OUTPUT.exists())
        self.assertEqual(
            DEFAULT_AUTHOR_OUTPUT.read_text(encoding="utf-8"),
            self.content,
        )

    def test_guide_covers_the_complete_author_path_and_demo(self):
        for topic in (
            "Scaffold",
            "Manifest",
            "Settings",
            "Implementation",
            "Results",
            "Artifacts",
            "Tests",
            "Health",
            "Ship",
            "scaffold_check",
            "Troubleshooting",
        ):
            self.assertIn(topic.lower(), self.content.lower())

    def test_extensibility_rule_forbids_node_and_ui_edits(self):
        lower = self.content.lower()
        self.assertIn("may not modify", lower)
        self.assertIn("node", lower)
        self.assertIn("generic ui", lower)

    def test_secret_rules_and_widgets_from_code(self):
        self.assertIn("password", self.content)
        self.assertIn("***", self.content)
        for widget in WIDGET_TYPES:
            self.assertIn(f"`{widget}`", self.content)

    def test_sync_and_async_examples_present(self):
        lower = self.content.lower()
        self.assertIn("sync document", lower)
        self.assertIn("sync artifact", lower)
        self.assertIn("async", lower)

    def test_live_catalog_lists_registered_providers(self):
        hub.discover_all()
        for domain_id in DOMAINS:
            for provider in hub.list(domain_id):
                self.assertIn(f"`{provider.id}`", self.content)

    def test_readme_links_provider_author_guide_and_troubleshooting(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/provider-author-guide.md", readme)
        self.assertIn("docs/providers.md", readme)
        # Troubleshooting is a section of the author guide (linked from README).
        self.assertIn("troubleshooting", readme.lower())
        self.assertIn("## Troubleshooting", self.content)

    def test_provider_template_points_at_author_guide(self):
        template = DOCS_DIR / "provider-template" / "README.md"
        self.assertTrue(template.exists())
        text = template.read_text(encoding="utf-8")
        self.assertIn("provider-author-guide.md", text)


if __name__ == "__main__":
    unittest.main()
