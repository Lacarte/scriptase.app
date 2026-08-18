"""Step 6.6 tests: generated node reference cannot drift from the registry."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scriptase.engine.docs import (
    DEFAULT_AUTHOR_OUTPUT,
    DEFAULT_OUTPUT,
    generate_node_author_guide,
    generate_node_reference,
    main,
)
from scriptase.engine.registry import CATEGORIES, PORT_TYPES, all_node_types

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"


class NodeReferenceGenerationTests(unittest.TestCase):
    def setUp(self):
        self.content = generate_node_reference()

    def test_committed_reference_matches_registry_output(self):
        """The committed markdown must be byte-identical to the generator output."""
        self.assertTrue(DEFAULT_OUTPUT.exists(), "docs/workflow-nodes.md is missing — run python -m scriptase.engine.docs")
        committed = DEFAULT_OUTPUT.read_text(encoding="utf-8")
        self.assertEqual(
            committed, self.content,
            "docs/workflow-nodes.md is stale — regenerate with: python -m scriptase.engine.docs",
        )

    def test_check_mode_agrees_with_drift_assertion(self):
        self.assertEqual(main(["--check"]), 0)

    def test_every_node_type_documented(self):
        for type_key, definition in all_node_types().items():
            with self.subTest(type_key=type_key):
                self.assertIn(f"(`{type_key}`)", self.content)
                self.assertIn(definition["display_name"], self.content)
                self.assertIn(definition["description"], self.content)
                for field in definition.get("config_schema", []):
                    self.assertIn(f"`{field['name']}`", self.content)

    def test_every_port_type_and_category_documented(self):
        for port_type in PORT_TYPES:
            self.assertIn(f"| `{port_type}` |", self.content)
        for key, info in CATEGORIES.items():
            self.assertIn(f"| `{key}` | {info['label']} |", self.content)

    def test_no_internal_executor_fields_leak(self):
        self.assertNotIn("executor", self.content)
        self.assertNotIn("scriptase.engine.adapters", self.content)

    def test_generated_header_marks_file_as_machine_written(self):
        self.assertTrue(self.content.startswith("<!-- GENERATED FILE"))
        self.assertIn("python -m scriptase.engine.docs", self.content)

    def test_builtin_templates_documented(self):
        for template_id in (
            "full_video",
            "narration_only",
            "storyboard_only",
            "reexport_existing_project",
        ):
            self.assertIn(f"`{template_id}`", self.content)


class UserGuideTests(unittest.TestCase):
    def test_guide_exists_and_links_generated_reference(self):
        guide = DOCS_DIR / "workflow-guide.md"
        self.assertTrue(guide.exists())
        text = guide.read_text(encoding="utf-8")
        self.assertIn("workflow-nodes.md", text)
        # The newcomer path: template, validate, run, and recovery topics are covered.
        for topic in ("Full Video", "Validate", "Run", "Sample Input", "run mode", "draft"):
            self.assertIn(topic.lower(), text.lower())

    def test_readme_links_workflow_onboarding(self):
        readme = DOCS_DIR.parent / "README.md"
        text = readme.read_text(encoding="utf-8")
        self.assertIn("docs/workflow-guide.md", text)
        self.assertIn("docs/workflow-nodes.md", text)


class NodeAuthorGuideTests(unittest.TestCase):
    def setUp(self):
        self.content = generate_node_author_guide()

    def test_committed_author_guide_matches_generated_output(self):
        self.assertTrue(DEFAULT_AUTHOR_OUTPUT.exists())
        self.assertEqual(DEFAULT_AUTHOR_OUTPUT.read_text(encoding="utf-8"), self.content)

    def test_guide_covers_the_complete_author_path_and_demo(self):
        for topic in ("Scaffold", "schema", "adapter", "Test", "Ship", "scaffold_check.echo"):
            self.assertIn(topic.lower(), self.content.lower())
        self.assertIn("contracts.md", self.content)

    def test_connection_rules_are_read_from_contracts(self):
        with TemporaryDirectory() as directory:
            contract = Path(directory) / "contracts.md"
            contract.write_text(
                "### 1.1 Port types & compatibility matrix\n\n"
                "Types (v1): `stale_on_purpose`.\n\n"
                "A unique frozen connection rule.\n\n"
                "### 1.2 Node type keys survive the rename\n",
                encoding="utf-8",
            )
            generated = generate_node_author_guide(contracts_path=contract)
        self.assertIn("A unique frozen connection rule.", generated)
        self.assertNotIn("stale_on_purpose", generated)

    def test_connection_rules_survive_contract_section_renumbering(self):
        with TemporaryDirectory() as directory:
            contract = Path(directory) / "contracts.md"
            contract.write_text(
                "### 1.1 Node definition\n\nNode prose.\n\n"
                "### 1.2 Port types & compatibility matrix\n\n"
                "A renumbered frozen connection rule.\n\n"
                "### 1.3 Stable port IDs\n",
                encoding="utf-8",
            )
            generated = generate_node_author_guide(contracts_path=contract)
        self.assertIn("A renumbered frozen connection rule.", generated)
        self.assertNotIn("Node prose.", generated)
        self.assertNotIn("Stable port IDs", generated)

    def test_port_tables_are_derived_from_the_registry(self):
        for port_type in PORT_TYPES:
            self.assertIn(f"| `{port_type}` |", self.content)
        for type_key, definition in all_node_types().items():
            self.assertIn(f"| `{type_key}` |", self.content)
            for port in definition["inputs"] + definition["outputs"]:
                self.assertIn(f"`{port['id']}:{port['type']}", self.content)

    def test_readme_links_author_guide(self):
        readme = DOCS_DIR.parent / "README.md"
        self.assertIn("docs/workflow-node-author-guide.md", readme.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
