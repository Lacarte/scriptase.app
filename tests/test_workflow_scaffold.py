import importlib.util
import json

import pytest

from scriptase.engine.registry import load_generated_node_types
from scriptase.engine.scaffold import ScaffoldError, build_parser, scaffold_node


def test_scaffolder_generates_definition_executable_adapter_and_passing_test(tmp_path):
    paths = scaffold_node("demo.echo", project_root=tmp_path)
    assert all(path.exists() for path in paths)

    generated = load_generated_node_types(tmp_path / "scriptase" / "engine" / "node_definitions")
    definition = generated["demo.echo"]
    assert definition["config_schema"][0]["name"] == "value"
    assert definition["executor"].endswith("demo_echo:execute")

    spec = importlib.util.spec_from_file_location("generated_demo_echo", paths[1])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.execute({}, {"value": {"hello": "world"}}, {}) == {
        "control": {"ok": True}, "result": {"hello": "world"},
    }


def test_scaffolder_refuses_existing_key_and_files(tmp_path):
    with pytest.raises(ScaffoldError, match="already exists"):
        scaffold_node("tts.generate", project_root=tmp_path)
    scaffold_node("demo.echo", project_root=tmp_path)
    with pytest.raises(ScaffoldError, match="existing file"):
        scaffold_node("demo.echo", project_root=tmp_path)


def test_scaffolder_refuses_invalid_port_type_at_cli_boundary():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["demo.echo", "--output", "result:not_a_type"])

    with pytest.raises(ScaffoldError, match="invalid output port type"):
        scaffold_node("demo.bad", outputs=[("result", "not_a_type")])


def test_scaffolder_wires_requested_ports(tmp_path):
    paths = scaffold_node(
        "demo.transform",
        inputs=[("source", "text")],
        outputs=[("result", "text")],
        category="ai",
        project_root=tmp_path,
    )
    payload = json.loads(paths[0].read_text(encoding="utf-8"))["definition"]
    assert payload["inputs"][-1] == {
        "id": "source", "type": "text", "required": False, "multiple": False,
    }
    assert payload["outputs"][-1] == {"id": "result", "type": "text"}
