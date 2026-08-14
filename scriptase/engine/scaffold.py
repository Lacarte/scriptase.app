"""Generate a complete, executable workflow node skeleton.

Run ``python -m scriptase.engine.scaffold --help`` for command-line usage.
"""

from __future__ import annotations

import argparse
import json
import keyword
import re
from pathlib import Path

from .registry import CATEGORIES, PORT_TYPES, get_node_type


NODE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
PORT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ScaffoldError(ValueError):
    """A safe, user-correctable scaffolding error."""


def _parse_port(value: str) -> tuple[str, str]:
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("ports must use ID:TYPE syntax")
    port_id, port_type = parts
    if not PORT_ID_RE.fullmatch(port_id):
        raise argparse.ArgumentTypeError(f"invalid port id {port_id!r}")
    if port_type not in PORT_TYPES:
        raise argparse.ArgumentTypeError(
            f"invalid port type {port_type!r}; choose from: {', '.join(PORT_TYPES)}"
        )
    if port_type == "control":
        raise argparse.ArgumentTypeError("data ports cannot use the reserved control type")
    return port_id, port_type


def _module_name(node_key: str) -> str:
    name = node_key.replace(".", "_")
    if keyword.iskeyword(name):
        name += "_node"
    return name


def _title(node_key: str) -> str:
    return " ".join(part.capitalize() for part in node_key.split(".")[-1].split("_"))


def _unique_ports(ports: list[tuple[str, str]], kind: str) -> None:
    for port_id, port_type in ports:
        if not PORT_ID_RE.fullmatch(port_id):
            raise ScaffoldError(f"invalid {kind} port id {port_id!r}")
        if port_type not in PORT_TYPES or port_type == "control":
            raise ScaffoldError(f"invalid {kind} port type {port_type!r}")
    ids = [port_id for port_id, _ in ports]
    duplicate = next((port_id for port_id in ids if ids.count(port_id) > 1), None)
    if duplicate:
        raise ScaffoldError(f"duplicate {kind} port id {duplicate!r}")
    reserved = "trigger" if kind == "input" else "control"
    if reserved in ids:
        raise ScaffoldError(f"{kind} port id {reserved!r} is reserved")


def _adapter_source(output_ports: list[tuple[str, str]]) -> str:
    assignments = []
    for index, (port_id, _port_type) in enumerate(output_ports):
        fallback = 'config.get("value", {})' if index == 0 else "None"
        assignments.append(f'        "{port_id}": inputs.get("{port_id}", {fallback}),')
    body = "\n".join(assignments)
    return f'''"""Adapter skeleton for a generated workflow node."""

from scriptase.engine.adapters.common import CONTROL


def execute(inputs, config, context):
    """Execute the node. Replace the placeholder data mapping with real work."""
    return {{
        "control": CONTROL,
{body}
    }}
'''


def _test_source(node_key: str, module_name: str, output_ports: list[tuple[str, str]]) -> str:
    output_ids = ["control", *(port_id for port_id, _ in output_ports)]
    return f'''"""Generated smoke tests for {node_key}."""

from scriptase.engine.adapters.generated.{module_name} import execute
from scriptase.engine.registry import get_node_type, serialize_registry


def test_{module_name}_is_registered_and_palette_visible():
    definition = get_node_type("{node_key}")
    assert definition is not None
    assert "{node_key}" in serialize_registry()["node_types"]


def test_{module_name}_executes_with_the_declared_outputs():
    result = execute({{}}, {{"value": {{"generated": True}}}}, {{}})
    assert set(result) == set({output_ids!r})
    assert result["control"] == {{"ok": True}}
'''


def scaffold_node(
    node_key: str,
    *,
    inputs: list[tuple[str, str]] | None = None,
    outputs: list[tuple[str, str]] | None = None,
    category: str = "utility",
    display_name: str | None = None,
    description: str | None = None,
    project_root: str | Path | None = None,
) -> list[Path]:
    """Create the definition, adapter, and passing smoke test for ``node_key``."""
    if not NODE_KEY_RE.fullmatch(node_key):
        raise ScaffoldError(
            "node key must contain at least two lowercase dot-separated identifiers "
            "(for example, demo.echo)"
        )
    if category not in CATEGORIES:
        raise ScaffoldError(f"unknown category {category!r}")
    if get_node_type(node_key) is not None:
        raise ScaffoldError(f"node key {node_key!r} already exists")

    data_inputs = list(inputs or [])
    data_outputs = list(outputs) if outputs is not None else [("result", "generic_json")]
    _unique_ports(data_inputs, "input")
    _unique_ports(data_outputs, "output")

    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    definitions_dir = root / "scriptase" / "engine" / "node_definitions"
    adapters_dir = root / "scriptase" / "engine" / "adapters" / "generated"
    tests_dir = root / "tests"
    module_name = _module_name(node_key)
    definition_path = definitions_dir / f"{node_key}.json"
    adapter_path = adapters_dir / f"{module_name}.py"
    test_path = tests_dir / f"test_workflow_node_{module_name}.py"
    targets = [definition_path, adapter_path, test_path]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise ScaffoldError(f"refusing to overwrite existing file: {existing[0]}")

    definition = {
        "key": node_key,
        "definition": {
            "type_version": 1,
            "display_name": display_name or _title(node_key),
            "description": description or f"Generated {display_name or _title(node_key)} workflow node.",
            "category": category,
            "icon": "box",
            "inputs": [
                {"id": "trigger", "type": "control", "required": False, "multiple": False},
                *[
                    {"id": port_id, "type": port_type, "required": False, "multiple": False}
                    for port_id, port_type in data_inputs
                ],
            ],
            "outputs": [
                {"id": "control", "type": "control"},
                *[{"id": port_id, "type": port_type} for port_id, port_type in data_outputs],
            ],
            "config_schema": [
                {"name": "value", "label": "Value", "type": "json", "default": {}},
            ],
            "capabilities": {"retry": False, "cancel": False},
            "executor": f"scriptase.engine.adapters.generated.{module_name}:execute",
        },
    }

    for directory in (definitions_dir, adapters_dir, tests_dir):
        directory.mkdir(parents=True, exist_ok=True)
    init_path = adapters_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text('"""Generated workflow node adapters."""\n', encoding="utf-8")

    definition_path.write_text(json.dumps(definition, indent=2) + "\n", encoding="utf-8")
    adapter_path.write_text(_adapter_source(data_outputs), encoding="utf-8")
    test_path.write_text(_test_source(node_key, module_name, data_outputs), encoding="utf-8")
    return targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scaffold an executable workflow-builder node")
    parser.add_argument("node_key", help="lowercase dotted key, for example demo.echo")
    parser.add_argument("--input", action="append", default=[], type=_parse_port, metavar="ID:TYPE",
                        help="add an optional data input (repeatable)")
    parser.add_argument("--output", action="append", default=None, type=_parse_port, metavar="ID:TYPE",
                        help="add a data output (repeatable; default: result:generic_json)")
    parser.add_argument("--category", choices=sorted(CATEGORIES), default="utility")
    parser.add_argument("--display-name")
    parser.add_argument("--description")
    parser.add_argument("--project-root", help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        paths = scaffold_node(
            args.node_key,
            inputs=args.input,
            outputs=args.output,
            category=args.category,
            display_name=args.display_name,
            description=args.description,
            project_root=args.project_root,
        )
    except ScaffoldError as exc:
        parser.error(str(exc))
    print(f"Scaffolded {args.node_key}:")
    for path in paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
